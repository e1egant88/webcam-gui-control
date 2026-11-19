"""Render the app icon (.ico, several sizes) with the same drawing as the tray icon."""

import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QImage

from gesture_control.activation import ActivationState


def main(out: str) -> None:
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 - needed for painting
    from gesture_control.overlay.tray import state_icon

    icon = state_icon(ActivationState.ACTIVE, size=256)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Qt's ICO writer stores one image; Windows scales it for small sizes.
    img: QImage = icon.pixmap(256, 256).toImage()
    if not img.save(str(path), "ICO"):
        # Fallback via Pillow (multi-size) if Qt lacks the ICO plugin.
        from PIL import Image

        tmp = path.with_suffix(".png")
        img.save(str(tmp), "PNG")
        Image.open(tmp).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        tmp.unlink()
    print(f"icon written to {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/icon.ico")
