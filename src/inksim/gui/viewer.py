from pathlib import Path
import time

import numba
import numpy as np
import pystitch as emb
import wx
import wx.html

from ..constants import *
from ..render import (
    calculate_stitch_density_numba,
    render_density_numba,
    render_fabric_numba,
    render_grid_numba,
    render_realistic_numba,
    render_shaded_numba,
)

class EmbroideryViewerPanel(wx.Panel):
    """Fast interactive embroidery preview with playback and viewport controls.

    Stitch data is kept in a NumPy array and rendered into a bitmap by the
    Numba rasterizers above. This panel owns the viewer state: loaded design,
    current stitch position, zoom and pan, grid visibility, playback, and
    keyboard/mouse interaction.
    """

    def __init__(self, parent, progress_bar):
        """Create an empty viewer connected to the progress bar."""
        super().__init__(parent, style=wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetDoubleBuffered(True)
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
        self.play_timer = wx.Timer(self)
        self.play_speed = 20
        self.play_speed_levels = (1, 5, 10, 20, 40, 80)
        self.play_speed_index = 2
        self.play_step = self.play_speed_levels[self.play_speed_index]
        self.is_playing = False
        self.Bind(wx.EVT_TIMER, self.OnPlayTimer, self.play_timer)
        self.Bind(wx.EVT_ERASE_BACKGROUND, self.OnEraseBackground)
        self.Bind(wx.EVT_PAINT, self.OnPaint)
        self.Bind(wx.EVT_MOUSEWHEEL, self.OnWheel)
        self.Bind(wx.EVT_LEFT_DOWN, self.OnLeftDown)
        self.Bind(wx.EVT_LEFT_UP, self.OnLeftUp)
        self.Bind(wx.EVT_MOTION, self.OnMotion)
        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.Bind(wx.EVT_KEY_DOWN, self.OnKeyDown)
        self.Bind(wx.EVT_KEY_UP, self.OnKeyUp)
        self.SetFocus()

    def OnEraseBackground(self, e):
        """Keep wxMSW from clearing the canvas before a buffered repaint."""

    def OnSize(self, e):
        """Invalidate the bitmap and retry deferred initial fitting."""
        self.need_redraw = True
        if self._pending_fit_to_screen and self.stitches_np.shape[0] > 0:
            wx.CallAfter(self._try_fit_to_screen)
        e.Skip()

    def _try_fit_to_screen(self, retries=20):
        """Fit the design once wx has assigned a usable panel size."""
        if not self._pending_fit_to_screen:
            return
        w, h = self.GetSize()
        # On startup wx can briefly report tiny panel sizes.
        # If we fit at that moment, the design appears tiny in the top-left.
        # Retry shortly until layout stabilizes.
        if w < 120 or h < 120:
            if retries > 0:
                wx.CallLater(30, self._try_fit_to_screen, retries - 1)
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
        w, h = self.GetSize()
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
            display_index = wx.Display.GetFromWindow(self)
            if display_index == wx.NOT_FOUND:
                display_index = 0
            ppi = wx.Display(display_index).GetPPI()
            ppi_x = float(ppi.x)
            ppi_y = float(ppi.y)
            if ppi_x <= 0 or ppi_y <= 0:
                raise ValueError("invalid display PPI")
            pixels_per_mm = (ppi_x + ppi_y) / (2.0 * 25.4)
        except (AttributeError, TypeError, ValueError, wx.PyNoAppError):
            pixels_per_mm = 96.0 / 25.4
        self.zoom = pixels_per_mm
        self.CenterDesign()

    def CenterDesign(self):
        """Center the loaded design without changing its current zoom."""
        if self.stitches_np.shape[0] == 0:
            return
        w, h = self.GetSize()
        if w < 10 or h < 10:
            w, h = 1200, 800
        min_x, min_y, max_x, max_y = self.bounds
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        self.pan_x = w / 2 - cx * self.zoom
        self.pan_y = h / 2 - cy * self.zoom
        self.need_redraw = True
        self.Refresh()
        if self.progress_bar:
            self.progress_bar.Refresh()

    def OnPlayTimer(self, e):
        """Advance playback by one timer step in the current direction."""
        total = self.stitches_np.shape[0]
        if total == 0:
            self.play_timer.Stop()
            self.is_playing = False
            return
        self.visible_count += self.play_step * self._last_dir
        if self.visible_count >= total:
            self.visible_count = total
            self.play_timer.Stop()
            self.is_playing = False
        elif self.visible_count <= 0:
            self.visible_count = 0
            self.play_timer.Stop()
            self.is_playing = False
        self.need_redraw = True
        self.Refresh()
        if self.progress_bar:
            self.progress_bar.Refresh()

    def ToggleAutoPlay(self, forward=True):
        """Start or stop playback, choosing its direction when starting."""
        if self.is_playing:
            self.play_timer.Stop()
            self.is_playing = False
        else:
            self._last_dir = 1 if forward else -1
            self.play_timer.Start(self.play_speed)
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
        e.Skip()

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
        key = e.GetKeyCode()
        is_alt = e.AltDown()
        is_ctrl = e.ControlDown()
        # Let menu mnemonics and global shortcuts pass through
        # Alt+F, Alt+P for menu, Ctrl+Q for Quit, Ctrl+O for Open etc.
        if is_alt and key in (ord('F'), ord('f'), ord('P'), ord('p')):
            e.Skip()
            return
        if is_ctrl and key in (ord('Q'), ord('q'), ord('O'), ord('o')):
            e.Skip()
            return
        is_space_or_c = key in (
            wx.WXK_SPACE,
            ord("C"),
            ord("c"),
        )
        if (not is_space_or_c
                and now - self._last_key_time < self._key_throttle
                and not is_alt and not is_ctrl):
            return
        self._last_key_time = now
        total = self.stitches_np.shape[0]
        is_shift = e.ShiftDown()
        changed = False
        highlight_needle = False
        step = 1 if is_alt else self.step_size
        if is_shift and not is_alt and not is_ctrl and key in (
                wx.WXK_RIGHT,
                wx.WXK_LEFT,
        ):
            changed = self.JumpToCommand(1 if key == wx.WXK_RIGHT else -1)
            highlight_needle = changed
            if changed and self.is_playing:
                self.play_timer.Stop()
                self.is_playing = False
        elif self.is_playing and not is_alt and not is_ctrl and key in (
                wx.WXK_RIGHT,
                wx.WXK_LEFT,
        ):
            key_direction = 1 if key == wx.WXK_RIGHT else -1
            changed = self.AdjustPlaybackSpeed(key_direction * self._last_dir)
        elif is_ctrl and key in (wx.WXK_RIGHT, wx.WXK_LEFT):
            if key == wx.WXK_RIGHT:
                self.JumpToColor(1)
                self._last_dir = 1
            else:
                self.JumpToColor(-1)
                self._last_dir = -1
            changed = True
            highlight_needle = True
        elif key == wx.WXK_RIGHT:
            if self.visible_count < total:
                self.visible_count = min(total, self.visible_count + step)
                self._last_dir = 1
                changed = True
        elif key == wx.WXK_LEFT:
            if self.visible_count > 0:
                self.visible_count = max(0, self.visible_count - step)
                self._last_dir = -1
                changed = True
        elif key == wx.WXK_UP:
            self.visible_count = min(total, self.visible_count + step * 10)
            self._last_dir = 1
            changed = True
        elif key == wx.WXK_DOWN:
            self.visible_count = max(0, self.visible_count - step * 10)
            self._last_dir = -1
            changed = True
        elif key == wx.WXK_HOME:
            self.visible_count = 0
            changed = True
        elif key == wx.WXK_END:
            self.visible_count = total
            changed = True
        elif key == wx.WXK_SPACE:
            self.ToggleAutoPlay(forward=self._last_dir > 0)
            return
        elif key in (ord("+"), ord("="), wx.WXK_NUMPAD_ADD):
            self.line_width = min(1.0, self.line_width + 0.1)
            changed = True
        elif key in (ord("-"), ord("_"), wx.WXK_NUMPAD_SUBTRACT):
            self.line_width = max(0.1, self.line_width - 0.1)
            changed = True
        elif key in (ord("["), ord("{"), ord("]"), ord("}")):
            shading_delta = self.shading_step
            if key in (ord("["), ord("{")):
                shading_delta = -shading_delta
            if e.ShiftDown() or key in (ord("{"), ord("}")):
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
        elif key == wx.WXK_F11:
            frame = wx.GetTopLevelParent(self)
            if hasattr(frame, "ToggleFullScreen"):
                frame.ToggleFullScreen()
                return
        elif key in (ord("G"), ord("g")) and not is_alt and not is_ctrl:
            self.show_grid = not self.show_grid
            frame = wx.GetTopLevelParent(self)
            if hasattr(frame, "gridItem"):
                frame.gridItem.Check(self.show_grid)
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
        elif key == wx.WXK_ESCAPE:
            if self.is_playing:
                self.play_timer.Stop()
                self.is_playing = False
                return
        if changed:
            if highlight_needle:
                self.HighlightNeedle()
            if (self.is_playing and key
                    in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_HOME, wx.WXK_END)
                    and not is_ctrl):
                self.play_timer.Stop()
                self.is_playing = False
            self.need_redraw = True
            self.Refresh()
            if self.progress_bar:
                self.progress_bar.Refresh()
        else:
            e.Skip()

    def ToggleDisplayMode(self, mode):
        """Toggle a mode or advance the three-state JUMP mode."""
        if mode == "R":
            self.show_realistic = not self.show_realistic
            frame = wx.GetTopLevelParent(self)
            if hasattr(frame, "realisticItem"):
                frame.realisticItem.Check(self.show_realistic)
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
        self.Refresh()

    def RefreshModeIndicators(self):
        if self.mode_panel is not None:
            self.mode_panel.RefreshIndicators()

    def _show_html_dialog(self, key, title, html_content, width=1050, height=700):
        """Helper to show HTML content in a resizable dialog with HtmlWindow."""
        dialog = getattr(self, key)
        if dialog is not None:
            dialog.Close()
            return
        dlg = wx.Dialog(self,
                        title=title,
                        size=(width, height),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
                        | wx.MAXIMIZE_BOX)
        sizer = wx.BoxSizer(wx.VERTICAL)
        html_win = wx.html.HtmlWindow(dlg, style=wx.html.HW_SCROLLBAR_AUTO)
        styled_html = f"""
        <html><head></head><body>
        {html_content}
        </body></html>
        """
        html_win.SetPage(styled_html)
        sizer.Add(html_win, 1, wx.EXPAND | wx.ALL, 6)
        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(dlg, wx.ID_OK)
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.Realize()
        ok_btn.Bind(wx.EVT_BUTTON, lambda event: dlg.Close())
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
        dlg.SetSizer(sizer)
        dlg.Layout()
        dlg.CentreOnParent()
        def on_close(event):
            setattr(self, key, None)
            dlg.Destroy()

        dlg.Bind(wx.EVT_CLOSE, on_close)
        def on_dialog_key(event):
            key_code = event.GetKeyCode()
            closes_dialog = (
                (key == "help_dialog" and key_code in (ord("H"), ord("h")))
                or (key == "settings_dialog" and key_code in (ord("I"), ord("i")))
            )
            if closes_dialog:
                dlg.Close()
                return
            event.Skip()

        dlg.Bind(wx.EVT_CHAR_HOOK, on_dialog_key)
        setattr(self, key, dlg)
        dlg.Show()

    def ShowHelp(self):
        """Show keyboard and mouse controls in a compact 2-column HtmlWindow."""
        # <!-- <div align="center"><font size="10"><b>{APP_TITLE} - Help</b></font></div> -->

        html = """
        <table class="layout" valign="top"><tr valign="top">
        <td class="col" valign="top">
            <font size="5"><b>Mouse</b></font><br>
            <table class="inner" valign="top">
                <tr><td><b>Wheel</b></td><td>Zoom</td></tr>
                <tr><td><b>Drag</b></td><td>Pan</td></tr>
                <tr><td nowrap="nowrap"><b>Click bar</b></td><td nowrap="nowrap">Seek stitch</td></tr>
            </table>
        </td>
        <td class="col" valign="top">
            <font size="5"><b>Playback</b></font><br>
            <table class="inner" valign="top">
                <tr><td><b>Right/Left</b></td><td nowrap="nowrap">Speed up/down (playing)</td></tr>
                <tr><td><b></b></td><td nowrap="nowrap">Next/prev N stitches</td></tr>
                <tr><td><b>Alt+Right/Left</b></td><td>Next/prev 1 stitch</td></tr>
                <tr><td><b>Shift+Right/Left</b></td><td>Next/prev command</td></tr>
                <tr><td><b>Ctrl+Right/Left</b></td><td>Next/prev color</td></tr>
                <tr><td><b>Up/Down</b></td><td>Fast seek 10x</td></tr>
                <tr><td><b>Home/End</b></td><td>First/last stitch</td></tr>
                <tr><td><b>Space</b></td><td>Play/pause</td></tr>
                <tr><td><b>Esc</b></td><td>Stop</td></tr>
            </table>
        </td>
        <td class="col" valign="top">
            <font size="5"><b>View</b></font><br>
            <table class="inner" valign="top">
                <tr><td><b>C</b></td><td>Center design</td></tr>
                <tr><td><b>F</b></td><td>Fit to window</td></tr>
                <tr><td><b>F11</b></td><td>Fullscreen</td></tr>
                <tr><td><b>1</b></td><td>Physical 1:1 size</td></tr>
                <tr><td><b>V</b></td><td>Toggle embroidery</td></tr>
                <tr><td><b>G</b></td><td>Toggle grid</td></tr>
                <tr><td><b>N</b></td><td>Toggle needle</td></tr>
                <tr><td><b>J</b></td><td>Toggle jumps (off->all->risky)</td></tr>
                <tr><td><b>X</b></td><td>Toggle density map</td></tr>
                <tr><td><b>R</b></td><td>Toggle realistic 2.5D</td></tr>
                <tr><td><b>H</b></td><td>Toggle help</td></tr>
                <tr><td><b>I</b></td><td>Toggle settings</td></tr>
            </table>
        </td>
        <td class="col" valign="top">
            <font size="5"><b>Rendering</b></font><br>
            <table class="inner" valign="top">
                <tr><td><b>+/-</b></td><td nowrap="nowrap">Thread width</td></tr>
                <tr><td><b>[/]</b></td><td nowrap="nowrap">Dark shading</td></tr>
                <tr><td><b>Shift+[/]</b></td><td nowrap="nowrap">Light shading</td></tr>
            </table>
        </td>
        </tr></table>
        """
        self._show_html_dialog("help_dialog", "Help - " + APP_TITLE,
                               html,
                               width=1050,
                               height=580)

    def ShowSettings(self):
        """Show viewer state in a compact 2-column HtmlWindow without scrolling."""
        total = self.stitches_np.shape[0]
        min_x, min_y, max_x, max_y = self.bounds
        bw = max_x - min_x
        bh = max_y - min_y
        density_mode = "on" if self.show_density else "off"
        jump_mode = "risky only" if self.risky_jumps_only else "all" if self.show_jumps else "off"

        def badge(on):
            cls = "badge-on" if on else "badge-off"
            txt = "ON" if on else "OFF"
            return f'<span class="badge {cls}">{txt}</span>'

        def badge_text(txt, is_on):
            cls = "badge-on" if is_on else "badge-off"
            return f'<span class="badge {cls}">{txt}</span>'

        # <font size="13"><b>{APP_TITLE} - Settings</b></font><br>
        html = f"""
        <table class="layout"><tr>
        <td class="col" valign="top">
            <font size="5"><b>Design</b></font><br>
            <table class="inner">
                <tr><td><b>Stitches</b></td><td>{self.visible_count} / {total}</td></tr>
                <tr><td><b>Colors</b></td><td>{self.color_count}</td></tr>
                <tr><td><b>Bounds</b></td><td nowrap="nowrap">{bw:.1f} x {bh:.1f} mm</td></tr>
                <tr><td><b>Min</b></td><td nowrap="nowrap">{min_x:.1f}, {min_y:.1f}</td></tr>
                <tr><td><b>Max</b></td><td nowrap="nowrap">{max_x:.1f}, {max_y:.1f}</td></tr>
            </table>
        </td>
        <td class="col" valign="top">
            <font size="5"><b>Viewport</b></font><br>
            <table class="inner">
                <tr><td><b>Zoom</b></td><td>{self.zoom:.3f}x</td></tr>
                <tr><td><b>Pan</b></td><td nowrap="nowrap">{self.pan_x:.0f}, {self.pan_y:.0f} px</td></tr>
                <tr><td><b>Grid</b></td><td>{badge(self.show_grid)}</td></tr>
                <tr><td><b>Embroidery</b></td><td>{badge(self.show_stitches)}</td></tr>
                <tr><td><b>Realistic</b></td><td>{badge(self.show_realistic)}</td></tr>
                <tr><td><b>Jumps</b></td><td>{badge_text(jump_mode, self.show_jumps)}</td></tr>
                <tr><td><b>Density</b></td><td>{badge_text(density_mode, self.show_density)}</td></tr>
                <tr><td><b>Needle</b></td><td>{badge(self.show_needle)}</td></tr>
                <tr><td><b>Gradient</b></td><td>{badge(self.zoom > 1.2)}</td></tr>
            </table>
        </td>
        <td class="col" valign="top">
            <font size="5"><b>Density</b></font><br>
            <table class="inner">
                <tr><td><b>Radius</b></td><td nowrap="nowrap">{DENSITY_RADIUS_MM:.1f} mm</td></tr>
                <tr><td><b>Warning</b></td><td nowrap="nowrap">{DENSITY_WARNING_PER_MM2:.1f} /mm²</td></tr>
                <tr><td><b>Critical</b></td><td nowrap="nowrap">{DENSITY_CRITICAL_PER_MM2:.1f} /mm²</td></tr>
            </table>
        </td>
        <td class="col" valign="top">
            <font size="5"><b>Rendering</b></font><br>
            <table class="inner">
                <tr><td nowrap="nowrap"><b>Line width</b></td><td nowrap="nowrap">{self.line_width:.2f} mm</td></tr>
                <tr><td nowrap="nowrap"><b>Dark factor</b></td><td>{self.dark_factor:.2f}</td></tr>
                <tr><td nowrap="nowrap"><b>Light factor</b></td><td>{self.light_factor:.2f}</td></tr>
                <tr><td nowrap="nowrap"><b>Shading step</b></td><td>{self.shading_step:.2f}</td></tr>
            </table>
        </td>
        <td class="col" valign="top">
            <font size="5"><b>Playback</b></font><br>
            <table class="inner">
                <tr><td><b>Step size</b></td><td>{self.step_size}</td></tr>
                <tr><td><b>Interval</b></td><td nowrap="nowrap">{self.play_speed} ms</td></tr>
                <tr><td nowrap="nowrap"><b>Timer step</b></td><td>{self.play_step}</td></tr>
                <tr><td><b>Direction</b></td><td>{'forward' if self._last_dir > 0 else 'backward'}</td></tr>
                <tr><td><b>Playing</b></td><td>{badge(self.is_playing)}</td></tr>
            </table>
        </td>
        </tr></table>
        """
        self._show_html_dialog("settings_dialog", "Settings - " + APP_TITLE,
                               html,
                               width=1050,
                               height=620)

    def SetStepSize(self, size):
        self.step_size = max(1, size)

    def LoadDesign(self, path, fit_to_screen=True):
        """Load an embroidery file into renderable stitch segments."""
        try:
            pattern = emb.read(path)
        except Exception as ex:
            wx.MessageBox(f"Failed to load embroidery file: {ex}", "Error")
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
                set(boundary for boundary in self.color_boundaries
                    if boundary < len(segs)))
            self.color_count = len(self.color_boundaries)
            if fit_to_screen:
                self._pending_fit_to_screen = True
                wx.CallAfter(self._try_fit_to_screen)
        self.need_redraw = True
        self.Refresh()
        if self.progress_bar:
            self.progress_bar.Refresh()
        self.SetFocus()
        return True

    def CalculateStitchDensity(self):
        """Calculate the density map once, on demand, using the Numba kernel."""
        if self.density_ready or len(self.stitch_points_np) == 0:
            return
        frame = wx.GetTopLevelParent(self)
        if hasattr(frame, "SetStatusText"):
            frame.SetStatusText("Calculating stitch density...")
        wx.BeginBusyCursor()
        wx.SafeYield(frame, True)
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
            wx.EndBusyCursor()
        self.density_ready = True
        if hasattr(frame, "SetStatusText"):
            frame.SetStatusText("Density map ready")
            wx.CallLater(1500, frame.SetStatusText, DEFAULT_STATUS_TEXT)
        self.need_redraw = True
        self.Refresh()

    def OnPaint(self, e):
        """Render the current viewport, using the cached bitmap when possible."""
        dc = wx.BufferedPaintDC(self)
        dc.Clear()
        if self._pending_fit_to_screen:
            return
        if not self.need_redraw and self.cached_bitmap:
            zoom_ratio = self.zoom / self.cached_zoom
            if abs(zoom_ratio - 1.0) < 0.001:
                pan_delta_x = round(self.pan_x - self.cached_pan_x)
                pan_delta_y = round(self.pan_y - self.cached_pan_y)
                dc.DrawBitmap(self.cached_bitmap, pan_delta_x, pan_delta_y)
            else:
                bitmap_width = self.cached_bitmap.GetWidth()
                bitmap_height = self.cached_bitmap.GetHeight()
                preview_x = round(self.pan_x - zoom_ratio * self.cached_pan_x)
                preview_y = round(self.pan_y - zoom_ratio * self.cached_pan_y)
                source_dc = wx.MemoryDC()
                source_dc.SelectObject(self.cached_bitmap)
                try:
                    dc.StretchBlit(
                        preview_x,
                        preview_y,
                        round(bitmap_width * zoom_ratio),
                        round(bitmap_height * zoom_ratio),
                        source_dc,
                        0,
                        0,
                        bitmap_width,
                        bitmap_height,
                    )
                finally:
                    source_dc.SelectObject(wx.NullBitmap)
            self.DrawAnalysisOverlays(dc)
            self.DrawNeedleOverlay(dc)
            return
        w, h = self.GetSize()
        if self.stitches_np.shape[0] == 0:
            dc.SetFont(
                wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                        wx.FONTWEIGHT_NORMAL))
            dc.DrawText(
                "Open an embroidery file via File > Open or pass it as a command-line argument",
                20,
                20,
            )
            dc.DrawText(
                "H=help, Space=play/pause, Ctrl+Arrows=color, Alt+Arrows=1",
                20, 45)
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
        img = wx.Image(w, h)
        img.SetData(buf.tobytes())
        bmp = wx.Bitmap(img)
        self.cached_bitmap = bmp
        self.cached_pan_x = self.pan_x
        self.cached_pan_y = self.pan_y
        self.cached_zoom = self.zoom
        self.need_redraw = False
        dc.DrawBitmap(bmp, 0, 0)
        self.DrawAnalysisOverlays(dc)
        self.DrawNeedleOverlay(dc)

    def DrawAnalysisOverlays(self, dc):
        """Draw optional jump paths and local stitch-density diagnostics."""
        if self.show_jumps:
            for x1, y1, x2, y2, risky, stitch_index in self.jump_segments:
                if stitch_index > self.visible_count:
                    continue
                if self.risky_jumps_only and not risky:
                    continue
                color = wx.Colour(220, 45, 45) if risky else wx.Colour(
                    100, 100, 100)
                dc.SetPen(wx.Pen(color, 2, wx.PENSTYLE_SHORT_DASH))
                dc.DrawLine(
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
        dc.SetPen(wx.Pen(wx.Colour(10, 10, 10), 8 if outer_radius else 4))
        dc.DrawLine(needle_x - arm, needle_y, needle_x + arm, needle_y)
        dc.DrawLine(needle_x, needle_y - arm, needle_x, needle_y + arm)
        if outer_radius:
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawCircle(needle_x, needle_y, outer_radius)
        dc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 3 if outer_radius else 2))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawCircle(needle_x, needle_y, radius)
        dc.DrawLine(needle_x - arm, needle_y, needle_x + arm, needle_y)
        dc.DrawLine(needle_x, needle_y - arm, needle_x, needle_y + arm)
        dc.SetBrush(wx.Brush(wx.Colour(255, 220, 40)))
        dc.SetPen(wx.Pen(wx.Colour(10, 10, 10), 2))
        dc.DrawCircle(needle_x, needle_y, 5 if outer_radius else 3)

    def HighlightNeedle(self):
        """Pulse a large needle marker after user navigation."""
        if not self.show_needle:
            return
        self.needle_highlighted = True
        self.needle_highlight_stage = 2
        if self._needle_highlight_timer is not None:
            self._needle_highlight_timer.Stop()
        self._needle_highlight_timer = wx.CallLater(
            200,
            self._SetNeedleHighlightStage,
            1,
        )
        self.Refresh()

    def _SetNeedleHighlightStage(self, stage):
        """Advance the temporary needle marker through its visual pulse."""
        if not self.show_needle:
            return
        self.needle_highlight_stage = stage
        self.Refresh()
        if stage == 1:
            self._needle_highlight_timer = wx.CallLater(
                300,
                self.StopNeedleHighlight,
            )

    def StopNeedleHighlight(self):
        """Return the needle crosshair to its normal size."""
        self.needle_highlighted = False
        self.needle_highlight_stage = 0
        self._needle_highlight_timer = None
        self.Refresh()

    def OnWheel(self, e):
        """Zoom around the mouse position while preserving its world point."""
        mx, my = e.GetPosition()
        old = self.zoom
        self.zoom *= 1.15 if e.GetWheelRotation() > 0 else 1 / 1.15
        self.zoom = max(0.05, min(50.0, self.zoom))
        scale = self.zoom / old
        self.pan_x = mx - scale * (mx - self.pan_x)
        self.pan_y = my - scale * (my - self.pan_y)
        if self.zoom_render_timer is not None:
            self.zoom_render_timer.Stop()
        if self.cached_bitmap:
            self.need_redraw = False
            self.zoom_render_timer = wx.CallLater(
                140,
                self._finish_zoom_render,
            )
        else:
            self.need_redraw = True
        self.Refresh()

    def _finish_zoom_render(self):
        """Schedule a full-quality render after zooming settles."""
        self.zoom_render_timer = None
        self.need_redraw = True
        self.Refresh()

    def OnLeftDown(self, e):
        """Start panning from the current mouse position."""
        self.drag_start = e.GetPosition()
        self.pan_start = (self.pan_x, self.pan_y)
        self.SetFocus()
        if not self.HasCapture():
            self.CaptureMouse()

    def OnLeftUp(self, e):
        """Stop panning and clean up any progress-bar mouse capture."""
        if self.HasCapture():
            self.ReleaseMouse()
        self.drag_start = None
        self.need_redraw = True
        self.Refresh()
        if self.progress_bar and self.progress_bar.dragging:
            self.progress_bar.dragging = False
            if self.progress_bar.HasCapture(): self.progress_bar.ReleaseMouse()

    def OnMotion(self, e):
        """Update the viewport offset while the user drags the canvas."""
        if self.drag_start and e.Dragging() and e.LeftIsDown():
            dx = e.GetPosition()[0] - self.drag_start[0]
            dy = e.GetPosition()[1] - self.drag_start[1]
            self.pan_x = self.pan_start[0] + dx
            self.pan_y = self.pan_start[1] + dy
            self.Refresh(eraseBackground=False)
