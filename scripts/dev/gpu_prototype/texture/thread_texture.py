#!/usr/bin/env uvr
"""
Professional PBR texture generator for embroidery thread.

Outputs:
  - diffuse / albedo map (colour)
  - normal map (for dynamic lighting)
  - alpha / mask map (transparency)
  - roughness map (for PBR)
  - height map (for displacement)
  - combined RGBA preview (diffuse + alpha)
"""
import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image


def generate_thread_textures(
    width: int = 512,
    height: int = 128,
    twist_periods: float = 3.0,
    strand_radius: float = 24.0,
    helix_radius: float = 11.0,
    num_strands: int = 3,
    twist_offset: float = 0.0,
    amp: float = 2.0,
    fiber_noise: float = 0.06,
    blend_softness: float = 2.5,
    color_top: tuple[int, int, int] = (180, 220, 255),
    color_mid: tuple[int, int, int] = (100, 140, 255),
    color_bottom: tuple[int, int, int] = (50, 60, 200),
    highlight: tuple[int, int, int] = (220, 240, 255),
    output_dir: str | Path = "./thread_textures",
    prefix: str = "thread",
) -> dict[str, Path]:
    """Generate a complete PBR texture set for one embroidered thread style."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Period in pixels: choose a value that tiles exactly across the texture width.
    # This guarantees the helix phase matches at the left and right edges.
    period = max(1, int(round(width / twist_periods)))

    # Convert colours to float arrays.
    c_top = np.array(color_top, dtype=float)
    c_mid = np.array(color_mid, dtype=float)
    c_bot = np.array(color_bottom, dtype=float)
    c_hl = np.array(highlight, dtype=float)

    # Fixed light and view directions used to bake the diffuse/specular maps.
    light = np.array([0.3, -0.6, 0.7])
    light = light / np.linalg.norm(light)
    view = np.array([0.0, 0.0, 1.0])

    # Initialise output channels.
    diffuse = np.zeros((height, width, 3), dtype=np.float32)
    normal_map = np.zeros((height, width, 3), dtype=np.float32)
    alpha_mask = np.zeros((height, width), dtype=np.float32)
    roughness = np.zeros((height, width), dtype=np.float32)
    height_map = np.zeros((height, width), dtype=np.float32)

    ys = np.arange(height, dtype=np.float32)

    # Fibre noise for thread micro-detail.
    if fiber_noise > 0.0:
        np.random.seed(42)
        noise = np.random.randn(height, width) * fiber_noise * 25.0
        try:
            from scipy.ndimage import gaussian_filter
            noise = gaussian_filter(noise, sigma=0.6)
        except ImportError:
            # Simple fallback smoothing.
            for _ in range(2):
                noise = (noise[:, :-1] + noise[:, 1:]) / 2.0
    else:
        noise = np.zeros((height, width), dtype=np.float32)

    for x in range(width):
        t = 2.0 * math.pi * x / period
        cy = height / 2.0 + amp * math.sin(t)

        # Compute strand centre positions in the cross-section.
        strands = []
        for i in range(num_strands):
            angle = t + 2.0 * math.pi * i / num_strands + twist_offset
            y_pos = cy + helix_radius * math.sin(angle)
            z_pos = helix_radius * math.cos(angle)
            strands.append({"y": y_pos, "z": z_pos, "angle": angle})

        for yi in ys:
            yi_int = int(yi)

            # Find all strands covering this pixel.
            candidates = []
            for s in strands:
                dy = yi - s["y"]
                if abs(dy) > strand_radius:
                    continue

                dz = math.sqrt(max(0.0, strand_radius * strand_radius - dy * dy))
                z_surface = s["z"] + dz

                # Surface normal of the strand cylinder.
                ny = dy / strand_radius
                nz = dz / strand_radius
                normal = np.array([0.0, ny, nz], dtype=np.float32)

                # Add helical twist to the normal.
                twist_factor = helix_radius / (strand_radius * 2.0)
                nx_correction = -math.sin(s["angle"]) * twist_factor * 0.3
                ny_correction = math.cos(s["angle"]) * twist_factor * 0.3
                normal = normal + np.array([nx_correction, ny_correction, 0.0], dtype=np.float32)
                normal = normal / (np.linalg.norm(normal) + 1e-8)

                # Diffuse lighting.
                diffuse_val = 0.4 + 0.6 * np.clip(np.dot(normal, light), 0.1, 1.0)

                # Specular highlight.
                half_vec = (light + view) / (np.linalg.norm(light + view) + 1e-8)
                spec = max(0.0, np.dot(normal, half_vec)) ** 40 * 0.8

                # Surface colour based on the normal's Y component.
                v = ny
                if v > 0:
                    tt = v
                    base_color = c_mid * (1.0 - tt ** 0.8) + c_top * (tt ** 0.8)
                else:
                    tt = -v
                    base_color = c_mid * (1.0 - tt) + c_bot * tt

                col = base_color * diffuse_val + spec * c_hl * 0.6

                # Edge anti-aliasing.
                edge = 1.0
                if abs(dy) > strand_radius - 1.5:
                    edge = np.clip(strand_radius + 1.5 - abs(dy), 0.0, 1.0)

                # Height value for the displacement map.
                height_val = (dz / strand_radius) * 0.5

                candidates.append(
                    {
                        "z": z_surface,
                        "color": col,
                        "normal": normal,
                        "edge": edge,
                        "height": height_val,
                    }
                )

            if not candidates:
                continue

            # Soft blending between overlapping strands.
            candidates.sort(key=lambda c: c["z"], reverse=True)

            total_weight = 0.0
            final_color = np.zeros(3, dtype=np.float32)
            final_normal = np.zeros(3, dtype=np.float32)
            final_edge = 0.0
            final_height = 0.0

            front = candidates[0]["z"]
            for c in candidates:
                z_dist = front - c["z"]
                weight = math.exp(-z_dist / blend_softness)
                weight *= c["edge"] ** 0.7

                total_weight += weight
                final_color += c["color"] * weight
                final_normal += c["normal"] * weight
                final_height += c["height"] * weight
                final_edge = max(final_edge, c["edge"])

            if total_weight > 0.0:
                final_color /= total_weight
                final_normal /= total_weight + 1e-8
                final_height /= total_weight
            else:
                final_color = candidates[0]["color"]
                final_normal = candidates[0]["normal"]
                final_edge = candidates[0]["edge"]
                final_height = candidates[0]["height"]

            final_normal = final_normal / (np.linalg.norm(final_normal) + 1e-8)

            # Add fibre micro-detail noise.
            if fiber_noise > 0.0:
                noise_val = noise[yi_int, x] * 0.5
                final_color += noise_val
                final_normal += np.array([noise_val * 0.01, noise_val * 0.01, 0.0], dtype=np.float32)
                final_normal = final_normal / (np.linalg.norm(final_normal) + 1e-8)

            final_color = np.clip(final_color, 0.0, 255.0)

            # Write the output channels.
            diffuse[yi_int, x, :] = final_color / 255.0
            normal_map[yi_int, x, :] = np.clip(final_normal * 0.5 + 0.5, 0.0, 1.0)
            alpha_mask[yi_int, x] = final_edge
            roughness_val = 0.3 + 0.3 * (1.0 - final_edge) + fiber_noise * 0.5
            roughness[yi_int, x] = np.clip(roughness_val, 0.05, 0.8)
            height_map[yi_int, x] = np.clip(final_height + 0.5, 0.0, 1.0)

    # Save textures.
    outputs: dict[str, Path] = {}

    diffuse_img = Image.fromarray((diffuse * 255.0).astype(np.uint8), "RGB")
    diffuse_path = output_dir / f"{prefix}_diffuse.png"
    diffuse_img.save(diffuse_path)
    outputs["diffuse"] = diffuse_path

    normal_img = Image.fromarray((normal_map * 255.0).astype(np.uint8), "RGB")
    normal_path = output_dir / f"{prefix}_normal.png"
    normal_img.save(normal_path)
    outputs["normal"] = normal_path

    alpha_img = Image.fromarray((alpha_mask * 255.0).astype(np.uint8), "L")
    alpha_path = output_dir / f"{prefix}_mask.png"
    alpha_img.save(alpha_path)
    outputs["mask"] = alpha_path

    roughness_img = Image.fromarray((roughness * 255.0).astype(np.uint8), "L")
    roughness_path = output_dir / f"{prefix}_roughness.png"
    roughness_img.save(roughness_path)
    outputs["roughness"] = roughness_path

    height_img = Image.fromarray((height_map * 255.0).astype(np.uint8), "L")
    height_path = output_dir / f"{prefix}_height.png"
    height_img.save(height_path)
    outputs["height"] = height_path

    rgba = np.dstack([diffuse, alpha_mask])
    rgba_img = Image.fromarray((rgba * 255.0).astype(np.uint8), "RGBA")
    rgba_path = output_dir / f"{prefix}_rgba.png"
    rgba_img.save(rgba_path)
    outputs["rgba"] = rgba_path

    print(f"Generated {len(outputs)} textures in {output_dir}:")
    for name, path in outputs.items():
        print(f"   - {name}: {path.name}")

    return outputs


def _parse_color(value: str) -> tuple[int, int, int]:
    """Parse an R,G,B colour string."""
    return tuple(int(v.strip()) for v in value.split(","))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate PBR textures for embroidered thread"
    )
    parser.add_argument("--width", type=int, default=512,
                        help="Texture width in pixels (along the stitch direction)")
    parser.add_argument("--height", type=int, default=128,
                        help="Texture height in pixels (across the thread width)")
    parser.add_argument("--twist-periods", "--twist-period", type=float, default=3.0,
                        dest="twist_periods",
                        help="Number of full twist periods across the texture width (tiling-safe)")
    parser.add_argument("--strands", type=int, default=3,
                        help="Number of twisted strands (2 or 3)")
    parser.add_argument("--strand-radius", type=float, default=24.0,
                        help="Strand radius in pixels")
    parser.add_argument("--helix-radius", type=float, default=11.0,
                        help="Helix radius in pixels")
    parser.add_argument("--blend-softness", type=float, default=2.5,
                        help="Strand blending softness (1-4)")
    parser.add_argument("--fiber-noise", type=float, default=0.06,
                        help="Fibre texture intensity (0-0.15)")
    parser.add_argument("--output-dir", type=Path, default="./thread_textures",
                        help="Output directory")
    parser.add_argument("--prefix", type=str, default="thread",
                        help="Output filename prefix")

    parser.add_argument("--color-top", type=str, default="180,220,255",
                        help="Top (lit) colour as R,G,B")
    parser.add_argument("--color-mid", type=str, default="100,140,255",
                        help="Mid colour as R,G,B")
    parser.add_argument("--color-bottom", type=str, default="50,60,200",
                        help="Bottom (shadow) colour as R,G,B")

    args = parser.parse_args()

    color_top = _parse_color(args.color_top)
    color_mid = _parse_color(args.color_mid)
    color_bottom = _parse_color(args.color_bottom)

    generate_thread_textures(
        width=args.width,
        height=args.height,
        twist_periods=args.twist_periods,
        strand_radius=args.strand_radius,
        helix_radius=args.helix_radius,
        num_strands=args.strands,
        blend_softness=args.blend_softness,
        fiber_noise=args.fiber_noise,
        color_top=color_top,
        color_mid=color_mid,
        color_bottom=color_bottom,
        output_dir=args.output_dir,
        prefix=args.prefix,
    )


if __name__ == "__main__":
    main()