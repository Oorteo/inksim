from collections import deque
from threading import Lock
import time

import numpy as np
import pystitch as emb
from PySide6.QtCore import (
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
    VECTOR_RENDERERS,
    calculate_stitch_density_numba,
    render_density_numba,
    render_viewport_raster,
)
from .help import show_help
from .settings import show_settings


_COMMAND_NAMES = {}
for _name in dir(emb):
    if not _name.isupper() or _name.endswith("_MASK"):
        continue
    _value = getattr(emb, _name)
    if (isinstance(_value, int) and 0 <= _value <= emb.COMMAND_MASK
            and _value not in _COMMAND_NAMES):
        _COMMAND_NAMES[_value] = _name


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

    RENDER_CACHE_PADDING = 200
    PAN_IDLE_RENDER_DELAY_MS = 150
    PAN_MAX_RENDER_INTERVAL_MS = 5000

    def __init__(self, parent, progress_bar):
        """Create an empty viewer connected to the progress bar."""
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(True)
        self.zoom = 1.0
        self.pan_x, self.pan_y = 400, 300
        self.drag_start = None
        self.pan_start = (0, 0)
        self.line_width = DEFAULT_LINE_WIDTH_MM
        self.dark_factor = DEFAULT_DARK_FACTOR
        self.light_factor = DEFAULT_LIGHT_FACTOR
        self.shading_step = 0.05
        self.visible_count = 0
        self.step_size = 10
        self.show_grid = True
        self.show_stitches = True
        self.show_realistic = False
        self.active_renderer = "shaded_volume"
        self._non_realistic_renderer = "shaded_volume"
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
        self.zero_length_np = np.zeros((0, ), dtype=np.bool_)
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
        self.cached_bitmap_width = 0
        self.cached_bitmap_height = 0
        self.cached_dpr = 1.0
        self.cached_padding = 0
        self.cached_pan_x = self.pan_x
        self.cached_pan_y = self.pan_y
        self.cached_zoom = self.zoom
        self.zoom_render_timer = None
        self.pan_render_timer = QTimer(self)
        self.pan_render_timer.setSingleShot(True)
        self.pan_render_timer.timeout.connect(self._finish_pan_render)
        self._last_pan_render_at = 0.0
        self._cache_valid = False
        self.progress_bar = progress_bar
        self.mode_panel = None
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

    def minimum_zoom(self):
        """Return the zoom that keeps the design visible as a small marker."""
        min_x, min_y, max_x, max_y = self.bounds
        design_extent = max(max_x - min_x, max_y - min_y)
        if design_extent <= 0:
            return 0.05
        return max(0.05, MIN_VISIBLE_DESIGN_PIXELS / design_extent)

    def maximum_zoom(self):
        """Return a viewport-sized maximum based on a 10 mm screen span."""
        viewport_extent = max(self.width(), self.height(), 1)
        return max(50.0, viewport_extent / MAX_ZOOM_DESIGN_MM)

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
        if self.progress_bar:
            self.progress_bar.update()

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
        """Move to the nearest recorded command event."""
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

    def toggle_display_mode(self, mode):
        """Toggle a mode or advance the three-state JUMP mode."""
        if mode == "Z":
            self.set_renderer(
                self._non_realistic_renderer
                if self.show_realistic
                else "shaded_volume_natural"
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
        if renderer_key not in ("realistic", "shaded_volume_natural"):
            self._non_realistic_renderer = renderer_key
        self.active_renderer = renderer_key
        self.show_realistic = renderer_key in ("realistic", "shaded_volume_natural")
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

    def reset_render_settings(self):
        """Restore the default thread width and shading factors."""
        self.line_width = DEFAULT_LINE_WIDTH_MM
        self.dark_factor = DEFAULT_DARK_FACTOR
        self.light_factor = DEFAULT_LIGHT_FACTOR
        self.invalidate_cache()
        self.update()
        self.update_mode_indicators()

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
        self.zero_length_np = np.zeros((0, ), dtype=np.bool_)
        self.density_ready = False
        self._density_request_id += 1
        self._density_worker = None
        jump_run_indices = []
        color_change_in_group = False
        has_stitch = False
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
                is_risky = has_stitch and not color_change_in_group
                self.jump_segments.append(
                    [last_x, last_y, x, y, int(is_risky), len(segs)])
                jump_run_indices.append(len(self.jump_segments) - 1)
                last_x, last_y = x, y
                continue
            if hasattr(emb, "END") and cmd == emb.END:
                event_position = len(segs)
                self.command_events.setdefault(event_position,
                                               []).append("END")
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
                color_change_in_group = True
                last_x, last_y = x, y
                continue
            command_name = _COMMAND_NAMES.get(cmd)
            if command_name is not None and command_name != "STITCH":
                event_position = len(segs)
                self.command_events.setdefault(event_position,
                                               []).append(command_name)
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
            has_stitch = True
            color_change_in_group = False
            jump_run_indices = []
        if segs:
            self.stitches_np = np.array(segs, dtype=np.float32)
            self.stitch_points_np = self.stitches_np[:, 2:4].copy()
            delta = self.stitches_np[:, 0:2] - self.stitches_np[:, 2:4]
            self.zero_length_np = np.sum(delta * delta, axis=1) <= 0.0001
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
        dpr = max(1.0, self.devicePixelRatioF())
        if self._cache_valid and self.cached_bitmap and self.cached_dpr == dpr:
            cache_drawn = False
            zoom_ratio = self.zoom / self.cached_zoom
            if abs(zoom_ratio - 1.0) < 0.001:
                pan_delta_x = round(self.pan_x - self.cached_pan_x)
                pan_delta_y = round(self.pan_y - self.cached_pan_y)
                if (
                    abs(pan_delta_x) <= self.cached_padding
                    and abs(pan_delta_y) <= self.cached_padding
                ):
                    painter.drawPixmap(
                        pan_delta_x - self.cached_padding,
                        pan_delta_y - self.cached_padding,
                        self.cached_bitmap,
                    )
                    cache_drawn = True
                else:
                    self._cache_valid = False
            else:
                bitmap_width = self.cached_bitmap_width
                bitmap_height = self.cached_bitmap_height
                preview_x = round(
                    self.pan_x
                    - zoom_ratio * (self.cached_pan_x + self.cached_padding)
                )
                preview_y = round(
                    self.pan_y
                    - zoom_ratio * (self.cached_pan_y + self.cached_padding)
                )
                painter.drawPixmap(
                    preview_x, preview_y,
                    round(bitmap_width * zoom_ratio),
                    round(bitmap_height * zoom_ratio),
                    self.cached_bitmap,
                )
                cache_drawn = True
            if cache_drawn:
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
        padding = self.RENDER_CACHE_PADDING
        cache_w = w + 2 * padding
        cache_h = h + 2 * padding
        render_w = max(1, round(cache_w * dpr))
        render_h = max(1, round(cache_h * dpr))
        render_zoom = self.zoom * dpr
        render_pan_x = (self.pan_x + padding) * dpr
        render_pan_y = (self.pan_y + padding) * dpr
        buf = self._get_render_buffer(render_w, render_h)
        render_viewport_raster(
            buf,
            self.active_renderer,
            self.stitches_np,
            self.visible_count,
            self.stitch_points_np,
            self.stitch_density_np,
            self.zero_length_np,
            render_zoom,
            render_pan_x,
            render_pan_y,
            self.line_width,
            self.dark_factor,
            self.light_factor,
            self.show_grid,
            self.show_density and self.active_renderer not in VECTOR_RENDERERS,
            self.show_stitches,
        )
        img = QImage(
            buf.data,
            render_w,
            render_h,
            3 * render_w,
            QImage.Format_RGB888,
        ).copy()
        if self.active_renderer in VECTOR_RENDERERS:
            stitch_painter = QPainter(img)
            stitch_painter.setRenderHint(QPainter.Antialiasing)
            render_function = VECTOR_RENDERERS[self.active_renderer]
            render_function(
                stitch_painter,
                self.stitches_np,
                self.visible_count,
                render_zoom,
                render_pan_x,
                render_pan_y,
                self.line_width,
                self.dark_factor,
                self.light_factor,
                self.show_stitches,
            )
            stitch_painter.end()
            if self.show_density and len(self.stitch_points_np) > 0:
                row_stride = img.bytesPerLine()
                image_bytes = np.frombuffer(img.bits(), dtype=np.uint8)
                image_rows = image_bytes.reshape((render_h, row_stride))
                image_buffer = image_rows[:, :3 * render_w].reshape(
                    (render_h, render_w, 3)
                )
                render_density_numba(
                    image_buffer,
                    self.stitch_points_np,
                    self.stitch_density_np,
                    self.zero_length_np,
                    self.visible_count,
                    render_zoom,
                    render_pan_x,
                    render_pan_y,
                )
        img.setDevicePixelRatio(dpr)
        bmp = QPixmap.fromImage(img)
        bmp.setDevicePixelRatio(dpr)
        self.cached_bitmap = bmp
        self.cached_bitmap_width = cache_w
        self.cached_bitmap_height = cache_h
        self.cached_dpr = dpr
        self.cached_padding = padding
        self.cached_pan_x = self.pan_x
        self.cached_pan_y = self.pan_y
        self.cached_zoom = self.zoom
        self._cache_valid = True
        self._last_pan_render_at = time.perf_counter()
        painter.drawPixmap(-padding, -padding, bmp)
        self.draw_analysis_overlays(painter)
        self.draw_needle_overlay(painter)
        painter.end()

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
        """Zoom or step through stitches around the mouse position."""
        is_step_modifier = bool(
            e.modifiers() & (Qt.AltModifier | Qt.ControlModifier))
        if is_step_modifier:
            delta = e.angleDelta().y()
            if delta == 0:
                delta = e.angleDelta().x()
            if delta == 0:
                delta = e.pixelDelta().y()
            if delta == 0:
                delta = e.pixelDelta().x()
            if delta != 0:
                total = self.stitches_np.shape[0]
                direction = 1 if delta > 0 else -1
                self.visible_count = max(
                    0, min(total, self.visible_count + direction))
                self._last_dir = direction
                self.invalidate_cache()
                self.update()
                if self.progress_bar:
                    self.progress_bar.update()
            e.accept()
            return
        position = e.position().toPoint()
        mx, my = position.x(), position.y()
        old = self.zoom
        self.zoom *= 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.zoom = max(self.minimum_zoom(), min(self.maximum_zoom(), self.zoom))
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

    def _schedule_pan_render(self):
        """Refresh the panning cache after idle or a maximum drag interval."""
        self.pan_render_timer.start(self.PAN_IDLE_RENDER_DELAY_MS)
        elapsed_ms = (time.perf_counter() - self._last_pan_render_at) * 1000.0
        if elapsed_ms >= self.PAN_MAX_RENDER_INTERVAL_MS:
            self._finish_pan_render()

    def _finish_pan_render(self):
        """Schedule a full render while panning is paused or long-running."""
        self.pan_render_timer.stop()
        if self._cache_valid:
            self.invalidate_cache()

    def seek_to_screen_stitch(self, position, tolerance=12.0):
        """Seek to the nearest currently visible stitch under screen position."""
        visible_count = min(self.visible_count, self.stitches_np.shape[0])
        if visible_count == 0:
            return False

        stitches = self.stitches_np[:visible_count]
        start = stitches[:, 0:2] * self.zoom
        start += (self.pan_x, self.pan_y)
        end = stitches[:, 2:4] * self.zoom
        end += (self.pan_x, self.pan_y)
        vectors = end - start
        lengths_squared = np.sum(vectors * vectors, axis=1)
        point = np.array([position.x(), position.y()], dtype=np.float32)
        offsets = point - start
        ratios = np.zeros(visible_count, dtype=np.float32)
        nonzero = lengths_squared > 0
        ratios[nonzero] = (
            np.sum(offsets[nonzero] * vectors[nonzero], axis=1)
            / lengths_squared[nonzero]
        )
        ratios = np.clip(ratios, 0.0, 1.0)
        closest = start + vectors * ratios[:, None]
        distances_squared = np.sum((closest - point) ** 2, axis=1)
        stitch_index = int(np.argmin(distances_squared))
        if distances_squared[stitch_index] > tolerance * tolerance:
            return False

        self.visible_count = stitch_index + 1
        self.invalidate_cache()
        self.update()
        if self.progress_bar:
            self.progress_bar.update()
        return True

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
        self.pan_render_timer.stop()
        self.invalidate_cache()
        self.update()
        if self.progress_bar and self.progress_bar.dragging:
            self.progress_bar.dragging = False
            self.progress_bar.releaseMouse()

    def mouseDoubleClickEvent(self, e):
        """Seek to a visible stitch when the canvas is double-clicked."""
        if e.button() == Qt.LeftButton:
            self.drag_start = None
            self.releaseMouse()
            self.seek_to_screen_stitch(e.position().toPoint())
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):
        """Update the viewport offset while the user drags the canvas."""
        if self.drag_start and e.buttons() & Qt.LeftButton:
            position = e.position().toPoint()
            dx = position.x() - self.drag_start.x()
            dy = position.y() - self.drag_start.y()
            self.pan_x = self.pan_start[0] + dx
            self.pan_y = self.pan_start[1] + dy
            self._schedule_pan_render()
            self.update()
