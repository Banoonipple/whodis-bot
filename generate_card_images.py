"""
Renders card artwork for every card in data/deck.json, built around the
"Who Dis?" logo (WhoDisLogo.png):

  assets/WhoDisLogo.png   -> mascot icon (cropped) + full wordmark, composited
                             directly onto every card (no template needed)

Output:
  assets/cards/back.png
  assets/cards/inbox/<ID>.png   (one per Inbox card)
  assets/cards/reply/<ID>.png   (one per Reply card)

Run:  python3 generate_card_images.py
"""
import json
import textwrap
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
OUT = ASSETS / "cards"
(OUT / "inbox").mkdir(parents=True, exist_ok=True)
(OUT / "reply").mkdir(parents=True, exist_ok=True)

LOGO_PATH = ROOT / "WhoDis?Logo.png"
MASCOT_CROP_BOX = (120, 130, 500, 950)  # just the mascot icon, excludes the wordmark

CANVAS_SIZE = (1000, 1300)

FONTS = ASSETS / "fonts"
FONT_BOLD = str(FONTS / "Poppins-Bold.ttf")
FONT_MEDIUM = str(FONTS / "Poppins-Medium.ttf")

for _p in (FONT_BOLD, FONT_MEDIUM):
    if not Path(_p).exists():
        raise SystemExit(f"Missing bundled font: {_p}")

print(f"Using fonts: Bold={FONT_BOLD}, Medium={FONT_MEDIUM}")

# Brand palette, sourced from the logo itself.
RED = (0xA4, 0x06, 0x07)
GREEN = (0x07, 0x50, 0x4E)
YELLOW = (0xFE, 0xC1, 0x03)
CREAM = (254, 249, 241)
INK = GREEN


from functools import lru_cache


@lru_cache(maxsize=None)
def font(path, size):
    for idx in (None, 0):
        try:
            if idx is None:
                return ImageFont.truetype(path, size)
            else:
                return ImageFont.truetype(path, size, index=idx)
        except Exception:
            continue
    raise OSError(f"Cannot open font: {path}")


def text_size(draw, text, f):
    l, t, r, b = draw.textbbox((0, 0), text, font=f)
    return r - l, b - t


def wrap_to_fit(draw, text, font_path, max_width, max_height, start_size, min_size=26, line_spacing=1.2):
    """Shrink font size until the wrapped text fits within max_width x max_height."""
    size = start_size
    while size >= min_size:
        f = font(font_path, size)
        avg_char_w = text_size(draw, "M", f)[0] * 0.62
        wrap_chars = max(8, int(max_width / max(avg_char_w, 1)))
        lines = []
        for para in text.split("\n"):
            lines.extend(textwrap.wrap(para, width=wrap_chars) or [""])
        line_h = text_size(draw, "Mg", f)[1] * line_spacing
        total_h = line_h * len(lines)
        max_line_w = max((text_size(draw, ln, f)[0] for ln in lines), default=0)
        if total_h <= max_height and max_line_w <= max_width:
            return f, lines, line_h
        size -= 2
    f = font(font_path, min_size)
    lines = textwrap.wrap(text, width=max(8, int(max_width / 12))) or [text]
    line_h = text_size(draw, "Mg", f)[1] * line_spacing
    return f, lines, line_h


def draw_centered_block(draw, lines, f, line_h, center_x, center_y, fill):
    total_h = line_h * len(lines)
    y = center_y - total_h / 2
    for ln in lines:
        w, _ = text_size(draw, ln, f)
        draw.text((center_x - w / 2, y), ln, font=f, fill=fill)
        y += line_h


_LOGO_CACHE = None


def get_logo() -> Image.Image:
    """The logo with every near-white pixel (background, plus enclosed letter
    counters/holes, which a flood-fill would miss since they're disconnected
    regions) recolored to the exact card cream, so it composites seamlessly."""
    global _LOGO_CACHE
    if _LOGO_CACHE is None:
        logo = Image.open(LOGO_PATH).convert("RGB")
        r, g, b = logo.split()
        min_ch = ImageChops.darker(ImageChops.darker(r, g), b)
        mask = min_ch.point(lambda p: 255 if p > 235 else 0)
        cream_layer = Image.new("RGB", logo.size, CREAM)
        _LOGO_CACHE = Image.composite(cream_layer, logo, mask)
    return _LOGO_CACHE.copy()


