from collections import deque
from threading import Lock
import time

import numpy as np
import pystitch as emb
from PySide6.QtCore import (
    QLineF,
    QRunnable,
    QThreadPool,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
    QTextTable,
)
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QWidget,
)

from ..constants import *
from ..debug import is_enabled, logger
from ..render import (
    RENDERERS_BY_KEY,
    calculate_stitch_density_numba,
    render_density_numba,
    render_fabric_numba,
    render_grid_numba,
    render_stitches,
)
from .help import show_help
from .settings import show_settings


def density_debug(message):
    logger.debug(message)


density_results = deque()
density_results_lock = Lock()


class DensityWorker(QRunnable):
    def __init__(self, owner_id, request_id, points, bounds):
        super().__init__()
        self.owner_id = owner_id
        self.request_id = request_id
        self.points = points
        self.bounds = bounds

    def run(self):
        density_debug(f"worker start request={self.request_id}")
        started_at = time.perf_counter()
        min_x, min_y, max_x, max_y = self.bounds
        try:
            density = calculate_stitch_density_numba(
                self.points,
                min_x,
                min_y,
                max_x,
                max_y,
            )
        except Exception as error:
            density_debug(
                f"worker failed request={self.request_id} "
                f"elapsed={time.perf_counter() - started_at:.3f}s "
                f"error={error!r}"
            )
            with density_results_lock:
                density_results.append(
                    ("failed", self.owner_id, self.request_id, error)
                )
        else:
            density_debug(
                f"worker finished request={self.request_id} "
                f"elapsed={time.perf_counter() - started_at:.3f}s"
            )
            with density_results_lock:
                density_results.append(
                    ("finished", self.owner_id, self.request_id, density)
                )


