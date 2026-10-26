"""Generate the small transparent PNG chessmen shipped with Pawnix."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


SIZE = 96
ROOT = Path(__file__).resolve().parents[1] / "src" / "pawnix" / "assets" / "pieces"


def _inside_polygon(x: float, y: float, points: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _segment_distance(x: float, y: float, start: tuple[float, float], end: tuple[float, float]) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = dx * dx + dy * dy
    ratio = 0 if length == 0 else max(0, min(1, ((x - start[0]) * dx + (y - start[1]) * dy) / length))
    return math.hypot(x - start[0] - ratio * dx, y - start[1] - ratio * dy)


class Canvas:
    def __init__(self, fill: tuple[int, int, int]) -> None:
        self.pixels = bytearray(SIZE * SIZE * 4)
        self.fill = fill
        for offset in range(3, len(self.pixels), 4):
            self.pixels[offset] = 0

    def _paint(self, predicate, outline: tuple[int, int, int], edge) -> None:
        for py in range(SIZE):
            for px in range(SIZE):
                point = (px + 0.5, py + 0.5)
                if predicate(*point):
                    color = outline if edge(*point) <= 2.2 else self.fill
                    at = (py * SIZE + px) * 4
                    self.pixels[at:at + 4] = bytes((*color, 255))

    def polygon(self, points: tuple[tuple[float, float], ...], outline: tuple[int, int, int]) -> None:
        self._paint(
            lambda x, y: _inside_polygon(x, y, points), outline,
            lambda x, y: min(_segment_distance(x, y, points[i], points[(i + 1) % len(points)]) for i in range(len(points))),
        )

    def ellipse(self, box: tuple[float, float, float, float], outline: tuple[int, int, int]) -> None:
        left, top, right, bottom = box
        cx, cy = (left + right) / 2, (top + bottom) / 2
        rx, ry = (right - left) / 2, (bottom - top) / 2
        self._paint(
            lambda x, y: ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1,
            outline,
            lambda x, y: abs(math.hypot((x - cx) / rx, (y - cy) / ry) - 1) * min(rx, ry),
        )


def _piece(canvas: Canvas, name: str, outline: tuple[int, int, int]) -> None:
    poly, ellipse = canvas.polygon, canvas.ellipse
    if name == "p":
        ellipse((37, 13, 59, 35), outline)
        poly(((40, 34), (56, 34), (62, 48), (70, 59), (27, 59), (35, 48)), outline)
    elif name == "r":
        poly(((27, 15), (37, 15), (37, 25), (45, 25), (45, 15), (54, 15), (54, 25), (62, 25), (62, 15), (71, 15), (69, 37), (64, 43), (64, 57), (30, 57), (30, 43), (25, 37)), outline)
    elif name == "n":
        poly(((27, 57), (33, 44), (30, 33), (36, 20), (48, 13), (48, 24), (58, 19), (66, 23), (59, 31), (69, 42), (66, 57)), outline)
        ellipse((47, 23, 52, 28), outline)
    elif name == "b":
        poly(((48, 11), (58, 22), (55, 35), (64, 42), (66, 57), (30, 57), (32, 42), (41, 35), (38, 22)), outline)
        poly(((40, 28), (56, 16), (58, 20), (42, 32)), outline)
    elif name == "q":
        for cx, cy, radius in ((30, 21, 5), (42, 15, 5), (54, 15, 5), (66, 21, 5)):
            ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline)
        poly(((28, 27), (38, 34), (48, 28), (58, 34), (68, 27), (62, 48), (64, 57), (32, 57), (34, 48)), outline)
    elif name == "k":
        poly(((45, 9), (51, 9), (51, 20), (61, 20), (61, 26), (51, 26), (51, 32), (62, 39), (66, 57), (30, 57), (34, 39), (45, 32), (45, 26), (35, 26), (35, 20), (45, 20)), outline)
    # A shared stepped pedestal gives all six pieces a grounded chessman shape.
    poly(((35, 57), (61, 57), (66, 64), (70, 67), (70, 73), (26, 73), (26, 67), (30, 64)), outline)
    poly(((22, 75), (74, 75), (77, 81), (19, 81)), outline)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _save(canvas: Canvas, path: Path) -> None:
    rows = b"".join(b"\0" + canvas.pixels[y * SIZE * 4:(y + 1) * SIZE * 4] for y in range(SIZE))
    payload = b"\x89PNG\r\n\x1a\n"
    payload += _chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
    payload += _chunk(b"IDAT", zlib.compress(rows, 9)) + _chunk(b"IEND", b"")
    path.write_bytes(payload)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for color_name, fill, outline in (
        ("white", (245, 242, 232), (30, 32, 36)),
        ("black", (34, 37, 43), (245, 242, 232)),
    ):
        for name in "kqrbnp":
            canvas = Canvas(fill)
            _piece(canvas, name, outline)
            _save(canvas, ROOT / f"{color_name}-{name}.png")


if __name__ == "__main__":
    main()
