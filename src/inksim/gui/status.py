import wx

class ModeStatusPanel(wx.Panel):
    """Clickable indicators for the main viewer display modes."""

    def __init__(self, parent, viewer):
        super().__init__(parent, size=(-1, 38))
        self.viewer = viewer
        self.SetBackgroundColour(wx.Colour(245, 245, 245))
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.buttons = {}
        for mode in ("R", "X", "J", "V"):
            button = wx.Button(self, label=mode, size=(32, 32))
            button.SetMinSize((32, 32))
            button.Bind(wx.EVT_BUTTON, self.OnModeClick)
            self.buttons[mode] = button
            sizer.Add(button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        self.SetSizer(sizer)
        self.RefreshIndicators()

    def OnModeClick(self, event):
        for mode, button in self.buttons.items():
            if event.GetEventObject() is button:
                self.viewer.ToggleDisplayMode(mode)
                self.viewer.SetFocus()
                return

    def RefreshIndicators(self):
        states = {
            "R": self.viewer.show_realistic,
            "X": self.viewer.show_density,
            "V": self.viewer.show_stitches,
        }
        jump_state = 0
        if self.viewer.show_jumps:
            jump_state = 2 if self.viewer.risky_jumps_only else 1
        for mode, button in self.buttons.items():
            state = jump_state if mode == "J" else int(states[mode])
            if mode == "J" and state == 2:
                color = wx.Colour(210, 145, 45)
            elif state:
                color = wx.Colour(75, 140, 90)
            else:
                color = wx.Colour(225, 225, 225)
            button.SetBackgroundColour(color)
            button.SetForegroundColour(
                wx.WHITE if state else wx.Colour(45, 45, 45)
            )
        self.Layout()
