from pathlib import Path

import wx

from ..formats import get_supported_input_extensions
from .viewer import EmbroideryViewerPanel


class EmbroideryOpenDialog(wx.Dialog):
    """Browse embroidery files with an in-app design preview."""

    def __init__(self, parent, initial_directory, selected_file=None):
        super().__init__(parent, title="Open embroidery file", size=(1100, 720))
        self.selected_path = None
        self._modal_result = None
        self.current_directory = Path(initial_directory or Path.cwd()).resolve()
        self.initial_file = Path(selected_file).resolve() if selected_file else None
        self.extensions = get_supported_input_extensions()

        root_sizer = wx.BoxSizer(wx.VERTICAL)
        directory_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.directory_text = wx.ComboBox(
            self,
            value=str(self.current_directory),
            style=wx.TE_PROCESS_ENTER,
        )
        directory_sizer.Add(self.directory_text, 1, wx.EXPAND | wx.RIGHT, 6)
        up_button = wx.Button(self, label="Up")
        browse_button = wx.Button(self, label="Browse...")
        directory_sizer.Add(up_button, 0, wx.RIGHT, 6)
        directory_sizer.Add(browse_button, 0)
        root_sizer.Add(directory_sizer, 0, wx.EXPAND | wx.ALL, 8)

        content_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.file_list = wx.ListBox(self)
        content_sizer.Add(self.file_list, 0, wx.EXPAND | wx.LEFT | wx.BOTTOM, 8)
        preview_container = wx.Panel(self)
        preview_sizer = wx.BoxSizer(wx.VERTICAL)
        self.preview = EmbroideryViewerPanel(preview_container, None)
        self.preview.show_grid = False
        self.preview.show_needle = False
        preview_sizer.Add(self.preview, 1, wx.EXPAND)
        preview_container.SetSizer(preview_sizer)
        content_sizer.Add(preview_container, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        root_sizer.Add(content_sizer, 1, wx.EXPAND)

        button_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        root_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(root_sizer)

        self.file_list.Bind(wx.EVT_LISTBOX, self.OnSelect)
        self.file_list.Bind(wx.EVT_LISTBOX_DCLICK, self.OnOpen)
        self.directory_text.Bind(wx.EVT_TEXT_ENTER, self.OnDirectoryEnter)
        self.directory_text.Bind(wx.EVT_COMBOBOX, self.OnDirectoryEnter)
        up_button.Bind(wx.EVT_BUTTON, self.OnUp)
        browse_button.Bind(wx.EVT_BUTTON, self.OnBrowse)
        self.Bind(wx.EVT_BUTTON, self.OnOpen, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self.OnCancel, id=wx.ID_CANCEL)

        self.RefreshFiles()

    def RefreshFiles(self):
        """Refresh the list for the current directory."""
        if not self.current_directory.is_dir():
            return
        directories = sorted(
            (path for path in self.current_directory.iterdir() if path.is_dir()),
            key=lambda path: path.name.lower(),
        )
        directory_choices = [str(self.current_directory), *(str(path) for path in directories)]
        self.directory_text.SetItems(directory_choices)
        self.directory_text.SetValue(str(self.current_directory))
        files = sorted(
            (
                path for path in self.current_directory.iterdir()
                if path.is_file() and path.suffix.lower().lstrip(".") in self.extensions
            ),
            key=lambda path: path.name.lower(),
        )
        file_names = [path.name for path in files]
        self.file_list.Set(file_names)
        self._resize_file_list(file_names)
        self.file_paths = files
        self.selected_path = None
        if files:
            selected_index = 0
            if self.initial_file:
                for index, path in enumerate(files):
                    if path == self.initial_file:
                        selected_index = index
                        break
            self.file_list.SetSelection(selected_index)
            self.OnSelect(None)

    def _resize_file_list(self, file_names):
        """Fit the file list to its names without starving the preview pane."""
        minimum_width = 160
        preview_width = 400
        content_margin = 32
        widest_name = max(
            (self.file_list.GetTextExtent(name)[0] for name in file_names),
            default=0,
        )
        available_width = max(
            minimum_width,
            self.GetClientSize().width - preview_width - content_margin,
        )
        list_width = min(max(minimum_width, widest_name + 32), available_width)
        self.file_list.SetMinSize((list_width, -1))
        self.Layout()

    def OnSelect(self, event):
        """Load the selected file into the preview panel."""
        selection = self.file_list.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        self.selected_path = self.file_paths[selection]
        self.preview.LoadDesign(str(self.selected_path), fit_to_screen=True)

    def OnOpen(self, event):
        """Accept the selected file."""
        if self.selected_path:
            self._EndModalOnce(wx.ID_OK)

    def OnCancel(self, event):
        self._EndModalOnce(wx.ID_CANCEL)

    def _EndModalOnce(self, result):
        """Finish the modal dialog only once while it is actually modal."""
        if self._modal_result is not None or not self.IsModal():
            return
        self._modal_result = result
        self.EndModal(result)

    def OnDirectoryEnter(self, event):
        self.SetDirectory(self.directory_text.GetValue())

    def SetDirectory(self, directory):
        """Change directory if it exists."""
        path = Path(directory).expanduser().resolve()
        if path.is_dir() and path != self.current_directory:
            self.current_directory = path
            self.initial_file = None
            self.RefreshFiles()

    def OnUp(self, event):
        self.SetDirectory(self.current_directory.parent)

    def OnBrowse(self, event):
        dialog = wx.DirDialog(
            self,
            "Choose directory",
            str(self.current_directory),
        )
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self.SetDirectory(dialog.GetPath())
        finally:
            dialog.Destroy()

    def GetPath(self):
        return str(self.selected_path) if self.selected_path else ""
