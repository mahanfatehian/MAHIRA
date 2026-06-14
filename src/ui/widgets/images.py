# src/ui/widgets/images.py
"""Image helpers for crisp cover thumbnails.

The book/level cover art is small (~40-80px on screen). Two things make it look
low quality without help:
  1) Qt doesn't render a plain QPixmap at the screen's device-pixel-ratio, so it
     blurs on scaled (HiDPI) Windows/macOS displays.
  2) A tall cover scaled to a tiny letterboxed square reads as a thumbnail
     floating in a box.

`rounded_cover_pixmap` fixes both: it renders at the real device pixel ratio and
fills the tile (cover-fit, center-cropped) with rounded corners, so covers look
like crisp, intentional thumbnails.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication


def _device_pixel_ratio() -> float:
    try:
        screen = QApplication.primaryScreen()
        if screen is not None:
            return max(1.0, float(screen.devicePixelRatio()))
    except Exception:
        pass
    return 1.0


def rounded_cover_pixmap(
    path: str, width: int, height: int, radius: int = 14
) -> Optional[QPixmap]:
    """Return a HiDPI-aware pixmap that FILLS a width x height tile (cover-fit,
    center-cropped) with rounded corners. Returns None if the image can't be
    loaded so callers can fall back to a placeholder.
    """
    if not path:
        return None
    src = QPixmap(path)
    if src.isNull():
        return None

    dpr = _device_pixel_ratio()
    tw = max(1, int(round(width * dpr)))
    th = max(1, int(round(height * dpr)))

    scaled = src.scaled(
        tw,
        th,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - tw) // 2)
    y = max(0, (scaled.height() - th) // 2)
    cropped = scaled.copy(x, y, tw, th)

    out = QPixmap(tw, th)
    out.fill(Qt.GlobalColor.transparent)

    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, tw, th), radius * dpr, radius * dpr)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, cropped)
    painter.end()

    out.setDevicePixelRatio(dpr)
    return out
