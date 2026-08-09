import wx

class EmbroideryFileDropTarget(wx.FileDropTarget):
    """Open the first dropped file in the owning frame."""

    def __init__(self, frame):
        super().__init__()
        self.frame = frame

    def OnDropFiles(self, x, y, filenames):
        if filenames:
            self.frame.OpenFile(filenames[0])
        return True
