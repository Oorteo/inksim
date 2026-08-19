"""Central keyboard handling for the main viewer window."""

import time

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication


class ViewerShortcutFilter(QObject):
    """Route main-window key presses to the viewer from one place."""

    def __init__(self, window, viewer):
        super().__init__(window)
        self.window = window
        self.viewer = viewer
        self._last_key_time = 0
        self._key_throttle = 0.03
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() != QEvent.KeyPress or not hasattr(watched, "window"):
            return False
        if watched.window() is not self.window:
            return False
        return self.handle_key_event(event)

    def handle_key_event(self, event):
        viewer = self.viewer
        now = time.time()
        key = event.key()
        is_alt = bool(event.modifiers() & Qt.AltModifier)
        is_ctrl = bool(event.modifiers() & Qt.ControlModifier)
        if is_alt and key in (Qt.Key_F, Qt.Key_P):
            return False
        if is_ctrl and key in (Qt.Key_Q, Qt.Key_O):
            return False
        is_space_or_c = key in (Qt.Key_Space, Qt.Key_C)
        if (
            not is_space_or_c
            and now - self._last_key_time < self._key_throttle
            and not is_alt
            and not is_ctrl
        ):
            return True
        self._last_key_time = now
        total = viewer.stitches_np.shape[0]
        is_shift = bool(event.modifiers() & Qt.ShiftModifier)
        changed = False
        cursor_changed = False
        highlight_needle = False
        step = 1 if is_alt else viewer.step_size

        if is_shift and not is_alt and not is_ctrl and key in (
            Qt.Key_Right,
            Qt.Key_Left,
        ):
            changed = viewer.jump_to_command(1 if key == Qt.Key_Right else -1)
            cursor_changed = changed
            highlight_needle = changed
            if changed and viewer.is_playing:
                viewer.play_timer.stop()
                viewer.is_playing = False
        elif viewer.is_playing and not is_alt and not is_ctrl and key in (
            Qt.Key_Right,
            Qt.Key_Left,
        ):
            key_direction = 1 if key == Qt.Key_Right else -1
            changed = viewer.adjust_playback_speed(key_direction * viewer._last_dir)
        elif is_ctrl and key in (Qt.Key_Right, Qt.Key_Left):
            viewer.jump_to_color(1 if key == Qt.Key_Right else -1)
            viewer._last_dir = 1 if key == Qt.Key_Right else -1
            changed = True
            cursor_changed = True
            highlight_needle = True
        elif not is_alt and not is_ctrl and key in (
            Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D
        ):
            pan_step = 40
            if key == Qt.Key_W:
                viewer.pan_y -= pan_step
            elif key == Qt.Key_A:
                viewer.pan_x -= pan_step
            elif key == Qt.Key_S:
                viewer.pan_y += pan_step
            else:
                viewer.pan_x += pan_step
            changed = True
        elif key == Qt.Key_Right:
            if viewer.visible_count < total:
                viewer.visible_count = min(total, viewer.visible_count + step)
                viewer._last_dir = 1
                changed = True
                cursor_changed = True
        elif key == Qt.Key_Left:
            if viewer.visible_count > 0:
                viewer.visible_count = max(0, viewer.visible_count - step)
                viewer._last_dir = -1
                changed = True
                cursor_changed = True
        elif key == Qt.Key_Up:
            viewer.visible_count = min(total, viewer.visible_count + step * 10)
            viewer._last_dir = 1
            changed = True
            cursor_changed = True
        elif key == Qt.Key_Down:
            viewer.visible_count = max(0, viewer.visible_count - step * 10)
            viewer._last_dir = -1
            changed = True
            cursor_changed = True
        elif key == Qt.Key_Home:
            viewer.visible_count = 0
            changed = True
            cursor_changed = True
        elif key == Qt.Key_End:
            viewer.visible_count = total
            changed = True
            cursor_changed = True
        elif key == Qt.Key_Space:
            viewer.toggle_auto_play()
            return True
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            old_zoom = viewer.zoom
            viewer.zoom = min(viewer.maximum_zoom(), viewer.zoom * 1.15)
            scale = viewer.zoom / old_zoom
            center_x = viewer.width() / 2
            center_y = viewer.height() / 2
            viewer.pan_x = center_x - scale * (center_x - viewer.pan_x)
            viewer.pan_y = center_y - scale * (center_y - viewer.pan_y)
            changed = True
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            old_zoom = viewer.zoom
            viewer.zoom = max(viewer.minimum_zoom(), viewer.zoom / 1.15)
            scale = viewer.zoom / old_zoom
            center_x = viewer.width() / 2
            center_y = viewer.height() / 2
            viewer.pan_x = center_x - scale * (center_x - viewer.pan_x)
            viewer.pan_y = center_y - scale * (center_y - viewer.pan_y)
            changed = True
        elif key in (
            Qt.Key_BracketLeft,
            Qt.Key_BracketRight,
            Qt.Key_BraceLeft,
            Qt.Key_BraceRight,
        ):
            shading_delta = viewer.shading_step
            if key in (Qt.Key_BracketLeft, Qt.Key_BraceLeft):
                shading_delta = -shading_delta
            if is_ctrl and not is_alt:
                viewer.dark_factor = max(
                    0.0,
                    min(1.0, viewer.dark_factor + shading_delta),
                )
            elif is_alt and not is_ctrl:
                viewer.light_factor = max(
                    0.0,
                    min(1.0, viewer.light_factor + shading_delta),
                )
            elif not is_ctrl and not is_alt:
                viewer.line_width = max(
                    0.1,
                    min(1.0, viewer.line_width + shading_delta),
                )
            changed = True
        elif key == Qt.Key_C and not is_alt and not is_ctrl:
            viewer.center_design()
            return True
        elif key == Qt.Key_F and not is_alt and not is_ctrl:
            viewer.fit_to_screen()
            return True
        elif key == Qt.Key_1 and not is_alt and not is_ctrl:
            viewer.set_one_to_one()
            return True
        elif key == Qt.Key_F11:
            viewer.fullscreen_requested.emit()
            return True
        elif key == Qt.Key_G and not is_alt and not is_ctrl:
            viewer.show_grid = not viewer.show_grid
            viewer.grid_toggled.emit(viewer.show_grid)
            changed = True
        elif key == Qt.Key_J and not is_alt and not is_ctrl:
            viewer.toggle_display_mode("J")
            changed = True
        elif key == Qt.Key_X and not is_alt and not is_ctrl:
            viewer.toggle_display_mode("X")
            changed = True
        elif key == Qt.Key_V and not is_alt and not is_ctrl:
            viewer.toggle_display_mode("V")
            changed = True
        elif key == Qt.Key_Z and not is_alt and not is_ctrl:
            viewer.toggle_display_mode("Z")
            changed = True
        elif key == Qt.Key_R and not is_alt and not is_ctrl:
            viewer.select_renderer()
            changed = True
        elif key == Qt.Key_N and not is_alt and not is_ctrl:
            viewer.show_needle = not viewer.show_needle
            if viewer.show_needle:
                viewer.highlight_needle()
            else:
                viewer.stop_needle_highlight()
            changed = True
        elif key == Qt.Key_H and not is_alt and not is_ctrl:
            viewer.show_help()
            return True
        elif key == Qt.Key_I and not is_alt and not is_ctrl:
            viewer.show_settings()
            return True
        elif key == Qt.Key_Escape:
            if viewer.is_playing:
                viewer.play_timer.stop()
                viewer.is_playing = False
                return True
            return False
        else:
            return False

        if changed:
            if cursor_changed and hasattr(viewer, "notify_cursor_changed"):
                viewer.notify_cursor_changed()
            if highlight_needle:
                viewer.highlight_needle()
            if (
                viewer.is_playing
                and key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End)
                and not is_ctrl
            ):
                viewer.play_timer.stop()
                viewer.is_playing = False
            viewer.invalidate_cache()
            viewer.update()
            viewer.update_mode_indicators()
            if viewer.progress_bar:
                viewer.progress_bar.update()
        return True
