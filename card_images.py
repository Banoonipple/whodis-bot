"""
Loads the pre-rendered card PNGs (see generate_card_images.py) and builds
composite images (hand grids, anonymized submission grids, round-result
side-by-sides) for the Discord bot to attach to messages.
"""
import io
import math
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).parent / "assets"
CARDS = ASSETS / "cards"
FONTS = ASSETS / "fonts"

# Bundled in the repo (not relying on system fonts, which aren't installed on
# minimal hosts like Railway's default container -- that gap silently fell
# back to a nonexistent "arial.ttf" path and crashed /submit and /vote).
FONT_BOLD = str(FONTS / "Poppins-Bold.ttf")
if not Path(FONT_BOLD).exists():
    raise SystemExit(f"Missing bundled font: {FONT_BOLD}")

def _load_font(path, size):
    for idx in (None, 0):
        try:
            if idx is None:
                return ImageFont.truetype(path, size)
            else:
                return ImageFont.truetype(path, size, index=idx)
        except Exception:
            continue
    raise OSError(f"Cannot open font: {path}")
RED = (0xA4, 0x06, 0x07)
GREEN = (0x07, 0x50, 0x4E)
YELLOW = (0xFE, 0xC1, 0x03)
CREAM = (254, 249, 241)
TRACK_GRAY = (223, 217, 207)
TEAL = GREEN
WHITE = (255, 255, 255)
PANEL_BG = (255, 255, 255)


def inbox_card_path(card_id: str) -> Path:
    return CARDS / "inbox" / f"{card_id}.png"


def reply_card_path(card_id: str) -> Path:
    return CARDS / "reply" / f"{card_id}.png"


def back_card_path() -> Path:
    return CARDS / "back.png"


def _load(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def image_to_file_bytes(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def _thumbnail(img: Image.Image, width: int) -> Image.Image:
    ratio = width / img.width
    return img.resize((width, int(img.height * ratio)), Image.LANCZOS)


def make_grid(
    card_paths: List[Path],
    labels: Optional[List[str]] = None,
    thumb_width: int = 260,
    max_columns: int = 5,
) -> Image.Image:
    """Lay out card thumbnails (with optional number labels) in a grid."""
    thumbs = [_thumbnail(_load(p), thumb_width) for p in card_paths]
    n = len(thumbs)
    columns = min(max_columns, n) or 1
    rows = math.ceil(n / columns)

    cell_w = thumb_width
    cell_h = max(t.height for t in thumbs)
    label_h = 46 if labels else 0
    pad = 24

    grid_w = pad + columns * (cell_w + pad)
    grid_h = pad + rows * (cell_h + label_h + pad)

    canvas = Image.new("RGB", (grid_w, grid_h), PANEL_BG)
    draw = ImageDraw.Draw(canvas)
    f = _load_font(FONT_BOLD, 32)

    for i, thumb in enumerate(thumbs):
        col = i % columns
        row = i // columns
        x = pad + col * (cell_w + pad)
        y = pad + row * (cell_h + label_h + pad)
        if labels:
            label = labels[i]
            bbox = draw.textbbox((0, 0), label, font=f)
            lw = bbox[2] - bbox[0]
            draw.text((x + (cell_w - lw) / 2, y), label, font=f, fill=TEAL)
            y += label_h
        canvas.paste(thumb, (x, y))

    return canvas


def make_scoreboard(entries: List[Tuple[str, int, Optional[bytes]]], points_to_win: int) -> Image.Image:
    """entries: (name, score, avatar_bytes-or-None), already sorted best first."""
    pad = 36
    row_h = 118
    avatar_size = 82
    w = 860
    h = pad * 2 + row_h * len(entries)

    canvas = Image.new("RGB", (w, h), CREAM)
    draw = ImageDraw.Draw(canvas)
    name_font = _load_font(FONT_BOLD, 38)
    score_font = _load_font(FONT_BOLD, 30)

    bar_x = pad + avatar_size + 28
    bar_h = 24
    bar_w = w - bar_x - pad - 130

    for i, (name, score, avatar_bytes) in enumerate(entries):
        y = pad + i * row_h
        row_cy = y + row_h / 2
        is_leader = i == 0 and score > 0
        accent = YELLOW if is_leader else GREEN

        if avatar_bytes:
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGB").resize(
                (avatar_size, avatar_size), Image.LANCZOS
            )
        else:
            avatar = Image.new("RGB", (avatar_size, avatar_size), GREEN)
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, avatar_size, avatar_size], fill=255)
        avatar_y = int(row_cy - avatar_size / 2)
        canvas.paste(avatar, (pad, avatar_y), mask)
        draw.ellipse(
            [pad - 4, avatar_y - 4, pad + avatar_size + 4, avatar_y + avatar_size + 4],
            outline=accent, width=5,
        )

        draw.text((bar_x, y + 14), name, font=name_font, fill=GREEN)

        bar_y = y + row_h - 40
        draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=bar_h // 2, fill=TRACK_GRAY)
        ratio = min(score / points_to_win, 1.0) if points_to_win else 0
        filled_w = int(bar_w * ratio)
        if filled_w > 0:
            draw.rounded_rectangle(
                [bar_x, bar_y, bar_x + max(filled_w, bar_h), bar_y + bar_h], radius=bar_h // 2, fill=accent,
            )

        score_text = f"{score}/{points_to_win}"
        bbox = draw.textbbox((0, 0), score_text, font=score_font)
        sw, sh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((bar_x + bar_w + 20, bar_y + bar_h / 2 - sh / 2 - bbox[1]), score_text, font=score_font, fill=RED)

    return canvas


def make_round_result_image(inbox_path: Path, reply_path: Path) -> Image.Image:
    """Side-by-side: the Inbox message on the left, winning Reply on the right."""
    left = _thumbnail(_load(inbox_path), 480)
    right = _thumbnail(_load(reply_path), 480)
    pad = 30
    h = max(left.height, right.height)
    canvas = Image.new("RGB", (left.width + right.width + pad * 3, h + pad * 2), PANEL_BG)
    canvas.paste(left, (pad, pad))
    canvas.paste(right, (pad * 2 + left.width, pad))
    return canvas
