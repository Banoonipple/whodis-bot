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

def _try_font(path):
    for idx in (None, 0):
        try:
            if idx is None:
                ImageFont.truetype(path, 20)
            else:
                ImageFont.truetype(path, 20, index=idx)
            return path
        except Exception:
            continue
    return None

def _find_system_font(bold=True):
    import platform, glob
    if bold:
        direct = [
            "/Library/Fonts/Arial Bold.ttf", "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            r"C:\Windows\Fonts\arialbd.ttf",
            "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        direct = [
            "/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for p in direct:
        if Path(p).exists():
            result = _try_font(p)
            if result:
                return result
    search_dirs = {
        "Darwin": ["/Library/Fonts", "/System/Library/Fonts/Supplemental", "/System/Library/Fonts"],
        "Windows": [r"C:\Windows\Fonts"],
    }.get(platform.system(), ["/usr/share/fonts", "/usr/local/share/fonts"])
    for d in search_dirs:
        for ext in ("ttf", "otf", "ttc"):
            for p in sorted(glob.glob(f"{d}/**/*.{ext}", recursive=True)):
                if "Italic" not in p:
                    result = _try_font(p)
                    if result:
                        return result
    return None

FONT_BOLD = _find_system_font(bold=True) or "arial.ttf"

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
GREEN = (0x07, 0x50, 0x4E)
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
