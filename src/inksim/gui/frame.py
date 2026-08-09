from pathlib import Path

from PIL import Image, ImageFilter
import wx

from ..constants import *
from ..render import render_export_image
from .dialogs import EmbroideryOpenDialog
from .drop_target import EmbroideryFileDropTarget
from .status import ModeStatusPanel
from .timeline import ProgressBarPanel
from .viewer import EmbroideryViewerPanel

class Frame(wx.Frame):
    """Main InkSim window coordinating the viewer and playback controls.

    The initial design is loaded before the frame is shown.  Fullscreen
    startup also gives the frame the display size before loading the design,
    then performs one final fit after wx has completed the layout.  This avoids
    showing an incorrectly positioned design while GTK applies fullscreen
    geometry asynchronously.
    """

    def __init__(
        self,
        initial_file=None,
        fullscreen=False,
        window_size=None,
        window_position=None,
        autoplay=False,
        batch=False,
    ):
        """Build the application window and optionally open a design file."""
        # Decide initial size before super().__init__
        # -f: use display size
        # default MaxWindow: also use display size so first FitToScreen is already correct
        # explicit --size: use that size
        init_size = (1200, 980)
        should_maximize_default = False
        if not window_size:
            try:
                disp = wx.Display(0).GetGeometry()
                disp_size = (disp.GetWidth(), disp.GetHeight())
                if fullscreen:
                    init_size = disp_size
                else:
                    # default MaxWindow behavior requested by user
                    init_size = disp_size
                    should_maximize_default = True
            except Exception:
                init_size = (1200, 980)
                should_maximize_default = not fullscreen
        else:
            init_size = window_size

        super().__init__(None, title=APP_TITLE, size=init_size)
        self.is_fullscreen = False
        self._should_maximize_default = should_maximize_default
        # TODO: Consider migrating wx.Config to an explicit XDG config path.
        self.config = wx.Config(APP_TITLE)
        self.last_directory = self.config.Read("last_directory", "")
        self.current_file_path = None
        if initial_file and Path(initial_file).is_file():
            self.current_file_path = Path(initial_file).resolve()
            self.last_directory = str(self.current_file_path.parent)
            self.config.Write("last_directory", self.last_directory)
            self.config.Flush()

        # Create the main panel, viewer, and progress bar, and arrange them vertically.
        main_panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.viewer = EmbroideryViewerPanel(main_panel, None)
        self.progress = ProgressBarPanel(main_panel, self.viewer)
        self.mode_status = ModeStatusPanel(main_panel, self.viewer)
        self.viewer.mode_panel = self.mode_status
        self.viewer.progress_bar = self.progress
        self.viewer.SetDropTarget(EmbroideryFileDropTarget(self))

        sizer.Add(self.viewer, 1, wx.EXPAND)
        sizer.Add(self.mode_status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        sizer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                  6)
        main_panel.SetSizer(sizer)
        self._main_panel = main_panel
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(main_panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

        # Build the menu bar with file and playback options, and bind them to handlers.
        menubar = wx.MenuBar()

        fileMenu = wx.Menu()
        openItem = fileMenu.Append(wx.ID_OPEN, "Open embroidery file\tCtrl+O")
        exportMenu = wx.Menu()
        exportShadedItem = exportMenu.Append(
            wx.ID_ANY, "Shaded PNG for print..."
        )
        exportIconItem = exportMenu.Append(wx.ID_ANY, "Preview PNG...")
        exportPrintItem = exportMenu.Append(wx.ID_ANY, "Simple PNG for print...")
        fileMenu.AppendSubMenu(exportMenu, "Export")
        centerItem = fileMenu.Append(wx.ID_ANY, "Center design\tC")
        fitItem = fileMenu.Append(wx.ID_ANY, "Fit design to window\tF")
        fullscreenItem = fileMenu.Append(wx.ID_ANY, "Fullscreen\tF11")
        gridItem = fileMenu.AppendCheckItem(wx.ID_ANY, "Show 1cm grid\tG")
        gridItem.Check(True)
        realisticItem = fileMenu.AppendCheckItem(
            wx.ID_ANY, "Realistic thread render\tR"
        )
        helpItem = fileMenu.Append(wx.ID_ANY, "Help\tH")
        fileMenu.AppendSeparator()
        rotateLeftItem = fileMenu.Append(wx.ID_ANY, "Rotate left 90 deg")
        rotateRightItem = fileMenu.Append(wx.ID_ANY, "Rotate right 90 deg")
        fileMenu.AppendSeparator()
        quitItem = fileMenu.Append(wx.ID_EXIT, "Quit\tCtrl+Q")
        menubar.Append(fileMenu, "&File")

        playbackMenu = wx.Menu()
        s1 = playbackMenu.AppendRadioItem(wx.ID_ANY, "Step 1 (Alt+Arrows)")
        s10 = playbackMenu.AppendRadioItem(wx.ID_ANY, "Step 10")
        s10.Check(True)
        s50 = playbackMenu.AppendRadioItem(wx.ID_ANY, "Step 50")
        s100 = playbackMenu.AppendRadioItem(wx.ID_ANY, "Step 100")
        s500 = playbackMenu.AppendRadioItem(wx.ID_ANY, "Step 500")
        playbackMenu.AppendSeparator()

        playItem = playbackMenu.Append(wx.ID_ANY, "Play/Pause\tSpace")
        nextCol = playbackMenu.Append(wx.ID_ANY, "Next color\tCtrl+Right")
        prevCol = playbackMenu.Append(wx.ID_ANY, "Prev color\tCtrl+Left")
        menubar.Append(playbackMenu, "&Playback")
        self.SetMenuBar(menubar)

        # Store menubar reference for key handling
        self.menubar = menubar
        self.fileMenu = fileMenu
        self.playbackMenu = playbackMenu
        self.gridItem = gridItem
        self.realisticItem = realisticItem

        # Global accelerators
        # Alt+F / Alt+P are handled by mnemonics in menu titles (&File / &Playback).
        # wxWidgets automatically exposes them as Alt+F and Alt+P.
        # Ctrl+Q for Quit is added explicitly via AcceleratorTable.
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('Q'), quitItem.GetId()),
        ])
        self.SetAcceleratorTable(accel_tbl)

        # Ensure Ctrl+Q works even when viewer has focus.
        # Alt+F / Alt+P are left to native menu bar mnemonics (no PopupMenu on attached menu).
        self.Bind(wx.EVT_CHAR_HOOK, self.OnCharHook)

        # Bind menu items to their handlers.
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        self.Bind(wx.EVT_MENU, self.OnOpen, openItem)
        self.Bind(wx.EVT_MENU, self.ExportPrintPng, exportPrintItem)
        self.Bind(wx.EVT_MENU, self.ExportShadedPng, exportShadedItem)
        self.Bind(wx.EVT_MENU, self.ExportIconPng, exportIconItem)
        self.Bind(wx.EVT_MENU, lambda e: self.viewer.CenterDesign(), centerItem)
        self.Bind(wx.EVT_MENU, lambda e: self.viewer.FitToScreen(), fitItem)
        self.Bind(wx.EVT_MENU, lambda e: self.ToggleFullScreen(), fullscreenItem)
        self.Bind(wx.EVT_MENU, self.OnToggleGrid, gridItem)
        self.Bind(wx.EVT_MENU, self.OnToggleRealistic, realisticItem)
        self.Bind(wx.EVT_MENU, lambda e: self.viewer.ShowHelp(), helpItem)
        self.Bind(wx.EVT_MENU, lambda e: self.viewer.RotateDesign(-1), rotateLeftItem)
        self.Bind(wx.EVT_MENU, lambda e: self.viewer.RotateDesign(1), rotateRightItem)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), quitItem)
        self.Bind(wx.EVT_MENU, lambda e: self.viewer.SetStepSize(1), s1)
        self.Bind(wx.EVT_MENU, lambda e: self.viewer.SetStepSize(10), s10)
        self.Bind(wx.EVT_MENU, lambda e: self.viewer.SetStepSize(50), s50)
        self.Bind(wx.EVT_MENU, lambda e: self.viewer.SetStepSize(100), s100)
        self.Bind(wx.EVT_MENU, lambda e: self.viewer.SetStepSize(500), s500)
        self.Bind(wx.EVT_MENU, lambda e: self.viewer.ToggleAutoPlay(True),
                  playItem)
        self.Bind(
            wx.EVT_MENU, lambda e: self.viewer.JumpToColor(1) or self.
            _refresh_after_color_jump(), nextCol)
        self.Bind(
            wx.EVT_MENU, lambda e: self.viewer.JumpToColor(-1) or self.
            _refresh_after_color_jump(), prevCol)

        # Set up the status bar with instructions.
        self.CreateStatusBar()
        self.SetStatusText(DEFAULT_STATUS_TEXT)

        # Window geometry
        if window_size:
            self.SetSize(window_size)
        if window_position:
            self.SetPosition(window_position)
        elif not window_size and not fullscreen and not should_maximize_default:
            self.Centre()

        # Load design with no auto-fit, we will fit explicitly after final size.
        initial_file_loaded = (
            initial_file
            and Path(initial_file).exists()
            and self.viewer.LoadDesign(initial_file, fit_to_screen=False)
        )
        if initial_file_loaded:
            total = self.viewer.stitches_np.shape[0]
            self.SetTitle(
                f"{APP_TITLE} - {Path(initial_file).name} - {total} sts"
            )

        if batch:
            return
        if fullscreen:
            self.is_fullscreen = True
            self.mode_status.Hide()
            self.Freeze()
            if not self.IsShown():
                self.Show()
            self.ShowFullScreen(True)
            self.Layout()
            self._main_panel.Layout()
            self.viewer.Layout()
            wx.CallAfter(self._finish_initial_display, autoplay)
        elif should_maximize_default:
            # Default MaxWindow - start maximized but without flicker.
            # Size is already display size, so first Fit is already almost correct.
            # Freeze to hide intermediate paint, then Maximize and fit again after GTK event.
            self.Freeze()
            if not self.IsShown():
                self.Show()
            # On GTK Maximize is async, so we need one more layout pass after it.
            self.Maximize(True)
            self.Layout()
            self._main_panel.Layout()
            self.viewer.Layout()
            wx.CallAfter(self._finish_initial_display, autoplay)
        else:
            if not self.IsShown():
                self.Show()
            if initial_file_loaded:
                wx.CallAfter(self._finish_initial_display, autoplay)

    def _finish_initial_display(self, autoplay):
        """Finish the one-time startup layout before playback begins.

        ``wx.CallAfter`` runs this after the frame and child panels have their
        final sizes.  The fit is intentionally limited to startup; changing
        fullscreen later with ``F11`` preserves the user's current viewport.
        """
        self.Layout()
        self._main_panel.Layout()
        self.viewer.Layout()
        # Final fit using real client size, not temporary 1200x980
        self.viewer.FitToScreen()
        if self.IsFrozen():
            self.Thaw()
        self.viewer.need_redraw = True
        self.viewer.Refresh()
        self.progress.Refresh()
        if autoplay:
            self.viewer.visible_count = 0
            self.viewer.need_redraw = True
            self.viewer.Refresh()
            self.progress.Refresh()
            self.viewer.ToggleAutoPlay(forward=True)

    def _refresh_after_color_jump(self):
        """Refresh the viewer and timeline after a color-boundary jump."""
        self.viewer.need_redraw = True
        self.viewer.Refresh()
        self.progress.Refresh()

    def OnCharHook(self, e):
        """Global keyboard shortcuts for menu.

        - Ctrl+Q -> Quit
        - Alt+F / Alt+P are handled natively by menubar mnemonics (&File, &Playback)
          so we just skip them here to let wxWidgets process them.
        """
        kc = e.GetKeyCode()
        # Ctrl+Q
        if e.ControlDown() and kc in (ord('Q'), ord('q')):
            self.Close()
            return
        # For Alt+F and Alt+P, do not intercept with PopupMenu (causes
        # !IsAttached() assertion on attached menus). Let the native
        # menubar mnemonic handling do its job.
        if e.AltDown() and kc in (ord('F'), ord('f'), ord('P'), ord('p')):
            e.Skip()
            return
        if not e.ControlDown() and not e.AltDown():
            if kc in (ord('H'), ord('h')):
                self.viewer.ShowHelp()
                return
            if kc in (ord('I'), ord('i')):
                self.viewer.ShowSettings()
                return
        e.Skip()

    def OnClose(self, e):
        """Stop playback before allowing the frame to close."""
        if self.viewer.is_playing:
            self.viewer.play_timer.Stop()
            self.viewer.is_playing = False
        e.Skip()

    def OnToggleGrid(self, e):
        """Apply the grid menu state to the viewer and redraw it."""
        self.viewer.show_grid = e.IsChecked()
        self.viewer.need_redraw = True
        self.viewer.Refresh()
        self.viewer.RefreshModeIndicators()

    def OnToggleRealistic(self, e):
        """Toggle the 2.5D realistic thread renderer."""
        self.viewer.show_realistic = e.IsChecked()
        self.viewer.need_redraw = True
        self.viewer.Refresh()
        self.viewer.RefreshModeIndicators()

    def OnOpen(self, e):
        """Prompt for an embroidery file and update the window metadata."""
        dlg = EmbroideryOpenDialog(
            self,
            self.last_directory,
            self.current_file_path,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.OpenFile(dlg.GetPath())
        dlg.Destroy()

    def _choose_export_path(self, title):
        """Ask for a PNG destination and return it, or None if cancelled."""
        dlg = wx.FileDialog(
            self,
            title,
            wildcard="PNG files (*.png)|*.png",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return None
            path = Path(dlg.GetPath())
        finally:
            dlg.Destroy()
        return path.with_suffix(".png")

    def ExportPng(self, path, icon=False, dpi=300, background="transparent",
                  grid=False, shaded=False):
        """Export clean embroidery geometry as a PNG file."""
        if self.viewer.stitches_np.shape[0] == 0:
            return False
        if icon:
            width = height = 256
        else:
            min_x, min_y, max_x, max_y = self.viewer.bounds
            width = max(1, round((max_x - min_x) / 25.4 * dpi))
            height = max(1, round((max_y - min_y) / 25.4 * dpi))
        render_scale = 3 if shaded else 1
        image, metadata = render_export_image(
            self.viewer.stitches_np,
            self.viewer.bounds,
            width * render_scale,
            height * render_scale,
            self.viewer.line_width,
            dpi=dpi,
            background=background,
            grid=grid,
            shaded=shaded,
            dark_factor=self.viewer.dark_factor,
            light_factor=self.viewer.light_factor,
        )
        if render_scale > 1:
            image = image.resize((width, height), Image.Resampling.LANCZOS)
            image = image.filter(
                ImageFilter.UnsharpMask(radius=0.55, percent=115, threshold=2)
            )
        image.save(path, "PNG", pnginfo=metadata, dpi=(dpi, dpi))
        return True

    def ExportPrintPng(self, e):
        """Export a flat 300 DPI PNG at the design's physical size."""
        path = self._choose_export_path("Export PNG for print")
        if path:
            self.ExportPng(path, dpi=300)

    def ExportShadedPng(self, e):
        """Export a shaded 300 DPI PNG at the design's physical size."""
        path = self._choose_export_path("Export shaded PNG for print")
        if path:
            self.ExportPng(path, dpi=300, shaded=True)

    def ExportIconPng(self, e):
        """Export a 256 pixel transparent preview PNG."""
        path = self._choose_export_path("Export preview PNG")
        if path:
            self.ExportPng(path, icon=True, dpi=96)

    def OpenFile(self, path):
        """Load a file and update window metadata after a successful load."""
        selected_path = Path(path).resolve()
        if not self.viewer.LoadDesign(str(selected_path), fit_to_screen=True):
            return False
        self.current_file_path = selected_path
        self.last_directory = str(selected_path.parent)
        self.config.Write("last_directory", self.last_directory)
        self.config.Flush()
        total = self.viewer.stitches_np.shape[0]
        bw = self.viewer.bounds[2] - self.viewer.bounds[0]
        bh = self.viewer.bounds[3] - self.viewer.bounds[1]
        self.SetTitle(
            f"{APP_TITLE} - {selected_path.name} - {total} sts - {bw:.1f}x{bh:.1f}mm"
        )
        self.progress.Refresh()
        return True

    def ToggleFullScreen(self):
        """Toggle undecorated fullscreen without changing the viewport."""
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.mode_status.Hide()
        else:
            self.mode_status.Show()
        self.Layout()
        self._main_panel.Layout()
        self.ShowFullScreen(self.is_fullscreen)
