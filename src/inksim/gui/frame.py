import os
import time
from pathlib import Path

import pystitch as emb
from PySide6.QtCore import QEvent, QRect, QSettings, QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..constants import *
from ..formats import (
    extension_from_output_filter,
    get_supported_output_filter,
    get_supported_output_formats,
)
from ..render import render_export_image
from .dialogs import EmbroideryOpenDialog
from .about import show_about
from .shortcuts import ViewerShortcutFilter
from .status import ModeBar
from .timeline import TimelineWidget
from .viewer import EmbroideryViewerWidget


class MainWindow(QMainWindow):
    """Main InkSim window coordinating the viewer and playback controls."""

    def __init__(
        self,
        fullscreen=False,
        window_size=None,
        window_position=None,
        server_mode=False,
        delete_input=False,
        document_path=None,
    ):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QIcon(str(
            Path(__file__).parent.parent / "assets" / "app_icons" / "inksim.svg")))
        self._default_size = window_size or (1200, 980)
        self.resize(*self._default_size)
        self.setAcceptDrops(True)
        self.is_fullscreen = False
        self.server_mode = server_mode
        self._delete_input = delete_input
        self._allow_close = False
        self._startup_fullscreen = fullscreen
        self._should_maximize_default = not window_size and not fullscreen
        self.config = QSettings(APP_ORGANIZATION, APP_TITLE)
        self.last_directory = self.config.value("last_directory", "", str)
        if document_path is not None and document_path.is_file():
            self.last_directory = str(document_path.parent)
        self.current_file_path = None
        self._source_mtime_ns = None
        self._last_source_check = 0.0
        self._source_check_interval_s = 0.4
        self._is_reloading_from_disk = False
        self._layout_state = "free"
        self._layout_changing = False
        self._free_geometry = None
        self._free_maximized = False
        self._snapped_geometry = None
        self._last_geometry = self.geometry()
        self._base_title = APP_TITLE

        main_panel = QWidget(self)
        layout = QVBoxLayout(main_panel)
        self.viewer = EmbroideryViewerWidget(main_panel, None)
        self.progress = TimelineWidget(main_panel, self.viewer)
        self.mode_status = ModeBar(main_panel, self.viewer)
        self.progress.seek_requested.connect(self.viewer.seek_to)
        self.viewer.mode_panel = self.mode_status
        self.viewer.progress_bar = self.progress
        layout.addWidget(self.viewer, 1)
        layout.addWidget(self.mode_status)
        layout.addWidget(self.progress)
        self.setCentralWidget(main_panel)
        self._main_panel = main_panel
        self._updating_command_panel = False
        self._build_command_dock()
        self.viewer.cursor_changed.connect(self._sync_command_panel_cursor)
        self.shortcut_filter = ViewerShortcutFilter(self, self.viewer)
        self._build_menus()
        self.statusBar().showMessage(DEFAULT_STATUS_TEXT)
        QApplication.instance().installEventFilter(self)

        if window_position:
            self.move(*window_position)
        elif not window_size and not fullscreen:
            self.move(self.screen().availableGeometry().center() - self.rect().center())

    def eventFilter(self, watched, event):
        if self._is_reloading_from_disk:
            return False
        if self.current_file_path is None:
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

    def _capture_source_mtime(self, file_path):
        try:
            return Path(file_path).stat().st_mtime_ns
        except OSError:
            return None

    def _show_reload_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        dialog.setModal(True)
        dialog.setWindowTitle("Reloading")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(QLabel("File changed on disk. Reloading...", dialog))
        dialog.adjustSize()
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.show()
        QApplication.processEvents()
        return dialog

    def _reload_if_source_changed(self):
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
    def show_initial_window(self, autoplay=False, initial_directory=None):
        """Show the fully initialized window after optional startup work."""
        if self._startup_fullscreen:
            self.is_fullscreen = True
            self.mode_status.hide()
            self.show()
            self.showFullScreen()
        elif self._should_maximize_default:
            self.show()
            self.showMaximized()
        else:
            self.show()
        QTimer.singleShot(0, lambda: self._finish_initial_display(autoplay))
        if initial_directory:
            directory_path = Path(initial_directory)
            if directory_path.is_dir():
                self.last_directory = str(directory_path.resolve())
            QTimer.singleShot(0, self.open_file_dialog)

    def _action(self, menu, text, slot, shortcut=None, checkable=False):
        action = QAction(text, self)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _build_menus(self):
        file_menu = self.menuBar().addMenu("&File")
        self._action(file_menu, "Open embroidery file", self.open_file_dialog, "Ctrl+O")
        self._action(file_menu, "Save as embroidery...", self.save_as_embroidery, "Ctrl+S")
        export_menu = file_menu.addMenu("Export")
        self._action(export_menu, "Shaded PNG for print...", self.export_shaded_png)
        self._action(export_menu, "Preview PNG...", self.export_icon_png)
        self._action(export_menu, "Simple PNG for print...", self.export_print_png)
        self._action(file_menu, "Center design", self.viewer.center_design, "C")
        self._action(file_menu, "Fit design to window", self.viewer.fit_to_screen, "F")
        self._action(file_menu, "Actual size (1:1)", self.viewer.set_one_to_one, "1")
        self._action(file_menu, "Calibrate display size...", self.viewer.calibrate_display)
        self._action(file_menu, "Fullscreen", self.toggle_full_screen, "F11")
        self.grid_action = self._action(file_menu, "Show measurement grid", self.toggle_grid, "G", True)
        self.grid_action.setChecked(True)
        self.realistic_action = self._action(file_menu, "Realistic thread render", self.toggle_realistic, checkable=True)
        self.viewer.grid_toggled.connect(self.grid_action.setChecked)
        self.viewer.renderer_changed.connect(
            lambda renderer: self.realistic_action.setChecked(
                renderer in ("realistic", "shaded_volume_natural", "realistic_gbuffer")
            )
        )
        self.viewer.fullscreen_requested.connect(self.toggle_full_screen)
        self.viewer.status_message.connect(self.statusBar().showMessage)
        self._action(file_menu, "Choose stitch renderer...", self.viewer.select_renderer)
        file_menu.addSeparator()
        self._action(file_menu, "Rotate left 90 deg", lambda: self.viewer.rotate_design(-1))
        self._action(file_menu, "Rotate right 90 deg", lambda: self.viewer.rotate_design(1))
        file_menu.addSeparator()
        self._action(file_menu, "Quit", self.request_quit, "Ctrl+Q")
        view_menu = self.menuBar().addMenu("&View")
        self.command_panel_action = self._action(
            view_menu,
            "Command list",
            self.toggle_command_panel,
            "Ctrl+L",
            True,
        )
        self.command_panel_action.setChecked(False)
        playback = self.menuBar().addMenu("&Playback")
        for step in (1, 10, 50, 100, 500):
            action = self._action(playback, f"Step {step}", lambda checked=False, s=step: self.viewer.set_step_size(s))
            action.setCheckable(True)
            if step == 10:
                action.setChecked(True)
        playback.addSeparator()
        self._action(
            playback,
            "Play/Pause",
            lambda checked=False: self.viewer.toggle_auto_play(),
            "Space",
        )
        self._action(playback, "Next color", lambda: (self.viewer.jump_to_color(1), self._refresh_after_color_jump()))
        self._action(playback, "Prev color", lambda: (self.viewer.jump_to_color(-1), self._refresh_after_color_jump()))
        help_menu = self.menuBar().addMenu("&Help")
        self._action(help_menu, "Help", self.viewer.show_help)
        self._action(help_menu, "Settings", self.viewer.show_settings)
        self._action(help_menu, f"About {APP_TITLE}", lambda: show_about(self))

    def _finish_initial_display(self, autoplay):
        self.viewer.fit_to_screen()
        self.progress.update()
        if autoplay:
            self.focus_window()
            self.viewer.seek_to(0)
            self.viewer.toggle_auto_play(forward=True)
        else:
            self.viewer.invalidate_cache()
            self.viewer.update()

    def _refresh_after_color_jump(self):
        self.viewer.invalidate_cache()
        self.viewer.update()
        self.progress.update()

    def _build_command_dock(self):
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
        self.command_table.currentCellChanged.connect(
            self._command_panel_current_cell_changed
        )

        self.command_dock = QDockWidget("Commands", self)
        self.command_dock.setObjectName("commandDock")
        self.command_dock.setWidget(self.command_table)
        self.command_dock.setMinimumWidth(360)
        self.command_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.command_dock)
        self.command_dock.hide()
        self.command_dock.visibilityChanged.connect(self._command_dock_visibility_changed)

    def _command_dock_visibility_changed(self, visible):
        if hasattr(self, "command_panel_action"):
            self.command_panel_action.setChecked(visible)
        if visible:
            self.refresh_command_panel()

    def toggle_command_panel(self, checked):
        self.command_dock.setVisible(checked)

    def refresh_command_panel(self):
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
                    item.setForeground(color)
        self._sync_command_panel_cursor()

    def _command_panel_color(self, label):
        if label == "STITCH":
            return QColor(35, 35, 35)
        if label == "JUMP":
            return QColor(110, 110, 110)
        if label.startswith("COLOR CHANGE"):
            return QColor(190, 45, 45)
        if label == "TRIM":
            return QColor(210, 125, 20)
        return QColor(55, 95, 160)

    def _sync_command_panel_cursor(self):
        if self._updating_command_panel:
            return
        if not self.command_dock.isVisible():
            return
        command_index = self.viewer.current_command_index()
        if command_index < 0:
            return
        with QSignalBlocker(self.command_table):
            self.command_table.setCurrentCell(command_index, 0)
            self.command_table.scrollToItem(
                self.command_table.item(command_index, 0),
                QAbstractItemView.PositionAtCenter,
            )

    def _command_panel_current_cell_changed(self, current_row, current_column,
                                            _previous_row, _previous_column):
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

    def show_window(self, focus=True):
        """Show the window and optionally request keyboard focus."""
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        else:
            self.show()
        if focus:
            self.focus_window()

    def focus_window(self):
        """Raise and activate the main window through the window manager."""
        self.show_window(focus=False)
        self.raise_()
        self.activateWindow()

    def _default_snapped_geometry(self):
        """Return a rectangle covering the right half of the primary screen."""
        screen = self.screen() or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        return geo.adjusted(geo.width() // 2, 0, 0, 0)

    def _set_snapped_geometry(self):
        """Apply the snapped layout, falling back to the right-half default."""
        target = self._snapped_geometry or self._default_snapped_geometry()
        self.setGeometry(target)

    def toggle_window_layout(self):
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
        finally:
            self._layout_changing = False

    def moveEvent(self, event):
        super().moveEvent(event)
        self._detect_manual_geometry_change()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._detect_manual_geometry_change()

    def _detect_manual_geometry_change(self):
        if self._layout_changing or self.is_fullscreen or self.isMaximized() or self.isMinimized():
            return
        current = self.geometry()
        if self._layout_state == "snapped":
            if current != self._last_geometry:
                self._snapped_geometry = current
        else:
            self._free_geometry = current
        self._last_geometry = current

    def _update_window_title(self):
        """Show layout state in the window title."""
        snap_prefix = "[snap] " if self._layout_state == "snapped" else ""
        self.setWindowTitle(f"{snap_prefix}{self._base_title}")

    def request_quit(self):
        """Close the application instead of hiding a server window."""
        self._allow_close = True
        self.close()

    @staticmethod
    def _inkscape_running():
        """Return True when at least one Inkscape process is running.

        Probing for a running process named ``inkscape`` is more reliable
        than trusting the PID of the extension process, which exits as soon
        as it has forwarded the design.
        """
        import subprocess
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["tasklist"], capture_output=True, text=True, check=False
                )
                lowered = result.stdout.lower()
                return ("inkscape.exe" in lowered
                        or "inkscape.com" in lowered)
            result = subprocess.run(
                ["pgrep", "-x", "inkscape"], capture_output=True, check=False
            )
            return result.returncode == 0
        except OSError:
            return False

    def closeEvent(self, event):
        if self.server_mode and not self._allow_close:
            alive = self._inkscape_running()
            if not alive:
                answer = QMessageBox.question(
                    self,
                    "Close InkSim server",
                    "The Inkscape instance that started this server is no "
                    "longer running.\n\nDo you want to close InkSim?",
                )
                if answer == QMessageBox.Yes:
                    self._allow_close = True
                    event.accept()
                    return
            self.setWindowState(self.windowState() | Qt.WindowMinimized)
            event.ignore()
            return
        if self.viewer.is_playing:
            self.viewer.play_timer.stop()
            self.viewer.is_playing = False
        interconnect = getattr(self, "interconnect", None)
        if interconnect is not None:
            interconnect.stop()
        event.accept()

    def toggle_grid(self, checked):
        self.viewer.show_grid = checked
        self.viewer.invalidate_cache()
        self.viewer.update()
        self.viewer.update_mode_indicators()

    def toggle_realistic(self, checked):
        self.viewer.toggle_display_mode("Z")

    def open_file_dialog(self):
        dialog = EmbroideryOpenDialog(self, self.last_directory, self.current_file_path)
        if dialog.exec() == QDialog.Accepted:
            self.open_file(dialog.selected_path)

    def _default_export_name(self, suffix):
        base_name = self.current_file_path.stem if self.current_file_path else "inksim"
        return f"{base_name}{suffix}"

    def _choose_export_path(self, title, default_name, file_filter, extension):
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

    def _default_save_name(self):
        base_name = self.current_file_path.stem if self.current_file_path else "inksim"
        current_extension = (
            self.current_file_path.suffix.lstrip(".").lower()
            if self.current_file_path else ""
        )
        writable_extensions = {
            file_type["extension"] for file_type in get_supported_output_formats()
        }
        if current_extension not in writable_extensions:
            current_extension = "dst"
        return f"{base_name}.{current_extension or 'dst'}"

    def _choose_save_as_path(self):
        output_filter = get_supported_output_filter()
        export_directory = Path(self.last_directory or Path.cwd())
        default_path = export_directory / self._default_save_name()
        dialog = QFileDialog(self, "Save embroidery as", str(default_path))
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setNameFilters(output_filter.split(";;"))
        dialog.selectFile(str(default_path))

        def on_filter_selected(selected_filter):
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

    def _path_with_output_extension(self, path, extension):
        return str(Path(path).with_suffix(f".{extension}"))

    def save_as_embroidery(self):
        path = self._choose_save_as_path()
        if path is None:
            return False
        return self.save_embroidery_to_path(path)

    def save_embroidery_to_path(self, path):
        pattern = self.viewer.pattern
        if pattern is None:
            QMessageBox.warning(self, "Save embroidery", "No embroidery file is loaded.")
            return False
        try:
            emb.write(pattern, str(path))
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.critical(self, "Save embroidery", f"Failed to save file: {error}")
            return False
        self.statusBar().showMessage(f"Saved {path}", 3000)
        return True

    def export_png(
        self,
        path,
        icon=False,
        dpi=300,
        background="transparent",
        grid=False,
        renderer_key=None,
    ):
        if self.viewer.stitches_np.shape[0] == 0:
            return False
        if icon:
            width = height = 256
        else:
            min_x, min_y, max_x, max_y = self.viewer.bounds
            width = max(1, round((max_x - min_x) / 25.4 * dpi))
            height = max(1, round((max_y - min_y) / 25.4 * dpi))
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
        )
        if not image.save(str(path), "PNG"):
            return False
        return True

    def export_print_png(self):
        path = self._choose_export_path(
            "Export PNG for print",
            self._default_export_name("-simple.png"),
            "PNG files (*.png)",
            ".png",
        )
        if path: self.export_png(path, dpi=300, renderer_key="simple")

    def export_shaded_png(self):
        path = self._choose_export_path(
            "Export shaded PNG for print",
            self._default_export_name(".png"),
            "PNG files (*.png)",
            ".png",
        )
        if path: self.export_png(path, dpi=300)

    def export_icon_png(self):
        path = self._choose_export_path(
            "Export preview PNG",
            self._default_export_name("_thumb.png"),
            "PNG files (*.png)",
            ".png",
        )
        if path: self.export_png(path, icon=True, dpi=96)

    def open_file(self, path, precompute_density=True, delete_after_load=False, autoplay=False):
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
            self.config.setValue("last_directory", self.last_directory)
        total = self.viewer.stitches_np.shape[0]
        bounds = self.viewer.bounds
        self._base_title = (
            f"{APP_TITLE} - {selected_path.name} - {total} sts - "
            f"{bounds[2] - bounds[0]:.1f}x{bounds[3] - bounds[1]:.1f}mm"
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

    def show_command_panel(self):
        self.command_dock.show()
        self.command_dock.raise_()
        self.refresh_command_panel()

    def toggle_full_screen(self):
        self.is_fullscreen = not self.is_fullscreen
        self.mode_status.setVisible(not self.is_fullscreen)
        self.showFullScreen() if self.is_fullscreen else self.showNormal()

    def play(self):
        """Start simulation playback from the beginning of the design."""
        if self.viewer.is_playing:
            self.viewer.play_timer.stop()
        self.focus_window()
        self.viewer.seek_to(0)
        self.viewer.is_playing = False
        self.viewer.toggle_auto_play(forward=True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.open_file(urls[0].toLocalFile())
            event.acceptProposedAction()
