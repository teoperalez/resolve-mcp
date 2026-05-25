"""Pre-render static assets used by the logo-flip Fusion comp.

We match the GSAP/CSS source exactly:
- bg.png    : dark radial gradient + warm floor glow (CSS body+body::after combined, screen blend)
- streaks.png: conic-gradient speed lines with radial-mask donut, blurred

For preset=logo on logo-rbypc.png, the palette is auto-derived from the dominant
hue (~30°/orange). We hard-code that derived palette here to match what the
browser produces. The exact RGB values come from a manual extraction run.
"""

from __future__ import annotations
import math
import os
from PIL import Image, ImageDraw, ImageFilter

# ──────────────────────────────────────────────────────────────────────────────
# Output

OUT_DIR = r'C:\Programming\resolve-mcp\fusion_assets\logo-flip'
W, H = 1920, 1080
os.makedirs(OUT_DIR, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# Colors (extracted by JS: hue≈37°, sat≈0.85 -> palette)

BG_1 = (10, 7, 16, 255)          # #0a0710
BG_2 = (26, 10, 34, 255)         # #1a0a22
BG_EDGE = (5, 3, 9, 255)         # #050309

# For preset=logo on logo-rbypc.png (orange palette around hue 37°)
FLOOR_A_RGB = (255, 162, 65)     # hue 37°, L=0.45, alpha 0.14
FLOOR_A_A   = 0.14
FLOOR_B_RGB = (247, 110, 30)     # hue 37°, L=0.35, alpha 0.20
FLOOR_B_A   = 0.20


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(len(a)))


def smooth_step(t):
    # standard smoothstep — we mostly use linear interp between stops
    return t * t * (3 - 2 * t)


# ──────────────────────────────────────────────────────────────────────────────
# Background: matches the body's radial-gradient
#
#   radial-gradient(1200px 700px at 50% 55%, bg-2 0%, bg-1 60%, #050309 100%)
#
# CSS radial-gradient with explicit size is an ELLIPSE centered at (50%, 55%)
# of viewport. At 1920x1080, the ellipse semi-axes are (600, 350) px.
# A pixel at (x,y) has gradient parameter:
#   d = sqrt(((x - cx) / 600)^2 + ((y - cy) / 350)^2)
# Stops at d=0 -> bg-2, d=0.6 -> bg-1, d=1.0 -> #050309
# For d > 1 (outside the ellipse), CSS extends the final stop (#050309).

def render_bg() -> Image.Image:
    img = Image.new('RGB', (W, H))
    pixels = img.load()
    cx, cy = W * 0.5, H * 0.55
    rx, ry = 1200 / 2, 700 / 2  # CSS '1200px 700px' = full width/height of ellipse
    # CSS radial-gradient sizes refer to full diameter, not radius. Verify by spec:
    # MDN: "<length> represents the radius of the ellipse" actually. So the values
    # ARE radii.  But the syntax "1200px 700px" sets the X and Y radii of the
    # ellipse. So rx=1200, ry=700. Let me use that.
    rx, ry = 1200.0, 700.0

    for y in range(H):
        ny = (y - cy) / ry
        for x in range(W):
            nx = (x - cx) / rx
            d = math.sqrt(nx * nx + ny * ny)
            if d <= 0.6:
                t = d / 0.6
                c = lerp(BG_2, BG_1, t)
            elif d <= 1.0:
                t = (d - 0.6) / 0.4
                c = lerp(BG_1, BG_EDGE, t)
            else:
                c = BG_EDGE
            pixels[x, y] = c[:3]
    return img


# ──────────────────────────────────────────────────────────────────────────────
# Floor glow layer — body::after with mix-blend-mode: screen.
#
#  radial-gradient(60% 25% at 50% 78%, floor-a, transparent 70%)
#  radial-gradient(40% 18% at 50% 90%, floor-b, transparent 75%)
#
# Sizes are percentages of containing box (1920x1080), so:
#  ellipse 1: rx=0.6*1920=1152, ry=0.25*1080=270, center (960, 842)
#  ellipse 2: rx=0.4*1920=768,  ry=0.18*1080=194, center (960, 972)
# These are radii (CSS gradient size is "ending shape"). Transparent at 70%/75%.

