"""
Generate the branded Windows packaging assets. Run once after changing the art:

    .venv/bin/python win_app/branding/make_assets.py

Produces (committed binaries — the build needs no generation step):
  - win_app/app.ico                     multi-size app/EXE/setup icon (cloud-sync mark)
  - win_app/branding/wizard-large.bmp   164x314 Inno WizardImageFile (cloud-sync hero)
  - win_app/branding/wizard-small.bmp   55x55   Inno WizardSmallImageFile (cloud-sync mark)
  - win_app/branding/footer-logo.bmp    AM Consulting wordmark for the wizard footer

The app icon is the "cloud sync" product mark (see cloud_art.py). The AM
Consulting wordmark is NOT in the icon — it appears only at the bottom (footer)
of the installer wizard pages and in the application's own footer.
"""
import os

from PIL import Image

import cloud_art

HERE = os.path.dirname(os.path.abspath(__file__))
WIN_APP = os.path.dirname(HERE)
LOGO = os.path.join(HERE, "am-logo.png")

BG = (11, 15, 25, 255)          # #0b0f19 — brand dark background
# Windows installer 3D button-face colour (light theme). The wordmark is
# composited onto this so the footer logo blends seamlessly (looks transparent).
PANEL = (240, 240, 240, 255)


def _fit(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    scale = min(max_w / img.width, max_h / img.height)
    w, h = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    return img.resize((w, h), Image.LANCZOS)


def make_icon():
    """Square multi-size .ico from the cloud-sync mark."""
    icon = cloud_art.render(256)
    out = os.path.join(WIN_APP, "app.ico")
    icon.save(out, format="ICO",
              sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("wrote", out)


def make_wizard_large():
    """164x314 left banner: cloud-sync mark near the top on the brand background."""
    w, h = 164, 314
    canvas = Image.new("RGBA", (w, h), BG)
    art = cloud_art.render(int(w * 0.92))
    x = (w - art.width) // 2
    canvas.alpha_composite(art, (x, int(h * 0.06)))
    out = os.path.join(HERE, "wizard-large.bmp")
    canvas.convert("RGB").save(out, format="BMP")
    print("wrote", out)


def make_wizard_small():
    """55x55 top-right mark: the cloud-sync mark on the brand background."""
    w = h = 55
    canvas = Image.new("RGBA", (w, h), BG)
    art = cloud_art.render(w)
    canvas.alpha_composite(art, (0, 0))
    out = os.path.join(HERE, "wizard-small.bmp")
    canvas.convert("RGB").save(out, format="BMP")
    print("wrote", out)


def make_footer_logo():
    """AM Consulting wordmark composited on the wizard panel colour, for the
    installer footer. Rendered at high resolution; Inno scales it down."""
    cw, ch = 300, 76
    canvas = Image.new("RGBA", (cw, ch), PANEL)
    logo = Image.open(LOGO).convert("RGBA")
    logo = _fit(logo, int(cw * 0.96), int(ch * 0.92))
    x = (cw - logo.width) // 2
    y = (ch - logo.height) // 2
    canvas.alpha_composite(logo, (x, y))
    out = os.path.join(HERE, "footer-logo.bmp")
    canvas.convert("RGB").save(out, format="BMP")
    print("wrote", out)


if __name__ == "__main__":
    make_icon()
    make_wizard_large()
    make_wizard_small()
    make_footer_logo()
