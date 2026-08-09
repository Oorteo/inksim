import wx

class ProgressBarPanel(wx.Panel):
    """Interactive stitch timeline shown below the embroidery viewer.

    The panel uses the viewer as its source of truth. It displays the loaded
    stitch colors, overlays the currently visible portion, and lets the user
    seek by clicking or dragging across the timeline.
    """

    def __init__(self, parent, viewer_panel):
        """Create a timeline connected to ``viewer_panel``."""
        super().__init__(parent, size=(-1, 58))
        self.viewer = viewer_panel
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetDoubleBuffered(True)
        self.SetBackgroundColour(wx.Colour(250, 250, 250))
        self.Bind(wx.EVT_ERASE_BACKGROUND, self.OnEraseBackground)
        self.Bind(wx.EVT_PAINT, self.OnPaint)
        self.Bind(wx.EVT_LEFT_DOWN, self.OnClick)
        self.Bind(wx.EVT_LEFT_UP, self.OnLeftUp)
        self.Bind(wx.EVT_MOTION, self.OnMotionClick)

        self.dragging = False
        self.drag_moved = False
        self.margin_x = 24
        self.bar_y = 8
        self.bar_h = 14

    def OnEraseBackground(self, e):
        """Keep wxMSW from clearing the timeline before painting."""
        pass

    def OnClick(self, e):
        """Start seeking at the mouse position."""
        self.dragging = True
        self.drag_moved = False
        self.Seek(e.GetPosition().x)
        self.viewer.HighlightNeedle()
        self.CaptureMouse()

    def OnLeftUp(self, e):
        """Finish a seek operation and release the mouse capture."""
        if self.dragging:
            self.Seek(e.GetPosition().x)
            self.viewer.HighlightNeedle()
            if self.HasCapture():
                self.ReleaseMouse()
            self.dragging = False
            self.drag_moved = False

    def OnMotionClick(self, e):
        """Update the seek position while the left button is dragged."""
        if self.dragging and e.Dragging() and e.LeftIsDown():
            self.drag_moved = True
            self.Seek(e.GetPosition().x)

    def Seek(self, mouse_x):
        """Map a horizontal mouse position to a visible stitch count."""
        w = self.GetSize().width
        total = self.viewer.stitches_np.shape[0]
        if total == 0 or w == 0:
            return

        bar_w = w - 2*self.margin_x
        rel_x = mouse_x - self.margin_x
        ratio = max(0.0, min(1.0, rel_x / bar_w if bar_w > 0 else 0))
        self.viewer.visible_count = int(ratio * total)
        self.viewer.need_redraw = True
        self.viewer.Refresh()
        self.Refresh()

    def OnPaint(self, e):
        """Paint the color timeline, progress overlay, knob, and labels."""
        dc = wx.BufferedPaintDC(self)
        w, _ = self.GetSize()
        dc.SetBackground(wx.Brush(wx.Colour(250, 250, 250)))
        dc.Clear()

        total = self.viewer.stitches_np.shape[0]
        vis = self.viewer.visible_count
        bar_x = self.margin_x
        bar_y = self.bar_y
        bar_w = w - 2*self.margin_x
        bar_h = self.bar_h
        dc.SetBrush(wx.Brush(wx.Colour(230, 230, 230)))
        dc.SetPen(wx.Pen(wx.Colour(200, 200, 200), 1))
        dc.DrawRoundedRectangle(bar_x, bar_y, bar_w, bar_h, 4)

        if total == 0:
            dc.SetTextForeground(wx.Colour(120, 120, 120))
            dc.DrawText("No file loaded - open an embroidery file", bar_x, bar_y + 22)
            return

        stitches = self.viewer.stitches_np
        dc.SetClippingRegion(bar_x, bar_y, bar_w, bar_h)
        if bar_w < total:
            step = max(1, total // bar_w)
            for i in range(0, total, step):
                r = int(stitches[i, 4])
                g = int(stitches[i, 5])
                b = int(stitches[i, 6])
                xi = bar_x + int((i / total) * bar_w)
                dc.SetPen(wx.Pen(wx.Colour(r, g, b), 1))
                dc.DrawLine(xi, bar_y, xi, bar_y + bar_h)
        else:
            last_color = None
            block_start = 0
            for i in range(total):
                r = int(stitches[i, 4])
                g = int(stitches[i, 5])
                b = int(stitches[i, 6])
                color = (r, g, b)
                if color != last_color and last_color is not None:
                    x0 = bar_x + int((block_start / total) * bar_w)
                    x1 = bar_x + int((i / total) * bar_w)
                    wx_color = wx.Colour(*last_color)
                    dc.SetBrush(wx.Brush(wx_color))
                    dc.SetPen(wx.Pen(wx_color, 1))
                    dc.DrawRectangle(x0, bar_y, max(2, x1 - x0), bar_h)
                    block_start = i
                last_color = color

            if last_color:
                x0 = bar_x + int((block_start / total) * bar_w)
                wx_color = wx.Colour(*last_color)
                dc.SetBrush(wx.Brush(wx_color))
                dc.SetPen(wx.Pen(wx_color, 1))
                dc.DrawRectangle(x0, bar_y, bar_w - (x0 - bar_x), bar_h)

        command_colors = {
            "JUMP": wx.Colour(100, 100, 100),
            "COLOR CHANGE": wx.Colour(210, 45, 45),
            "TRIM": wx.Colour(230, 140, 20),
            "STOP": wx.Colour(180, 40, 40),
            "SLOW": wx.Colour(70, 100, 180),
            "FAST": wx.Colour(40, 150, 90),
        }
        for stitch_index, commands in self.viewer.command_events.items():
            marker_x = bar_x + int((stitch_index / total) * bar_w)
            for marker_index, command in enumerate(commands):
                marker_y = bar_y + marker_index * 5
                marker = [
                    (marker_x, marker_y),
                    (marker_x - 4, marker_y + 5),
                    (marker_x + 4, marker_y + 5),
                ]
                color = command_colors.get(command)
                if color is None and command.startswith("COLOR CHANGE"):
                    color = command_colors["COLOR CHANGE"]
                if color is None:
                    color = wx.Colour(80, 80, 80)
                dc.SetBrush(wx.Brush(color))
                dc.SetPen(wx.Pen(color, 1))
                dc.DrawPolygon(marker)

        progress_w = int((vis / total) * bar_w)
        dc.SetBrush(wx.Brush(wx.Colour(255, 255, 255, 150)))
        dc.SetPen(wx.TRANSPARENT_PEN)
        if progress_w < bar_w:
            dc.DrawRectangle(bar_x + progress_w, bar_y, bar_w - progress_w, bar_h)
        dc.DestroyClippingRegion()

        knob_x = bar_x + progress_w
        dc.SetPen(wx.Pen(wx.Colour(40, 40, 40), 2))
        dc.SetBrush(wx.Brush(wx.Colour(250, 250, 250)))
        dc.DrawCircle(knob_x, bar_y + bar_h // 2, 6)
        dc.SetBrush(wx.Brush(wx.Colour(40, 40, 40)))
        dc.DrawCircle(knob_x, bar_y + bar_h // 2, 3)
        dc.SetFont(wx.Font(
            9,
            wx.FONTFAMILY_DEFAULT,
            wx.FONTSTYLE_NORMAL,
            wx.FONTWEIGHT_NORMAL,
        ))
        dc.SetTextForeground(wx.Colour(30, 30, 30))

        txt_left = f"{vis}/{total} stitches"
        commands = self.viewer.command_events.get(vis, ())
        if commands:
            txt_left += f" | {' | '.join(commands)}"
        txt_center = f"{vis / total * 100:.1f}%"
        if hasattr(self.viewer, "bounds") and self.viewer.bounds != (0, 0, 0, 0):
            bw = self.viewer.bounds[2] - self.viewer.bounds[0]
            bh = self.viewer.bounds[3] - self.viewer.bounds[1]
            txt_right = (
                f"{bw:.1f} x {bh:.1f} mm | "
                f"{self.viewer.color_count} color sections"
            )
        else:
            txt_right = ""

        text_y = bar_y + bar_h + 6
        dc.DrawText(txt_left, bar_x, text_y)
        tw, _ = dc.GetTextExtent(txt_center)
        dc.DrawText(txt_center, bar_x + (bar_w - tw) // 2, text_y)
        if txt_right:
            tw, _ = dc.GetTextExtent(txt_right)
            dc.DrawText(txt_right, bar_x + bar_w - tw, text_y)
