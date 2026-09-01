# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Central keyboard handling for the main viewer window."""

import time

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication

from ..debug import logger


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
        if QApplication.activePopupWidget() is not None:
            return False
        return self.handle_key_event(event)

    def _key_label(self, event) -> str:
        """Return a compact label describing the key press for event trace."""
        modifiers = []
        if event.modifiers() & Qt.ControlModifier:
            modifiers.append("Ctrl")
        if event.modifiers() & Qt.AltModifier:
            modifiers.append("Alt")
        if event.modifiers() & Qt.ShiftModifier:
            modifiers.append("Shift")
        key_map = {
            Qt.Key_Space: "Space",
            Qt.Key_Right: "→",
            Qt.Key_Left: "←",
            Qt.Key_Up: "↑",
            Qt.Key_Down: "↓",
            Qt.Key_Home: "Home",
            Qt.Key_End: "End",
            Qt.Key_PageUp: "PgUp",
            Qt.Key_PageDown: "PgDn",
            Qt.Key_Escape: "Esc",
            Qt.Key_Return: "Enter",
            Qt.Key_Enter: "Enter",
            Qt.Key_Tab: "Tab",
            Qt.Key_Backspace: "Backspace",
            Qt.Key_Delete: "Del",
            Qt.Key_Plus: "+",
            Qt.Key_Equal: "=",
            Qt.Key_Minus: "-",
            Qt.Key_Underscore: "_",
            Qt.Key_BracketLeft: "[",
            Qt.Key_BracketRight: "]",
            Qt.Key_BraceLeft: "{",
            Qt.Key_BraceRight: "}",
            Qt.Key_F1: "F1",
            Qt.Key_F2: "F2",
            Qt.Key_F3: "F3",
            Qt.Key_F4: "F4",
            Qt.Key_F5: "F5",
            Qt.Key_F6: "F6",
            Qt.Key_F7: "F7",
            Qt.Key_F8: "F8",
            Qt.Key_F9: "F9",
            Qt.Key_F10: "F10",
            Qt.Key_F11: "F11",
            Qt.Key_F12: "F12",
            Qt.Key_0: "0",
            Qt.Key_1: "1",
            Qt.Key_2: "2",
            Qt.Key_3: "3",
            Qt.Key_4: "4",
            Qt.Key_5: "5",
            Qt.Key_6: "6",
            Qt.Key_7: "7",
            Qt.Key_8: "8",
            Qt.Key_9: "9",
            **{getattr(Qt, f"Key_{chr(c)}"): chr(c) for c in range(ord("A"), ord("Z") + 1)},
        }
        key = event.key()
        label = key_map.get(key, event.text().upper())
        if not label:
            label = f"Key_{key}"
        if modifiers:
            return f"{'+'.join(modifiers)}+{label}"
        return label

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
        handled = False
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
            handled = changed
        elif viewer.is_playing and not is_alt and not is_ctrl and key in (
            Qt.Key_Right,
            Qt.Key_Left,
        ):
            viewer.set_playback_direction(key == Qt.Key_Right)
            handled = True
        elif viewer.is_playing and not is_alt and not is_ctrl and key in (
            Qt.Key_Up, Qt.Key_Down
        ):
            viewer.adjust_playback_speed(1 if key == Qt.Key_Up else -1)
            handled = True
        elif is_ctrl and key in (Qt.Key_Right, Qt.Key_Left):
            viewer.jump_to_color(1 if key == Qt.Key_Right else -1)
            viewer._last_dir = 1 if key == Qt.Key_Right else -1
            changed = True
            cursor_changed = True
            highlight_needle = True
            handled = True
        elif is_ctrl and key == Qt.Key_A:
            # Toggle between "show all stitches" and "show none". This makes
            # Ctrl+A a quick way to prepare for playback from either end.
            total = viewer.stitches_np.shape[0]
            if viewer.visible_count < total:
                viewer.visible_count = total
                viewer._last_dir = 1
            else:
                viewer.visible_count = 0
                viewer._last_dir = -1
            logger.debug(
                "Ctrl+A toggled visible_count to %s/%s (renderer=%s)",
                viewer.visible_count, total, viewer.active_renderer,
            )
            viewer.notify_cursor_changed()
            viewer.invalidate_cache()
            viewer.update()
            viewer.update_mode_indicators()
            if viewer.progress_bar:
                viewer.progress_bar.update()
            if viewer.is_playing:
                viewer.play_timer.stop()
                viewer.is_playing = False
            handled = True
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
            handled = True
        elif key in (Qt.Key_Right, Qt.Key_Left, Qt.Key_Up, Qt.Key_Down):
            if key == Qt.Key_Right:
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
            else:
                viewer.visible_count = max(0, viewer.visible_count - step * 10)
                viewer._last_dir = -1
                changed = True
                cursor_changed = True
            handled = changed
        elif key in (Qt.Key_Home, Qt.Key_End):
            viewer.visible_count = 0 if key == Qt.Key_Home else total
            changed = True
            cursor_changed = True
            handled = True
        elif key == Qt.Key_Space:
            viewer.toggle_auto_play()
            handled = True
        elif key in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Minus, Qt.Key_Underscore):
            old_zoom = viewer.zoom
            zoom_in = key in (Qt.Key_Plus, Qt.Key_Equal)
            viewer.zoom = (
                min(viewer.maximum_zoom(), viewer.zoom * 1.15)
                if zoom_in
                else max(viewer.minimum_zoom(), viewer.zoom / 1.15)
            )
            scale = viewer.zoom / old_zoom
            center_x = viewer.width() / 2
            center_y = viewer.height() / 2
            viewer.pan_x = center_x - scale * (center_x - viewer.pan_x)
            viewer.pan_y = center_y - scale * (center_y - viewer.pan_y)
            changed = True
            handled = True
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
            handled = True
        elif key == Qt.Key_F and not is_alt and not is_ctrl:
            viewer.fit_to_screen()
            handled = True
        elif key == Qt.Key_1 and not is_alt and not is_ctrl:
            viewer.set_one_to_one()
            handled = True
        elif key == Qt.Key_F11:
            viewer.fullscreen_requested.emit()
            handled = True
        elif key == Qt.Key_G and not is_alt and not is_ctrl:
            viewer.show_grid = not viewer.show_grid
            viewer.grid_toggled.emit(viewer.show_grid)
            changed = True
            handled = True
        elif key in (Qt.Key_J, Qt.Key_X, Qt.Key_V, Qt.Key_Z) and not is_alt and not is_ctrl:
            viewer.toggle_display_mode(
                {Qt.Key_J: "J", Qt.Key_X: "X", Qt.Key_V: "V", Qt.Key_Z: "Z"}[key]
            )
            changed = True
            handled = True
        elif key == Qt.Key_R and not is_alt and not is_ctrl:
            viewer.select_renderer()
            changed = True
            handled = True
        elif key == Qt.Key_N and not is_alt and not is_ctrl:
            viewer.show_needle = not viewer.show_needle
            if viewer.show_needle:
                viewer.highlight_needle()
            else:
                viewer.stop_needle_highlight()
            changed = True
            handled = True
        elif key == Qt.Key_H and not is_alt and not is_ctrl:
            viewer.show_help()
            handled = True
        elif key == Qt.Key_I and not is_alt and not is_ctrl:
            viewer.show_settings()
            handled = True
        elif key == Qt.Key_M and not is_alt and not is_ctrl:
            viewer.window().toggle_window_layout()
            handled = True
        elif key == Qt.Key_Escape:
            if viewer.is_playing:
                viewer.play_timer.stop()
                viewer.is_playing = False
                if viewer._last_dir >= 0:
                    viewer.visible_count = viewer.stitches_np.shape[0]
                else:
                    viewer.visible_count = 0
                viewer.notify_cursor_changed()
                viewer.invalidate_cache()
                viewer.update()
                if viewer.progress_bar:
                    viewer.progress_bar.update()
                handled = True
            else:
                handled = False

        if not handled:
            return False

        if changed:
            if cursor_changed and hasattr(viewer, "notify_cursor_changed"):
                viewer.notify_cursor_changed()
            if highlight_needle:
                viewer.highlight_needle()
            if (
                viewer.is_playing
                and key in (Qt.Key_Home, Qt.Key_End)
                and not is_ctrl
            ):
                viewer.play_timer.stop()
                viewer.is_playing = False
            viewer.invalidate_cache()
            viewer.update()
            viewer.update_mode_indicators()
            if viewer.progress_bar:
                viewer.progress_bar.update()

        viewer._trace_event(self._key_label(event))
        return True
