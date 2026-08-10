"""Markdown settings view for the InkSim viewer."""

from ..constants import (
    DENSITY_CRITICAL_PER_MM2,
    DENSITY_RADIUS_MM,
    DENSITY_WARNING_PER_MM2,
)


def _state(value):
    return "on" if value else "off"


def _jump_state(viewer):
    if not viewer.show_jumps:
        return "off"
    return "risky only" if viewer.risky_jumps_only else "all"


def settings_sections(viewer):
    """Build Markdown sections for the current viewer state."""
    total = viewer.stitches_np.shape[0]
    min_x, min_y, max_x, max_y = viewer.bounds
    width = max_x - min_x
    height = max_y - min_y
    return (
        ("Design", f"""

| Property | Value |
| --- | --- |
| Stitches | {viewer.visible_count} / {total} |
| Colors | {viewer.color_count} |
| Bounds | {width:.1f} x {height:.1f} mm |
| Minimum | {min_x:.1f}, {min_y:.1f} |
| Maximum | {max_x:.1f}, {max_y:.1f} |
"""),
    ("Viewport", f"""

| Property | Value |
| --- | --- |
| Zoom | {viewer.zoom:.3f}x |
| Pan | {viewer.pan_x:.0f}, {viewer.pan_y:.0f} px |
| Grid | {_state(viewer.show_grid)} |
| Embroidery | {_state(viewer.show_stitches)} |
| Realistic | {_state(viewer.show_realistic)} |
| Jumps | {_jump_state(viewer)} |
| Density | {_state(viewer.show_density)} |
| Needle | {_state(viewer.show_needle)} |
| Gradient | {_state(viewer.zoom > 1.2)} |
"""),
    ("Density", f"""

| Property | Value |
| --- | --- |
| Radius | {DENSITY_RADIUS_MM:.1f} mm |
| Warning | {DENSITY_WARNING_PER_MM2:.1f} /mm^2 |
| Critical | {DENSITY_CRITICAL_PER_MM2:.1f} /mm^2 |
"""),
    ("Rendering", f"""

| Property | Value |
| --- | --- |
| Line width | {viewer.line_width:.2f} mm |
| Dark factor | {viewer.dark_factor:.2f} |
| Light factor | {viewer.light_factor:.2f} |
| Shading step | {viewer.shading_step:.2f} |
"""),
    ("Playback", f"""

| Property | Value |
| --- | --- |
| Step size | {viewer.step_size} |
| Interval | {viewer.play_speed} ms |
| Timer step | {viewer.play_step} |
| Direction | {"forward" if viewer._last_dir > 0 else "backward"} |
| Playing | {_state(viewer.is_playing)} |
"""),
    )


def show_settings(viewer):
    """Show a Markdown snapshot of the current viewer state."""
    viewer._show_markdown_columns_dialog(
        "settings_dialog",
        "Settings - InkSim",
        settings_sections(viewer),
        columns=5,
        width=1100,
        height=560,
    )
