# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pystitch as emb
from PySide6.QtCore import QEvent, QObject, QProcess, QRect, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QImage,
    QKeySequence,
    QMoveEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from ..constants import APP_TITLE, DEFAULT_STATUS_TEXT
from ..debug import logger
from ..formats import (
    extension_from_output_filter,
    get_supported_output_filter,
    get_supported_output_formats,
)
from ..i18n import (
    _,
    active_locale,
    available_locales,
    clear_active_locale,
    get_language_name,
    set_active_locale,
)
from ..render import render_export_image
from ..runtime import _sanitize_path, _unsanitize_path
from ..update_check import (
    UpdateCheckThread,
    current_version,
    is_newer,
    last_result,
    record_check,
    record_result,
    should_check,
)
from .about import show_about
from .config_editor import show_config_editor
from .dialogs import EmbroideryOpenDialog
from .export_dialog import ExportPreviewDialog
from .help import show_command_line_help
from .shortcuts import ViewerShortcutFilter
from .status import ModeBar
from .timeline import TimelineWidget
from .viewer import EmbroideryViewerWidget


class MainWindow(QMainWindow):
    """Main InkSim window coordinating the viewer and playback controls."""

    def __init__(
        self,
        fullscreen: bool = False,
        window_size: tuple[int, int] | None = None,
        window_position: tuple[int, int] | None = None,
        server_mode: bool = False,
        delete_input: bool = False,
        document_path: str | Path | None = None,
        snap_layout_key: str | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(
            QIcon(str(Path(__file__).parent.parent / "assets" / "app_icons" / "inksim.svg"))
        )
        self._default_size: tuple[int, int] = window_size or (1200, 980)
        self.resize(*self._default_size)
        self.setAcceptDrops(True)
        self.is_fullscreen: bool = False
        self._fullscreen_was_maximized: bool = False
        self.server_mode: bool = server_mode
        self._delete_input: bool = delete_input
        self._allow_close: bool = False
        self._startup_fullscreen: bool = fullscreen
        self._should_maximize_default: bool = not window_size and not fullscreen
        self.config: Config = Config()
        self._snap_layout_key: str | None = snap_layout_key
        self.last_directory: str = _unsanitize_path(self.config.get("last_directory", ""))
        self.export_transparent_background: bool = self.config.get(
            "export_transparent_background", False
        )
        self.document_path: Path | None = None
        if document_path is not None:
            self.set_document_path(document_path)
        self.recent_directories: list[str] = self._load_recent_directories()
        self.current_file_path: Path | None = None
        self._source_mtime_ns: int | None = None
        self._last_source_check: float = 0.0
        self._source_check_interval_s: float = 0.4
        self._is_reloading_from_disk: bool = False
        self._layout_state: str = "free"
        self._layout_changing: bool = False
        self._free_geometry: QRect | None = None
        self._free_maximized: bool = False
        self._snapped_geometry: QRect | None = None
        self._last_geometry: QRect = self.geometry()
        self._base_title: str = APP_TITLE
        self._update_thread: UpdateCheckThread | None = None
        self._update_suffix: str = self._resolve_update_suffix(last_result(self.config))
        self._update_window_title()

        main_panel = QWidget(self)
        layout = QVBoxLayout(main_panel)
        self.viewer: EmbroideryViewerWidget = EmbroideryViewerWidget(main_panel, None, self.config)
        self.progress: TimelineWidget = TimelineWidget(main_panel, self.viewer)
        self.mode_status: ModeBar = ModeBar(main_panel, self.viewer)
        self.progress.seek_requested.connect(self.viewer.seek_to)
        self.viewer.mode_panel = self.mode_status
        self.viewer.progress_bar = self.progress
        layout.addWidget(self.viewer, 1)
        layout.addWidget(self.mode_status)
        layout.addWidget(self.progress)
        self.setCentralWidget(main_panel)
        self._main_panel: QWidget = main_panel
        self._updating_command_panel: bool = False
        self._build_command_dock()
        self.viewer.cursor_changed.connect(self._sync_command_panel_cursor)
        self.shortcut_filter: ViewerShortcutFilter = ViewerShortcutFilter(self, self.viewer)
        self._build_menus()
        self.statusBar().showMessage(DEFAULT_STATUS_TEXT)
        app = QApplication.instance()
        assert app is not None
        app.installEventFilter(self)

        if window_position:
            self.move(*window_position)
        elif not window_size and not fullscreen:
            self._restore_window_layout()

    def set_snap_layout_key(self, key: str | None) -> None:
        """Switch the snap-layout profile used for save/restore."""
        if not key:
            return
        self._snap_layout_key = key
        if self._layout_state == "snapped":
            self._restore_snap_layout()

    def _layout_config_key(self, key: str | None = None) -> str:
        """Return the config section name for the active layout profile."""
        key = key or self._snap_layout_key
        if key:
            return f"window_layout_snap/{key}"
        return "window_layout"

    def _restore_window_layout(self) -> None:
        """Restore the last saved window geometry, falling back to centred."""
        layout = self.config.get(self._layout_config_key(), {})
        if not isinstance(layout, dict):
            layout = {}
        x = layout.get("x")
        y = layout.get("y")
        width = layout.get("width")
        height = layout.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            self.resize(width, height)
        if isinstance(x, int) and isinstance(y, int):
            self.move(x, y)
        else:
            self.move(self.screen().availableGeometry().center() - self.rect().center())
        if layout.get("maximized"):
            self.showMaximized()

    def _has_snap_layout(self) -> bool:
        """Return True when a saved snap layout exists for the active profile."""
        layout = self.config.get(self._layout_config_key(), {})
        return isinstance(layout, dict) and layout.get("x") is not None

    def _restore_snap_layout(self) -> None:
        """Restore the snapped geometry for the active profile."""
        layout = self.config.get(self._layout_config_key(), {})
        if isinstance(layout, dict) and layout.get("x") is not None:
            self._snapped_geometry = QRect(
                layout["x"], layout["y"], layout["width"], layout["height"]
            )
        else:
            self._snapped_geometry = self._default_snapped_geometry()
        self.setGeometry(self._snapped_geometry)
        self._last_geometry = self._snapped_geometry

    def _save_window_layout(self) -> None:
        """Persist the current window geometry to the active profile."""
        if self.is_fullscreen or self.isMinimized():
            return
        geo = self.geometry()
        layout = {
            "x": geo.x(),
            "y": geo.y(),
            "width": geo.width(),
            "height": geo.height(),
            "maximized": self.isMaximized(),
        }
        self.config.set(self._layout_config_key(), layout)

    def _save_snap_layout(self) -> None:
        """Persist the current snapped geometry if it is valid."""
        if self._snapped_geometry is None:
            return
        geo = self._snapped_geometry
        self.config.set(
            self._layout_config_key(),
            {"x": geo.x(), "y": geo.y(), "width": geo.width(), "height": geo.height()},
        )

    def _save_current_snap_position(self, checked: bool = False) -> None:
        """Save the current snapped geometry under the active profile."""
        if self._layout_state != "snapped":
            self.statusBar().showMessage("Switch to snap layout first (press M).", 3000)
            return
        self._save_snap_layout()
        key_text = f" ({self._snap_layout_key})" if self._snap_layout_key else ""
        self.statusBar().showMessage(f"Snap position saved{key_text}.", 3000)

    def _clear_saved_snap_position(self, checked: bool = False) -> None:
        """Remove the saved snap geometry for the active profile."""
        self.config.delete(self._layout_config_key())
        key_text = f" ({self._snap_layout_key})" if self._snap_layout_key else ""
        self.statusBar().showMessage(f"Saved snap position cleared{key_text}.", 3000)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if self._is_reloading_from_disk:
            return False
        if self.current_file_path is None:
            return False
        if event is None:
            return False
        event_type = event.type()
        if event_type not in {
            QEvent.KeyPress,
            QEvent.MouseButtonPress,
            QEvent.MouseButtonDblClick,
            QEvent.Wheel,
        }:
            return False
        watched_window = getattr(watched, "window", None)
        if watched_window is None or watched_window() is not self:
            return False
        self._reload_if_source_changed()
        return False

    def _capture_source_mtime(self, file_path: Path | str) -> int | None:
        try:
            return Path(file_path).stat().st_mtime_ns
        except OSError:
            return None

    def _show_reload_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        dialog.setModal(True)
        dialog.setWindowTitle(_("message.reload.title"))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(QLabel("File changed on disk. Reloading...", dialog))
        dialog.adjustSize()
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.show()
        QApplication.processEvents()
        return dialog

    def _reload_if_source_changed(self) -> None:
        now = time.monotonic()
        if now - self._last_source_check < self._source_check_interval_s:
            return
        self._last_source_check = now
        if self.current_file_path is None:
            return
        current_mtime = self._capture_source_mtime(self.current_file_path)
        if current_mtime is None:
            return
        if self._source_mtime_ns is None:
            self._source_mtime_ns = current_mtime
            return
        if current_mtime == self._source_mtime_ns:
            return
        self._is_reloading_from_disk = True
        dialog = self._show_reload_dialog()
        try:
            self.open_file(str(self.current_file_path))
        finally:
            dialog.close()
            self._is_reloading_from_disk = False

    def _load_recent_directories(self) -> list[str]:
        """Load the last opened embroidery directories from TOML config."""
        values = self.config.get("recent_directories", [])
        if not isinstance(values, list):
            values = []
        seen: set[Path] = set()
        result: list[str] = []
        for value in values:
            path = Path(_unsanitize_path(str(value))).resolve()
            if path.is_dir() and path not in seen:
                seen.add(path)
                result.append(str(path))
                if len(result) >= 10:
                    break
        return result

    def _save_recent_directories(self) -> None:
        """Persist the recent-directory list back to TOML config."""
        compact = [_sanitize_path(d) for d in self.recent_directories]
        self.config.set("recent_directories", compact)

    def _add_recent_directory(self, directory: Path | str) -> None:
        """Move *directory* to the front of the recent list, cap at 10."""
        path = Path(str(directory)).resolve()
        if not path.is_dir():
            return
        text = str(path)
        self.recent_directories = [text] + [d for d in self.recent_directories if d != text][:9]
        self._save_recent_directories()

    def show_initial_window(
        self, autoplay: bool = False, initial_directory: str | Path | None = None
    ) -> None:
        """Show the fully initialized window after optional startup work."""
        if self._startup_fullscreen:
            self.is_fullscreen = True
            self.mode_status.hide()
            self.show()
            self.showFullScreen()
        elif self._snap_layout_key and self._has_snap_layout():
            self.show()
            self._restore_snap_layout()
            self._layout_state = "snapped"
            self._free_maximized = True
            self._update_window_title()
            QTimer.singleShot(0, self._update_snap_menu_state)
        elif self._should_maximize_default:
            self.show()
            self.showMaximized()
        else:
            self.show()
        QTimer.singleShot(0, lambda: self._finish_initial_display(autoplay))
        QTimer.singleShot(1500, self._maybe_auto_check_updates)
        if initial_directory:
            directory_path = Path(initial_directory)
            if directory_path.is_dir():
                self.last_directory = str(directory_path.resolve())
            QTimer.singleShot(0, self.open_file_dialog)

    def _action(
        self,
        menu: QMenu | None,
        text: str,
        slot: Callable[..., None],
        shortcut: str | None = None,
        checkable: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))

        def _traced_slot(checked: bool = False) -> None:
            self.viewer._trace_event(shortcut or "")
            try:
                slot(checked)
            except TypeError:
                slot()

        action.triggered.connect(_traced_slot if shortcut else slot)
        if menu is not None:
            menu.addAction(action)
        return action

    def _add_separator(self, menu: QMenu | None) -> None:
        if menu is not None:
            menu.addSeparator()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu(_("menu.file"))
        self._action(file_menu, _("menu.file.open"), self.open_file_dialog, "Ctrl+O")
        self._action(file_menu, _("menu.file.save_as"), self._save_as_embroidery_slot, "Ctrl+S")
        export_menu = file_menu.addMenu(_("menu.file.export"))
        self._action(
            export_menu, _("menu.file.export.shaded_print"), self.export_shaded_png, "Ctrl+E"
        )
        self._action(export_menu, _("menu.file.export.icon"), self.export_icon_png)
        self._action(export_menu, _("menu.file.export.simple_print"), self.export_print_png)
        self._action(file_menu, _("menu.file.center_needle"), self._center_needle_slot, "C")
        self._action(file_menu, _("menu.file.fit_design"), self._fit_to_screen_slot, "F")
        self._action(file_menu, _("menu.file.calibrate"), self._calibrate_display_slot)
        self.grid_action = self._action(
            file_menu, _("menu.file.show_grid"), self.toggle_grid, "G", True
        )
        self.grid_action.setChecked(True)
        self.realistic_action = self._action(
            file_menu, _("menu.file.gpu_textured_render"), self.toggle_realistic, "Z", True
        )
        self.viewer.grid_toggled.connect(self.grid_action.setChecked)
        self.viewer.renderer_changed.connect(
            lambda renderer: self.realistic_action.setChecked(renderer == "gpu_textured")
        )
        # The renderer may already be restored from config before this action
        # is created, so sync the checkbox with the current state now.
        self.realistic_action.setChecked(self.viewer.active_renderer == "gpu_textured")
        self.viewer.fullscreen_requested.connect(self.toggle_full_screen)
        self.viewer.status_message.connect(self.statusBar().showMessage)
        self._action(file_menu, _("menu.file.choose_renderer"), self._select_renderer_slot, "R")
        self._add_separator(file_menu)
        self._action(
            file_menu, _("menu.file.rotate_left"), lambda checked: self.viewer.rotate_design(-1)
        )
        self._action(
            file_menu, _("menu.file.rotate_right"), lambda checked: self.viewer.rotate_design(1)
        )
        self._add_separator(file_menu)
        self._action(file_menu, _("menu.file.quit"), self.request_quit, "Ctrl+Q")
        self._add_separator(file_menu)
        view_menu = self.menuBar().addMenu(_("menu.view"))
        self._action(view_menu, _("menu.view.actual_size"), self._set_one_to_one_slot, "1")
        self._action(view_menu, _("menu.view.fullscreen"), self.toggle_full_screen, "F11")
        view_menu.addSeparator()
        self.command_panel_action = self._action(
            view_menu,
            _("menu.view.command_list"),
            self.toggle_command_panel,
            "Ctrl+L",
            True,
        )
        self.command_panel_action.setChecked(False)
        self._action(
            view_menu,
            _("menu.view.show_hide_all"),
            self._toggle_show_all_slot,
            "Ctrl+A",
        )
        self.needle_action = self._action(
            view_menu,
            _("menu.view.show_needle"),
            self.toggle_needle,
            "N",
            True,
        )
        self.needle_action.setChecked(True)
        self.viewer.show_needle_toggled.connect(self.needle_action.setChecked)
        self.layout_action = self._action(
            view_menu,
            _("menu.view.snap_layout"),
            self.toggle_window_layout,
            "M",
        )
        self.layout_action.triggered.connect(self._update_snap_menu_state)
        view_menu.addSeparator()
        self.save_snap_action = self._action(
            view_menu,
            _("menu.view.save_snap"),
            self._save_current_snap_position,
        )
        self.clear_snap_action = self._action(
            view_menu,
            _("menu.view.clear_snap"),
            self._clear_saved_snap_position,
        )
        self._update_snap_menu_state()
        view_menu.addSeparator()
        self._action(view_menu, _("menu.view.cycle_bg"), self._cycle_background_slot, "B")
        playback = self.menuBar().addMenu(_("menu.playback"))
        self._action(playback, _("menu.playback.play_pause"), self._toggle_auto_play_slot, "Space")
        playback.addSeparator()
        self._action(playback, _("menu.playback.prev_color"), self._prev_color_slot, "Ctrl+Left")
        self._action(playback, _("menu.playback.next_color"), self._next_color_slot, "Ctrl+Right")
        playback.addSeparator()
        self._action(
            playback, _("menu.playback.prev_command"), self._prev_command_slot, "Shift+Left"
        )
        self._action(
            playback, _("menu.playback.next_command"), self._next_command_slot, "Shift+Right"
        )
        language_menu = self.menuBar().addMenu(_("menu.language", "Language"))
        current = active_locale()
        language_group = QActionGroup(self)
        language_group.setExclusive(True)

        system_action = self._action(
            language_menu,
            _("menu.language.system_default", "System default"),
            self._clear_language_slot,
        )
        system_action.setCheckable(True)
        system_action.setChecked(self.config.get("language") is None)
        language_group.addAction(system_action)
        language_menu.addSeparator()

        for locale in available_locales():
            name = get_language_name(locale)
            action = self._action(
                language_menu,
                f"{name} ({locale})",
                lambda checked=False, loc=locale: self._set_language_slot(loc),
            )
            action.setCheckable(True)
            action.setChecked(locale == current)
            language_group.addAction(action)

        help_menu = self.menuBar().addMenu(_("menu.help"))
        self._action(help_menu, _("menu.help.help"), self._show_help_slot, "H")
        self._action(help_menu, _("menu.help.status"), self._show_settings_slot, "I")
        self._action(help_menu, _("menu.help.config"), self._show_config_editor_slot)
        self._action(
            help_menu,
            _("menu.help.cli_options"),
            self._show_command_line_help_slot,
        )
        self.trace_action: QAction = self._action(
            help_menu,
            _("menu.help.trace_events"),
            self._trace_events_slot,
            "Ctrl+T",
            checkable=True,
        )
        self._action(
            help_menu, _("menu.help.about").format(app_title=APP_TITLE), self._show_about_slot
        )
        help_menu.addSeparator()
        self._action(help_menu, _("menu.help.check_updates"), self._check_for_updates)

    def _center_needle_slot(self, checked: bool = False) -> None:
        self.viewer.center_needle()

    def _fit_to_screen_slot(self, checked: bool = False) -> None:
        self.viewer.fit_to_screen()

    def _calibrate_display_slot(self, checked: bool = False) -> None:
        self.viewer.calibrate_display()

    def _select_renderer_slot(self, checked: bool = False) -> None:
        self.viewer.select_renderer()

    def _toggle_show_all_slot(self, checked: bool = False) -> None:
        self.toggle_show_all()

    def _show_help_slot(self, checked: bool = False) -> None:
        self.viewer.show_help()

    def _show_settings_slot(self, checked: bool = False) -> None:
        self.viewer.show_settings()

    def _set_language_slot(self, locale: str) -> None:
        """Store the requested UI language and restart the application.

        The change is only applied if the user confirms the restart; pressing
        Escape or "No" reverts to the previous language.
        """
        previous = active_locale()
        set_active_locale(locale)
        name = get_language_name(locale)
        answer = self._show_language_restart_prompt(
            "dialog.language.restart_message",
            "The language has been set to {language}. Restart InkSim now to apply it?",
            language=name,
        )
        if answer == QMessageBox.Yes:
            self._restart_application()
        else:
            set_active_locale(previous)
            self._rebuild_menus()

    def _clear_language_slot(self, checked: bool = False) -> None:
        """Revert to the system default language and restart the application."""
        previous = active_locale()
        clear_active_locale()
        answer = self._show_language_restart_prompt(
            "dialog.language.system_default_message",
            "The system default language will be used. Restart InkSim now to apply it?",
        )
        if answer == QMessageBox.Yes:
            self._restart_application()
        else:
            set_active_locale(previous)
            self._rebuild_menus()

    def _show_language_restart_prompt(
        self, message_key: str, default_text: str, **kwargs: str
    ) -> int:
        """Ask whether to restart now, with a clearer explanation in server mode.

        In server mode a plain restart would reopen InkSim without the current
        embroidery file (Inkscape provides it once via a temporary file), so the
        dialog tells the user to restart from Inkscape instead.
        """
        if self.server_mode:
            return QMessageBox.information(
                self,
                _("dialog.language.title", "Language changed"),
                _(
                    "dialog.language.server_message",
                    "The language has been changed. Close InkSim and reopen it from Inkscape to apply the new language.",
                ),
                QMessageBox.Ok,
            )
        return QMessageBox.question(
            self,
            _("dialog.language.title", "Language changed"),
            _(message_key, default_text).format(**kwargs),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

    def _rebuild_menus(self) -> None:
        """Rebuild the menu bar so checkmarks reflect the active locale."""
        self.menuBar().clear()
        self._build_menus()

    def _restart_application(self) -> None:
        """Relaunch InkSim with the same arguments and quit this instance.

        The ``-l/--lang/--language`` flag is dropped so the language stored in
        config (just set by the menu) takes effect instead of the old CLI value.

        The relaunch command mirrors how InkSim was originally started:

        * Installed via ``.whl`` → ``sys.argv[0]`` is the ``inksim`` console
          script, so it is relaunched directly.
        * Run as ``python -m inksim`` → ``sys.argv[0]`` is ``__main__.py``,
          which has no package context, so it is relaunched as ``-m inksim``.
        """
        program = sys.executable
        args = self._args_without_language_flag(sys.argv[1:])
        if Path(sys.argv[0]).name == "__main__.py":
            launch = ["-m", "inksim", *args]
        else:
            launch = [sys.argv[0], *args]
        QProcess.startDetached(program, launch)
        self._allow_close = True
        self.close()

    def _confirm_and_close(
        self, title_key: str, title_default: str, text_key: str, text_default: str
    ) -> None:
        """Show a confirmation dialog and close the window if the user accepts."""
        answer = QMessageBox.question(
            self,
            _(title_key, title_default),
            _(text_key, text_default),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self._allow_close = True
            self.close()

    @staticmethod
    def _args_without_language_flag(argv: list[str]) -> list[str]:
        """Return *argv* with any ``-l/--lang/--language`` flag and its value removed."""
        result: list[str] = []
        skip_next = False
        for arg in argv:
            if skip_next:
                skip_next = False
                continue
            if arg in ("-l", "--lang", "--language"):
                skip_next = True
                continue
            if arg.startswith("--lang=") or arg.startswith("--language="):
                continue
            result.append(arg)
        return result

    def _show_config_editor_slot(self, checked: bool = False) -> None:
        show_config_editor(self, self.config)

    def _show_command_line_help_slot(self, checked: bool = False) -> None:
        show_command_line_help(self)

    def _show_about_slot(self, checked: bool = False) -> None:
        show_about(self)

    def _rotate_left_slot(self, checked: bool = False) -> None:
        self.viewer.rotate_design(-1)

    def _rotate_right_slot(self, checked: bool = False) -> None:
        self.viewer.rotate_design(1)

    def _set_one_to_one_slot(self, checked: bool = False) -> None:
        self.viewer.set_one_to_one()

    def _cycle_background_slot(self, checked: bool = False) -> None:
        self.viewer.toggle_display_mode("B")

    def _toggle_auto_play_slot(self, checked: bool = False) -> None:
        self.viewer.toggle_auto_play()

    def _prev_color_slot(self, checked: bool = False) -> None:
        self.viewer.jump_to_color(-1)
        self._refresh_after_color_jump()

    def _next_color_slot(self, checked: bool = False) -> None:
        self.viewer.jump_to_color(1)
        self._refresh_after_color_jump()

    def _prev_command_slot(self, checked: bool = False) -> None:
        self.viewer.jump_to_command(-1)
        self._refresh_after_color_jump()

    def _next_command_slot(self, checked: bool = False) -> None:
        self.viewer.jump_to_command(1)
        self._refresh_after_color_jump()

    def _trace_events_slot(self, checked: bool = False) -> None:
        self.viewer.set_trace_events(self.trace_action.isChecked())

    def _finish_initial_display(self, autoplay: bool) -> None:
        self.viewer.fit_to_screen()
        self.progress.update()
        if autoplay:
            self.focus_window()
            self.viewer.seek_to(0)
            self.viewer.toggle_auto_play(forward=True)
        else:
            self.viewer.invalidate_cache()
            self.viewer.update()

    def _refresh_after_color_jump(self) -> None:
        self.viewer.invalidate_cache()
        self.viewer.update()
        self.progress.update()

    def _maybe_auto_check_updates(self) -> None:
        """Run an update check once per configured interval, if enabled."""
        if not should_check(self.config):
            return
        self._check_for_updates(automatic=True)

    def _check_for_updates(self, automatic: bool = False) -> None:
        """Query PyPI for a newer version and notify the user."""
        if self._update_thread is not None and self._update_thread.isRunning():
            return
        self.statusBar().showMessage("Checking for updates...", 3000)
        thread = UpdateCheckThread(self)
        thread.result_ready.connect(lambda latest: self._on_update_result(latest, automatic))
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_update_thread(thread))
        self._update_thread = thread
        thread.start()

    def _clear_update_thread(self, thread: UpdateCheckThread) -> None:
        if self._update_thread is thread:
            self._update_thread = None

    def _on_update_result(self, latest: str, automatic: bool = False) -> None:
        record_check(self.config)
        if not latest:
            if automatic:
                return
            QMessageBox.information(
                self,
                "Check for updates",
                "Could not reach PyPI to check for updates.\nCheck your internet connection and try again.",
            )
            return
        installed = current_version()
        if is_newer(latest, installed):
            title = "Update available"
            suffix = f" [available version {latest}]"
            stored = latest
            message = (
                f"A newer InkSim version is available.\n\n"
                f"Installed: {installed}\n"
                f"Latest:    {latest}\n\n"
                f"Update InkSim using the same tool you used to install it."
            )
        elif is_newer(installed, latest):
            title = "Development version"
            suffix = f" [development version {installed}]"
            stored = installed
            message = (
                f"Your local InkSim is newer than the published release.\n\n"
                f"Installed: {installed}\n"
                f"Published: {latest}\n\n"
                f"This is expected while developing locally."
            )
        else:
            title = "Up to date"
            suffix = ""
            stored = ""
            message = f"InkSim is up to date.\n\nInstalled: {installed}\nLatest:    {latest}"
        if automatic:
            # Automatic checks surface the result permanently in the window
            # title instead of popping up another dialog.  Store only the raw
            # version so we can suppress stale suffixes on the next start.
            self._update_suffix = suffix
            record_result(self.config, stored)
            self._update_window_title()
            return
        QMessageBox.information(self, title, message)

    def _build_command_dock(self) -> None:
        self.command_table = QTableWidget(0, 4, self)
        command_font = self.command_table.font()
        command_font.setPointSize(max(8, command_font.pointSize() - 1))
        self.command_table.setFont(command_font)
        self.command_table.horizontalHeader().hide()
        self.command_table.verticalHeader().hide()
        self.command_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 4):
            self.command_table.horizontalHeader().setSectionResizeMode(
                column,
                QHeaderView.ResizeToContents,
            )
        self.command_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.command_table.setWordWrap(False)
        self.command_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.command_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.command_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.command_table.setAlternatingRowColors(True)
        self.command_table.currentCellChanged.connect(self._command_panel_current_cell_changed)

        self.command_dock = QDockWidget("Commands", self)
        self.command_dock.setObjectName("commandDock")
        self.command_dock.setWidget(self.command_table)
        self.command_dock.setMinimumWidth(360)
        self.command_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.command_dock)
        self.command_dock.hide()
        self.command_dock.visibilityChanged.connect(self._command_dock_visibility_changed)

    def _command_dock_visibility_changed(self, visible: bool) -> None:
        if hasattr(self, "command_panel_action"):
            self.command_panel_action.setChecked(visible)
        if visible:
            self.refresh_command_panel()

    def toggle_command_panel(self, checked: bool) -> None:
        self.command_dock.setVisible(checked)

    def refresh_command_panel(self) -> None:
        table = self.command_table
        with QSignalBlocker(table):
            table.setRowCount(len(self.viewer.command_timeline))
            for row, (label, position, stitch_index, x, y) in enumerate(
                self.viewer.command_timeline
            ):
                position_text = str(position) if stitch_index >= 0 else f"after {position}"
                color = self._command_panel_color(label)
                values = (
                    label,
                    position_text,
                    f"{x:.2f}",
                    f"{y:.2f}",
                )
                for column, value in enumerate(values):
                    item = table.item(row, column)
                    if item is None:
                        item = QTableWidgetItem()
                        table.setItem(row, column, item)
                    item.setText(value)
                    item.setData(Qt.UserRole, row)
                    if column == 0:
                        item.setData(Qt.UserRole + 1, label)
                    item.setForeground(color)
        self._sync_command_panel_cursor()

    def _command_panel_color(self, label: str) -> QColor:
        if label == "STITCH":
            return QColor(35, 35, 35)
        if label == "JUMP":
            return QColor(110, 110, 110)
        if label.startswith("COLOR CHANGE"):
            return QColor(190, 45, 45)
        if label == "TRIM":
            return QColor(210, 125, 20)
        return QColor(55, 95, 160)

    def _sync_command_panel_cursor(self) -> None:
        if self._updating_command_panel:
            return
        if not self.command_dock.isVisible():
            return
        command_index = self.viewer.current_command_index()
        if command_index < 0:
            return
        with QSignalBlocker(self.command_table):
            for row in range(self.command_table.rowCount()):
                item = self.command_table.item(row, 0)
                if item is None:
                    continue
                label = item.data(Qt.UserRole + 1)
                item.setText(f"> {label}" if row == command_index else label)
            self.command_table.setCurrentCell(command_index, 0)
            scroll_item = self.command_table.item(command_index, 0)
            if scroll_item is not None:
                self.command_table.scrollToItem(
                    scroll_item,
                    QAbstractItemView.PositionAtCenter,
                )

    def _command_panel_current_cell_changed(
        self,
        current_row: int,
        current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        if current_row < 0:
            return
        item = self.command_table.item(current_row, current_column)
        if item is None:
            item = self.command_table.item(current_row, 0)
        if item is None:
            return
        command_index = item.data(Qt.UserRole)
        if command_index is None:
            return
        self._updating_command_panel = True
        try:
            self.viewer._set_visible_count_from_command_index(int(command_index))
            self.progress.update()
        finally:
            self._updating_command_panel = False

    def show_window(self, focus: bool = True) -> None:
        """Show the window and optionally request keyboard focus."""
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        else:
            self.show()
        if focus:
            self.focus_window()

    def focus_window(self) -> None:
        """Raise and activate the main window through the window manager."""
        self.show_window(focus=False)
        self.raise_()
        self.activateWindow()

    def _default_snapped_geometry(self) -> QRect:
        """Return a rectangle covering the right half of the primary screen."""
        screen = self.screen() or QApplication.primaryScreen()
        assert screen is not None
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        client = self.geometry()
        left = client.x() - frame.x()
        top = client.y() - frame.y()
        right = frame.right() - client.right()
        bottom = frame.bottom() - client.bottom()
        outer_x = area.x() + area.width() // 2
        outer_width = area.right() - outer_x + 1
        return QRect(
            outer_x + left,
            area.y() + top,
            outer_width - left - right,
            area.height() - top - bottom,
        )

    def _set_snapped_geometry(self) -> None:
        """Apply the snapped layout, restoring the active profile if known."""
        layout = self.config.get(self._layout_config_key(), {})
        if isinstance(layout, dict) and layout.get("x") is not None:
            target = QRect(layout["x"], layout["y"], layout["width"], layout["height"])
        else:
            target = self._snapped_geometry or self._default_snapped_geometry()
        self.setGeometry(target)

    def toggle_window_layout(self) -> None:
        """Toggle between the free layout and the snapped layout."""
        if self.is_fullscreen or self._layout_changing:
            return
        self._layout_changing = True
        try:
            if self._layout_state == "free":
                self._free_maximized = self.isMaximized()
                if self._free_maximized:
                    default_width, default_height = self._default_size
                    screen = self.screen() or QApplication.primaryScreen()
                    assert screen is not None
                    area = screen.availableGeometry()
                    x = area.x() + max(0, (area.width() - default_width) // 2)
                    y = area.y() + max(0, (area.height() - default_height) // 2)
                    self._free_geometry = QRect(x, y, default_width, default_height)
                    self.showNormal()
                elif self._free_geometry is None:
                    self._free_geometry = self.geometry()
                self._snapped_geometry = self._snapped_geometry or self._default_snapped_geometry()
                self._set_snapped_geometry()
                self._layout_state = "snapped"
            else:
                if self._free_maximized:
                    self.showMaximized()
                elif self._free_geometry is not None:
                    self.setGeometry(self._free_geometry)
                self._layout_state = "free"
            self._last_geometry = self.geometry()
            self._update_window_title()
            self._update_snap_menu_state()
        finally:
            self._layout_changing = False

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self._detect_manual_geometry_change()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._detect_manual_geometry_change()

    def _detect_manual_geometry_change(self) -> None:
        if self._layout_changing or self.is_fullscreen or self.isMaximized() or self.isMinimized():
            return
        current = self.geometry()
        if self._layout_state == "snapped":
            if current != self._last_geometry:
                self._snapped_geometry = current
        else:
            self._free_geometry = current
        self._last_geometry = current

    def _update_window_title(self) -> None:
        """Show layout state and update status in the window title."""
        snap_prefix = "[snap] " if self._layout_state == "snapped" else ""
        base = self._base_title
        suffix = self._update_suffix
        # The suffix must never repeat the application name.
        if suffix and APP_TITLE in suffix:
            suffix = ""
        self.setWindowTitle(f"{snap_prefix}{base}{suffix}")

    def _resolve_update_suffix(self, stored: str) -> str:
        """Return a clean title suffix from the stored version, if any."""
        if not stored or not isinstance(stored, str):
            return ""
        stored = stored.strip()
        installed = current_version()
        # A stored plain version equal to the installed one means we are up to
        # date, so suppress the suffix.
        if stored == installed:
            return ""
        # Legacy verbose values are dropped.
        if "InkSim" in stored or "update:" in stored or "dev:" in stored or "  —  " in stored:
            return ""
        if is_newer(stored, installed):
            return f" [available version {stored}]"
        if is_newer(installed, stored):
            return f" [development version {installed}]"
        return ""

    def _update_snap_menu_state(self) -> None:
        """Enable snap save/clear only when the snap layout is active."""
        enabled = self._layout_state == "snapped"
        if getattr(self, "save_snap_action", None):
            self.save_snap_action.setEnabled(enabled)
        if getattr(self, "clear_snap_action", None):
            self.clear_snap_action.setEnabled(enabled)

    def request_quit(self, checked: bool = False) -> None:
        """Close the application instead of hiding a server window."""
        self._allow_close = True
        self.close()

    @staticmethod
    def _inkscape_running() -> bool:
        """Return True when at least one Inkscape process is running.

        Probing for a running process named ``inkscape`` is more reliable
        than trusting the PID of the extension process, which exits as soon
        as it has forwarded the design.
        """
        import subprocess

        try:
            if os.name == "nt":
                # Suppress the console window that ``tasklist`` would
                # otherwise flash on Windows.
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                result = subprocess.run(
                    ["tasklist"],
                    capture_output=True,
                    text=True,
                    check=False,
                    creationflags=creationflags,
                )
                lowered = result.stdout.lower()
                return "inkscape.exe" in lowered or "inkscape.com" in lowered
            result = subprocess.run(
                ["pgrep", "-x", "inkscape"], capture_output=True, check=False, text=True
            )
            return result.returncode == 0
        except OSError:
            return False

    def _save_current_layout(self) -> None:
        """Persist whatever layout is currently active."""
        if self.is_fullscreen or self.isMinimized():
            return
        if self._layout_state == "snapped":
            self._save_snap_layout()
        else:
            self._save_window_layout()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.server_mode and not self._allow_close:
            alive = self._inkscape_running()
            if not alive:
                answer = QMessageBox.question(
                    self,
                    "Close InkSim server",
                    (
                        "The Inkscape instance that started this server is no longer running.\n\n"
                        "Do you want to close InkSim?"
                    ),
                )
                if answer == QMessageBox.Yes:
                    self._allow_close = True
                    event.accept()
                    return
            self._save_current_layout()
            self.setWindowState(self.windowState() | Qt.WindowMinimized)
            event.ignore()
            return
        if self.viewer.is_playing:
            self.viewer.play_timer.stop()
            self.viewer.is_playing = False
        # Release OpenGL resources while the context is still valid so Qt does
        # not warn about textures/buffers not being destroyed.
        try:
            self.viewer._gl_widget.cleanup()
        except Exception:
            pass
        interconnect = getattr(self, "interconnect", None)
        if interconnect is not None:
            interconnect.stop()
        event.accept()

    def toggle_grid(self, checked: bool) -> None:
        self.viewer.show_grid = checked
        self.viewer.invalidate_cache()
        self.viewer.update()
        self.viewer.update_mode_indicators()

    def toggle_realistic(self, checked: bool) -> None:
        if not self.viewer._opengl33_available and self.viewer.active_renderer != "gpu_textured":
            self.statusBar().showMessage(
                "GPU textured renderer requires OpenGL 3.3 (not available); using CPU raster renderer",
                5000,
            )
            self.realistic_action.setChecked(False)
            return
        self.viewer.toggle_display_mode("Z")

    def toggle_show_all(self, checked: bool = False) -> None:
        total = self.viewer.stitches_np.shape[0]
        if self.viewer.visible_count < total:
            self.viewer.visible_count = total
            self.viewer._last_dir = 1
        else:
            self.viewer.visible_count = 0
            self.viewer._last_dir = -1
        logger.debug(
            "Show/hide all toggled visible_count to %s/%s",
            self.viewer.visible_count,
            total,
        )
        self.viewer.notify_cursor_changed()
        self.viewer.invalidate_cache()
        self.viewer.update()
        self.viewer.update_mode_indicators()
        if self.viewer.progress_bar:
            self.viewer.progress_bar.update()
        if self.viewer.is_playing:
            self.viewer.play_timer.stop()
            self.viewer.is_playing = False

    def toggle_needle(self, checked: bool) -> None:
        self.viewer.show_needle = checked
        if checked:
            self.viewer.highlight_needle()
        else:
            self.viewer.stop_needle_highlight()
        self.viewer.update()

    def open_file_dialog(self, checked: bool = False) -> None:
        dialog = EmbroideryOpenDialog(
            self, self.last_directory, self.current_file_path, self.recent_directories
        )
        if dialog.exec() == QDialog.Accepted:
            selected = dialog.selected_path
            if selected is not None:
                self.open_file(selected)
            chosen_background = dialog.background_color
            if chosen_background != self.viewer.background_color:
                self.viewer.background_color = chosen_background
                self.viewer._save_view_setting("view/background_color", list(chosen_background))
                if self.viewer.active_renderer == "gpu_textured":
                    self.viewer._gl_widget.set_background(*chosen_background)
                self.viewer.invalidate_cache()
                self.viewer.repaint()

    def set_document_path(self, document_path: str | Path) -> None:
        """Set the source document used for Save As defaults."""
        path = Path(document_path).resolve()
        self.document_path = path
        self.last_directory = str(path.parent)

    def _preferred_source_path(self) -> Path | None:
        """Return the authoritative source path for output defaults."""
        return self.document_path or self.current_file_path

    def _default_export_name(self, suffix: str) -> str:
        source_path = self._preferred_source_path()
        base_name = source_path.stem if source_path else "inksim"
        return f"{base_name}{suffix}"

    def _choose_export_path(
        self,
        title: str,
        default_name: str,
        file_filter: str,
        extension: str,
    ) -> Path | None:
        export_directory = Path(self.last_directory or Path.cwd())
        default_path = export_directory / default_name
        path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            str(default_path),
            file_filter,
        )
        if not path:
            return None
        selected_path = Path(path)
        return selected_path.with_suffix(extension)

    def _default_save_name(self) -> str:
        return self._default_save_path().name

    def _default_save_path(self) -> Path:
        source_path = self._preferred_source_path()
        base_name = source_path.stem if source_path else "inksim"
        current_extension = (
            self.current_file_path.suffix.lstrip(".").lower() if self.current_file_path else ""
        )
        writable_extensions = {
            file_type["extension"] for file_type in get_supported_output_formats()
        }
        if current_extension not in writable_extensions:
            current_extension = "dst"
        filename = f"{base_name}.{current_extension or 'dst'}"
        if self.document_path is not None:
            return self.document_path.with_name(filename)
        return Path(self.last_directory or Path.cwd()) / filename

    def _choose_save_as_path(self) -> Path | None:
        output_filter = get_supported_output_filter()
        default_path = self._default_save_path()
        dialog = QFileDialog(self, "Save embroidery as", str(default_path))
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setNameFilters(output_filter.split(";;"))
        dialog.setDirectory(str(default_path.parent))
        dialog.selectFile(default_path.name)

        def on_filter_selected(selected_filter: str) -> None:
            extension = extension_from_output_filter(selected_filter)
            if not extension:
                return
            selected_files = dialog.selectedFiles()
            selected_file = selected_files[0] if selected_files else str(default_path)
            dialog.selectFile(self._path_with_output_extension(selected_file, extension))

        dialog.filterSelected.connect(on_filter_selected)
        if dialog.exec() != QDialog.Accepted:
            return None
        selected_files = dialog.selectedFiles()
        if not selected_files:
            return None
        path = selected_files[0]
        selected_filter = dialog.selectedNameFilter()
        if not path:
            return None
        selected_path = Path(path)
        if selected_path.suffix:
            return selected_path
        extension = extension_from_output_filter(selected_filter)
        if not extension:
            extension = "dst"
        return selected_path.with_suffix(f".{extension}")

    def _save_as_embroidery_slot(self, checked: bool = False) -> None:
        self.save_as_embroidery()

    def _path_with_output_extension(self, path: str | Path, extension: str) -> str:
        return str(Path(path).with_suffix(f".{extension}"))

    def save_as_embroidery(self) -> bool:
        path = self._choose_save_as_path()
        if path is None:
            return False
        return self.save_embroidery_to_path(path)

    def save_embroidery_to_path(self, path: str | Path) -> bool:
        pattern = self.viewer.pattern
        if pattern is None:
            QMessageBox.warning(self, "Save embroidery", _("message.no_file_to_save"))
            return False
        try:
            emb.write(pattern, str(path))
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.critical(
                self, "Save embroidery", _("message.save_error.message").format(error=error)
            )
            return False
        self.statusBar().showMessage(f"Saved {path}", 3000)
        return True

    def _can_export_image(self) -> bool:
        if self.viewer.stitches_np.shape[0] == 0:
            QMessageBox.information(self, "Export", _("message.no_file_to_export"))
            return False
        return True

    def export_png(
        self,
        path: str | Path | None = None,
        icon: bool = False,
        dpi: int = 300,
        background: tuple[int, int, int] | str = "transparent",
        grid: bool = False,
        renderer_key: str | None = None,
        scale_factor: float = 1.0,
        format: str = "PNG",
    ) -> QImage | bool | None:
        if self.viewer.stitches_np.shape[0] == 0:
            return None
        if icon:
            width = height = 256
        else:
            min_x, min_y, max_x, max_y = self.viewer.bounds
            width = max(1, round((max_x - min_x) / 25.4 * dpi))
            height = max(1, round((max_y - min_y) / 25.4 * dpi))
        if format in ("JPEG", "WebP") and background == "transparent":
            background = "white"
        image = render_export_image(
            self.viewer.stitches_np,
            self.viewer.bounds,
            width,
            height,
            self.viewer.line_width,
            renderer_key or self.viewer.active_renderer,
            dpi=dpi,
            background=background,
            grid=grid,
            dark_factor=self.viewer.dark_factor,
            light_factor=self.viewer.light_factor,
            scale_factor=scale_factor,
            lighting_mode=self.viewer.lighting_mode,
        )
        if path is not None:
            quality = -1
            if format in ("JPEG", "WebP"):
                quality = 95
            return image.save(str(path), format, quality)  # type: ignore[call-overload]
        return image

    def _show_export_preview(
        self,
        title: str,
        image: QImage,
        default_name: str,
        renderer_key: str | None = None,
        icon: bool = False,
        dpi: int = 300,
    ) -> None:
        default_path = str(Path(self.last_directory or Path.cwd()) / default_name)
        bounds = self.viewer.bounds
        design_width_mm = bounds[2] - bounds[0]
        design_height_mm = bounds[3] - bounds[1]

        def _render_callback(
            transparent: bool = False,
            scale_factor: float = 1.0,
            format: str = "PNG",
            quality: int = 95,
        ) -> QImage | None:
            background = "transparent" if transparent else self.viewer.background_color
            result = self.export_png(
                icon=icon,
                dpi=dpi,
                background=background,
                renderer_key=renderer_key,
                scale_factor=scale_factor,
                format=format,
            )
            if isinstance(result, QImage):
                return result
            return None

        def _on_transparent_changed(checked: bool) -> None:
            self.export_transparent_background = checked
            self.config.set("export_transparent_background", checked)

        dialog = ExportPreviewDialog(
            title,
            image,
            default_path,
            "Image files (*.png *.webp *.jpg *.jpeg)",
            ".png",
            render_callback=_render_callback,
            transparent_default=self.export_transparent_background,
            on_transparent_changed=_on_transparent_changed,
            parent=self,
            base_dpi=dpi,
            design_width_mm=design_width_mm,
            design_height_mm=design_height_mm,
        )
        dialog.exec()
        selected_path = dialog.selected_path()
        if selected_path is not None:
            self.last_directory = str(selected_path.parent)
            self.statusBar().showMessage(f"Exported {_sanitize_path(selected_path)}", 3000)

    def export_print_png(self, checked: bool = False) -> None:
        if not self._can_export_image():
            return
        background: tuple[int, int, int] | str
        if self.export_transparent_background:
            background = "transparent"
        else:
            background = self.viewer.background_color
        image = self.export_png(dpi=300, background=background, renderer_key="simple")
        if image is None or not isinstance(image, QImage):
            return
        self._show_export_preview(
            "Export simple print",
            image,
            self._default_export_name("-simple.png"),
            renderer_key="simple",
            dpi=300,
        )

    def export_shaded_png(self, checked: bool = False) -> None:
        if not self._can_export_image():
            return
        background: tuple[int, int, int] | str
        if self.export_transparent_background:
            background = "transparent"
        else:
            background = self.viewer.background_color
        image = self.export_png(dpi=300, background=background)
        if image is None or not isinstance(image, QImage):
            return
        self._show_export_preview(
            "Export shaded print",
            image,
            self._default_export_name(".png"),
            dpi=300,
        )

    def export_icon_png(self, checked: bool = False) -> None:
        if not self._can_export_image():
            return
        background: tuple[int, int, int] | str
        if self.export_transparent_background:
            background = "transparent"
        else:
            background = self.viewer.background_color
        image = self.export_png(icon=True, dpi=96, background=background)
        if image is None or not isinstance(image, QImage):
            return
        self._show_export_preview(
            "Export icon/thumbnail",
            image,
            self._default_export_name("_thumb.png"),
            icon=True,
            dpi=96,
        )

    def open_file(
        self,
        path: str | Path,
        precompute_density: bool = True,
        delete_after_load: bool = False,
        autoplay: bool = False,
    ) -> bool:
        selected_path = Path(path).resolve()
        if not self.viewer.load_design(
            str(selected_path),
            fit_to_screen=True,
            precompute_density=precompute_density,
            autoplay=autoplay,
        ):
            return False
        self.current_file_path = selected_path
        self._source_mtime_ns = self._capture_source_mtime(selected_path)
        if not delete_after_load:
            self.last_directory = str(selected_path.parent)
            self.config.set("last_directory", _sanitize_path(self.last_directory))
            self._add_recent_directory(selected_path.parent)
        total = self.viewer.stitches_np.shape[0]
        bounds = self.viewer.bounds
        width_mm = bounds[2] - bounds[0]
        height_mm = bounds[3] - bounds[1]
        self._base_title = (
            f"{APP_TITLE} - {selected_path.name} - {total} sts - {width_mm:.1f}x{height_mm:.1f}mm"
        )
        self._update_window_title()
        self.progress.update()
        self.refresh_command_panel()
        self.viewer.invalidate_cache()
        self.viewer.update()
        if delete_after_load and self.server_mode:
            try:
                selected_path.unlink()
            except OSError:
                # Ignore deletion failures; the caller already has the data
                # and the file may have been removed by other means.
                pass
        return True

    def show_command_panel(self) -> None:
        self.command_dock.show()
        self.command_dock.raise_()
        self.refresh_command_panel()

    def toggle_full_screen(self, checked: bool = False) -> None:
        if not self.is_fullscreen:
            self._fullscreen_was_maximized = self.isMaximized()
            self.is_fullscreen = True
            self.mode_status.hide()
            self.showFullScreen()
            return
        self.is_fullscreen = False
        self.mode_status.show()
        if self._fullscreen_was_maximized:
            self.showMaximized()
        else:
            self.showNormal()

    def play(self) -> None:
        """Start simulation playback from the beginning of the design."""
        if self.viewer.is_playing:
            self.viewer.play_timer.stop()
        self.focus_window()
        self.viewer.seek_to(0)
        self.viewer.is_playing = False
        self.viewer.toggle_auto_play(forward=True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            self.open_file(urls[0].toLocalFile())
            event.acceptProposedAction()
