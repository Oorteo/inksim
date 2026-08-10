import time

import numpy as np
import pystitch as emb
from PySide6.QtCore import Qt, QTimer
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
    QApplication,
    QDialog,
    QGridLayout,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QWidget,
)

from ..constants import *
from ..render import (
    calculate_stitch_density_numba,
    render_density_numba,
    render_fabric_numba,
    render_grid_numba,
    render_realistic_numba,
    render_shaded_numba,
)
from .help import show_help
from .settings import show_settings


class EmbroideryViewerPanel(QWidget):
    """Fast interactive embroidery preview with playback and viewport controls.

    Stitch data is kept in a NumPy array and rendered into a bitmap by the
    Numba rasterizers above. This panel owns the viewer state: loaded design,
    current stitch position, zoom and pan, grid visibility, playback, and
    keyboard/mouse interaction.
    """

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
        self.cached_bitmap = None
        self.cached_pan_x = self.pan_x
        self.cached_pan_y = self.pan_y
        self.cached_zoom = self.zoom
        self.zoom_render_timer = None
        self.need_redraw = True
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
        self.play_timer.timeout.connect(self.OnPlayTimer)

    def OnEraseBackground(self, e):
        """Keep the canvas from clearing before a buffered repaint."""

    def OnSize(self, e):
        """Invalidate the bitmap and retry deferred initial fitting."""
        self.need_redraw = True
        if self._pending_fit_to_screen and self.stitches_np.shape[0] > 0:
            QTimer.singleShot(0, self._try_fit_to_screen)

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
        self.FitToScreen()

    def FitToScreen(self):
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
        self.CenterDesign()

    def SetOneToOne(self):
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
        self.CenterDesign()

    def CenterDesign(self):
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
        self.need_redraw = True
        self.update()
        if self.progress_bar:
            self.progress_bar.update()

    def OnPlayTimer(self, e=None):
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
        self.need_redraw = True
        self.update()
        if self.progress_bar:
            self.progress_bar.update()

    def ToggleAutoPlay(self, forward=None):
        """Start or stop playback, choosing its direction when starting."""
        if self.is_playing:
            self.play_timer.stop()
            self.is_playing = False
        else:
            if forward is not None:
                self._last_dir = 1 if forward else -1
            self.play_timer.start(self.play_speed)
            self.is_playing = True

    def AdjustPlaybackSpeed(self, direction):
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

    def OnKeyUp(self, e):
        """Reset key-repeat throttling after a key is released."""
        self._last_key_time = 0
        e.accept()

    def JumpToColor(self, direction):
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

    def JumpToCommand(self, direction):
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

    def RotateDesign(self, quarter_turns):
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
        self.need_redraw = True
        self.CenterDesign()

    def OnKeyDown(self, e):
        """Handle playback, navigation, display, and view shortcut keys."""
        now = time.time()
        key = e.key()
        is_alt = bool(e.modifiers() & Qt.AltModifier)
        is_ctrl = bool(e.modifiers() & Qt.ControlModifier)
        # Let menu mnemonics and global shortcuts pass through
        # Alt+F, Alt+P for menu, Ctrl+Q for Quit, Ctrl+O for Open etc.
        if is_alt and key in (ord('F'), ord('f'), ord('P'), ord('p')):
            e.ignore()
            return
        if is_ctrl and key in (ord('Q'), ord('q'), ord('O'), ord('o')):
            e.ignore()
            return
        is_space_or_c = key in (
            Qt.Key_Space,
            ord("C"),
            ord("c"),
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
            changed = self.JumpToCommand(1 if key == Qt.Key_Right else -1)
            highlight_needle = changed
            if changed and self.is_playing:
                self.play_timer.stop()
                self.is_playing = False
        elif self.is_playing and not is_alt and not is_ctrl and key in (
                Qt.Key_Right,
                Qt.Key_Left,
        ):
            key_direction = 1 if key == Qt.Key_Right else -1
            changed = self.AdjustPlaybackSpeed(key_direction * self._last_dir)
        elif is_ctrl and key in (Qt.Key_Right, Qt.Key_Left):
            if key == Qt.Key_Right:
                self.JumpToColor(1)
                self._last_dir = 1
            else:
                self.JumpToColor(-1)
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
            self.ToggleAutoPlay()
            return
        elif key in (ord("+"), ord("="), Qt.Key_Plus):
            self.line_width = min(1.0, self.line_width + 0.1)
            changed = True
        elif key in (ord("-"), ord("_"), Qt.Key_Minus):
            self.line_width = max(0.1, self.line_width - 0.1)
            changed = True
        elif key in (ord("["), ord("{"), ord("]"), ord("}")):
            shading_delta = self.shading_step
            if key in (ord("["), ord("{")):
                shading_delta = -shading_delta
            if is_shift or key in (ord("{"), ord("}")):
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
        elif key in (ord("C"), ord("c")) and not is_alt and not is_ctrl:
            self.CenterDesign()
            return
        elif key in (ord("F"), ord("f")) and not is_alt and not is_ctrl:
            self.FitToScreen()
            return
        elif key == ord("1") and not is_alt and not is_ctrl:
            self.SetOneToOne()
            return
        elif key == Qt.Key_F11:
            frame = self.window()
            if hasattr(frame, "ToggleFullScreen"):
                frame.ToggleFullScreen()
                return
        elif key in (ord("G"), ord("g")) and not is_alt and not is_ctrl:
            self.show_grid = not self.show_grid
            frame = self.window()
            if hasattr(frame, "gridItem"):
                frame.gridItem.setChecked(self.show_grid)
            changed = True
        elif key in (ord("J"), ord("j")) and not is_alt and not is_ctrl:
            self.ToggleDisplayMode("J")
            changed = True
        elif key in (ord("X"), ord("x")) and not is_alt and not is_ctrl:
            self.ToggleDisplayMode("X")
            changed = True
        elif key in (ord("V"), ord("v")) and not is_alt and not is_ctrl:
            self.ToggleDisplayMode("V")
            changed = True
        elif key in (ord("R"), ord("r")) and not is_alt and not is_ctrl:
            self.ToggleDisplayMode("R")
            changed = True
        elif key in (ord("N"), ord("n")) and not is_alt and not is_ctrl:
            self.show_needle = not self.show_needle
            if self.show_needle:
                self.HighlightNeedle()
            else:
                self.StopNeedleHighlight()
            changed = True
        elif key in (ord("H"), ord("h")) and not is_alt and not is_ctrl:
            self.ShowHelp()
            return
        elif key in (ord("I"), ord("i")) and not is_alt and not is_ctrl:
            self.ShowSettings()
            return
        elif key == Qt.Key_Escape:
            if self.is_playing:
                self.play_timer.stop()
                self.is_playing = False
                return
        if changed:
            if highlight_needle:
                self.HighlightNeedle()
            if (self.is_playing and key
                    in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End)
                    and not is_ctrl):
                self.play_timer.stop()
                self.is_playing = False
            self.need_redraw = True
            self.update()
            if self.progress_bar:
                self.progress_bar.update()
        else:
            e.ignore()

    def ToggleDisplayMode(self, mode):
        """Toggle a mode or advance the three-state JUMP mode."""
        if mode == "R":
            self.show_realistic = not self.show_realistic
            frame = self.window()
            if hasattr(frame, "realisticItem"):
                frame.realisticItem.setChecked(self.show_realistic)
        elif mode == "X":
            self.show_density = not self.show_density
            if self.show_density and not self.density_ready:
                self.CalculateStitchDensity()
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
        self.RefreshModeIndicators()
        self.need_redraw = True
        self.update()

    def RefreshModeIndicators(self):
        if self.mode_panel is not None:
            self.mode_panel.RefreshIndicators()

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
            if key_code in (ord(shortcut), ord(shortcut.lower())):
                dlg.close()
                return
            event.ignore()
        dlg.keyPressEvent = on_dialog_key
        setattr(self, key, dlg)
        dlg.show()

    def ShowHelp(self):
        show_help(self)

    def ShowSettings(self):
        show_settings(self)

    def SetStepSize(self, size):
        self.step_size = max(1, size)

    def LoadDesign(self, path, fit_to_screen=True):
        """Load an embroidery file into renderable stitch segments."""
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
        self.need_redraw = True
        self.update()
        if self.progress_bar:
            self.progress_bar.update()
        return True

    def CalculateStitchDensity(self):
        """Calculate the density map once, on demand, using the Numba kernel."""
        if self.density_ready or len(self.stitch_points_np) == 0:
            return
        frame = self.window()
        if hasattr(frame, "statusBar"):
            frame.statusBar().showMessage("Calculating stitch density...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        min_x, min_y, max_x, max_y = self.bounds
        try:
            self.stitch_density_np = calculate_stitch_density_numba(
                self.stitch_points_np,
                min_x,
                min_y,
                max_x,
                max_y,
            )
        finally:
            QApplication.restoreOverrideCursor()
        self.density_ready = True
        if hasattr(frame, "statusBar"):
            frame.statusBar().showMessage("Density map ready")
            QTimer.singleShot(1500, lambda: frame.statusBar().showMessage(DEFAULT_STATUS_TEXT))
        self.need_redraw = True
        self.update()

    def paintEvent(self, e):
        """Render the current viewport, using the cached bitmap when possible."""
        dc = QPainter(self)
        dc.fillRect(self.rect(), QColor(255, 255, 255))
        if self._pending_fit_to_screen:
            dc.end()
            return
        if not self.need_redraw and self.cached_bitmap:
            zoom_ratio = self.zoom / self.cached_zoom
            if abs(zoom_ratio - 1.0) < 0.001:
                pan_delta_x = round(self.pan_x - self.cached_pan_x)
                pan_delta_y = round(self.pan_y - self.cached_pan_y)
                dc.drawPixmap(pan_delta_x, pan_delta_y, self.cached_bitmap)
            else:
                bitmap_width = self.cached_bitmap.width()
                bitmap_height = self.cached_bitmap.height()
                preview_x = round(self.pan_x - zoom_ratio * self.cached_pan_x)
                preview_y = round(self.pan_y - zoom_ratio * self.cached_pan_y)
                dc.drawPixmap(
                    preview_x, preview_y,
                    round(bitmap_width * zoom_ratio),
                    round(bitmap_height * zoom_ratio),
                    self.cached_bitmap,
                )
            self.DrawAnalysisOverlays(dc)
            self.DrawNeedleOverlay(dc)
            dc.end()
            return
        w, h = self.width(), self.height()
        if self.stitches_np.shape[0] == 0:
            dc.setFont(QFont(self.font().family(), 14))
            dc.drawText(
                20,
                20,
                "Open an embroidery file via File > Open or pass it as a command-line argument",
            )
            dc.drawText(
                20,
                45,
                "H=help, Space=play/pause, Ctrl+Arrows=color, Alt+Arrows=1",
            )
            dc.end()
            return
        use_shaded = self.zoom > 1.2
        buf = np.full((h, w, 3), 255, dtype=np.uint8)
        use_realistic = self.show_realistic and self.zoom > 1.2
        if use_realistic:
            render_fabric_numba(buf, self.zoom)
        if self.show_grid:
            render_grid_numba(buf, self.zoom, self.pan_x, self.pan_y)
        if self.show_stitches and self.stitches_np.shape[
                0] > 0 and self.visible_count > 0:
            if use_realistic:
                render_realistic_numba(
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
            else:
                render_shaded_numba(
                    buf,
                    self.stitches_np,
                    self.visible_count,
                    self.zoom,
                    self.pan_x,
                    self.pan_y,
                    use_shaded,
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
        self.need_redraw = False
        dc.drawPixmap(0, 0, bmp)
        self.DrawAnalysisOverlays(dc)
        self.DrawNeedleOverlay(dc)
        dc.end()

    def DrawAnalysisOverlays(self, dc):
        """Draw optional jump paths and local stitch-density diagnostics."""
        if self.show_jumps:
            for x1, y1, x2, y2, risky, stitch_index in self.jump_segments:
                if stitch_index > self.visible_count:
                    continue
                if self.risky_jumps_only and not risky:
                    continue
                color = QColor(220, 45, 45) if risky else QColor(100, 100, 100)
                dc.setPen(QPen(color, 2, Qt.DashLine))
                dc.drawLine(
                    int(x1 * self.zoom + self.pan_x),
                    int(y1 * self.zoom + self.pan_y),
                    int(x2 * self.zoom + self.pan_x),
                    int(y2 * self.zoom + self.pan_y),
                )

    def DrawNeedleOverlay(self, dc):
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
        dc.setPen(QPen(QColor(10, 10, 10), 8 if outer_radius else 4))
        dc.drawLine(needle_x - arm, needle_y, needle_x + arm, needle_y)
        dc.drawLine(needle_x, needle_y - arm, needle_x, needle_y + arm)
        if outer_radius:
            dc.setBrush(Qt.NoBrush)
            dc.drawEllipse(needle_x - outer_radius, needle_y - outer_radius,
                           outer_radius * 2, outer_radius * 2)
        dc.setPen(QPen(QColor(255, 255, 255), 3 if outer_radius else 2))
        dc.setBrush(Qt.NoBrush)
        dc.drawEllipse(needle_x - radius, needle_y - radius, radius * 2, radius * 2)
        dc.drawLine(needle_x - arm, needle_y, needle_x + arm, needle_y)
        dc.drawLine(needle_x, needle_y - arm, needle_x, needle_y + arm)
        dc.setBrush(QColor(255, 220, 40))
        dc.setPen(QPen(QColor(10, 10, 10), 2))
        marker_radius = 5 if outer_radius else 3
        dc.drawEllipse(needle_x - marker_radius, needle_y - marker_radius,
                       marker_radius * 2, marker_radius * 2)

    def HighlightNeedle(self):
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
            lambda: self._SetNeedleHighlightStage(1))
        self._needle_highlight_timer.start(200)
        self.update()

    def _SetNeedleHighlightStage(self, stage):
        """Advance the temporary needle marker through its visual pulse."""
        if not self.show_needle:
            return
        self.needle_highlight_stage = stage
        self.update()
        if stage == 1:
            self._needle_highlight_timer = QTimer(self)
            self._needle_highlight_timer.setSingleShot(True)
            self._needle_highlight_timer.timeout.connect(self.StopNeedleHighlight)
            self._needle_highlight_timer.start(300)

    def StopNeedleHighlight(self):
        """Return the needle crosshair to its normal size."""
        self.needle_highlighted = False
        self.needle_highlight_stage = 0
        self._needle_highlight_timer = None
        self.update()

    def OnWheel(self, e):
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
            self.need_redraw = False
            self.zoom_render_timer = QTimer(self)
            self.zoom_render_timer.setSingleShot(True)
            self.zoom_render_timer.timeout.connect(self._finish_zoom_render)
            self.zoom_render_timer.start(140)
        else:
            self.need_redraw = True
        self.update()

    def _finish_zoom_render(self):
        """Schedule a full-quality render after zooming settles."""
        self.zoom_render_timer = None
        self.need_redraw = True
        self.update()

    def OnLeftDown(self, e):
        """Start panning from the current mouse position."""
        self.drag_start = e.position().toPoint()
        self.pan_start = (self.pan_x, self.pan_y)
        self.setFocus()
        self.grabMouse()

    def OnLeftUp(self, e):
        """Stop panning and clean up any progress-bar mouse capture."""
        self.releaseMouse()
        self.drag_start = None
        self.need_redraw = True
        self.update()
        if self.progress_bar and self.progress_bar.dragging:
            self.progress_bar.dragging = False
            self.progress_bar.releaseMouse()

    def OnMotion(self, e):
        """Update the viewport offset while the user drags the canvas."""
        if self.drag_start and e.buttons() & Qt.LeftButton:
            position = e.position().toPoint()
            dx = position.x() - self.drag_start.x()
            dy = position.y() - self.drag_start.y()
            self.pan_x = self.pan_start[0] + dx
            self.pan_y = self.pan_start[1] + dy
            self.update()

    def keyPressEvent(self, event):
        self.OnKeyDown(event)

    def keyReleaseEvent(self, event):
        self.OnKeyUp(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.OnLeftDown(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.OnLeftUp(event)

    def mouseMoveEvent(self, event):
        self.OnMotion(event)

    def wheelEvent(self, event):
        self.OnWheel(event)
