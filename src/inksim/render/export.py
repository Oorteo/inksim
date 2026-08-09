from PIL import Image, ImageDraw, ImageFilter, PngImagePlugin
import numpy as np

def render_export_image(stitches, bounds, width, height, line_width, dpi=None,
                        background="transparent", grid=False, shaded=False,
                        dark_factor=0.75, light_factor=0.45):
    """Render clean embroidery geometry into a standalone RGBA PNG image."""
    image = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    if background == "white":
        draw.rectangle((0, 0, width, height), fill=(255, 255, 255, 255))

    min_x, min_y, max_x, max_y = bounds
    design_width = max(max_x - min_x, 1.0)
    design_height = max(max_y - min_y, 1.0)
    margin = max(12, min(width, height) * 0.06)
    zoom = min(
        (width - 2 * margin) / design_width,
        (height - 2 * margin) / design_height,
    )
    offset_x = (width - design_width * zoom) / 2 - min_x * zoom
    offset_y = (height - design_height * zoom) / 2 - min_y * zoom

    if grid:
        grid_color = (205, 205, 205, 150)
        for grid_x in range(int(np.floor(min_x / 10)) * 10,
                           int(np.ceil(max_x / 10)) * 10 + 1, 10):
            x = int(grid_x * zoom + offset_x)
            if 0 <= x < width:
                draw.line((x, 0, x, height), fill=grid_color, width=1)
        for grid_y in range(int(np.floor(min_y / 10)) * 10,
                           int(np.ceil(max_y / 10)) * 10 + 1, 10):
            y = int(grid_y * zoom + offset_y)
            if 0 <= y < height:
                draw.line((0, y, width, y), fill=grid_color, width=1)

    stroke_width = max(2, round(max(line_width, 0.7) * zoom))
    cap_radius = max(1, stroke_width // 2)
    for x1, y1, x2, y2, red, green, blue in stitches:
        start = (x1 * zoom + offset_x, y1 * zoom + offset_y)
        end = (x2 * zoom + offset_x, y2 * zoom + offset_y)
        if not shaded:
            draw.line(
                (round(start[0]), round(start[1]), round(end[0]), round(end[1])),
                fill=(int(red), int(green), int(blue), 255),
                width=stroke_width,
            )
            draw.ellipse(
                (
                    round(start[0]) - cap_radius,
                    round(start[1]) - cap_radius,
                    round(start[0]) + cap_radius,
                    round(start[1]) + cap_radius,
                ),
                fill=(int(red), int(green), int(blue), 255),
            )
            draw.ellipse(
                (
                    round(end[0]) - cap_radius,
                    round(end[1]) - cap_radius,
                    round(end[0]) + cap_radius,
                    round(end[1]) + cap_radius,
                ),
                fill=(int(red), int(green), int(blue), 255),
            )
            continue
        dark = (
            int(red * dark_factor),
            int(green * dark_factor),
            int(blue * dark_factor),
        )
        light = (
            int(red + (255 - red) * light_factor),
            int(green + (255 - green) * light_factor),
            int(blue + (255 - blue) * light_factor),
        )
        for sample in range(4):
            start_ratio = sample / 4
            end_ratio = (sample + 1) / 4
            start_point = (
                round(start[0] + (end[0] - start[0]) * start_ratio),
                round(start[1] + (end[1] - start[1]) * start_ratio),
            )
            end_point = (
                round(start[0] + (end[0] - start[0]) * end_ratio),
                round(start[1] + (end[1] - start[1]) * end_ratio),
            )
            ratio = (start_ratio + end_ratio) / 2
            color = tuple(
                int(dark[channel] + (light[channel] - dark[channel]) * ratio)
                for channel in range(3)
            )
            draw.line(
                (*start_point, *end_point),
                fill=(*color, 255),
                width=stroke_width,
            )

    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("InkSim design size", f"{design_width:.2f} x {design_height:.2f} mm")
    metadata.add_text("InkSim background", background)
    metadata.add_text("InkSim layers", "embroidery only")
    metadata.add_text("InkSim rendering", "shaded" if shaded else "flat")
    if dpi:
        metadata.add_text("InkSim DPI", str(dpi))
    return image, metadata
