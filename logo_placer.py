from __future__ import annotations
import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

_face_clf = None
_upper_clf = None


# ════════════════════════════════════════════════════════════════════════════
#  DETECCIÓN DE PERSONAS
# ════════════════════════════════════════════════════════════════════════════

def _load_classifiers():
    global _face_clf, _upper_clf
    if _face_clf is None:
        _face_clf = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if _upper_clf is None:
        _upper_clf = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_upperbody.xml")


def _detect_regions(img_cv: np.ndarray) -> list[tuple[int, int, int, int]]:
    _load_classifiers()
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    img_h, img_w = gray.shape
    regions = []

    faces = _face_clf.detectMultiScale(gray, 1.1, 4, minSize=(20, 20))
    for fx, fy, fw, fh in (faces if len(faces) else []):
        hair  = int(fh * 0.7)
        torso = int(fh * 4.0)
        side  = int(fw * 1.0)
        rx = max(0, fx - side)
        ry = max(0, fy - hair)
        rw = min(fw + 2 * side, img_w - rx)
        rh = min(fh + hair + torso, img_h - ry)
        regions.append((rx, ry, rw, rh))

    upper = _upper_clf.detectMultiScale(gray, 1.1, 3, minSize=(60, 60))
    for x, y, bw, bh in (upper if len(upper) else []):
        extra = int(bh * 0.5)
        regions.append((x, y, bw, min(bh + extra, img_h - y)))

    return regions


# ════════════════════════════════════════════════════════════════════════════
#  SCORING DE ZONAS
# ════════════════════════════════════════════════════════════════════════════

def _overlap_ratio(lx, ly, lw, lh, regions) -> float:
    area = lw * lh
    if area == 0:
        return 0.0
    total = 0
    for rx, ry, rw, rh in regions:
        ix1, iy1 = max(lx, rx), max(ly, ry)
        ix2, iy2 = min(lx + lw, rx + rw), min(ly + lh, ry + rh)
        if ix2 > ix1 and iy2 > iy1:
            total += (ix2 - ix1) * (iy2 - iy1)
    return total / area


def _zone_score(img_cv, x, y, w, h) -> float:
    roi = img_cv[y:y + h, x:x + w]
    if roi.size == 0:
        return 1.0
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
    brightness = float(np.mean(gray)) / 255.0
    lap_var    = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    complexity = min(lap_var / 600.0, 1.0)
    return 0.4 * brightness + 0.6 * complexity


