"""
The AM Consulting "cloud sync" mark — two volumetric clouds exchanging data via
bidirectional arrows. This is the product icon (Drive <-> NotebookLM sync).

`render(size, bg=...)` returns a square RGBA image at `size` px, drawn at 4x
supersample and downscaled for clean antialiasing. Used by make_assets.py to
build app.ico and the installer wizard art. Keep the look in sync with the
approved concept (win_app/branding/concepts/2c_clouds_512.png).
"""
import math

from PIL import Image, ImageDraw, ImageFilter

_SS = 1024                       # internal supersample resolution
BG = (11, 15, 25, 255)           # #0b0f19 brand base
ARROW = (240, 247, 255, 255)     # near-white arrows

# puff offsets/radii as fractions of the cloud width `w`
PUFFS = [(-0.34, 0.06, 0.32), (-0.05, -0.22, 0.42),
         (0.30, -0.02, 0.36), (0.12, 0.16, 0.32)]


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _cloud_mask(cx, cy, w):
    m = Image.new("L", (_SS, _SS), 0)
    md = ImageDraw.Draw(m)
    for ox, oy, pr in PUFFS:
        r = w * pr
        x, y = cx + ox * w, cy + oy * w
        md.ellipse([x - r, y - r, x + r, y + r], fill=255)
    md.rounded_rectangle([cx - w * 0.62, cy - w * 0.02, cx + w * 0.62, cy + w * 0.36],
                         radius=w * 0.18, fill=255)
    return m


def _clip(layer, mask):
    out = Image.new("RGBA", (_SS, _SS), (0, 0, 0, 0))
    out.paste(layer, (0, 0), mask)
    return out


def _cloud_layer(cx, cy, w, top, bot, outline):
    mask = _cloud_mask(cx, cy, w)

    # vertical gradient (lighter top -> darker bottom) gives the cloud volume;
    # span the FULL silhouette (lowest puff bottom is cy + 0.48*w) so the fill
    # always reaches the outline rim — no dark gap at the base.
    grad = Image.new("RGBA", (_SS, _SS), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    y0, y1 = cy - 0.66 * w, cy + 0.52 * w
    for yy in range(max(0, int(y0)), min(_SS, int(y1)) + 1):
        t = min(1, max(0, (yy - y0) / (y1 - y0)))
        gd.line([(0, yy), (_SS, yy)], fill=_lerp(top, bot, t) + (255,))
    layer = _clip(grad, mask)

    # soft highlight on the upper part of each puff
    hl = Image.new("RGBA", (_SS, _SS), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hl)
    for ox, oy, pr in PUFFS:
        r = w * pr
        x, y = cx + ox * w, cy + oy * w - 0.30 * r
        hr = r * 0.62
        hd.ellipse([x - hr, y - hr, x + hr, y + hr], fill=(255, 255, 255, 80))
    hl = hl.filter(ImageFilter.GaussianBlur(22))
    layer = Image.alpha_composite(layer, _clip(hl, mask))

    # grounding shadow along the base
    sh = Image.new("RGBA", (_SS, _SS), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    sd.ellipse([cx - w * 0.60, cy + 0.12 * w, cx + w * 0.60, cy + 0.46 * w],
               fill=(0, 18, 45, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(26))
    layer = Image.alpha_composite(layer, _clip(sh, mask))

    # dark outline rim (also separates the two clouds where they overlap)
    edge = mask.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(11))
    ol = Image.new("RGBA", (_SS, _SS), outline + (255,))
    layer = Image.alpha_composite(layer, _clip(ol, edge))
    return layer


def _arrow(d, c, dirv, perp, half, t, head, color):
    sx, sy = c[0] - dirv[0] * half, c[1] - dirv[1] * half
    ex, ey = c[0] + dirv[0] * half, c[1] + dirv[1] * half
    bx, by = ex - dirv[0] * head, ey - dirv[1] * head
    d.line([(sx, sy), (bx, by)], fill=color, width=t, joint="curve")
    r = t // 2
    d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=color)
    d.polygon([(ex, ey),
               (bx + perp[0] * head * 0.85, by + perp[1] * head * 0.85),
               (bx - perp[0] * head * 0.85, by - perp[1] * head * 0.85)], fill=color)


def render(size, bg=BG):
    """Square RGBA cloud-sync mark at `size` px (drawn at 4x, downscaled)."""
    img = Image.new("RGBA", (_SS, _SS), bg)
    a, b, w = (330, 350), (694, 712), 480
    # back cloud first, then front cloud so its rim separates the overlap
    img = Image.alpha_composite(img, _cloud_layer(*a, w, (96, 165, 250), (33, 99, 200), (12, 48, 115)))
    img = Image.alpha_composite(img, _cloud_layer(*b, w, (152, 226, 252), (40, 158, 205), (16, 86, 135)))

    d = ImageDraw.Draw(img)
    vx, vy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(vx, vy)
    dirv = (vx / n, vy / n)
    perp = (-dirv[1], dirv[0])
    c = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    half, t, head, off = 150, 50, 78, 78
    fwd = (c[0] + perp[0] * off, c[1] + perp[1] * off)
    back = (c[0] - perp[0] * off, c[1] - perp[1] * off)
    ndir, nperp = (-dirv[0], -dirv[1]), (-perp[0], -perp[1])
    # dark backing so the white arrows stay legible over both clouds
    _arrow(d, fwd, dirv, perp, half, t + 16, head + 8, (10, 28, 60, 150))
    _arrow(d, back, ndir, nperp, half, t + 16, head + 8, (10, 28, 60, 150))
    _arrow(d, fwd, dirv, perp, half, t, head, ARROW)
    _arrow(d, back, ndir, nperp, half, t, head, ARROW)

    return img.resize((size, size), Image.LANCZOS)