def get_mascot_crop() -> Image.Image:
    return get_logo().crop(MASCOT_CROP_BOX)


def base_card(accent) -> tuple:
    """Cream card with a thick rounded double-line frame in the given accent color."""
    img = Image.new("RGB", CANVAS_SIZE, CREAM)
    draw = ImageDraw.Draw(img)
    w, h = CANVAS_SIZE
    outer = [34, 34, w - 34, h - 34]
    draw.rounded_rectangle(outer, radius=70, outline=accent, width=22)
    inner = [outer[0] + 34, outer[1] + 34, outer[2] - 34, outer[3] - 34]
    draw.rounded_rectangle(inner, radius=46, outline=accent, width=5)
    return img, draw


def render_front(text: str, label: str, pill_bg, pill_fg, accent) -> Image.Image:
    img, draw = base_card(accent)
    w, h = CANVAS_SIZE
    mx, my = 96, 96

    mascot = get_mascot_crop()
    icon_w = 150
    icon = mascot.resize((icon_w, int(mascot.height * icon_w / mascot.width)), Image.LANCZOS)
    icon_y = my
    img.paste(icon, (mx, icon_y))

    pill_font = font(FONT_MEDIUM, 34)
    pw, ph = text_size(draw, label, pill_font)
    pad_x, pad_y = 30, 18
    pill_x = mx + icon_w + 26
    pill_y = icon_y + (icon.height - (ph + pad_y * 2)) // 2
    pill_box = [pill_x, pill_y, pill_x + pw + pad_x * 2, pill_y + ph + pad_y * 2]
    draw.rounded_rectangle(pill_box, radius=(pill_box[3] - pill_box[1]) // 2, fill=pill_bg)
    draw.text((pill_x + pad_x, pill_y + pad_y - 2), label, font=pill_font, fill=pill_fg)

    content_top = icon_y + icon.height + 60
    content_bottom = h - my - 170
    f, lines, line_h = wrap_to_fit(
        draw, text, FONT_BOLD, max_width=(w - 2 * mx), max_height=(content_bottom - content_top), start_size=72,
    )
    center_y = (content_top + content_bottom) / 2
    draw_centered_block(draw, lines, f, line_h, w / 2, center_y, INK)

    logo = get_logo()
    wm_w = 240
    wm = logo.resize((wm_w, int(logo.height * wm_w / logo.width)), Image.LANCZOS)
    img.paste(wm, (w - mx - wm_w, h - my - wm.height))

    return img


def render_inbox_card(card: dict) -> Image.Image:
    return render_front(card["text"], "INCOMING TEXT", RED, CREAM, RED)


def render_reply_card(card: dict) -> Image.Image:
    return render_front(card["text"], "YOUR REPLY", YELLOW, GREEN, GREEN)


def make_back_image():
    img, draw = base_card(GREEN)
    w, h = CANVAS_SIZE
    logo = get_logo()
    logo_w = 780
    logo_img = logo.resize((logo_w, int(logo.height * logo_w / logo.width)), Image.LANCZOS)
    img.paste(logo_img, ((w - logo_w) // 2, (h - logo_img.height) // 2))
    img.save(OUT / "back.png")


def main():
    make_back_image()

    deck = json.loads((DATA / "deck.json").read_text(encoding="utf-8"))

    total_inbox = 0
    for card in deck["inbox"]:
        out_path = OUT / "inbox" / f"{card['id']}.png"
        if not out_path.exists():
            render_inbox_card(card).save(out_path, optimize=True)
        total_inbox += 1

    total_reply = 0
    for card in deck["replies"]:
        out_path = OUT / "reply" / f"{card['id']}.png"
        if not out_path.exists():
            render_reply_card(card).save(out_path, optimize=True)
        total_reply += 1

    print(f"Rendered {total_inbox} inbox cards and {total_reply} reply cards, plus 1 back.png")


if __name__ == "__main__":
    main()
