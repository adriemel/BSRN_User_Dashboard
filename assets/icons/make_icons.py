"""Build the BSRN desktop icons (.ico) for the User and Curator dashboards.

Usage: python assets/icons/make_icons.py [user|curator]   (default: user)
Requires Pillow. Writes BSRN-<Theme>-Dashboard.ico next to this script.
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageChops

S = 1024
HERE = Path(__file__).resolve().parent
BOLD = str(HERE.parents[1] / 'web' / 'fonts' / 'plex-sans-700.woff2')
ORANGE, AMBER, INK, PETROL, CREAM = '#F28508', '#FDAD3E', '#211F20', '#12343C', '#FAF7F4'
THEMES = {
    'user':    dict(bg=CREAM, horizon='#537284', word=INK, band=PETROL, band_text='#FFFFFF', label='USER', letter='U', edge='#D9D3CB'),
    'curator': dict(bg=PETROL, horizon='#8FB0BF', word='#FFFFFF', band=ORANGE, band_text=INK, label='CURATOR', letter='C', edge=None),
}

def spaced(draw, cx, top, text, font, fill, tracking):
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, top), ch, font=font, fill=fill)
        x += w + tracking

def sun(draw, cx, base, r_out, w_out, r_in, w_in, horizon_color, img):
    draw.arc((cx - r_out, base - r_out, cx + r_out, base + r_out), 180, 360, fill=ORANGE, width=w_out)
    draw.arc((cx - r_in, base - r_in, cx + r_in, base + r_in), 180, 360, fill=AMBER, width=w_in)
    # Horizon: crescent between two vertically offset ellipses, as in the logo.
    rx, ry, thick = r_out * 1.62, r_out * 0.75, max(8, w_out * 0.6)
    top = base + w_out * 0.15
    a = Image.new('L', img.size, 0); ImageDraw.Draw(a).ellipse((cx - rx, top, cx + rx, top + 2 * ry), fill=255)
    b = Image.new('L', img.size, 0); ImageDraw.Draw(b).ellipse((cx - rx, top + thick, cx + rx, top + thick + 2 * ry), fill=255)
    clip = Image.new('L', img.size, 0); ImageDraw.Draw(clip).rectangle((0, 0, img.width, top + thick + r_out * 0.25), fill=255)
    mask = ImageChops.multiply(ImageChops.subtract(a, b), clip)
    img.paste(Image.new('RGBA', img.size, horizon_color), (0, 0), mask)

def render(theme, variant):
    t = THEMES[theme]
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    tile = Image.new('L', (S, S), 0)
    radius = 190 if variant != 'mark' else 220
    ImageDraw.Draw(tile).rounded_rectangle((0, 0, S - 1, S - 1), radius, fill=255)
    body = Image.new('RGBA', (S, S), t['bg'])
    d = ImageDraw.Draw(body)
    if variant == 'full':
        d.rectangle((0, 780, S, S), fill=t['band'])
        sun(d, 512, 372, 270, 48, 182, 40, t['horizon'], body)
        spaced(d, 512, 455, 'BSRN', ImageFont.truetype(BOLD, 250), t['word'], 34)
        size = 150 if len(t['label']) <= 4 else 118
        spaced(d, 512, 902 - size * 0.62, t['label'], ImageFont.truetype(BOLD, size), t['band_text'], 26 if size > 120 else 14)
    elif variant == 'letter':
        sun(d, 512, 470, 330, 92, 205, 80, t['horizon'], body)
        f = ImageFont.truetype(BOLD, 430)
        w = d.textlength(t['letter'], font=f)
        d.text((512 - w / 2, 470), t['letter'], font=f, fill=t['word'])
    else:  # 'mark': sun only, for 16 px
        sun(d, 512, 640, 400, 150, 215, 130, t['horizon'], body)
    if t['edge'] and variant != 'mark':
        ImageDraw.Draw(body).rounded_rectangle((4, 4, S - 5, S - 5), radius - 4, outline=t['edge'], width=12)
    img.paste(body, (0, 0), tile)
    return img

def build(theme, out):
    variants = {256: 'full', 128: 'full', 64: 'full', 48: 'full', 32: 'letter', 24: 'letter', 16: 'mark'}
    frames = {n: render(theme, v).resize((n, n), Image.LANCZOS) for n, v in variants.items()}
    target = out / f'BSRN-{theme.capitalize()}-Dashboard.ico'
    frames[256].save(target, sizes=[(n, n) for n in variants], append_images=[frames[n] for n in variants if n != 256])
    return target

if __name__ == '__main__':
    theme = sys.argv[1].lower() if len(sys.argv) > 1 else 'user'
    if theme not in THEMES:
        sys.exit(f'Unknown theme {theme!r}; choose one of: {", ".join(THEMES)}')
    if not Path(BOLD).is_file():
        sys.exit(f'Font not found: {BOLD}')
    print(build(theme, HERE))
