"""Build the Windows icon set from the Kirby mascot art.

Qt only; no Pillow dependency. The transparent margins are trimmed, the
remaining art is centred in a square (no stretching), then each icon layer is
scaled independently with smooth interpolation. 16-128 px are 32-bit DIB
payloads and 256 px is a PNG payload, the standard Windows layout.

    py -3.13 tools/make_icon.py

Outputs: assets/icon.ico (16, 24, 32, 48, 64, 128, 256 px), assets/icon.png.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QBuffer, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)
ICON_SOURCE = "kirby.png"


def png_bytes(image: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    data = bytes(buf.data())
    buf.close()
    return data


def dib_bytes(image: QImage) -> bytes:
    """32-bit BGRA bottom-up DIB with a fully-transparent AND mask."""
    img = image.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    header = struct.pack(
        "<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, w * h * 4, 0, 0, 0, 0
    )
    rows = []
    ptr = img.constBits()
    stride = img.bytesPerLine()
    for y in range(h - 1, -1, -1):
        rows.append(bytes(ptr[y * stride : y * stride + w * 4]))
    pixels = b"".join(rows)
    mask_row = ((w + 31) // 32) * 4
    mask = b"\x00" * (mask_row * h)
    return header + pixels + mask


def build_ico(cropped: QImage, out: Path) -> list[tuple[int, int]]:
    entries = []
    payloads = []
    offset = 6 + 16 * len(SIZES)
    for size in SIZES:
        scaled = cropped.scaled(
            size,
            size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        payload = png_bytes(scaled) if size == 256 else dib_bytes(scaled)
        dim = 0 if size == 256 else size
        entries.append(
            (dim, dim, 0, 0, 1, 32, len(payload), offset + sum(len(p) for p in payloads))
        )
        payloads.append(payload)
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    directory = b"".join(
        struct.pack("<BBBBHHII", *entry) for entry in entries
    )
    out.write_bytes(header + directory + b"".join(payloads))
    return [(size, size) for size in SIZES]


def trimmed_square(image: QImage) -> QImage:
    """Crop the transparent margins, then centre the art in a transparent square."""
    rgba = image.convertToFormat(QImage.Format_ARGB32)
    left, top = rgba.width(), rgba.height()
    right, bottom = -1, -1
    for y in range(rgba.height()):
        for x in range(rgba.width()):
            if rgba.pixelColor(x, y).alpha() > 12:
                left = min(left, x)
                top = min(top, y)
                right = max(right, x)
                bottom = max(bottom, y)
    if right < 0:
        return rgba
    width = right - left + 1
    height = bottom - top + 1
    side = max(width, height)
    pad = max(2, int(side * 0.06))
    side += pad * 2
    square = QImage(side, side, QImage.Format_ARGB32)
    square.fill(Qt.transparent)
    offset_x = (side - width) // 2
    offset_y = (side - height) // 2
    for y in range(height):
        for x in range(width):
            square.setPixelColor(
                offset_x + x, offset_y + y, rgba.pixelColor(left + x, top + y)
            )
    return square


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841 - required for QImage plugins
    source = BASE / "assets" / ICON_SOURCE
    image = QImage(str(source))
    if image.isNull():
        raise SystemExit(f"could not load {source}")
    cropped = trimmed_square(image)

    png = cropped.scaled(
        256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )
    png_out = BASE / "assets" / "icon.png"
    png.save(str(png_out), "PNG")

    ico_out = BASE / "assets" / "icon.ico"
    layers = build_ico(cropped, ico_out)
    print(f"source {image.width()}x{image.height()} -> icon {cropped.width()}x{cropped.height()}")
    print(f"saved {ico_out} ({ico_out.stat().st_size} bytes) layers={layers}")
    print(f"saved {png_out} ({png_out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
