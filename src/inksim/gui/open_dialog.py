# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Custom file browser with previews and Inkscape/InkStitch guidance."""

from __future__ import annotations

import math
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from filelock import Timeout as FileLockTimeout
from PySide6.QtCore import (
    QDir,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QProcess,
    QProcessEnvironment,
    QRectF,
    QRunnable,
    QSize,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QFontDatabase,
    QIcon,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from ..debug import logger
from ..formats import (
    color_block_count,
    get_supported_input_extensions,
    is_stitchblock_svg,
)
from ..i18n import _
from ..integration.inkstitch import (
    active_inkstitch_installation,
    inkstitch_process_environment,
    resolve_inkstitch_preview,
)
from ..integration.paths import (
    INKSCAPE_CONFIG_KEY,
    ToolStatus,
    clean_child_environment,
    detect_tools,
    prefer_saved_inkscape,
)
from ..paths import _sanitize_path, _sanitize_path_text, _unsanitize_path
from ..render.thumbnails import (
    THUMBNAIL_SIZE,
    thumbnail_details,
    thumbnail_is_current,
    thumbnail_path,
    write_thumbnail,
)
from .inkscape_dialog import InkscapeIntegrationDialog
from .palette import apply_palette_to_design
from .viewer import EmbroideryViewerWidget

KIND_DIRECTORY = "directory"
KIND_EMBROIDERY = "embroidery"
KIND_SVG = "svg"
KIND_CSV = "csv"
KIND_OTHER = "other"

_THUMBNAIL_UPDATE = "update"
_THUMBNAIL_REGENERATE = "regenerate"

_VIEW_ICONS_TEXT = "icons_text"
_VIEW_ICONS = "icons"
_VIEW_DETAILS = "details"

_MAX_SVG_THUMBNAIL_BYTES = 20 * 1024 * 1024
_CONVERSION_TIMEOUT_MS = 180_000
_CONVERSION_PROGRESS_INTERVAL_MS = 100
_SELECTION_PREVIEW_DEBOUNCE_MS = 250
_INITIAL_PREVIEW_ESTIMATE_SECONDS = 10.0
_MAX_PREVIEW_ESTIMATE_SECONDS = 60.0
_PREVIEW_TIMING_CONFIG_KEY = "svg_preview_timing"
_ICON_SIZE_CONFIG_KEY = "open_dialog_icon_size"
_SKIP_EXTENSIONS_CONFIG_KEY = "open_dialog_skip_extensions"
_SKIP_SAVE_DEBOUNCE_MS = 600
_ICON_SIZE_MIN = 32
_ICON_SIZE_MAX = 160
_ICON_SIZE_DEFAULT = 96
_FAVORITE_DIRECTORIES_CONFIG_KEY = "favorite_directories"
_WINDOWS_CREATE_NO_WINDOW = 0x08000000
_PLACE_PATH_ROLE = Qt.ItemDataRole.UserRole
_PLACE_FAVORITE_ROLE = Qt.ItemDataRole.UserRole + 1


class _ThumbnailSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(int, int, int)


class ThumbnailJob(QRunnable):
    """Write sidecar thumbnails for a batch of designs off the GUI thread."""

    def __init__(self, paths: Sequence[Path], *, regenerate: bool = False) -> None:
        super().__init__()
        self.signals = _ThumbnailSignals()
        self._paths = list(paths)
        self._regenerate = regenerate
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        created = skipped = failed = 0
        total = len(self._paths)
        for index, path in enumerate(self._paths, 1):
            if self._stop:
                break
            current = thumbnail_is_current(path)
            if write_thumbnail(path, overwrite=self._regenerate) is None:
                failed += 1
            elif current and not self._regenerate:
                skipped += 1
            else:
                created += 1
            self.signals.progress.emit(index, total)
        self.signals.finished.emit(created, skipped, failed)


def _preview_timing_stats(value: object) -> tuple[float, int] | None:
    if not isinstance(value, dict):
        return None
    total_seconds = value.get("total_seconds")
    count = value.get("count")
    if (
        isinstance(total_seconds, bool)
        or not isinstance(total_seconds, (int, float))
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
    ):
        return None
    try:
        total_seconds = float(total_seconds)
    except OverflowError:
        return None
    if not math.isfinite(total_seconds) or total_seconds < 0 or (count == 0 and total_seconds != 0):
        return None
    return total_seconds, count


def _hide_windows_console(arguments: Any) -> None:
    """Keep console-subsystem Inkscape exports from opening a terminal window."""
    arguments.flags |= _WINDOWS_CREATE_NO_WINDOW


def _create_temporary_conversion_files() -> tuple[Path, Path]:
    """Create the temporary CSV and stderr files used by one conversion."""
    created: list[Path] = []
    try:
        for suffix in (".csv", ".err"):
            with tempfile.NamedTemporaryFile(
                prefix="inksim-preview-",
                suffix=suffix,
                delete=False,
            ) as temporary:
                created.append(Path(temporary.name))
    except OSError:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return created[0], created[1]


def _remove_temporary_file(path: Path | None, description: str) -> None:
    """Delete a temporary conversion file, reporting failures without failing."""
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as ex:
        logger.warning(
            "Could not remove %s %s: %s",
            description,
            _sanitize_path_text(str(path)),
            _sanitize_path_text(str(ex)),
        )


def _store_conversion_log(
    source_path: Path | None,
    error_path: Path | None,
    stderr_text: str,
) -> Path | None:
    """Keep a failed conversion's stderr next to its source file.

    A successful conversion leaves nothing behind, so the log only exists when
    there is an error to read. It is named after the converted file, which makes
    it obvious which document produced it.
    """
    if error_path is None:
        return None
    if not stderr_text:
        _remove_temporary_file(error_path, "temporary Ink/Stitch log")
        return None
    if source_path is not None:
        log_path = source_path.with_name(f"{source_path.name}.inksim.log")
        try:
            log_path.write_text(stderr_text + "\n", encoding="utf-8")
        except OSError as ex:
            logger.warning(
                "Could not write Ink/Stitch log %s: %s",
                _sanitize_path_text(str(log_path)),
                _sanitize_path_text(str(ex)),
            )
        else:
            _remove_temporary_file(error_path, "temporary Ink/Stitch log")
            return log_path
    return error_path


class SvgPreviewWidget(QWidget):
    """Display an SVG preview with mouse-wheel zooming and drag panning."""

    MIN_ZOOM = 0.2
    MAX_ZOOM = 8.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source: QPixmap | None = None
        self.zoom = 1.0
        self.pan = QPointF()
        self._drag_start: QPointF | None = None
        self._drag_pan = QPointF()
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_source(self, source: QPixmap) -> None:
        self._source = source
        self.fit_to_view()

    def _fit_scale(self) -> float:
        if self._source is None or self.width() <= 0 or self.height() <= 0:
            return 0.0
        return min(
            self.width() / self._source.width(),
            self.height() / self._source.height(),
        )

    def _image_rect(self, scale: float) -> QRectF:
        if self._source is None:
            return QRectF()
        width = self._source.width() * scale
        height = self._source.height() * scale
        return QRectF(
            (self.width() - width) / 2 + self.pan.x(),
            (self.height() - height) / 2 + self.pan.y(),
            width,
            height,
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        if self._source is None:
            return
        scale = self._fit_scale() * self.zoom
        if scale <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self._image_rect(scale), self._source, QRectF(self._source.rect()))

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        if self._source is None:
            return
        fit_scale = self._fit_scale()
        if fit_scale <= 0:
            return
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        old_scale = fit_scale * self.zoom
        old_rect = self._image_rect(old_scale)
        source_x = (anchor.x() - old_rect.left()) / old_scale
        source_y = (anchor.y() - old_rect.top()) / old_scale
        new_zoom = min(self.MAX_ZOOM, max(self.MIN_ZOOM, self.zoom * factor))
        if new_zoom == self.zoom:
            return
        self.zoom = new_zoom
        new_scale = fit_scale * self.zoom
        self.pan = QPointF(
            anchor.x()
            - source_x * new_scale
            - (self.width() - self._source.width() * new_scale) / 2,
            anchor.y()
            - source_y * new_scale
            - (self.height() - self._source.height() * new_scale) / 2,
        )
        self.update()

    def fit_to_view(self) -> None:
        self.zoom = 1.0
        self.pan = QPointF()
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()
        if delta == 0:
            event.ignore()
            return
        self.zoom_by(1.15 if delta > 0 else 1 / 1.15, event.position())
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position()
            self._drag_pan = self.pan
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.pan = self._drag_pan + event.position() - self._drag_start
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class OpenBrowserDialog(QDialog):
    """Browse supported files, preview them, and guide the user to tools.

    The dialog is intentionally standalone: it detects whether Inkscape is
    available, renders a vector thumbnail for SVG sources, and can convert an
    SVG to a temporary CSV through Inkscape/InkStitch.  The main window only
    receives the selected path and result action.
    """

    def __init__(
        self,
        parent: QWidget | None,
        initial_directory: str | Path | None,
        selected_file: str | Path | None = None,
        recent_directories: Sequence[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("dialog.open_browser.title", "Open file"))
        self.resize(1280, 820)
        self.selected_path: Path | None = None
        self.preview_csv_path: Path | None = None
        self.document_path: Path | None = None
        self.result_action: str | None = None
        self.launch_directory = Path.cwd().resolve()
        self.current_directory = Path(initial_directory or Path.cwd()).resolve()
        self._directory_return_path: Path | None = None
        self.initial_file: Path | None = Path(selected_file).resolve() if selected_file else None
        self.extensions = get_supported_input_extensions() | {"svg"}
        self.config = Config()
        self.favorite_directories = self._load_favorite_directories()
        self.tool_status: ToolStatus = self._detect_tools()
        self._all_paths: list[Path] = []
        self._visible_paths: list[Path] = []
        self._svg_kind_cache: dict[Path, str] = {}
        self._preview_loaded = False
        self._palette_note: str | None = None
        self._svg_source: QPixmap | None = None
        self._conversion_process: QProcess | None = None
        self._conversion_csv: Path | None = None
        self._conversion_error: Path | None = None
        self._conversion_source: Path | None = None
        self._conversion_aborted = False
        self._conversion_started_at: float | None = None
        self._conversion_estimate_seconds = _INITIAL_PREVIEW_ESTIMATE_SECONDS
        self._closing = False
        self._thumbnail_icons: dict[Path, QIcon] = {}
        self._thumbnail_job: ThumbnailJob | None = None
        stored_icon_size = self.config.get(_ICON_SIZE_CONFIG_KEY, _ICON_SIZE_DEFAULT)
        self._icon_size = (
            max(_ICON_SIZE_MIN, min(_ICON_SIZE_MAX, stored_icon_size))
            if isinstance(stored_icon_size, int)
            else _ICON_SIZE_DEFAULT
        )
        stored_skips = self.config.get(_SKIP_EXTENSIONS_CONFIG_KEY, "")
        self._skip_extensions = _parse_skip_extensions(
            stored_skips if isinstance(stored_skips, str) else ""
        )
        self._thumbnail_mode = _THUMBNAIL_UPDATE
        self._thumbnail_actions: dict[str, QAction] = {}
        self._thumbnail_pool = QThreadPool(self)
        self._thumbnail_pool.setMaxThreadCount(1)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_SELECTION_PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._load_embroidery_preview)

        self._conversion_timer = QTimer(self)
        self._conversion_timer.setSingleShot(True)
        self._conversion_timer.timeout.connect(self._on_conversion_timeout)

        self._conversion_progress_timer = QTimer(self)
        self._conversion_progress_timer.setInterval(_CONVERSION_PROGRESS_INTERVAL_MS)
        self._conversion_progress_timer.timeout.connect(self._update_conversion_progress)

        self._skip_save_timer = QTimer(self)
        self._skip_save_timer.setSingleShot(True)
        self._skip_save_timer.setInterval(_SKIP_SAVE_DEBOUNCE_MS)
        self._skip_save_timer.timeout.connect(self._store_skip_extensions)

        self._folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self._file_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self._place_items: list[QListWidgetItem] = []

        self._build_ui(recent_directories or [])
        self._refresh_places()
        self._update_tool_status()
        self.refresh_files()
        QTimer.singleShot(0, self.file_list.setFocus)

    def _build_ui(self, recent_directories: Sequence[str]) -> None:
        root = QVBoxLayout(self)

        status_row = QHBoxLayout()
        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_row.addWidget(self.status_label, 1)
        self.tools_button = QPushButton(_("dialog.open_browser.tools", "Tools..."), self)
        self.tools_button.clicked.connect(self._open_tools_dialog)
        status_row.addWidget(self.tools_button)
        root.addLayout(status_row)

        directory_row = QHBoxLayout()
        directory_row.addWidget(QLabel(_("dialog.open_browser.folder", "Folder"), self))
        self.breadcrumb_scroll = QScrollArea(self)
        self.breadcrumb_scroll.setWidgetResizable(True)
        self.breadcrumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.breadcrumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.breadcrumb_widget = QWidget(self.breadcrumb_scroll)
        self.breadcrumb_layout = QHBoxLayout(self.breadcrumb_widget)
        self.breadcrumb_layout.setContentsMargins(0, 0, 0, 0)
        self.breadcrumb_layout.setSpacing(2)
        self.breadcrumb_scroll.setWidget(self.breadcrumb_widget)
        self.breadcrumb_scroll.setFixedHeight(
            self.breadcrumb_widget.fontMetrics().height()
            + 2 * self.breadcrumb_layout.contentsMargins().top()
            + 12
        )

        self.path_stack = QStackedWidget(self)
        self.path_stack.addWidget(self.breadcrumb_scroll)
        self.path_editor_page = QWidget(self.path_stack)
        path_editor_layout = QHBoxLayout(self.path_editor_page)
        path_editor_layout.setContentsMargins(0, 0, 0, 0)
        self.path_entry = QLineEdit(self.path_editor_page)
        self.path_entry.setPlaceholderText(
            _("dialog.open_browser.path_placeholder", "Enter or paste a folder path")
        )
        self.path_entry.returnPressed.connect(self._apply_path_entry)
        path_editor_layout.addWidget(self.path_entry, 1)
        self.path_go_button = QPushButton(_("dialog.open_browser.go", "Go"), self.path_editor_page)
        self.path_go_button.clicked.connect(self._apply_path_entry)
        path_editor_layout.addWidget(self.path_go_button)
        self.path_stack.addWidget(self.path_editor_page)
        directory_row.addWidget(self.path_stack, 1)
        self.edit_path_button = QPushButton(_("dialog.open_browser.edit_path", "Edit path"), self)
        self.edit_path_button.clicked.connect(self._toggle_path_edit)
        directory_row.addWidget(self.edit_path_button)
        self.add_favorite_button = QPushButton(
            _("dialog.open_browser.add_favorite", "Add to places"), self
        )
        self.add_favorite_button.clicked.connect(self._add_current_favorite)
        directory_row.addWidget(self.add_favorite_button)
        root.addLayout(directory_row)

        recent_row = QHBoxLayout()
        recent_row.addWidget(QLabel(_("dialog.open_browser.recent", "Recent:"), self))
        self.recent_combo = QComboBox(self)
        self.recent_combo.addItem(
            _("dialog.open_browser.recent_placeholder", "— choose directory —")
        )
        self.recent_combo.addItems(list(recent_directories))
        self.recent_combo.setEnabled(self.recent_combo.count() > 1)
        self.recent_combo.currentIndexChanged.connect(self._on_recent_selected)
        recent_row.addWidget(self.recent_combo, 1)
        root.addLayout(recent_row)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(_("dialog.open_browser.view", "View"), self))
        self.view_combo = QComboBox(self)
        self.view_combo.addItem(
            _("dialog.open_browser.view.icons_text", "Icons & text"), _VIEW_ICONS_TEXT
        )
        self.view_combo.addItem(_("dialog.open_browser.view.icons", "Icons only"), _VIEW_ICONS)
        self.view_combo.addItem(_("dialog.open_browser.view.details", "Details"), _VIEW_DETAILS)
        self.view_combo.currentIndexChanged.connect(self._apply_view_mode)
        search_row.addWidget(self.view_combo)
        self.icon_size_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.icon_size_slider.setObjectName("iconSizeSlider")
        self.icon_size_slider.setRange(_ICON_SIZE_MIN, _ICON_SIZE_MAX)
        self.icon_size_slider.setValue(self._icon_size)
        self.icon_size_slider.setFixedWidth(110)
        self.icon_size_slider.setToolTip(
            _("dialog.open_browser.icon_size", "Icon size ({size} px)").format(size=self._icon_size)
        )
        self.icon_size_slider.valueChanged.connect(self._on_icon_size_changed)
        search_row.addWidget(self.icon_size_slider)
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText(_("dialog.open_browser.search", "Search files"))
        self.search_edit.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(QLabel(_("dialog.open_browser.skip_label", "Skip"), self))
        self.skip_edit = QLineEdit(self)
        self.skip_edit.setPlaceholderText(_("dialog.open_browser.skip", "dst|exp"))
        self.skip_edit.setToolTip(
            _(
                "dialog.open_browser.skip_hint",
                "Hide these extensions in the dialog.\n"
                "Separate them with | and the list is stored in config.toml.",
            )
        )
        self.skip_edit.setClearButtonEnabled(True)
        self.skip_edit.setMinimumWidth(150)
        self.skip_edit.setMaximumWidth(220)
        self.skip_edit.setText("|".join(self._skip_extensions))
        self.skip_edit.textChanged.connect(self._on_skip_extensions_changed)
        search_row.addWidget(self.skip_edit)
        search_row.addWidget(QLabel(_("dialog.open_browser.filter", "Show"), self))
        self.filter_combo = QComboBox(self)
        self.filter_combo.addItem(_("dialog.open_browser.filter.all", "All supported"), "all")
        self.filter_combo.addItem(
            _("dialog.open_browser.filter.embroidery", "Embroidery"), "embroidery"
        )
        self.filter_combo.addItem(_("dialog.open_browser.filter.svg", "SVG source"), "svg")
        self.filter_combo.addItem(_("dialog.open_browser.filter.csv", "CSV stitch data"), "csv")
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        search_row.addWidget(self.filter_combo)
        root.addLayout(search_row)

        self.file_list = QListWidget(self)
        self._list_font = self.file_list.font()
        self._mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.file_list.installEventFilter(self)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.setIconSize(QSize(THUMBNAIL_SIZE // 4, THUMBNAIL_SIZE // 4))
        self.file_list.currentItemChanged.connect(self._on_current_item_changed)
        self.file_list.itemSelectionChanged.connect(self._update_actions)
        self.file_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.places_list = QListWidget(self)
        self.places_list.setObjectName("openPlaces")
        self.places_list.setMaximumWidth(190)
        self.places_list.currentItemChanged.connect(self._on_place_selected)
        self.places_list.itemClicked.connect(self._on_place_clicked)

        self.preview_container = QWidget(self)
        preview_layout = QVBoxLayout(self.preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = EmbroideryViewerWidget(self.preview_container, None)
        self.preview.show_grid = False
        self.preview.show_needle = False
        preview_layout.addWidget(self.preview)

        self.svg_page = QWidget(self)
        svg_layout = QVBoxLayout(self.svg_page)
        svg_layout.setContentsMargins(0, 0, 0, 0)
        self.svg_preview = SvgPreviewWidget(self.svg_page)
        svg_layout.addWidget(self.svg_preview, 1)
        self.svg_caption = QLabel(self.svg_page)
        self.svg_caption.setWordWrap(True)
        self.svg_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        svg_layout.addWidget(self.svg_caption)

        self.message_page = QWidget(self)
        message_layout = QVBoxLayout(self.message_page)
        self.message_label = QLabel(self.message_page)
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_layout.addWidget(self.message_label, 1)

        self.preview_stack = QStackedWidget(self)
        self.preview_stack.addWidget(self.preview_container)
        self.preview_stack.addWidget(self.svg_page)
        self.preview_stack.addWidget(self.message_page)

        preview_panel = QWidget(self)
        preview_panel_layout = QVBoxLayout(preview_panel)
        preview_panel_layout.setContentsMargins(0, 0, 0, 0)
        preview_panel_layout.addWidget(self.preview_stack, 1)
        self.preview_controls = QWidget(preview_panel)
        preview_controls_layout = QHBoxLayout(self.preview_controls)
        preview_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.zoom_out_button = QPushButton("-", self.preview_controls)
        self.zoom_out_button.setAccessibleName(_("dialog.open_browser.zoom_out", "Zoom out"))
        self.zoom_out_button.clicked.connect(
            lambda _checked=False: self._change_preview_zoom(1 / 1.25)
        )
        preview_controls_layout.addWidget(self.zoom_out_button)
        self.zoom_in_button = QPushButton("+", self.preview_controls)
        self.zoom_in_button.setAccessibleName(_("dialog.open_browser.zoom_in", "Zoom in"))
        self.zoom_in_button.clicked.connect(lambda _checked=False: self._change_preview_zoom(1.25))
        preview_controls_layout.addWidget(self.zoom_in_button)
        self.fit_button = QPushButton(_("dialog.open_browser.fit", "Fit"), self.preview_controls)
        self.fit_button.clicked.connect(self._fit_preview)
        preview_controls_layout.addWidget(self.fit_button)
        preview_controls_layout.addStretch(1)
        self.preview_controls.setVisible(False)
        preview_panel_layout.addWidget(self.preview_controls)

        self.file_list_container = QWidget(self)
        list_layout = QVBoxLayout(self.file_list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)
        self.details_header = QLabel(self.file_list_container)
        self.details_header.setObjectName("fileDetailsHeader")
        self.details_header.setFont(self._mono_font)
        self.details_header.hide()
        list_layout.addWidget(self.details_header)
        list_layout.addWidget(self.file_list, 1)

        file_preview_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.file_preview_splitter = file_preview_splitter
        file_preview_splitter.addWidget(self.file_list_container)
        file_preview_splitter.addWidget(preview_panel)
        file_preview_splitter.setStretchFactor(1, 1)
        places_panel = QWidget(self)
        places_layout = QVBoxLayout(places_panel)
        places_layout.setContentsMargins(0, 0, 0, 0)
        places_layout.addWidget(QLabel(_("dialog.open_browser.places", "Places"), places_panel))
        places_layout.addWidget(self.places_list, 1)
        self.remove_favorite_button = QPushButton(
            _("dialog.open_browser.remove_favorite", "Remove favorite"), places_panel
        )
        self.remove_favorite_button.clicked.connect(self._remove_selected_favorite)
        places_layout.addWidget(self.remove_favorite_button)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(places_panel)
        splitter.addWidget(file_preview_splitter)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self.details_label = QLabel(self)
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.details_label)

        button_row = QHBoxLayout()
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(160)
        self.progress.setVisible(False)
        button_row.addWidget(self.progress)
        self.activity_label = QLabel(self)
        self.activity_label.setVisible(False)
        button_row.addWidget(self.activity_label)
        button_row.addStretch(1)
        self.thumbnails_button = QToolButton(self)
        self.thumbnails_button.setObjectName("createThumbnails")
        self.thumbnails_button.setToolTip(
            _(
                "dialog.open_browser.create_thumbnails_hint",
                "Write a 256 px PNG next to each selected design (design.pes.png)."
                "\nThe menu picks whether outdated files or every thumbnail is rebuilt.",
            )
        )
        self.thumbnails_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.thumbnails_button.clicked.connect(self._run_thumbnail_action)
        thumbnails_menu = QMenu(self.thumbnails_button)
        action_group = QActionGroup(self.thumbnails_button)
        action_group.setExclusive(True)
        for mode, message_id, fallback in (
            (
                _THUMBNAIL_UPDATE,
                "dialog.open_browser.thumbnails_update",
                "Update outdated thumbnails",
            ),
            (
                _THUMBNAIL_REGENERATE,
                "dialog.open_browser.thumbnails_regenerate",
                "Regenerate all thumbnails",
            ),
        ):
            action = QAction(_(message_id, fallback), self.thumbnails_button)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, selected=mode: self._select_thumbnail_mode(selected)
            )
            action_group.addAction(action)
            thumbnails_menu.addAction(action)
            self._thumbnail_actions[mode] = action
        self.thumbnails_button.setMenu(thumbnails_menu)
        self._select_thumbnail_mode(_THUMBNAIL_UPDATE)
        button_row.addWidget(self.thumbnails_button)
        self.edit_button = QPushButton(
            _("dialog.open_browser.edit_inkscape", "Edit in Inkscape"), self
        )
        self.edit_button.clicked.connect(self._edit_in_inkscape)
        button_row.addWidget(self.edit_button)
        self.palette_button = QPushButton(_("dialog.open_browser.palette", "Colors…"), self)
        self.palette_button.setObjectName("applyPalette")
        self.palette_button.setToolTip(
            _(
                "dialog.open_browser.palette_hint",
                "Store the thread colors of a design that keeps none (DST, EXP)"
                "\nas <name>.edr next to it.",
            )
        )
        self.palette_button.clicked.connect(self._apply_palette)
        button_row.addWidget(self.palette_button)
        self.cancel_button = QPushButton(_("dialog.open_browser.cancel", "Cancel"), self)
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_button)
        self.open_button = QPushButton(_("dialog.open_browser.open", "Open"), self)
        self.open_button.setDefault(True)
        self.open_button.clicked.connect(self._open_selected)
        button_row.addWidget(self.open_button)
        root.addLayout(button_row)

        self._apply_view_mode()
        self._update_actions()

    def _load_favorite_directories(self) -> list[Path]:
        values = self.config.get(_FAVORITE_DIRECTORIES_CONFIG_KEY, [])
        if not isinstance(values, list):
            return []
        favorites: list[Path] = []
        for value in values:
            if not isinstance(value, str):
                continue
            path = Path(_unsanitize_path(value)).expanduser().resolve()
            if path not in favorites:
                favorites.append(path)
        return favorites

    def _refresh_places(self) -> None:
        selected = self.places_list.currentItem()
        selected_path = selected.data(_PLACE_PATH_ROLE) if selected is not None else None
        self.places_list.blockSignals(True)
        self.places_list.clear()
        self._place_items = []
        locations = [
            (
                _("dialog.open_browser.home", "Home"),
                Path.home(),
            ),
            *(
                (label, Path(QStandardPaths.writableLocation(location)))
                for location, label in (
                    (
                        QStandardPaths.StandardLocation.DesktopLocation,
                        _("dialog.open_browser.desktop", "Desktop"),
                    ),
                    (
                        QStandardPaths.StandardLocation.DocumentsLocation,
                        _("dialog.open_browser.documents", "Documents"),
                    ),
                    (
                        QStandardPaths.StandardLocation.DownloadLocation,
                        _("dialog.open_browser.downloads", "Downloads"),
                    ),
                )
                if QStandardPaths.writableLocation(location)
            ),
        ]
        seen: set[Path] = set()
        for label, path in locations:
            path = path.resolve()
            if path.is_dir() and path not in seen:
                seen.add(path)
                self._add_place_item(label, path)
        for drive in QDir.drives():
            path = Path(drive.absoluteFilePath()).resolve()
            if path.is_dir() and path not in seen:
                seen.add(path)
                self._add_place_item(_sanitize_path_text(str(path)), path)

        self._add_place_item(
            _sanitize_path_text(self.launch_directory.name or str(self.launch_directory)),
            self.launch_directory,
        )
        self._add_place_heading(_("dialog.open_browser.favorites", "Favorites"))
        for path in self.favorite_directories:
            self._add_place_item(path.name or str(path), path, favorite=True)
        selected_item = next(
            (
                self._place_items[index]
                for index in range(len(self._place_items))
                if self._place_items[index].data(_PLACE_PATH_ROLE) == selected_path
            ),
            None,
        )
        if selected_item is not None:
            self.places_list.setCurrentItem(selected_item)
        self.places_list.blockSignals(False)
        self.remove_favorite_button.setEnabled(
            bool(selected_item and selected_item.data(_PLACE_FAVORITE_ROLE))
        )

    def _add_place_heading(self, label: str) -> None:
        item = QListWidgetItem(label)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.places_list.addItem(item)

    def _add_place_item(self, label: str, path: Path, favorite: bool = False) -> None:
        item = QListWidgetItem(self._folder_icon, label)
        item.setData(_PLACE_PATH_ROLE, str(path))
        item.setData(_PLACE_FAVORITE_ROLE, favorite)
        item.setToolTip(_sanitize_path_text(str(path)))
        self.places_list.addItem(item)
        self._place_items.append(item)

    def _on_place_selected(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            self.remove_favorite_button.setEnabled(False)
            return
        path_text = current.data(_PLACE_PATH_ROLE)
        self.remove_favorite_button.setEnabled(bool(current.data(_PLACE_FAVORITE_ROLE)))
        if isinstance(path_text, str):
            self.set_directory(path_text)

    def _on_place_clicked(self, item: QListWidgetItem) -> None:
        path_text = item.data(_PLACE_PATH_ROLE)
        if isinstance(path_text, str):
            self.set_directory(path_text)

    def _add_current_favorite(self, checked: bool = False) -> None:
        del checked
        path = self.current_directory.resolve()
        if path not in self.favorite_directories:
            self.favorite_directories.append(path)
            self._save_favorite_directories()
            self._refresh_places()
        self.add_favorite_button.setEnabled(False)

    def _remove_selected_favorite(self, checked: bool = False) -> None:
        del checked
        item = self.places_list.currentItem()
        if item is None or not item.data(_PLACE_FAVORITE_ROLE):
            return
        path_text = item.data(_PLACE_PATH_ROLE)
        if not isinstance(path_text, str):
            return
        path = Path(path_text)
        self.favorite_directories = [
            favorite for favorite in self.favorite_directories if favorite != path
        ]
        self._save_favorite_directories()
        self._refresh_places()

    def _save_favorite_directories(self) -> None:
        self.config.set(
            _FAVORITE_DIRECTORIES_CONFIG_KEY,
            [_sanitize_path(str(path)) for path in self.favorite_directories],
        )

    def _refresh_breadcrumbs(self) -> None:
        while self.breadcrumb_layout.count():
            item = self.breadcrumb_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        current = Path(self.current_directory.anchor)
        parts = self.current_directory.parts
        for index, part in enumerate(parts):
            if index == 0:
                current = Path(part)
                label = part
            else:
                current /= part
                label = part
            button = QPushButton(_sanitize_path_text(label), self.breadcrumb_widget)
            button.setFlat(True)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setFixedWidth(button.fontMetrics().horizontalAdvance(button.text()) + 16)
            button.setToolTip(_sanitize_path_text(str(current)))
            button.clicked.connect(lambda _checked=False, path=current: self.set_directory(path))
            self.breadcrumb_layout.addWidget(button)
            if index < len(parts) - 1:
                self.breadcrumb_layout.addWidget(QLabel("›", self.breadcrumb_widget))
        self.breadcrumb_layout.addStretch(1)
        self.breadcrumb_scroll.horizontalScrollBar().setValue(
            self.breadcrumb_scroll.horizontalScrollBar().maximum()
        )

    def _update_tool_status(self) -> None:
        self.config.reload()
        self.tool_status = self._detect_tools()
        lines = []
        if self.tool_status.has_inkscape:
            lines.append(
                _("dialog.open_browser.status.inkscape", "Inkscape: {path}").format(
                    path=_sanitize_path_text(self.tool_status.inkscape.path or "")
                )
            )
        else:
            lines.append(_("dialog.open_browser.status.inkscape_missing", "Inkscape: not found."))
        extension_status = self._cached_inkstitch_extension_status()
        if extension_status is None:
            lines.append(
                _("dialog.open_browser.status.inkstitch_unchecked")
                if self.tool_status.has_inkscape
                else _("dialog.open_browser.status.inkstitch_no_inkscape")
            )
        elif extension_status.get("status") == "found":
            selected_installation = self._active_inkstitch_installation(extension_status)
            paths = (
                [_sanitize_path(selected_installation["extension_dir"])]
                if selected_installation is not None
                else []
            )
            lines.append(
                _(
                    "dialog.open_browser.status.inkstitch_extension",
                    "Ink/Stitch extension: {path}",
                ).format(path=", ".join(paths))
                if paths
                else _("dialog.open_browser.status.inkstitch_missing")
            )
        elif extension_status.get("status") == "not_found":
            lines.append(_("dialog.open_browser.status.inkstitch_missing"))
        else:
            lines.append(_("dialog.open_browser.status.inkstitch_check_failed"))
        self.status_label.setText("\n".join(lines))
        self._update_actions()

    def _detect_tools(self) -> ToolStatus:
        detected = detect_tools()
        inkscape = prefer_saved_inkscape(self.config.get(INKSCAPE_CONFIG_KEY), detected.inkscape)
        return ToolStatus(inkscape=inkscape, inkstitch=detected.inkstitch)

    @staticmethod
    def _active_inkstitch_installation(status: dict[str, Any]) -> dict[str, Any] | None:
        return active_inkstitch_installation(status)

    def _cached_inkstitch_extension_status(self) -> dict[str, Any] | None:
        result = self.config.get(INKSCAPE_CONFIG_KEY)
        if not isinstance(result, dict):
            return None
        if not self.tool_status.has_inkscape:
            return result if result.get("status") == "found" else None
        command = self.tool_status.inkscape.command
        if not command:
            return None
        executable = result.get("executable")
        if not isinstance(executable, str):
            return None
        current_path = os.path.normcase(str(Path(command[0]).expanduser().resolve()))
        stored_path = os.path.normcase(str(Path(executable).expanduser().resolve()))
        return result if current_path == stored_path else None

    def _active_inkstitch_preview(self) -> tuple[Path, Path | None, Path] | None:
        status = self._cached_inkstitch_extension_status()
        return resolve_inkstitch_preview(status) if status else None

    def _inkstitch_process_environment(self, extension_dir: Path) -> dict[str, str]:
        status = self._cached_inkstitch_extension_status()
        return inkstitch_process_environment(extension_dir, status)

    def _refresh_tools(self, checked: bool = False) -> None:
        del checked
        self._update_tool_status()
        self._update_current_preview()

    def _open_tools_dialog(self, checked: bool = False) -> None:
        del checked
        dialog = InkscapeIntegrationDialog(self, self.tool_status.inkscape.path)
        dialog.exec()
        self._refresh_tools()

    def _update_current_preview(self) -> None:
        path = self._current_path()
        if path is None:
            return
        kind = self._kind_for_path(path)
        if kind == KIND_SVG:
            self._show_svg_preview(path)

    def refresh_files(self) -> None:
        if not self.current_directory.is_dir():
            self._show_message(
                _("dialog.open_browser.invalid_folder", "This folder is not accessible.")
            )
            return
        try:
            entries = list(self.current_directory.iterdir())
        except OSError as ex:
            self._show_message(
                _("dialog.open_browser.read_failed", "Cannot read this folder: {error}").format(
                    error=ex
                )
            )
            return

        self._svg_kind_cache.clear()
        directories = sorted(
            (path for path in entries if path.is_dir()), key=lambda path: path.name.casefold()
        )
        parent_directory = self.current_directory.parent
        parent_entry = [parent_directory] if parent_directory != self.current_directory else []
        files = sorted(
            (
                path
                for path in entries
                if path.is_file() and path.suffix.lstrip(".").lower() in self.extensions
            ),
            key=lambda path: path.name.casefold(),
        )
        self._all_paths = [*parent_entry, *directories, *files]
        self._refresh_breadcrumbs()
        self.add_favorite_button.setEnabled(self.current_directory not in self.favorite_directories)
        self._apply_filter()

    def _view_mode(self) -> str:
        return self.view_combo.currentData() or _VIEW_ICONS_TEXT

    def _on_skip_extensions_changed(self, text: str) -> None:
        self._skip_extensions = _parse_skip_extensions(text)
        self._skip_save_timer.start()
        self._apply_filter()

    def _store_skip_extensions(self) -> None:
        try:
            self.config.set(_SKIP_EXTENSIONS_CONFIG_KEY, "|".join(self._skip_extensions))
        except OSError as ex:
            logger.warning("Could not store the skipped extensions: %s", ex)

    def _on_icon_size_changed(self, size: int) -> None:
        self._icon_size = size
        self.icon_size_slider.setToolTip(
            _("dialog.open_browser.icon_size", "Icon size ({size} px)").format(size=size)
        )
        try:
            self.config.set(_ICON_SIZE_CONFIG_KEY, size)
        except OSError as ex:
            logger.warning("Could not store the icon size: %s", ex)
        self._apply_view_mode()

    def _apply_view_mode(self, *_args: object) -> None:
        """Switch between the compact list, the icon grid and the detail list."""
        mode = self._view_mode()
        details = mode == _VIEW_DETAILS
        self.details_header.setVisible(details)
        self.icon_size_slider.setEnabled(not details)
        self.file_list.setFont(self._mono_font if details else self._list_font)
        if mode == _VIEW_ICONS:
            self.file_list.setViewMode(QListView.ViewMode.IconMode)
            # Per-item scrolling leaves the wheel step at a single pixel, so one
            # notch would move the grid by three pixels and a folder of hundreds
            # of icons would crawl. Scrolling per pixel follows the grid row.
            self.file_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            self.file_list.setUniformItemSizes(True)
            self.file_list.setResizeMode(QListView.ResizeMode.Adjust)
            self.file_list.setMovement(QListView.Movement.Static)
            self.file_list.setGridSize(QSize(self._icon_size + 16, self._icon_size + 8))
            self.file_list.setIconSize(QSize(self._icon_size, self._icon_size))
            self.file_list.setWordWrap(False)
        else:
            self.file_list.setViewMode(QListView.ViewMode.ListMode)
            self.file_list.setUniformItemSizes(False)
            self.file_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
            self.file_list.setGridSize(QSize())
            icon_size = self._icon_size if mode == _VIEW_ICONS_TEXT else 24
            self.file_list.setIconSize(QSize(icon_size, icon_size))
            self.file_list.setWordWrap(mode == _VIEW_ICONS_TEXT)
        width = max(self.file_preview_splitter.width(), 900)
        share = {_VIEW_ICONS: 0.62, _VIEW_DETAILS: 0.58}.get(mode, 0.30)
        list_width = int(width * share)
        self.file_preview_splitter.setSizes([list_width, width - list_width])
        self.details_header.setText(
            f"{'    ' + _('dialog.open_browser.details.name', 'Name'):<40.40}"
            f" {_('dialog.open_browser.details.size', 'Size'):>10}"
            f" {_('dialog.open_browser.details.stitches', 'Stitches'):>9}"
            f" {_('dialog.open_browser.details.colors', 'Colors'):>6}"
        )
        # The first population happens in refresh_files(); filtering an empty
        # folder here would show the "no files" message before the scan runs.
        if self._all_paths:
            self._apply_filter()

    def _details_line(self, path: Path, kind: str, label: str) -> str:
        if kind == KIND_DIRECTORY:
            return label
        try:
            size = _format_size(path.stat().st_size)
        except OSError:
            size = ""
        stitches = colors = ""
        if kind in (KIND_EMBROIDERY, KIND_CSV):
            details = thumbnail_details(path)
            if details is not None:
                stitches = str(details.stitches)
                colors = str(details.colors)
        return f"{label:<40.40} {size:>10} {stitches:>9} {colors:>6}"

    def _apply_filter(self, *_args: object) -> None:
        query = self.search_edit.text().strip().casefold()
        selected_filter = self.filter_combo.currentData() or "all"
        current_path = self._current_path()
        visible: list[Path] = []
        parent_directory = self.current_directory.parent
        for path in self._all_paths:
            kind = self._kind_for_path(path)
            if kind == KIND_DIRECTORY:
                # Folders stay in the list, otherwise a file search leaves no way
                # to navigate to where the matches actually are.
                visible.append(path)
                continue
            if query and query not in path.name.casefold():
                continue
            if path.suffix.lstrip(".").casefold() in self._skip_extensions:
                continue
            if selected_filter != "all" and kind != selected_filter:
                continue
            visible.append(path)

        self._visible_paths = visible
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for path in visible:
            kind = self._kind_for_path(path)
            if kind == KIND_DIRECTORY:
                icon = self._folder_icon
            else:
                icon = self._thumbnail_icon(path) or self._file_icon
            label = (
                ".."
                if path == parent_directory and path != self.current_directory
                else f"{path.name}/"
                if kind == KIND_DIRECTORY
                else path.name
            )
            if self._view_mode() == _VIEW_ICONS:
                label = ""
            elif self._view_mode() == _VIEW_DETAILS:
                label = self._details_line(path, kind, label)
            item = QListWidgetItem(icon, label)
            if self._view_mode() == _VIEW_ICONS:
                # Keep the selection box around the icon instead of an empty text row.
                item.setSizeHint(QSize(self._icon_size, self._icon_size))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(_sanitize_path_text(str(path)))
            self.file_list.addItem(item)
        self.file_list.blockSignals(False)

        if not visible:
            self.selected_path = None
            self._preview_loaded = False
            self._show_message(_("dialog.open_browser.empty", "No supported files in this folder."))
            self.details_label.clear()
            self._update_actions()
            return

        target_row = 0
        if self._directory_return_path in visible:
            target_row = visible.index(self._directory_return_path)
        elif current_path in visible:
            target_row = visible.index(current_path)
        elif self.initial_file is not None and self.initial_file in visible:
            target_row = visible.index(self.initial_file)
        else:
            for index, path in enumerate(visible):
                if self._kind_for_path(path) != KIND_DIRECTORY:
                    target_row = index
                    break
        self._directory_return_path = None
        self.file_list.setCurrentRow(target_row)

    def _on_recent_selected(self, index: int) -> None:
        if index <= 0:
            return
        directory = self.recent_combo.itemText(index)
        self.recent_combo.setCurrentIndex(0)
        self.set_directory(directory)

    def _toggle_path_edit(self, checked: bool = False) -> None:
        del checked
        if self.path_stack.currentWidget() == self.path_editor_page:
            self.path_stack.setCurrentWidget(self.breadcrumb_scroll)
            self.edit_path_button.setText(_("dialog.open_browser.edit_path", "Edit path"))
            return
        self.path_entry.setText(_sanitize_path(self.current_directory))
        self.path_stack.setCurrentWidget(self.path_editor_page)
        self.edit_path_button.setText(_("dialog.open_browser.cancel", "Cancel"))
        self.path_entry.setFocus()
        self.path_entry.selectAll()

    def _apply_path_entry(self) -> None:
        path = Path(_unsanitize_path(self.path_entry.text())).expanduser().resolve()
        if not path.is_dir():
            self._show_message(
                _("dialog.open_browser.invalid_folder", "This folder is not accessible.")
            )
            return
        self.set_directory(path)
        self.path_stack.setCurrentWidget(self.breadcrumb_scroll)
        self.edit_path_button.setText(_("dialog.open_browser.edit_path", "Edit path"))

    def set_directory(self, directory: str | Path) -> None:
        path = Path(_unsanitize_path(str(directory))).expanduser().resolve()
        if not path.is_dir():
            self._show_message(
                _("dialog.open_browser.invalid_folder", "This folder is not accessible.")
            )
            return
        if path == self.current_directory:
            self.path_stack.setCurrentWidget(self.breadcrumb_scroll)
            self.edit_path_button.setText(_("dialog.open_browser.edit_path", "Edit path"))
            return
        self._directory_return_path = self.current_directory
        self.current_directory = path
        self.initial_file = None
        self.path_stack.setCurrentWidget(self.breadcrumb_scroll)
        self.edit_path_button.setText(_("dialog.open_browser.edit_path", "Edit path"))
        self.refresh_files()
        self.add_favorite_button.setEnabled(path not in self.favorite_directories)

    def _current_path(self) -> Path | None:
        item = self.file_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return Path(value) if value else None

    def _kind_for_path(self, path: Path) -> str:
        if path.is_dir():
            return KIND_DIRECTORY
        suffix = path.suffix.lstrip(".").lower()
        if suffix == "svg":
            kind = self._svg_kind_cache.get(path)
            if kind is None:
                kind = KIND_EMBROIDERY if is_stitchblock_svg(path) else KIND_SVG
                self._svg_kind_cache[path] = kind
            return kind
        if suffix == "csv":
            return KIND_CSV
        if suffix in self.extensions:
            return KIND_EMBROIDERY
        return KIND_OTHER

    def _type_label(self, kind: str) -> str:
        labels = {
            KIND_DIRECTORY: _("dialog.open_browser.type.directory", "Folder"),
            KIND_EMBROIDERY: _("dialog.open_browser.type.embroidery", "Embroidery"),
            KIND_SVG: _("dialog.open_browser.type.svg", "SVG source"),
            KIND_CSV: _("dialog.open_browser.type.csv", "CSV stitch data"),
            KIND_OTHER: _("dialog.open_browser.type.other", "Unsupported"),
        }
        return labels.get(kind, labels[KIND_OTHER])

    def _on_current_item_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            self.selected_path = None
            self._preview_loaded = False
            self.details_label.clear()
            self._show_message(_("dialog.open_browser.select_file", "Select a file to open."))
            self._update_actions()
            return

        path = Path(current.data(Qt.ItemDataRole.UserRole))
        kind = self._kind_for_path(path)
        self._palette_note = None
        self.preview_controls.setVisible(False)
        self.preview_csv_path = None
        self.document_path = None
        if kind == KIND_DIRECTORY:
            self.selected_path = None
            self._preview_loaded = False
            self._show_message(
                _(
                    "dialog.open_browser.folder_hint",
                    "Double-click the folder to browse its files.",
                )
            )
            self._update_details(path, kind)
            self._update_actions()
            return
        if kind == KIND_SVG:
            self.selected_path = path
            self._preview_loaded = False
            self._show_svg_preview(path)
            self._update_details(path, kind)
            self._update_actions()
            return
        if kind in (KIND_EMBROIDERY, KIND_CSV):
            self.selected_path = path
            self._preview_loaded = False
            self._preview_timer.start()
            self._update_details(path, kind)
            self._update_actions()
            return

        self.selected_path = None
        self._preview_loaded = False
        self._show_message(
            _(
                "dialog.open_browser.unsupported",
                "This file type cannot be opened in InkSim.",
            )
        )
        self._update_details(path, kind)
        self._update_actions()

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        if self._kind_for_path(path) == KIND_DIRECTORY:
            self.set_directory(path)
            return
        self._open_selected()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.file_list and event.type() == QEvent.Type.KeyPress:
            # Arrow keys belong to the list: in the icon grid they move between
            # icons, so directories are entered with Enter on the current row.
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return self._activate_current()
        return super().eventFilter(watched, event)

    def _activate_current(self) -> bool:
        """Enter on the current row: folders are entered, files are opened."""
        path = self._current_path()
        if path is None:
            return False
        if self._kind_for_path(path) == KIND_DIRECTORY:
            self.set_directory(path)
            return True
        if not self.open_button.isEnabled():
            return False
        self._open_selected()
        return True

    def _show_message(self, message: str) -> None:
        self.preview_controls.setVisible(False)
        self.message_label.setText(_sanitize_path_text(message))
        self.preview_stack.setCurrentWidget(self.message_page)

    def _show_svg_preview(self, path: Path) -> None:
        self._svg_source = None
        try:
            size = path.stat().st_size
        except OSError as ex:
            self._show_message(
                _(
                    "dialog.open_browser.file_read_failed",
                    "Cannot read this file: {error}",
                ).format(error=ex)
            )
            return
        if size > _MAX_SVG_THUMBNAIL_BYTES:
            self._show_message(
                _(
                    "dialog.open_browser.svg_too_large",
                    "This SVG is too large to preview here.",
                )
            )
            return
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            self._show_message(
                _("dialog.open_browser.svg_invalid", "The SVG could not be rendered.")
            )
            return
        svg_size = renderer.defaultSize()
        if svg_size.width() <= 0 or svg_size.height() <= 0:
            view_box = renderer.viewBoxF()
            svg_width, svg_height = view_box.width(), view_box.height()
        else:
            svg_width, svg_height = svg_size.width(), svg_size.height()
        aspect_ratio = svg_width / svg_height if svg_width > 0 and svg_height > 0 else 1.0
        if aspect_ratio >= 1.0:
            pixmap_size = QSize(1800, max(1, round(1800 / aspect_ratio)))
        else:
            pixmap_size = QSize(max(1, round(1400 * aspect_ratio)), 1400)
        pixmap = QPixmap(pixmap_size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            renderer.render(
                painter,
                QRectF(0.0, 0.0, float(pixmap.width()), float(pixmap.height())),
            )
        finally:
            painter.end()
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
            image.height(), image.bytesPerLine()
        )
        alpha = pixels[:, 3 : image.width() * 4 : 4]
        content_rows = np.flatnonzero(alpha.any(axis=1))
        content_columns = np.flatnonzero(alpha.any(axis=0))
        if content_rows.size and content_columns.size:
            left = max(0, int(content_columns[0]) - 4)
            top = max(0, int(content_rows[0]) - 4)
            right = min(image.width(), int(content_columns[-1]) + 5)
            bottom = min(image.height(), int(content_rows[-1]) + 5)
            pixmap = pixmap.copy(left, top, right - left, bottom - top)
        self._svg_source = pixmap
        self.svg_preview.set_source(pixmap)
        if self.tool_status.has_inkscape:
            caption = _(
                "dialog.open_browser.svg_caption_ready",
                "SVG source. Choose Preview to generate stitch data with Inkscape/Ink/Stitch.",
            )
        else:
            caption = _(
                "dialog.open_browser.svg_caption_needs_inkscape",
                "SVG source. Inkscape is required for stitch preview.",
            )
        self.svg_caption.setText(caption)
        self.preview_stack.setCurrentWidget(self.svg_page)
        self.preview_controls.setVisible(True)

    def _change_preview_zoom(self, factor: float) -> None:
        if self.preview_stack.currentWidget() == self.svg_page:
            self.svg_preview.zoom_by(factor)
        elif self._preview_loaded:
            self.preview.zoom_at(
                QPoint(self.preview.width() // 2, self.preview.height() // 2),
                factor,
            )

    def _fit_preview(self, checked: bool = False) -> None:
        del checked
        if self.preview_stack.currentWidget() == self.svg_page:
            self.svg_preview.fit_to_view()
        elif self._preview_loaded:
            self.preview._pending_fit_to_screen = False
            self.preview.fit_to_screen()

    def _apply_palette(self) -> None:
        """Store thread colors for a design whose format keeps none."""
        path = self.selected_path
        if path is None:
            return
        pattern = getattr(self.preview, "pattern", None)
        blocks = color_block_count(pattern) if pattern is not None else 0
        note = apply_palette_to_design(self, path, blocks, self.config)
        if note is None:
            return
        self._palette_note = note
        self._thumbnail_icons.pop(path, None)
        self._load_embroidery_preview()

    def _load_embroidery_preview(self) -> None:
        path = self.selected_path
        if path is None:
            return
        kind = self._kind_for_path(path)
        if kind not in (KIND_EMBROIDERY, KIND_CSV):
            return
        self.preview_stack.setCurrentWidget(self.preview_container)
        loaded = self.preview.load_design(
            str(path),
            fit_to_screen=True,
            precompute_density=False,
            show_error_dialog=False,
        )
        self._preview_loaded = loaded
        if not loaded:
            self._show_message(
                _("dialog.open_browser.not_embroidery", "Not a valid embroidery file")
            )
        else:
            self.preview_controls.setVisible(True)
        self._update_details(path, kind)
        self._update_actions()

    def _update_details(self, path: Path, kind: str) -> None:
        lines = [path.name, self._type_label(kind)]
        try:
            stat = path.stat()
        except OSError:
            self.details_label.setText("\n".join(lines))
            return
        lines.append(
            _("dialog.open_browser.size", "Size: {size}").format(size=_format_size(stat.st_size))
        )
        lines.append(
            _("dialog.open_browser.modified", "Modified: {time}").format(
                time=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            )
        )
        if kind in (KIND_EMBROIDERY, KIND_CSV) and self._preview_loaded:
            stitches = getattr(self.preview, "stitches_np", None)
            if stitches is not None:
                lines.append(
                    _("dialog.open_browser.stitches", "Stitches: {count}").format(
                        count=int(stitches.shape[0])
                    )
                )
            bounds = getattr(self.preview, "bounds", None)
            if bounds is not None:
                width_mm = float(bounds[2] - bounds[0])
                height_mm = float(bounds[3] - bounds[1])
                lines.append(
                    _(
                        "dialog.open_browser.dimensions",
                        "Size: {width:.1f} x {height:.1f} mm",
                    ).format(width=width_mm, height=height_mm)
                )
        if self._palette_note is not None and path == self.selected_path:
            lines.append(self._palette_note)
        self.details_label.setText("\n".join(lines))

    def _thumbnail_icon(self, path: Path) -> QIcon | None:
        cached = self._thumbnail_icons.get(path)
        if cached is not None:
            return cached
        thumbnail = thumbnail_path(path)
        if not thumbnail.is_file():
            return None
        icon = QIcon(str(thumbnail))
        if icon.isNull():
            return None
        self._thumbnail_icons[path] = icon
        return icon

    def _selected_design_paths(self) -> list[Path]:
        paths: list[Path] = []
        for item in self.file_list.selectedItems():
            value = item.data(Qt.ItemDataRole.UserRole)
            if not value:
                continue
            path = Path(value)
            if self._kind_for_path(path) in (KIND_EMBROIDERY, KIND_CSV, KIND_SVG):
                paths.append(path)
        return sorted(paths)

    def _select_thumbnail_mode(self, mode: str) -> None:
        """Show the chosen action on the button itself, without running it."""
        self._thumbnail_mode = mode
        action = self._thumbnail_actions.get(mode)
        if action is None:
            return
        action.setChecked(True)
        self.thumbnails_button.setText(action.text())

    def _run_thumbnail_action(self) -> None:
        self._create_thumbnails(regenerate=self._thumbnail_mode == _THUMBNAIL_REGENERATE)

    def _create_thumbnails(self, regenerate: bool = False) -> None:
        """Write sidecar thumbnails for every selected design.

        Without *regenerate* only missing or outdated images are written, so a
        repeated run is cheap; the menu forces a full rebuild instead.
        """
        if self._thumbnail_job is not None:
            return
        paths = self._selected_design_paths()
        if not paths:
            return
        job = ThumbnailJob(paths, regenerate=regenerate)
        job.signals.progress.connect(self._on_thumbnail_progress)
        job.signals.finished.connect(self._on_thumbnails_finished)
        self._thumbnail_job = job
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.activity_label.setText(
            _("dialog.open_browser.thumbnails_running", "Creating thumbnails…")
        )
        self.activity_label.setVisible(True)
        self._update_actions()
        self._thumbnail_pool.start(job)

    def _on_thumbnail_progress(self, done: int, total: int) -> None:
        self.progress.setValue(done)
        self.activity_label.setText(
            _("dialog.open_browser.thumbnails_progress", "Thumbnails: {done}/{total}").format(
                done=done, total=total
            )
        )

    def _on_thumbnails_finished(self, created: int, skipped: int, failed: int) -> None:
        self._thumbnail_job = None
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        self.activity_label.setText(
            _(
                "dialog.open_browser.thumbnails_done",
                "Thumbnails: {created} created, {skipped} up to date, {failed} failed",
            ).format(created=created, skipped=skipped, failed=failed)
        )
        self._refresh_thumbnail_icons()
        self._update_actions()

    def _refresh_thumbnail_icons(self) -> None:
        self._thumbnail_icons.clear()
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            value = item.data(Qt.ItemDataRole.UserRole)
            if not value:
                continue
            path = Path(value)
            if self._kind_for_path(path) == KIND_DIRECTORY:
                continue
            item.setIcon(self._thumbnail_icon(path) or self._file_icon)

    def _stop_thumbnail_job(self) -> None:
        job = self._thumbnail_job
        if job is None:
            return
        job.stop()
        self._thumbnail_pool.waitForDone(2000)
        self._thumbnail_job = None

    def _update_actions(self) -> None:
        path = self._current_path()
        kind = self._kind_for_path(path) if path is not None else None
        converting = self._conversion_process is not None
        generating = self._thumbnail_job is not None
        self.thumbnails_button.setEnabled(
            not converting and not generating and bool(self._selected_design_paths())
        )

        self.palette_button.setEnabled(
            not converting and not generating and kind in (KIND_EMBROIDERY, KIND_CSV)
        )

        if converting or generating:
            self.open_button.setEnabled(False)
            self.edit_button.setEnabled(False)
            self.cancel_button.setEnabled(True)
            return

        can_open = False
        can_edit = False
        open_label = _("dialog.open_browser.open", "Open")
        open_tip = ""
        edit_tip = ""
        if kind in (KIND_EMBROIDERY, KIND_CSV):
            can_open = self._preview_loaded
            open_tip = _(
                "dialog.open_browser.open_hint",
                "Open the selected embroidery file.",
            )
            if kind == KIND_EMBROIDERY and path is not None and path.suffix.lower() == ".svg":
                can_edit = self.tool_status.can_edit_svg
                edit_tip = _(
                    "dialog.open_browser.edit_hint",
                    "Open this SVG in a new Inkscape window.",
                )
                if not self.tool_status.has_inkscape:
                    edit_tip = _(
                        "dialog.open_browser.inkscape_required",
                        "Inkscape is required to edit SVG files.",
                    )
        elif kind == KIND_SVG:
            open_label = _("dialog.open_browser.preview", "Preview")
            can_open = self._active_inkstitch_preview() is not None
            can_edit = self.tool_status.can_edit_svg
            open_tip = _(
                "dialog.open_browser.preview_hint",
                "Generate stitch data from this SVG with Inkscape/Ink/Stitch.",
            )
            edit_tip = _(
                "dialog.open_browser.edit_hint",
                "Open this SVG in a new Inkscape window.",
            )
            if not can_open:
                open_tip = _(
                    "dialog.open_browser.inkstitch_required",
                    "A configured Ink/Stitch installation and Python launcher are required.",
                )
            if not self.tool_status.has_inkscape:
                edit_tip = _(
                    "dialog.open_browser.inkscape_required",
                    "Inkscape is required to edit SVG files.",
                )
        elif kind == KIND_DIRECTORY:
            open_tip = _(
                "dialog.open_browser.folder_open_hint",
                "Press Enter or double-click the folder to browse its files.",
            )
        else:
            open_tip = _(
                "dialog.open_browser.unsupported",
                "This file type cannot be opened in InkSim.",
            )

        self.open_button.setText(open_label)
        self.open_button.setEnabled(can_open)
        self.open_button.setToolTip(open_tip)
        self.edit_button.setEnabled(can_edit)
        self.edit_button.setToolTip(edit_tip)
        self.cancel_button.setEnabled(True)

    def _open_selected(self, checked: bool = False) -> None:
        del checked
        path = self._current_path()
        if path is None:
            return
        kind = self._kind_for_path(path)
        if kind in (KIND_EMBROIDERY, KIND_CSV):
            if not self._preview_loaded:
                return
            self.selected_path = path
            self.result_action = "open"
            self.accept()
            return
        if kind == KIND_SVG:
            self._start_svg_conversion(path)

    def _start_svg_conversion(self, path: Path) -> None:
        preview = self._active_inkstitch_preview()
        if preview is None:
            QMessageBox.warning(
                self,
                _("dialog.open_browser.title", "Open file"),
                _("dialog.open_browser.preview_unavailable"),
            )
            return
        script_path, python_path, extension_dir = preview
        program = str(python_path) if python_path is not None else str(script_path)
        arguments = ([str(script_path)] if python_path is not None else []) + [
            "--extension=output",
            "--format=csv",
            "--skip_palette=true",
            str(path),
        ]

        try:
            csv_path, error_path = _create_temporary_conversion_files()
        except OSError as ex:
            QMessageBox.warning(
                self,
                _("dialog.open_browser.title", "Open file"),
                _("dialog.open_browser.temp_file_failed").format(
                    error=_sanitize_path_text(str(ex))
                ),
            )
            return

        self._conversion_csv = csv_path
        self._conversion_error = error_path
        self._conversion_source = path
        self._conversion_aborted = False
        self._conversion_estimate_seconds = self._get_conversion_estimate()
        self._conversion_started_at = time.monotonic()
        process = QProcess(self)
        if sys.platform == "win32" and hasattr(process, "setCreateProcessArgumentsModifier"):
            process.setCreateProcessArgumentsModifier(_hide_windows_console)
        process.setProgram(program)
        process.setArguments(arguments)
        process.setWorkingDirectory(str(script_path.parent))
        process.setStandardOutputFile(str(csv_path))
        process.setStandardErrorFile(str(error_path))
        process_environment = QProcessEnvironment()
        for key, value in self._inkstitch_process_environment(extension_dir).items():
            process_environment.insert(key, value)
        process.setProcessEnvironment(process_environment)
        process.finished.connect(self._on_conversion_finished)
        process.errorOccurred.connect(self._on_conversion_error)
        self._conversion_process = process
        self.progress.setVisible(True)
        self.activity_label.setText(_("dialog.open_browser.converting"))
        self.activity_label.setVisible(True)
        self._update_actions()
        process.start()
        if not process.waitForStarted(3000):
            self._discard_conversion_csv()
            if not self._conversion_aborted:
                self._finish_conversion_ui()
                QMessageBox.warning(
                    self,
                    _("dialog.open_browser.title", "Open file"),
                    _(
                        "dialog.open_browser.inkscape_launch_failed",
                        "Inkscape could not be started: {error}",
                    ).format(error=_sanitize_path_text(process.errorString())),
                )
            return
        self._conversion_progress_timer.start()
        self._conversion_timer.start(_CONVERSION_TIMEOUT_MS)

    def _get_conversion_estimate(self) -> float:
        timing = self.config.get(_PREVIEW_TIMING_CONFIG_KEY)
        if timing is None:
            return _INITIAL_PREVIEW_ESTIMATE_SECONDS
        stats = _preview_timing_stats(timing)
        if stats is None:
            logger.warning("Ignoring invalid SVG preview timing configuration")
            return _INITIAL_PREVIEW_ESTIMATE_SECONDS
        total_seconds, count = stats
        if count == 0:
            return _INITIAL_PREVIEW_ESTIMATE_SECONDS
        return min(
            _MAX_PREVIEW_ESTIMATE_SECONDS,
            max(_INITIAL_PREVIEW_ESTIMATE_SECONDS, total_seconds / count),
        )

    def _update_conversion_progress(self) -> None:
        if self._conversion_started_at is None:
            return
        elapsed = max(0.0, time.monotonic() - self._conversion_started_at)
        fraction = elapsed / self._conversion_estimate_seconds
        self.progress.setValue(min(99, int(fraction * 100)))

    def _record_conversion_duration(self) -> None:
        started_at = self._conversion_started_at
        self._conversion_started_at = None
        if started_at is None:
            return
        elapsed = time.monotonic() - started_at
        if not math.isfinite(elapsed) or elapsed <= 0:
            logger.warning("Skipping invalid SVG preview duration measurement")
            return

        def add_measurement(value: object) -> dict[str, float | int]:
            stats = _preview_timing_stats(value)
            if stats is None:
                if value is not None:
                    logger.warning("Resetting invalid SVG preview timing configuration")
                total_seconds, count = 0.0, 0
            else:
                total_seconds, count = stats
            return {
                "total_seconds": total_seconds + elapsed,
                "count": count + 1,
            }

        try:
            self.config.update(_PREVIEW_TIMING_CONFIG_KEY, add_measurement)
        except (FileLockTimeout, OSError, TypeError, ValueError) as ex:
            logger.warning("Could not save SVG preview timing configuration: %s", ex)

    def _on_conversion_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        del exit_status
        if self._closing or self._conversion_aborted:
            self._discard_conversion_csv()
            _remove_temporary_file(self._conversion_error, "temporary Ink/Stitch log")
            return
        self._record_conversion_duration()
        self.progress.setValue(100)
        csv_path = self._conversion_csv
        error_path = self._conversion_error
        source_path = self._conversion_source
        self._finish_conversion_ui()
        try:
            has_output = csv_path is not None and csv_path.is_file() and csv_path.stat().st_size > 0
        except OSError:
            has_output = False
        if exit_code == 0 and has_output:
            _remove_temporary_file(error_path, "temporary Ink/Stitch log")
            self.preview_csv_path = csv_path
            self._conversion_csv = None
            self.document_path = source_path
            self.selected_path = source_path
            self.result_action = "preview"
            self.accept()
            return

        try:
            stderr_text = (
                error_path.read_text(encoding="utf-8", errors="replace").strip()
                if error_path is not None and error_path.is_file()
                else ""
            )
        except OSError as ex:
            stderr_text = str(ex)
        self._discard_conversion_csv()
        log_path = _store_conversion_log(source_path, error_path, stderr_text)
        message = _(
            "dialog.open_browser.conversion_failed",
            "Ink/Stitch CSV export failed.",
        )
        if log_path is not None:
            message += "\n\n" + _(
                "dialog.open_browser.conversion_hint",
                "Full log: {path}",
            ).format(path=str(log_path))
        if stderr_text:
            message += "\n\n" + stderr_text[-1200:]
        message += f"\n\n{_('dialog.open_browser.conversion_exit_code').format(code=exit_code)}"
        QMessageBox.warning(
            self,
            _("dialog.open_browser.title", "Open file"),
            _sanitize_path_text(message),
        )

    def _on_conversion_error(self, error: QProcess.ProcessError) -> None:
        if self._closing or self._conversion_aborted:
            return
        self._conversion_aborted = True
        process = self._conversion_process
        if process is not None and process.state() == QProcess.ProcessState.Running:
            process.kill()
            process.waitForFinished(2000)
        self._discard_conversion_csv()
        _remove_temporary_file(self._conversion_error, "temporary Ink/Stitch log")
        self._finish_conversion_ui()
        QMessageBox.warning(
            self,
            _("dialog.open_browser.title", "Open file"),
            _(
                "dialog.open_browser.conversion_error",
                "The stitch preview process failed: {error}",
            ).format(error=_sanitize_path_text(str(error))),
        )

    def _on_conversion_timeout(self) -> None:
        self._conversion_aborted = True
        process = self._conversion_process
        if process is not None:
            process.kill()
            process.waitForFinished(2000)
        self._discard_conversion_csv()
        _remove_temporary_file(self._conversion_error, "temporary Ink/Stitch log")
        self._finish_conversion_ui()
        if not self._closing:
            QMessageBox.warning(
                self,
                _("dialog.open_browser.title", "Open file"),
                _(
                    "dialog.open_browser.conversion_timeout",
                    "Stitch preview timed out.",
                ),
            )

    def _finish_conversion_ui(self) -> None:
        self._conversion_timer.stop()
        self._conversion_progress_timer.stop()
        self._conversion_started_at = None
        self.progress.setVisible(False)
        self.activity_label.setVisible(False)
        process = self._conversion_process
        self._conversion_process = None
        if process is not None:
            process.deleteLater()
        self._conversion_error = None
        self._update_actions()

    def _edit_in_inkscape(self, checked: bool = False) -> None:
        del checked
        path = self._current_path()
        if path is None or path.suffix.lower() != ".svg":
            return
        if self._kind_for_path(path) not in (KIND_SVG, KIND_EMBROIDERY):
            return
        command = self.tool_status.inkscape.command
        if not command:
            QMessageBox.warning(
                self,
                _("dialog.open_browser.title", "Open file"),
                _(
                    "dialog.open_browser.inkscape_required",
                    "Inkscape is required to edit SVG files.",
                ),
            )
            return
        tag = f"inksim-{uuid.uuid4().hex[:12]}"
        arguments = [*command[1:], f"--app-id-tag={tag}", str(path)]
        try:
            child_env = clean_child_environment()
            if os.name == "nt":
                subprocess.Popen(
                    [command[0], *arguments],
                    env=child_env,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                subprocess.Popen(
                    [command[0], *arguments],
                    env=child_env,
                    start_new_session=True,
                )
        except OSError as ex:
            QMessageBox.warning(
                self,
                _("dialog.open_browser.title", "Open file"),
                _(
                    "dialog.open_browser.inkscape_launch_failed",
                    "Inkscape could not be started: {error}",
                ).format(error=_sanitize_path_text(str(ex))),
            )
            return
        self.selected_path = path
        self.document_path = path
        self.result_action = "edit"
        self.accept()

    def done(self, result: int) -> None:
        """Stop the conversion process and release preview GL resources."""
        self._closing = True
        self._stop_thumbnail_job()
        self._conversion_timer.stop()
        self._conversion_progress_timer.stop()
        if self._skip_save_timer.isActive():
            self._skip_save_timer.stop()
            self._store_skip_extensions()
        self._conversion_started_at = None
        process = self._conversion_process
        if process is not None:
            if process.state() == QProcess.ProcessState.Running:
                process.kill()
                process.waitForFinished(2000)
            process.deleteLater()
            self._conversion_process = None
        self._discard_conversion_csv()
        self.preview._gl_widget.cleanup()
        super().done(result)

    def _discard_conversion_csv(self) -> None:
        csv_path = self._conversion_csv
        self._conversion_csv = None
        _remove_temporary_file(csv_path, "temporary preview CSV")

    @property
    def background_color(self) -> tuple[int, int, int]:
        """Return the preview viewer's background colour chosen by the user."""
        return self.preview.background_color


def _parse_skip_extensions(text: str) -> tuple[str, ...]:
    """Split "edr|dst, .EXP" into the skipped lowercase extensions."""
    tokens = (token.strip().lstrip(".") for token in re.split(r"[|,;\s]+", text))
    return tuple(token.casefold() for token in tokens if token)


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} GB"