class EmbroideryViewerWidget(QWidget):
    """Fast interactive embroidery preview with playback and viewport controls.

    Stitch data is kept in a NumPy array and rendered into a bitmap by the
    Numba rasterizers above. This panel owns the viewer state: loaded design,
    current stitch position, zoom and pan, grid visibility, playback, and
    keyboard/mouse interaction.
    """

    grid_toggled = Signal(bool)
    renderer_changed = Signal(str)
    fullscreen_requested = Signal()
    status_message = Signal(str, int)

    def __init__(self, parent, progress_bar):
        """Create an empty viewer connected to the progress bar."""
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(True)
        self.zoom = 1.0
        self.pan_x, self.pan_y = 400, 300
        self.drag_start = None
        self.pan_start = (0, 0)
        self.line_width = 0.4
        self.dark_factor = 0.75
        self.light_factor = 0.45
        self.shading_step = 0.05
        self.visible_count = 0
        self.step_size = 10
        self.show_grid = True
        self.show_stitches = True
        self.show_realistic = False
        self.active_renderer = "shaded"
        self._non_realistic_renderer = "shaded"
        self.show_density = False
        self.show_jumps = False
        self.risky_jumps_only = False
        self.show_needle = True
        self.needle_highlighted = False
        self.needle_highlight_stage = 0
        self._needle_highlight_timer = None
        self.stitches_np = np.zeros((0, 7), dtype=np.float32)
        self.bounds = (0, 0, 0, 0)
        self.color_boundaries = []
        self.color_count = 0
        self.command_events = {}
        self.jump_segments = []
        self.stitch_points_np = np.zeros((0, 2), dtype=np.float32)
        self.stitch_density_np = np.zeros((0, ), dtype=np.float32)
        self.density_ready = False
        self._density_request_id = 0
        self._density_worker = None
        self._density_owner_id = id(self)
        self._density_result_timer = QTimer(self)
        self._density_result_timer.timeout.connect(self._poll_density_results)
        self._density_result_timer.start(50)
        self._paint_sequence = 0
        self._render_buffer = None
        self._render_buffer_size = None
        self.cached_bitmap = None
        self.cached_pan_x = self.pan_x
        self.cached_pan_y = self.pan_y
        self.cached_zoom = self.zoom
        self.zoom_render_timer = None
        self._cache_valid = False
        self.progress_bar = progress_bar
        self.mode_panel = None
        self._last_key_time = 0
        self._key_throttle = 0.03
        self.help_dialog = None
        self.settings_dialog = None
        self._last_dir = 1
        self._pending_fit_to_screen = False
        self.play_timer = QTimer(self)
        self.play_speed = 20
        self.play_speed_levels = (1, 5, 10, 20, 40, 80)
        self.play_speed_index = 2
        self.play_step = self.play_speed_levels[self.play_speed_index]
        self.is_playing = False
        self.play_timer.timeout.connect(self.advance_playback)

    def invalidate_cache(self):
        self._cache_valid = False
        self.update()

    def _get_render_buffer(self, width, height):
        size = (width, height)
        if self._render_buffer_size != size:
            self._render_buffer = np.empty((height, width, 3), dtype=np.uint8)
            self._render_buffer_size = size
        self._render_buffer.fill(255)
        return self._render_buffer

    def resizeEvent(self, event):
        """Invalidate the bitmap and retry deferred initial fitting."""
        self.invalidate_cache()
        if self._pending_fit_to_screen and self.stitches_np.shape[0] > 0:
            QTimer.singleShot(0, self._try_fit_to_screen)
        super().resizeEvent(event)

    def _try_fit_to_screen(self, retries=20):
        """Fit the design once Qt has assigned a usable panel size."""
        if not self._pending_fit_to_screen:
            return
        w, h = self.width(), self.height()
        # On startup Qt can briefly report tiny panel sizes.
        # If we fit at that moment, the design appears tiny in the top-left.
        # Retry shortly until layout stabilizes.
        if w < 120 or h < 120:
            if retries > 0:
                QTimer.singleShot(30, lambda: self._try_fit_to_screen(retries - 1))
            return
        self._pending_fit_to_screen = False
        self.fit_to_screen()

    def fit_to_screen(self):
        """Center the loaded design and scale it to fit the viewport."""
        if self.stitches_np.shape[0] == 0:
            return
        min_x, min_y, max_x, max_y = self.bounds
        bw = max_x - min_x
        bh = max_y - min_y
        bw = max(bw, 1)
        bh = max(bh, 1)
        w, h = self.width(), self.height()
        if w < 10 or h < 10:
            w, h = 1200, 800
        zoom_x = (w * 0.8) / bw
        zoom_y = (h * 0.8) / bh
        self.zoom = min(zoom_x, zoom_y)
        self.center_design()

    def set_one_to_one(self):
        """Display the design at its physical size when display PPI is known."""
        if self.stitches_np.shape[0] == 0:
            return
        try:
            screen = self.screen()
            ppi_x = float(screen.logicalDotsPerInchX())
            ppi_y = float(screen.logicalDotsPerInchY())
            if ppi_x <= 0 or ppi_y <= 0:
                raise ValueError("invalid display PPI")
            pixels_per_mm = (ppi_x + ppi_y) / (2.0 * 25.4)
        except (AttributeError, TypeError, ValueError):
            pixels_per_mm = 96.0 / 25.4
        self.zoom = pixels_per_mm
        self.center_design()

    def center_design(self):
        """Center the loaded design without changing its current zoom."""
        if self.stitches_np.shape[0] == 0:
            return
        w, h = self.width(), self.height()
        if w < 10 or h < 10:
            w, h = 1200, 800
        min_x, min_y, max_x, max_y = self.bounds
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        self.pan_x = w / 2 - cx * self.zoom
        self.pan_y = h / 2 - cy * self.zoom
        self.invalidate_cache()
        self.update()
        if self.progress_bar:
            self.progress_bar.update()

    def advance_playback(self):
        """Advance playback by one timer step in the current direction."""
        total = self.stitches_np.shape[0]
        if total == 0:
            self.play_timer.stop()
            self.is_playing = False
            return
        self.visible_count += self.play_step * self._last_dir
        if self.visible_count >= total:
            self.visible_count = total
            self.play_timer.stop()
            self.is_playing = False
        elif self.visible_count <= 0:
            self.visible_count = 0
            self.play_timer.stop()
            self.is_playing = False
        self.invalidate_cache()
        self.update()
        if self.progress_bar:
            self.progress_bar.update()

    def seek_to(self, visible_count):
        total = self.stitches_np.shape[0]
        self.visible_count = max(0, min(total, visible_count))
        self.invalidate_cache()
        self.update()

    def toggle_auto_play(self, forward=None):
        """Start or stop playback, choosing its direction when starting."""
        if self.is_playing:
            self.play_timer.stop()
            self.is_playing = False
        else:
            if forward is not None:
                self._last_dir = 1 if forward else -1
            self.play_timer.start(self.play_speed)
            self.is_playing = True

    def adjust_playback_speed(self, direction):
        """Increase or decrease playback speed while preserving its direction."""
        new_index = max(
            0,
            min(
                len(self.play_speed_levels) - 1,
                self.play_speed_index + direction),
        )
        if new_index == self.play_speed_index:
            return False
        self.play_speed_index = new_index
        self.play_step = self.play_speed_levels[new_index]
        return True

    def keyReleaseEvent(self, event):
        """Reset key-repeat throttling after a key is released."""
        self._last_key_time = 0
        event.accept()

    def jump_to_color(self, direction):
        """Move to the next or previous recorded thread-color boundary."""
        if not self.color_boundaries:
            return
        cur = self.visible_count
        if direction > 0:
            for b in self.color_boundaries:
                if b > cur:
                    self.visible_count = b
                    return
            self.visible_count = self.stitches_np.shape[0]
        else:
            prev = 0
            for b in self.color_boundaries:
                if b < cur:
                    prev = b
                else:
                    break
            if cur in self.color_boundaries:
                idx = self.color_boundaries.index(cur)
                if idx > 0:
                    self.visible_count = self.color_boundaries[idx - 1]
                else:
                    self.visible_count = 0
            else:
                self.visible_count = prev

    def jump_to_command(self, direction):
        """Move to the nearest recorded JUMP, TRIM, or color-change event."""
        positions = sorted(self.command_events)
        current = self.visible_count
        if direction > 0:
            targets = (position for position in positions
                       if position > current)
        else:
            targets = (position for position in reversed(positions)
                       if position < current)
        target = next(targets, None)
        if target is None:
            target = self.stitches_np.shape[0] if direction > 0 else 0
            if target == current:
                return False
        self.visible_count = target
        return True

    def rotate_design(self, quarter_turns):
        """Rotate the loaded design by quarter turns around its center."""
        if self.stitches_np.shape[0] == 0:
            return

        min_x, min_y, max_x, max_y = self.bounds
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        turns = quarter_turns % 4
        if turns == 0:
            return

        def rotate_coordinates(coordinates):
            relative_x = coordinates[:, 0] - center_x
            relative_y = coordinates[:, 1] - center_y
            if turns == 1:
                coordinates[:, 0] = center_x - relative_y
                coordinates[:, 1] = center_y + relative_x
            elif turns == 2:
                coordinates[:, 0] = center_x - relative_x
                coordinates[:, 1] = center_y - relative_y
            else:
                coordinates[:, 0] = center_x + relative_y
                coordinates[:, 1] = center_y - relative_x

        rotate_coordinates(self.stitches_np[:, 0:2])
        rotate_coordinates(self.stitches_np[:, 2:4])
        rotate_coordinates(self.stitch_points_np)
        if self.jump_segments:
            jump_coordinates = np.asarray(self.jump_segments, dtype=np.float32)
            rotate_coordinates(jump_coordinates[:, 0:2])
            rotate_coordinates(jump_coordinates[:, 2:4])
            self.jump_segments = jump_coordinates.tolist()

        rotated_corners = np.array(
            [[min_x, min_y], [min_x, max_y], [max_x, min_y], [max_x, max_y]],
            dtype=np.float32,
        )
        rotate_coordinates(rotated_corners)
        self.bounds = (
            float(rotated_corners[:, 0].min()),
            float(rotated_corners[:, 1].min()),
            float(rotated_corners[:, 0].max()),
            float(rotated_corners[:, 1].max()),
        )
        self.invalidate_cache()
        self.center_design()

    def keyPressEvent(self, e):
        """Handle playback, navigation, display, and view shortcut keys."""
        now = time.time()
        key = e.key()
        is_alt = bool(e.modifiers() & Qt.AltModifier)
        is_ctrl = bool(e.modifiers() & Qt.ControlModifier)
        # Let menu mnemonics and global shortcuts pass through
        # Alt+F, Alt+P for menu, Ctrl+Q for Quit, Ctrl+O for Open etc.
        if is_alt and key in (Qt.Key_F, Qt.Key_P):
            e.ignore()
            return
        if is_ctrl and key in (Qt.Key_Q, Qt.Key_O):
            e.ignore()
            return
        is_space_or_c = key in (
            Qt.Key_Space,
            Qt.Key_C,
        )
        if (not is_space_or_c
                and now - self._last_key_time < self._key_throttle
                and not is_alt and not is_ctrl):
            return
        self._last_key_time = now
        total = self.stitches_np.shape[0]
        is_shift = bool(e.modifiers() & Qt.ShiftModifier)
        changed = False
        highlight_needle = False
        step = 1 if is_alt else self.step_size
        if is_shift and not is_alt and not is_ctrl and key in (
                Qt.Key_Right,
                Qt.Key_Left,
        ):
            changed = self.jump_to_command(1 if key == Qt.Key_Right else -1)
            highlight_needle = changed
            if changed and self.is_playing:
                self.play_timer.stop()
                self.is_playing = False
        elif self.is_playing and not is_alt and not is_ctrl and key in (
                Qt.Key_Right,
                Qt.Key_Left,
        ):
            key_direction = 1 if key == Qt.Key_Right else -1
            changed = self.adjust_playback_speed(key_direction * self._last_dir)
        elif is_ctrl and key in (Qt.Key_Right, Qt.Key_Left):
            if key == Qt.Key_Right:
                self.jump_to_color(1)
                self._last_dir = 1
            else:
                self.jump_to_color(-1)
                self._last_dir = -1
            changed = True
            highlight_needle = True
        elif key == Qt.Key_Right:
            if self.visible_count < total:
                self.visible_count = min(total, self.visible_count + step)
                self._last_dir = 1
                changed = True
        elif key == Qt.Key_Left:
            if self.visible_count > 0:
                self.visible_count = max(0, self.visible_count - step)
                self._last_dir = -1
                changed = True
        elif key == Qt.Key_Up:
            self.visible_count = min(total, self.visible_count + step * 10)
            self._last_dir = 1
            changed = True
        elif key == Qt.Key_Down:
            self.visible_count = max(0, self.visible_count - step * 10)
            self._last_dir = -1
            changed = True
        elif key == Qt.Key_Home:
            self.visible_count = 0
            changed = True
        elif key == Qt.Key_End:
            self.visible_count = total
            changed = True
        elif key == Qt.Key_Space:
            self.toggle_auto_play()
            return
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.line_width = min(1.0, self.line_width + 0.1)
            changed = True
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            self.line_width = max(0.1, self.line_width - 0.1)
            changed = True
        elif key in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
            shading_delta = self.shading_step
            if key == Qt.Key_BracketLeft:
                shading_delta = -shading_delta
            if is_shift:
                self.light_factor = max(
                    0.0,
                    min(1.0, self.light_factor + shading_delta),
                )
            else:
                self.dark_factor = max(
                    0.05,
                    min(1.0, self.dark_factor + shading_delta),
                )
            changed = True
        elif key == Qt.Key_C and not is_alt and not is_ctrl:
            self.center_design()
            return
        elif key == Qt.Key_F and not is_alt and not is_ctrl:
            self.fit_to_screen()
            return
        elif key == Qt.Key_1 and not is_alt and not is_ctrl:
            self.set_one_to_one()
            return
        elif key == Qt.Key_F11:
            self.fullscreen_requested.emit()
            return
        elif key == Qt.Key_G and not is_alt and not is_ctrl:
            self.show_grid = not self.show_grid
            self.grid_toggled.emit(self.show_grid)
            changed = True
        elif key == Qt.Key_J and not is_alt and not is_ctrl:
            self.toggle_display_mode("J")
            changed = True
        elif key == Qt.Key_X and not is_alt and not is_ctrl:
            self.toggle_display_mode("X")
            changed = True
        elif key == Qt.Key_V and not is_alt and not is_ctrl:
            self.toggle_display_mode("V")
            changed = True
        elif key == Qt.Key_Z and not is_alt and not is_ctrl:
            self.toggle_display_mode("Z")
            changed = True
        elif key == Qt.Key_R and not is_alt and not is_ctrl:
            self.select_renderer()
            changed = True
        elif key == Qt.Key_N and not is_alt and not is_ctrl:
            self.show_needle = not self.show_needle
            if self.show_needle:
                self.highlight_needle()
            else:
                self.stop_needle_highlight()
            changed = True
        elif key == Qt.Key_H and not is_alt and not is_ctrl:
            self.show_help()
            return
        elif key == Qt.Key_I and not is_alt and not is_ctrl:
            self.show_settings()
            return
        elif key == Qt.Key_Escape:
            if self.is_playing:
                self.play_timer.stop()
                self.is_playing = False
                return
        if changed:
            if highlight_needle:
                self.highlight_needle()
            if (self.is_playing and key
                    in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End)
                    and not is_ctrl):
                self.play_timer.stop()
                self.is_playing = False
            self.invalidate_cache()
            self.update()
            if self.progress_bar:
                self.progress_bar.update()
        else:
            e.ignore()

    def toggle_display_mode(self, mode):
        """Toggle a mode or advance the three-state JUMP mode."""
        if mode == "Z":
            self.set_renderer(
                self._non_realistic_renderer
                if self.active_renderer == "realistic"
                else "realistic"
            )
        elif mode == "X":
            self.show_density = not self.show_density
            if self.show_density and not self.density_ready:
                self.calculate_stitch_density()
        elif mode == "V":
            self.show_stitches = not self.show_stitches
        elif mode == "J":
            if not self.show_jumps:
                self.show_jumps = True
                self.risky_jumps_only = False
            elif not self.risky_jumps_only:
                self.risky_jumps_only = True
            else:
                self.show_jumps = False
                self.risky_jumps_only = False
        self.update_mode_indicators()
        self.invalidate_cache()
        self.update()

    def set_renderer(self, renderer_key):
        """Select a registered stitch renderer and refresh the canvas."""
        if renderer_key not in RENDERERS_BY_KEY:
            raise ValueError(f"unknown stitch renderer: {renderer_key}")
        if renderer_key != "realistic":
            self._non_realistic_renderer = renderer_key
        self.active_renderer = renderer_key
        self.show_realistic = renderer_key == "realistic"
        self.renderer_changed.emit(renderer_key)
        self.invalidate_cache()
        self.update()
        self.update_mode_indicators()

    def select_renderer(self):
        """Open the renderer picker dialog."""
        from .renderer_picker import RendererPickerDialog

        dialog = RendererPickerDialog(self, self.active_renderer)
        if dialog.exec():
            self.set_renderer(dialog.selected_renderer)

    def update_mode_indicators(self):
        if self.mode_panel is not None:
            self.mode_panel.update_indicators()

    def _show_markdown_columns_dialog(
        self, key, title, sections, columns=3, width=1050, height=700
    ):
        """Show Markdown sections side by side in a responsive Qt grid."""
        dialog = getattr(self, key)
        if dialog is not None:
            dialog.close()
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(width, height)
        grid = QGridLayout(dlg)
        grid.setSpacing(12)
        for index, (heading, markdown) in enumerate(sections):
            browser = QTextBrowser(dlg)
            browser.document().setDefaultStyleSheet(
                "table { border: none; margin-top: 8px; margin-bottom: 8px; }"
                "th, td { border: none; padding: 6px 12px; }"
                "th { font-weight: bold; color: #30343b; }"
                "code { background-color: #f4f4f4; padding: 2px 4px; }"
            )
            browser.setMarkdown(f"# {heading}\n\n{markdown}")
            for child_frame in browser.document().rootFrame().childFrames():
                if isinstance(child_frame, QTextTable):
                    table_format = child_frame.format()
                    table_format.setBorder(0)
                    table_format.setCellPadding(6)
                    child_frame.setFormat(table_format)
            browser.setFrameShape(QTextBrowser.NoFrame)
            grid.addWidget(browser, index // columns, index % columns)
        close_btn = QPushButton("Close", dlg)
        close_btn.setDefault(True)
        close_btn.clicked.connect(dlg.close)
        close_btn.setFocus()
        grid.addWidget(close_btn, (len(sections) + columns - 1) // columns, 0,
                        1, columns, alignment=Qt.AlignRight)
        for sequence in ("Esc", "Return", "Space"):
            shortcut = QShortcut(QKeySequence(sequence), dlg)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(dlg.close)
        dlg.setMinimumSize(width, height)
        dlg.move(self.window().geometry().center() - dlg.rect().center())
        def on_close(event):
            setattr(self, key, None)
            event.accept()
        dlg.closeEvent = on_close
        def on_dialog_key(event):
            key_code = event.key()
            shortcut = "H" if key == "help_dialog" else "I"
            shortcut_key = Qt.Key_H if shortcut == "H" else Qt.Key_I
            if key_code == shortcut_key:
                dlg.close()
                return
            event.ignore()
        dlg.keyPressEvent = on_dialog_key
        setattr(self, key, dlg)
        dlg.show()

    def show_help(self):
        show_help(self)

    def show_settings(self):
        show_settings(self)

    def set_step_size(self, size):
        self.step_size = max(1, size)

    def load_design(self, path, fit_to_screen=True, precompute_density=True):
        """Load an embroidery file into renderable stitch segments."""
        started_at = time.perf_counter()
        density_debug(
            f"load start path={path!r} precompute_density={precompute_density}"
        )
        try:
            pattern = emb.read(path)
        except (OSError, RuntimeError, ValueError) as ex:
            QMessageBox.critical(self, "Error", f"Failed to load embroidery file: {ex}")
            return False
        segs = []
        last_x = last_y = 0
        cur_color_idx = 0
        has_thread_colors = bool(
            hasattr(pattern, "threadlist") and pattern.threadlist)
        palette = pattern.threadlist if has_thread_colors else AUTO_THREAD_COLORS
        min_x = min_y = 1e9
        max_x = max_y = -1e9
        self.color_boundaries = [0]
        self.color_count = 0
        self.command_events = {}
        self.jump_segments = []
        self.stitch_points_np = np.zeros((0, 2), dtype=np.float32)
        self.stitch_density_np = np.zeros((0, ), dtype=np.float32)
        self.density_ready = False
        self._density_request_id += 1
        self._density_worker = None
        jump_run_indices = []
        for st in pattern.stitches:
            x = st[0] / 10.0
            y = st[1] / 10.0
            raw_command = st[2] if len(st) > 2 else emb.STITCH
            if hasattr(emb, "decode_embroidery_command"):
                cmd, thread, needle, order = emb.decode_embroidery_command(
                    raw_command)
            else:
                cmd = raw_command
                thread = needle = order = None
            if hasattr(emb, "JUMP") and cmd == emb.JUMP:
                event_position = len(segs)
                self.command_events.setdefault(event_position,
                                               []).append("JUMP")
                self.jump_segments.append([last_x, last_y, x, y, 1, len(segs)])
                jump_run_indices.append(len(self.jump_segments) - 1)
                last_x, last_y = x, y
                continue
            if hasattr(emb, "END") and cmd == emb.END:
                break
            is_color_change = (hasattr(emb, "COLOR_CHANGE")
                               and cmd == emb.COLOR_CHANGE)
            if is_color_change:
                for jump_index in jump_run_indices:
                    self.jump_segments[jump_index][4] = 0
                jump_run_indices = []
                event_position = len(segs)
                details = []
                if thread is not None:
                    details.append(f"T{thread}")
                if needle is not None:
                    details.append(f"N{needle}")
                if order is not None:
                    details.append(f"O{order}")
                command_label = "COLOR CHANGE"
                if details:
                    command_label += f" ({', '.join(details)})"
                self.command_events.setdefault(event_position,
                                               []).append(command_label)
                cur_color_idx += 1
                if segs:
                    self.color_boundaries.append(len(segs))
                last_x, last_y = x, y
                continue
            if hasattr(emb, "TRIM") and cmd == emb.TRIM:
                event_position = len(segs)
                self.command_events.setdefault(event_position,
                                               []).append("TRIM")
                continue
            for command_name in ("STOP", "SLOW", "FAST"):
                if hasattr(emb, command_name) and cmd == getattr(
                        emb, command_name):
                    event_position = len(segs)
                    self.command_events.setdefault(event_position,
                                                   []).append(command_name)
                    break
            else:
                command_name = None
            if command_name is not None:
                continue
            if has_thread_colors:
                color_idx = min(cur_color_idx, len(palette) - 1)
            else:
                color_idx = cur_color_idx % len(AUTO_THREAD_COLORS)
            col = palette[color_idx]
            if hasattr(col, "get_red"):
                rgb = (col.get_red(), col.get_green(), col.get_blue())
            elif isinstance(col, (list, tuple)):
                rgb = tuple(col[:3])
            else:
                rgb = AUTO_THREAD_COLORS[color_idx % len(AUTO_THREAD_COLORS)]
            segs.append((last_x, last_y, x, y, rgb[0], rgb[1], rgb[2]))
            min_x = min(min_x, last_x, x)
            min_y = min(min_y, last_y, y)
            max_x = max(max_x, last_x, x)
            max_y = max(max_y, last_y, y)
            last_x, last_y = x, y
        if segs:
            self.stitches_np = np.array(segs, dtype=np.float32)
            self.stitch_points_np = self.stitches_np[:, 2:4].copy()
            self.bounds = (min_x, min_y, max_x, max_y)
            self.visible_count = self.stitches_np.shape[0]
            self.color_boundaries = sorted(
                {boundary for boundary in self.color_boundaries
                 if boundary < len(segs)})
            self.color_count = len(self.color_boundaries)
            if fit_to_screen:
                self._pending_fit_to_screen = True
                QTimer.singleShot(0, self._try_fit_to_screen)
        self.invalidate_cache()
        self.update()
        if self.progress_bar:
            self.progress_bar.update()
        if precompute_density and len(self.stitch_points_np) > 0:
            self._start_density_calculation()
        density_debug(
            f"load finished path={path!r} stitches={len(self.stitches_np)} "
            f"elapsed={time.perf_counter() - started_at:.3f}s"
        )
        return True

    def calculate_stitch_density(self):
        """Calculate the density map once, on demand, using the Numba kernel."""
        if self.density_ready or len(self.stitch_points_np) == 0:
            return
        self._start_density_calculation(show_status=True)

    def _start_density_calculation(self, show_status=False):
        if self.density_ready or self._density_worker is not None:
            density_debug(
                f"worker skipped request={self._density_request_id} "
                f"ready={self.density_ready} active={self._density_worker is not None}"
            )
            return
        if show_status:
            self.status_message.emit("Calculating stitch density...", 0)
        worker = DensityWorker(
            self._density_owner_id,
            self._density_request_id,
            self.stitch_points_np.copy(),
            self.bounds,
        )
        self._density_worker = worker
        density_debug(
            f"worker queued request={self._density_request_id} "
            f"points={len(self.stitch_points_np)}"
        )
        QThreadPool.globalInstance().start(worker)

    def _poll_density_results(self):
        own_results = []
        other_results = []
        with density_results_lock:
            while density_results:
                result = density_results.popleft()
                (own_results if result[1] == self._density_owner_id
                 else other_results).append(result)
            density_results.extend(other_results)
        for result_type, _, request_id, result in own_results:
            if result_type == "finished":
                self._density_ready(request_id, result)
            else:
                self._density_failed(request_id, result)

    def _density_ready(self, request_id, density):
        density_debug(
            f"result received request={request_id} "
            f"current={self._density_request_id}"
        )
        if request_id != self._density_request_id:
            return
        self._density_worker = None
        self.stitch_density_np = density
        self.density_ready = True
        self.status_message.emit("Density map ready", 1500)
        self.invalidate_cache()

    def _density_failed(self, request_id, error):
        density_debug(
            f"error received request={request_id} "
            f"current={self._density_request_id} error={error!r}"
        )
        if request_id != self._density_request_id:
            return
        self._density_worker = None
        self.status_message.emit(f"Density calculation failed: {error}", 5000)

    def paintEvent(self, e):
        """Render the current viewport, using the cached bitmap when possible."""
        self._paint_sequence += 1
        paint_sequence = self._paint_sequence
        paint_started_at = time.perf_counter()
        if is_enabled():
            QTimer.singleShot(
                0,
                lambda: density_debug(
                    f"paint finished sequence={paint_sequence} "
                    f"elapsed={time.perf_counter() - paint_started_at:.3f}s"
                ),
            )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(255, 255, 255))
        if self._pending_fit_to_screen:
            painter.end()
            return
        if self._cache_valid and self.cached_bitmap:
            zoom_ratio = self.zoom / self.cached_zoom
            if abs(zoom_ratio - 1.0) < 0.001:
                pan_delta_x = round(self.pan_x - self.cached_pan_x)
                pan_delta_y = round(self.pan_y - self.cached_pan_y)
                painter.drawPixmap(pan_delta_x, pan_delta_y, self.cached_bitmap)
            else:
                bitmap_width = self.cached_bitmap.width()
                bitmap_height = self.cached_bitmap.height()
                preview_x = round(self.pan_x - zoom_ratio * self.cached_pan_x)
                preview_y = round(self.pan_y - zoom_ratio * self.cached_pan_y)
                painter.drawPixmap(
                    preview_x, preview_y,
                    round(bitmap_width * zoom_ratio),
                    round(bitmap_height * zoom_ratio),
                    self.cached_bitmap,
                )
            if self.active_renderer == "simple":
                self.draw_simple_stitches(painter)
            self.draw_analysis_overlays(painter)
            self.draw_needle_overlay(painter)
            painter.end()
            return
        w, h = self.width(), self.height()
        if self.stitches_np.shape[0] == 0:
            painter.setFont(QFont(self.font().family(), 14))
            painter.drawText(
                20,
                20,
                "Open an embroidery file via File > Open or pass it as a command-line argument",
            )
            painter.drawText(
                20,
                45,
                "H=help, Space=play/pause, Ctrl+Arrows=color, Alt+Arrows=1",
            )
            painter.end()
            return
        buf = self._get_render_buffer(w, h)
        if self.active_renderer == "realistic" and self.zoom > 1.2:
            render_fabric_numba(buf, self.zoom)
        if self.show_grid:
            render_grid_numba(buf, self.zoom, self.pan_x, self.pan_y)
        if (
            self.active_renderer != "simple"
            and self.show_stitches
            and self.stitches_np.shape[0] > 0
            and self.visible_count > 0
        ):
            render_stitches(
                self.active_renderer,
                buf,
                self.stitches_np,
                self.visible_count,
                self.zoom,
                self.pan_x,
                self.pan_y,
                self.line_width,
                self.dark_factor,
                self.light_factor,
            )
        if self.show_density and len(self.stitch_points_np) > 0:
            render_density_numba(
                buf,
                self.stitch_points_np,
                self.stitch_density_np,
                self.visible_count,
                self.zoom,
                self.pan_x,
                self.pan_y,
            )
        img = QImage(buf.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        bmp = QPixmap.fromImage(img)
        self.cached_bitmap = bmp
        self.cached_pan_x = self.pan_x
        self.cached_pan_y = self.pan_y
        self.cached_zoom = self.zoom
        self._cache_valid = True
        painter.drawPixmap(0, 0, bmp)
        if self.active_renderer == "simple":
            self.draw_simple_stitches(painter)
        self.draw_analysis_overlays(painter)
        self.draw_needle_overlay(painter)
        painter.end()

    def draw_simple_stitches(self, painter):
        """Draw flat-color stitches with Qt's antialiased vector painter."""
        if not self.show_stitches or self.visible_count == 0:
            return
        pen = QPen()
        pen.setWidthF(max(1.0, self.line_width * self.zoom))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        for stitch in self.stitches_np[:self.visible_count]:
            pen.setColor(QColor(int(stitch[4]), int(stitch[5]), int(stitch[6])))
            painter.setPen(pen)
            painter.drawLine(
                QLineF(
                    stitch[0] * self.zoom + self.pan_x,
                    stitch[1] * self.zoom + self.pan_y,
                    stitch[2] * self.zoom + self.pan_x,
                    stitch[3] * self.zoom + self.pan_y,
                )
            )

    def draw_analysis_overlays(self, painter):
        """Draw optional jump paths and local stitch-density diagnostics."""
        if self.show_jumps:
            for x1, y1, x2, y2, risky, stitch_index in self.jump_segments:
                if stitch_index > self.visible_count:
                    continue
                if self.risky_jumps_only and not risky:
                    continue
                color = QColor(220, 45, 45) if risky else QColor(100, 100, 100)
                painter.setPen(QPen(color, 2, Qt.DashLine))
                painter.drawLine(
                    int(x1 * self.zoom + self.pan_x),
                    int(y1 * self.zoom + self.pan_y),
                    int(x2 * self.zoom + self.pan_x),
                    int(y2 * self.zoom + self.pan_y),
                )

    def draw_needle_overlay(self, painter):
        """Draw the current needle position above the cached stitch bitmap."""
        if not self.show_stitches or not self.show_needle or self.stitches_np.shape[
                0] == 0:
            return
        if self.visible_count > 0:
            stitch = self.stitches_np[self.visible_count - 1]
            world_x, world_y = stitch[2], stitch[3]
        else:
            stitch = self.stitches_np[0]
            world_x, world_y = stitch[0], stitch[1]
        needle_x = int(world_x * self.zoom + self.pan_x)
        needle_y = int(world_y * self.zoom + self.pan_y)
        if self.needle_highlight_stage == 2:
            arm, radius, outer_radius = 80, 24, 42
        elif self.needle_highlight_stage == 1:
            arm, radius, outer_radius = 48, 16, 28
        else:
            arm, radius, outer_radius = 14, 6, 0
        painter.setPen(QPen(QColor(10, 10, 10), 8 if outer_radius else 4))
        painter.drawLine(needle_x - arm, needle_y, needle_x + arm, needle_y)
        painter.drawLine(needle_x, needle_y - arm, needle_x, needle_y + arm)
        if outer_radius:
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(needle_x - outer_radius, needle_y - outer_radius,
                           outer_radius * 2, outer_radius * 2)
        painter.setPen(QPen(QColor(255, 255, 255), 3 if outer_radius else 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(needle_x - radius, needle_y - radius, radius * 2, radius * 2)
        painter.drawLine(needle_x - arm, needle_y, needle_x + arm, needle_y)
        painter.drawLine(needle_x, needle_y - arm, needle_x, needle_y + arm)
        painter.setBrush(QColor(255, 220, 40))
        painter.setPen(QPen(QColor(10, 10, 10), 2))
        marker_radius = 5 if outer_radius else 3
        painter.drawEllipse(needle_x - marker_radius, needle_y - marker_radius,
                       marker_radius * 2, marker_radius * 2)

    def highlight_needle(self):
        """Pulse a large needle marker after user navigation."""
        if not self.show_needle:
            return
        self.needle_highlighted = True
        self.needle_highlight_stage = 2
        if self._needle_highlight_timer is not None:
            self._needle_highlight_timer.stop()
        self._needle_highlight_timer = QTimer(self)
        self._needle_highlight_timer.setSingleShot(True)
        self._needle_highlight_timer.timeout.connect(
            lambda: self._set_needle_highlight_stage(1))
        self._needle_highlight_timer.start(200)
        self.update()

    def _set_needle_highlight_stage(self, stage):
        """Advance the temporary needle marker through its visual pulse."""
        if not self.show_needle:
            return
        self.needle_highlight_stage = stage
        self.update()
        if stage == 1:
            self._needle_highlight_timer = QTimer(self)
            self._needle_highlight_timer.setSingleShot(True)
            self._needle_highlight_timer.timeout.connect(self.stop_needle_highlight)
            self._needle_highlight_timer.start(300)

    def stop_needle_highlight(self):
        """Return the needle crosshair to its normal size."""
        self.needle_highlighted = False
        self.needle_highlight_stage = 0
        self._needle_highlight_timer = None
        self.update()

    def wheelEvent(self, e):
        """Zoom around the mouse position while preserving its world point."""
        position = e.position().toPoint()
        mx, my = position.x(), position.y()
        old = self.zoom
        self.zoom *= 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.zoom = max(0.05, min(50.0, self.zoom))
        scale = self.zoom / old
        self.pan_x = mx - scale * (mx - self.pan_x)
        self.pan_y = my - scale * (my - self.pan_y)
        if self.zoom_render_timer is not None:
            self.zoom_render_timer.stop()
        if self.cached_bitmap:
            self._cache_valid = True
            self.zoom_render_timer = QTimer(self)
            self.zoom_render_timer.setSingleShot(True)
            self.zoom_render_timer.timeout.connect(self._finish_zoom_render)
            self.zoom_render_timer.start(140)
        else:
            self.invalidate_cache()
        self.update()

    def _finish_zoom_render(self):
        """Schedule a full-quality render after zooming settles."""
        self.zoom_render_timer = None
        self.invalidate_cache()
        self.update()

    def mousePressEvent(self, e):
        """Start panning from the current mouse position."""
        self.drag_start = e.position().toPoint()
        self.pan_start = (self.pan_x, self.pan_y)
        self.setFocus()
        self.grabMouse()

    def mouseReleaseEvent(self, e):
        """Stop panning and clean up any progress-bar mouse capture."""
        self.releaseMouse()
        self.drag_start = None
        self.invalidate_cache()
        self.update()
        if self.progress_bar and self.progress_bar.dragging:
            self.progress_bar.dragging = False
            self.progress_bar.releaseMouse()

    def mouseMoveEvent(self, e):
        """Update the viewport offset while the user drags the canvas."""
        if self.drag_start and e.buttons() & Qt.LeftButton:
            position = e.position().toPoint()
            dx = position.x() - self.drag_start.x()
            dy = position.y() - self.drag_start.y()
            self.pan_x = self.pan_start[0] + dx
            self.pan_y = self.pan_start[1] + dy
            self.update()