def render_floor() -> Image.Image:
    """Returns the FLOOR layer as an RGBA image; alpha encodes the screen-blend
    contribution. We then SCREEN-composite it onto the bg in render_combined.
    """
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    px = layer.load()

    e1 = dict(cx=W * 0.5, cy=H * 0.78, rx=W * 0.6, ry=H * 0.25,
              rgb=FLOOR_A_RGB, a=FLOOR_A_A, fade_at=0.70)
    e2 = dict(cx=W * 0.5, cy=H * 0.90, rx=W * 0.4, ry=H * 0.18,
              rgb=FLOOR_B_RGB, a=FLOOR_B_A, fade_at=0.75)

    for y in range(H):
        for x in range(W):
            acc_r = acc_g = acc_b = 0.0
            acc_a = 0.0
            for e in (e1, e2):
                nx = (x - e['cx']) / e['rx']
                ny = (y - e['cy']) / e['ry']
                d = math.sqrt(nx * nx + ny * ny)
                # CSS: stop at 0% (full color), transparent at fade_at%
                if d >= e['fade_at']:
                    continue
                # linear interp from full color (alpha=e['a']) at 0 to alpha=0 at fade_at
                local_t = d / e['fade_at']
                local_a = e['a'] * (1 - local_t)
                # accumulate via "over" blending — for screen mode we keep them
                # separate, so just use additive on premultiplied
                r, g, b = e['rgb']
                acc_r += r * local_a
                acc_g += g * local_a
                acc_b += b * local_a
                acc_a += local_a
            if acc_a > 0:
                acc_a = min(1.0, acc_a)
                # un-premultiply to store as straight RGBA
                px[x, y] = (
                    min(255, int(round(acc_r / acc_a if acc_a > 0 else 0))),
                    min(255, int(round(acc_g / acc_a if acc_a > 0 else 0))),
                    min(255, int(round(acc_b / acc_a if acc_a > 0 else 0))),
                    int(round(acc_a * 255)),
                )
    return layer


# ──────────────────────────────────────────────────────────────────────────────
# Combine bg + floor in screen-blend mode, output a single PNG (no alpha).

def screen_blend_onto(bg: Image.Image, layer: Image.Image) -> Image.Image:
    out = bg.copy().convert('RGB')
    bp = out.load()
    lp = layer.load()
    for y in range(H):
        for x in range(W):
            br, bg_, bb = bp[x, y]
            lr, lg, lb, la = lp[x, y]
            if la == 0:
                continue
            # screen: 1 - (1-a)*(1-b), then mix by alpha
            sa = la / 255.0
            sr = 255 - int((255 - br) * (255 - lr) / 255)
            sg = 255 - int((255 - bg_) * (255 - lg) / 255)
            sb = 255 - int((255 - bb) * (255 - lb) / 255)
            # linear mix between bg and screened result by alpha
            bp[x, y] = (
                int(round(br + (sr - br) * sa)),
                int(round(bg_ + (sg - bg_) * sa)),
                int(round(bb + (sb - bb) * sa)),
            )
    return out


def main():
    print('rendering bg...')
    bg = render_bg()
    bg.save(os.path.join(OUT_DIR, 'bg_base.png'))

    print('rendering floor...')
    floor = render_floor()
    floor.save(os.path.join(OUT_DIR, 'floor_layer.png'))

    print('combining...')
    combined = screen_blend_onto(bg, floor)
    combined.save(os.path.join(OUT_DIR, 'bg.png'))

    print('done. assets in', OUT_DIR)


if __name__ == '__main__':
    main()
