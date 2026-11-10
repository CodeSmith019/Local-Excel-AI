"""Generate simple PNG icons for the Excel AI Office add-in.

Uses only Python standard library (struct + zlib) - no third-party imaging dependencies.
"""

import struct
import zlib
from pathlib import Path


def create_png_rgba(width: int, height: int, pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    """Encode RGBA pixels to a standard PNG image bytes."""
    raw_scanlines = bytearray()
    for y in range(height):
        raw_scanlines.append(0)  # Filter type 0 (None)
        for x in range(width):
            r, g, b, a = pixels[y][x]
            raw_scanlines.extend((r, g, b, a))

    compressed = zlib.compress(bytes(raw_scanlines), level=9)

    def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        payload = chunk_type + data
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr = make_chunk(b"IHDR", ihdr_data)
    idat = make_chunk(b"IDAT", compressed)
    iend = make_chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def render_icon(size: int) -> bytes:
    """Render an Excel AI branded icon of size x size."""
    # Excel brand green #107C41
    bg_r, bg_g, bg_b = 16, 124, 65
    fg_r, fg_g, fg_b = 255, 255, 255

    pixels: list[list[tuple[int, int, int, int]]] = []
    stroke_width = max(1, size // 8)

    for y in range(size):
        row: list[tuple[int, int, int, int]] = []
        for x in range(size):
            # Normalize to [-1.0, 1.0] from center
            nx = (x - size / 2.0 + 0.5) / (size / 2.0)
            ny = (y - size / 2.0 + 0.5) / (size / 2.0)

            # Check if within bounding box with rounded corners
            corner_r = 0.25
            in_bounds = True
            ax, ay = abs(nx), abs(ny)
            if ax > 1.0 or ay > 1.0:
                in_bounds = False
            elif ax > (1.0 - corner_r) and ay > (1.0 - corner_r):
                dx = ax - (1.0 - corner_r)
                dy = ay - (1.0 - corner_r)
                if (dx * dx + dy * dy) > (corner_r * corner_r):
                    in_bounds = False

            if not in_bounds:
                row.append((0, 0, 0, 0))  # Transparent outside
                continue

            # Draw "X" inside [-0.55, 0.55]
            is_symbol = False
            if abs(nx) <= 0.6 and abs(ny) <= 0.6:
                d1 = abs(nx - ny)
                d2 = abs(nx + ny)
                threshold = stroke_width / (size / 2.0)
                if d1 <= threshold or d2 <= threshold:
                    is_symbol = True

            if is_symbol:
                row.append((fg_r, fg_g, fg_b, 255))
            else:
                row.append((bg_r, bg_g, bg_b, 255))
        pixels.append(row)

    return create_png_rgba(size, size, pixels)


def main() -> None:
    """Generate 16px, 32px, and 80px icons in frontend/assets/."""
    assets_dir = Path(__file__).resolve().parent.parent / "frontend" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    sizes = [16, 32, 80]
    for s in sizes:
        icon_path = assets_dir / f"icon-{s}.png"
        png_data = render_icon(s)
        icon_path.write_bytes(png_data)
        print(f"Generated {icon_path} ({len(png_data)} bytes)")


if __name__ == "__main__":
    main()
