"""Markdown help content for the InkSim viewer."""

HELP_SECTIONS = (
    ("Mouse", """

| Action | Result |
| --- | --- |
| Wheel | Zoom |
| Alt or Ctrl + Wheel | Move by one stitch |
| Drag | Pan |
| Double-click design | Seek to visible stitch |
| W / A / S / D | Pan up / left / down / right |
| Click timeline | Seek stitch |
"""),
    ("Playback", """

| Key | Result |
| --- | --- |
| Right / Left | Move by the selected step, or adjust playback speed |
| Alt + Right / Left | Move by one stitch |
| Shift + Right / Left | Next or previous command |
| Ctrl + Right / Left | Next or previous color |
| Up / Down | Fast seek, 10x |
| Home / End | First or last stitch |
| Space | Play or pause |
| Esc | Finish playback directionally (forward → full design, backward → hide all) |
"""),
    ("View", """

| Key | Result |
| --- | --- |
| C | Center design |
| F | Fit design to window |
| F11 | Fullscreen |
| M | Snap to right half / restore free layout |
| Shift + M | Save current layout as snap target |
| 1 | Physical 1:1 size |
| V | Toggle embroidery |
| G | Toggle grid |
| N | Toggle needle |
| J | Cycle jumps: off, all, risky only |
| X | Toggle density map |
| Z | Toggle realistic rendering |
| R | Choose stitch renderer |
| H | Toggle help |
| I | Toggle settings |
"""),
    ("Rendering", """

| Key | Result |
| --- | --- |
| [ / ] | Change thread width |
| Ctrl + [ / ] | Adjust dark shading |
| Alt + [ / ] | Adjust light shading |
| + / - | Zoom |
"""),
)


def show_help(viewer):
    """Show the viewer help dialog."""
    viewer._show_markdown_columns_dialog(
        "help_dialog",
        "Help - InkSim",
        HELP_SECTIONS,
        columns=4,
        width=1100,
        height=500,
    )
