from pathlib import Path

from PIL import Image, ImageFilter
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from ..constants import *
from ..render import render_export_image
from .dialogs import EmbroideryOpenDialog
from .status import ModeBar
from .timeline import TimelineWidget
from .viewer import EmbroideryViewerWidget


class MainWindow(QMainWindow):
    """Main InkSim window coordinating the viewer and playback controls."""

    def __init__(self, fullscreen=False, window_size=None, window_position=None):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(*(window_size or (1200, 980)))
        self.setAcceptDrops(True)
        self.is_fullscreen = False
        self._startup_fullscreen = fullscreen
        self._should_maximize_default = not window_size and not fullscreen
        self.config = QSettings(APP_ORGANIZATION, APP_TITLE)
        self.last_directory = self.config.value("last_directory", "", str)
        self.current_file_path = None

        main_panel = QWidget(self)
        layout = QVBoxLayout(main_panel)
        self.viewer = EmbroideryViewerWidget(main_panel, None)
        self.progress = TimelineWidget(main_panel, self.viewer)
        self.mode_status = ModeBar(main_panel, self.viewer)
        self.viewer.mode_panel = self.mode_status
        self.viewer.progress_bar = self.progress
        layout.addWidget(self.viewer, 1)
        layout.addWidget(self.mode_status)
        layout.addWidget(self.progress)
        self.setCentralWidget(main_panel)
        self._main_panel = main_panel
        self._build_menus()
        self.statusBar().showMessage(DEFAULT_STATUS_TEXT)

        if window_position:
            self.move(*window_position)
        elif not window_size and not fullscreen:
            self.move(self.screen().availableGeometry().center() - self.rect().center())
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
        export_menu = file_menu.addMenu("Export")
        self._action(export_menu, "Shaded PNG for print...", self.export_shaded_png)
        self._action(export_menu, "Preview PNG...", self.export_icon_png)
        self._action(export_menu, "Simple PNG for print...", self.export_print_png)
        self._action(file_menu, "Center design", self.viewer.center_design, "C")
        self._action(file_menu, "Fit design to window", self.viewer.fit_to_screen, "F")
        self._action(file_menu, "Fullscreen", self.toggle_full_screen, "F11")
        self.grid_action = self._action(file_menu, "Show 1cm grid", self.toggle_grid, "G", True)
        self.grid_action.setChecked(True)
        self.realistic_action = self._action(file_menu, "Realistic thread render", self.toggle_realistic, "R", True)
        self.viewer.grid_toggled.connect(self.grid_action.setChecked)
        self.viewer.renderer_changed.connect(
            lambda renderer: self.realistic_action.setChecked(renderer == "realistic")
        )
        self.viewer.fullscreen_requested.connect(self.toggle_full_screen)
        self.viewer.status_message.connect(self.statusBar().showMessage)
        self._action(file_menu, "Choose stitch renderer...", self.viewer.select_renderer)
        self._action(file_menu, "Help", self.viewer.show_help, "H")
        file_menu.addSeparator()
        self._action(file_menu, "Rotate left 90 deg", lambda: self.viewer.rotate_design(-1))
        self._action(file_menu, "Rotate right 90 deg", lambda: self.viewer.rotate_design(1))
        file_menu.addSeparator()
        self._action(file_menu, "Quit", self.close, "Ctrl+Q")
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
        self.menubar = self.menuBar()

    def _finish_initial_display(self, autoplay):
        self._main_panel.layout().activate()
        self.viewer.fit_to_screen()
        self.viewer.invalidate_cache()
        self.viewer.update()
        self.progress.update()
        if autoplay:
            self.viewer.visible_count = 0
            self.viewer.toggle_auto_play(forward=True)

    def _refresh_after_color_jump(self):
        self.viewer.invalidate_cache()
        self.viewer.update()
        self.progress.update()

    def closeEvent(self, event):
        if self.viewer.is_playing:
            self.viewer.play_timer.stop()
            self.viewer.is_playing = False
        event.accept()

    def toggle_grid(self, checked):
        self.viewer.show_grid = checked
        self.viewer.invalidate_cache()
        self.viewer.update()
        self.viewer.update_mode_indicators()

    def toggle_realistic(self, checked):
        self.viewer.set_renderer("realistic" if checked else "shaded")

    def open_file_dialog(self):
        dialog = EmbroideryOpenDialog(self, self.last_directory, self.current_file_path)
        if dialog.exec() == QDialog.Accepted:
            self.open_file(dialog.path)

    def _default_export_name(self, suffix):
        base_name = self.current_file_path.stem if self.current_file_path else "inksim"
        return f"{base_name}{suffix}"

    def _choose_export_path(self, title, default_name, file_filter, extension):
        export_directory = Path(self.last_directory or Path.cwd())
        if self.current_file_path is not None:
            export_directory = self.current_file_path.parent
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

    def export_png(self, path, icon=False, dpi=300, background="transparent", grid=False, shaded=False):
        if self.viewer.stitches_np.shape[0] == 0:
            return False
        if icon:
            width = height = 256
        else:
            min_x, min_y, max_x, max_y = self.viewer.bounds
            width = max(1, round((max_x - min_x) / 25.4 * dpi))
            height = max(1, round((max_y - min_y) / 25.4 * dpi))
        scale = 3 if shaded else 1
        image, metadata = render_export_image(self.viewer.stitches_np, self.viewer.bounds,
            width * scale, height * scale, self.viewer.line_width, dpi=dpi,
            background=background, grid=grid, shaded=shaded,
            dark_factor=self.viewer.dark_factor, light_factor=self.viewer.light_factor)
        if scale > 1:
            image = image.resize((width, height), Image.Resampling.LANCZOS)
            image = image.filter(ImageFilter.UnsharpMask(radius=0.55, percent=115, threshold=2))
        image.save(path, "PNG", pnginfo=metadata, dpi=(dpi, dpi))
        return True

    def export_print_png(self, event=None):
        path = self._choose_export_path(
            "Export PNG for print",
            self._default_export_name("-simple.png"),
            "PNG files (*.png)",
            ".png",
        )
        if path: self.export_png(path, dpi=300)

    def export_shaded_png(self, event=None):
        path = self._choose_export_path(
            "Export shaded PNG for print",
            self._default_export_name(".png"),
            "PNG files (*.png)",
            ".png",
        )
        if path: self.export_png(path, dpi=300, shaded=True)

    def export_icon_png(self, event=None):
        path = self._choose_export_path(
            "Export preview PNG",
            self._default_export_name("_thumb.png"),
            "PNG files (*.png)",
            ".png",
        )
        if path: self.export_png(path, icon=True, dpi=96)

    def open_file(self, path):
        selected_path = Path(path).resolve()
        if not self.viewer.load_design(str(selected_path), fit_to_screen=True):
            return False
        self.current_file_path = selected_path
        self.last_directory = str(selected_path.parent)
        self.config.setValue("last_directory", self.last_directory)
        total = self.viewer.stitches_np.shape[0]
        bounds = self.viewer.bounds
        self.setWindowTitle(f"{APP_TITLE} - {selected_path.name} - {total} sts - "
                            f"{bounds[2] - bounds[0]:.1f}x{bounds[3] - bounds[1]:.1f}mm")
        self.progress.update()
        return True

    def toggle_full_screen(self):
        self.is_fullscreen = not self.is_fullscreen
        self.mode_status.setVisible(not self.is_fullscreen)
        self.showFullScreen() if self.is_fullscreen else self.showNormal()

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
