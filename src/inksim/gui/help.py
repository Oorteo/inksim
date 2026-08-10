"""Markdown help content for the InkSim viewer."""

HELP_MARKDOWN = """# InkSim Help

## Mouse

| Action | Result |
| --- | --- |
| Wheel | Zoom |
| Drag | Pan |
| Click timeline | Seek stitch |

## Playback

| Key | Result |
| --- | --- |
| Right / Left | Move by the selected step, or adjust playback speed |
| Alt + Right / Left | Move by one stitch |
| Shift + Right / Left | Next or previous command |
| Ctrl + Right / Left | Next or previous color |
| Up / Down | Fast seek, 10x |
| Home / End | First or last stitch |
| Space | Play or pause |
| Esc | Stop playback |

## View

| Key | Result |
| --- | --- |
| C | Center design |
| F | Fit design to window |
| F11 | Fullscreen |
| 1 | Physical 1:1 size |
| V | Toggle embroidery |
| G | Toggle grid |
| N | Toggle needle |
| J | Cycle jumps: off, all, risky only |
| X | Toggle density map |
| R | Toggle realistic rendering |
| H | Toggle help |
| I | Toggle settings |

## Rendering

| Key | Result |
| --- | --- |
| + / - | Change thread width |
| [ / ] | Adjust dark shading |
| Shift + [ / ] | Adjust light shading |
"""


def show_help(viewer):
    """Show the viewer help dialog."""
    viewer._show_markdown_dialog(
        "help_dialog",
        "Help - InkSim",
        HELP_MARKDOWN,
        width=900,
        height=650,
    )
