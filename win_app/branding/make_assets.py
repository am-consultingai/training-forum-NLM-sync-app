"""
Generate the branded Windows packaging assets from the AM Consulting wordmark.

Produces, next to this script / in win_app/:
  - win_app/app.ico                     multi-size app/EXE icon
  - win_app/branding/wizard-large.bmp   164x314 Inno Setup WizardImageFile
  - win_app/branding/wizard-small.bmp   55x55   Inno Setup WizardSmallImageFile

The source is am-logo.png (a wide, transparent wordmark designed for dark
backgrounds), so every target is composited onto the AM Consulting brand dark
background (#0b0f19) with padding. Run once after changing the logo:

    .venv/bin/python win_app/branding/make_assets.py

The outputs are committed binaries, so the build (iscc / PyInstaller) needs no
generation step.
"""
import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
WIN_APP = os.path.dirname(HERE)
LOGO = os.path.join(HERE, "am-logo.png")

BG = (11, 15, 25, 255)  # #0b0f19 — AM Consulting brand base background


def _logo() -> Image.Image:
    return Image.open(LOGO).convert("RGBA")


def _fit(logo: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """Scale the logo to fit within max_w x max_h, preserving aspect ratio."""
    scale = min(max_w / logo.width, max_h / logo.height)
    w, h = max(1, round(logo.width * scale)), max(1, round(logo.height * scale))
    return logo.resize((w, h), Image.LANCZOS)


def _canvas(w: int, h: int) -> Image.Image:
    return Image.new("RGBA", (w, h), BG)


def _paste_centered(canvas: Image.Image, logo: Image.Image, cy: float = 0.5):
    x = (canvas.width - logo.width) // 2
    y = int((canvas.height - logo.height) * cy)
    canvas.alpha_composite(logo, (x, y))


def make_icon():
    """Square multi-size .ico: wordmark centered on the brand background."""
    base = 256
    canvas = _canvas(base, base)
    logo = _fit(_logo(), int(base * 0.82), int(base * 0.42))
    _paste_centered(canvas, logo, cy=0.5)
    out = os.path.join(WIN_APP, "app.ico")
    canvas.save(out, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("wrote", out)


def make_wizard_large():
    """164x314 left-side banner: wordmark near the top on the brand background."""
    w, h = 164, 314
    canvas = _canvas(w, h)
    logo = _fit(_logo(), int(w * 0.84), int(h * 0.22))
    x = (w - logo.width) // 2
    canvas.alpha_composite(logo, (x, int(h * 0.10)))
    out = os.path.join(HERE, "wizard-large.bmp")
    canvas.convert("RGB").save(out, format="BMP")
    print("wrote", out)


def make_wizard_small():
    """55x55 top-right mark: wordmark fit onto the brand background."""
    w, h = 55, 55
    canvas = _canvas(w, h)
    logo = _fit(_logo(), int(w * 0.88), int(h * 0.62))
    _paste_centered(canvas, logo, cy=0.5)
    out = os.path.join(HERE, "wizard-small.bmp")
    canvas.convert("RGB").save(out, format="BMP")
    print("wrote", out)


if __name__ == "__main__":
    make_icon()
    make_wizard_large()
    make_wizard_small()