def _candidates(iw, ih, lw, lh, margin=14):
    return [
        ("top-left",      margin,             margin),
        ("top-right",     iw - lw - margin,   margin),
        ("bottom-left",   margin,             ih - lh - margin),
        ("bottom-right",  iw - lw - margin,   ih - lh - margin),
        ("top-center",    (iw - lw) // 2,     margin),
        ("bottom-center", (iw - lw) // 2,     ih - lh - margin),
        ("mid-left",      margin,             (ih - lh) // 2),
        ("mid-right",     iw - lw - margin,   (ih - lh) // 2),
        ("center",        (iw - lw) // 2,     (ih - lh) // 2),
    ]


# ════════════════════════════════════════════════════════════════════════════
#  MARCA DE AGUA DE TEXTO
# ════════════════════════════════════════════════════════════════════════════

def _apply_text_watermark(img: Image.Image, text_config: dict) -> Image.Image:
    """
    Dibuja marca de agua de texto (esquina inferior derecha).
    text_config = {"text": str, "font_size": int, "color": "#rrggbb"}
    """
    text = text_config.get("text", "").strip()
    if not text:
        return img

    font_size = max(8, int(text_config.get("font_size", 24)))
    color_hex = text_config.get("color", "#ffffff").lstrip("#")
    try:
        r = int(color_hex[0:2], 16)
        g = int(color_hex[2:4], 16)
        b = int(color_hex[4:6], 16)
    except Exception:
        r, g, b = 255, 255, 255

    font = None
    for fp in [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/Arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            font = ImageFont.truetype(fp, font_size)
            break
        except Exception:
            pass
    if font is None:
        try:
            font = ImageFont.load_default(size=font_size)
        except Exception:
            font = ImageFont.load_default()

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw = font_size * len(text) // 2
        th = font_size

    margin = max(14, int(min(img.width, img.height) * 0.018))
    tx = img.width  - tw - margin
    ty = img.height - th - margin

    # Shadow for legibility
    draw.text((tx + 2, ty + 2), text, font=font, fill=(0, 0, 0, 160))
    draw.text((tx,     ty),     text, font=font, fill=(r, g, b, 230))

    return Image.alpha_composite(img.convert("RGBA"), overlay)


# ════════════════════════════════════════════════════════════════════════════
#  LÓGICA INTERNA COMPARTIDA
# ════════════════════════════════════════════════════════════════════════════

def _resize_logo(logo_path: str, iw: int, ih: int,
                 size_pct: int, opacity: int) -> tuple[Image.Image, int, int]:
    logo_orig = Image.open(logo_path).convert("RGBA")
    lw = max(1, int(iw * size_pct / 100))
    lh = max(1, int(lw * logo_orig.height / logo_orig.width))
    if lw > iw or lh > ih:
        scale = min(iw / lw, ih / lh) * 0.9
        lw, lh = max(1, int(lw * scale)), max(1, int(lh * scale))
    logo = logo_orig.resize((lw, lh), Image.LANCZOS)
    if opacity < 100:
        r, g, b, a = logo.split()
        a = a.point(lambda v: int(v * opacity / 100))
        logo = Image.merge("RGBA", (r, g, b, a))
    return logo, lw, lh


def _compute_position(iw, ih, lw, lh, img_cv,
                      force_position, absolute_xy) -> tuple[int, int]:
    valid = [
        (name, x, y)
        for name, x, y in _candidates(iw, ih, lw, lh)
        if x >= 0 and y >= 0 and x + lw <= iw and y + lh <= ih
    ]

    if absolute_xy is not None:
        fx, fy = absolute_xy
        px = max(0, min(int(fx * iw), iw - lw))
        py = max(0, min(int(fy * ih), ih - lh))
        return px, py

    if force_position:
        match = [(n, x, y) for n, x, y in valid if n == force_position]
        if match:
            return match[0][1], match[0][2]

    regions: list[tuple[int, int, int, int]] = []
    if _CV2_AVAILABLE and img_cv is not None:
        try:
            regions = _detect_regions(img_cv)
        except Exception:
            pass

    scored = []
    for name, x, y in valid:
        overlap = _overlap_ratio(x, y, lw, lh, regions)
        zone    = _zone_score(img_cv, x, y, lw, lh) if img_cv is not None else 0.5
        scored.append((overlap, zone, name, x, y))

    scored.sort(key=lambda t: (t[0], t[1]))
    _, _, _, px, py = scored[0] if scored else (0, 0, "fallback", 0, 0)
    return px, py


# ════════════════════════════════════════════════════════════════════════════
#  API PÚBLICA
# ════════════════════════════════════════════════════════════════════════════

def prepare_preview(
    image_path: str,
    logo_path: str,
    size_pct: int = 15,
    opacity: int = 80,
    force_position: str | None = None,
    absolute_xy: tuple[float, float] | None = None,
    text_config: dict | None = None,
) -> tuple[Image.Image, Image.Image, int, int]:
    """
    Devuelve (imagen_base, logo_rgba, px, py).
    Si text_config tiene texto, lo aplica sobre la imagen base (para la vista previa).
    """
    img = Image.open(image_path).convert("RGBA")
    iw, ih = img.size

    logo, lw, lh = _resize_logo(logo_path, iw, ih, size_pct, opacity)

    img_cv = None
    if _CV2_AVAILABLE and absolute_xy is None and force_position is None:
        try:
            img_cv = cv2.cvtColor(
                np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        except Exception:
            pass

    px, py = _compute_position(iw, ih, lw, lh, img_cv, force_position, absolute_xy)

    if text_config and text_config.get("text", "").strip():
        img = _apply_text_watermark(img, text_config)

    return img, logo, px, py


def place_logo(
    image_path: str,
    logo_path: str,
    size_pct: int = 15,
    opacity: int = 80,
    force_position: str | None = None,
    absolute_xy: tuple[float, float] | None = None,
    text_config: dict | None = None,
) -> Image.Image:
    """Aplica logo y marca de agua de texto a la imagen. Devuelve la imagen compuesta."""
    # Sin texto en prepare_preview: lo aplicamos después del logo
    img, logo, px, py = prepare_preview(
        image_path, logo_path, size_pct, opacity, force_position, absolute_xy,
        text_config=None)
    result = img.copy()
    result.paste(logo, (px, py), logo)
    if text_config and text_config.get("text", "").strip():
        result = _apply_text_watermark(result, text_config)
    return result
