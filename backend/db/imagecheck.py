"""Server-side inspection of an uploaded field photo: EXIF GPS + original capture time, image
sanity/quality, a lightweight "does this look like water" heuristic, and a perceptual hash.

Everything here reads the actual uploaded bytes; nothing the client types is consulted. It uses only
Pillow + numpy (already dependencies) so no model has to be downloaded. The water check is a colour
and texture heuristic, not a classifier: it rejects blank, document-like and obviously unrelated
images. Every verdict is automatic; there is no human review step.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from db.credit_rules import CreditRules

Image.MAX_IMAGE_PIXELS = 100_000_000  # decompression-bomb guard

_EXIF_IFD, _GPS_IFD = 0x8769, 0x8825
_DATETIME_ORIGINAL, _OFFSET_ORIGINAL = 36867, 36880


class ImageDecodeError(Exception):
    pass


@dataclass
class ImageFacts:
    width: int
    height: int
    fmt: str
    gps_lat: float | None = None
    gps_lon: float | None = None
    captured_at: datetime | None = None
    capture_source: str | None = None  # exif_original | gps_time
    time_inconsistent: bool = False
    sharpness: float = 0.0
    mean_luma: float = 0.0
    luma_std: float = 0.0
    document_like: bool = False
    water_like: float = 0.0  # fraction of the lower frame that looks like a uniform, finely textured water surface
    row_std: float = 99.0  # horizontal colour variation of the lower frame (low for water)
    quality_score: float = 0.0
    phash: int = 0
    notes: list[str] = field(default_factory=list)


# --- EXIF ---------------------------------------------------------------------------------------

def _ratio(value) -> float:
    return float(value[0]) / float(value[1]) if isinstance(value, tuple) else float(value)


def _dms(values, ref) -> float | None:
    try:
        d, m, s = (_ratio(v) for v in values)
        sign = -1.0 if str(ref).upper() in ("S", "W") else 1.0
        return sign * (d + m / 60.0 + s / 3600.0)
    except Exception:
        return None


def _parse_dt(text) -> datetime | None:
    try:
        return datetime.strptime(str(text).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _offset(text) -> timezone | None:
    try:
        t = str(text).strip()
        sign = -1 if t.startswith("-") else 1
        hh, mm = t.lstrip("+-").split(":")
        return timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))
    except Exception:
        return None


def read_exif(img: Image.Image, rules: CreditRules) -> dict:
    """GPS position and original capture time, from the image's own EXIF only."""
    out = {"lat": None, "lon": None, "captured_at": None, "source": None, "inconsistent": False}
    try:
        exif = img.getexif()
        gps = exif.get_ifd(_GPS_IFD)
        sub = exif.get_ifd(_EXIF_IFD)
    except Exception:
        return out
    if gps.get(2) and gps.get(4):
        out["lat"], out["lon"] = _dms(gps[2], gps.get(1)), _dms(gps[4], gps.get(3))

    gps_dt = None
    if gps.get(29) and gps.get(7):
        try:
            h, m, s = (_ratio(v) for v in gps[7])
            day = datetime.strptime(str(gps[29]).strip()[:10], "%Y:%m:%d")
            gps_dt = day.replace(hour=int(h), minute=int(m), second=int(s), tzinfo=timezone.utc)
        except Exception:
            gps_dt = None

    naive = _parse_dt(sub.get(_DATETIME_ORIGINAL))
    if naive is not None:
        tz = _offset(sub.get(_OFFSET_ORIGINAL)) or timezone(timedelta(minutes=rules.assumed_utc_offset_minutes))
        original = naive.replace(tzinfo=tz)
        out["captured_at"], out["source"] = original.astimezone(timezone.utc), "exif_original"
        if gps_dt is not None and abs(gps_dt - out["captured_at"]) > timedelta(hours=26):
            out["inconsistent"] = True  # GPS clock and camera clock disagree: metadata was likely edited
    elif gps_dt is not None:
        out["captured_at"], out["source"] = gps_dt, "gps_time"
    return out


# --- pixels -------------------------------------------------------------------------------------

def _dhash(gray: Image.Image) -> int:
    small = np.asarray(gray.resize((9, 8), Image.LANCZOS), dtype=np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return value


def hamming(a: int, b: int) -> int:
    return bin((a ^ b) & (2**64 - 1)).count("1")


def to_signed64(value: int) -> int:
    return value - 2**64 if value >= 2**63 else value


def from_signed64(value: int) -> int:
    return value + 2**64 if value < 0 else value


def _laplacian_var(gray: np.ndarray) -> float:
    g = gray.astype(np.float32)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def _water_scene(rgb: np.ndarray) -> tuple[float, float]:
    """(water_like, row_std) over the lower ~65% of the frame, in 8x8 blocks of the <=640px image.

    A water surface is horizontally uniform (the same colour and fine ripple texture across a row),
    finely textured but low-contrast, and not strongly warm-coloured. Indoor scenes, objects, text and
    noise fail these: they vary a lot across a row or have hard edges.
      water_like  fraction of blocks that are textured (not flat, not busy), not warm-saturated, of
                  plausible brightness, and similar to both horizontal neighbours.
      row_std     how much block colour varies across a row (low for water, high for cluttered scenes).
    """
    rgb = rgb[int(rgb.shape[0] * 0.35):, :, :].astype(np.float32)
    h, w = (rgb.shape[0] // 8) * 8, (rgb.shape[1] // 8) * 8
    if h < 16 or w < 24:
        return 0.0, 99.0
    blocks = rgb[:h, :w].reshape(h // 8, 8, w // 8, 8, 3)
    mean = blocks.mean(axis=(1, 3))
    luma = 0.299 * blocks[..., 0] + 0.587 * blocks[..., 1] + 0.114 * blocks[..., 2]
    std = luma.std(axis=(1, 3))
    lum = luma.mean(axis=(1, 3))
    mx, mn = mean.max(-1), mean.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    warm = (mean[..., 0] > mean[..., 2] + 15) & (sat > 0.40)
    step = np.abs(np.diff(mean, axis=1)).max(-1)
    homogeneous = np.zeros(lum.shape, bool)
    homogeneous[:, 1:-1] = (step[:, 1:] < 10) & (step[:, :-1] < 10)
    textured = (std > 1.5) & (std < 25)
    water_like = (~warm) & homogeneous & textured & (lum > 30) & (lum < 235)
    row_std = float(mean.std(axis=1).mean())
    return float(water_like.mean()), row_std


def analyze(data: bytes, rules: CreditRules) -> ImageFacts:
    """Decode and inspect. Raises ImageDecodeError if the bytes are not a readable image."""
    try:
        Image.open(io.BytesIO(data)).verify()  # detects truncation/corruption
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageDecodeError(str(exc)) from exc
    fmt = img.format
    if fmt not in ("JPEG", "PNG", "WEBP", "TIFF"):
        raise ImageDecodeError(f"unsupported format {fmt}")

    exif = read_exif(img, rules)
    img = ImageOps.exif_transpose(img).convert("RGB")
    facts = ImageFacts(width=img.width, height=img.height, fmt=fmt)
    facts.gps_lat, facts.gps_lon = exif["lat"], exif["lon"]
    facts.captured_at, facts.capture_source = exif["captured_at"], exif["source"]
    facts.time_inconsistent = exif["inconsistent"]

    scale = 640 / max(img.size)
    work = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS) if scale < 1 else img
    rgb = np.asarray(work, dtype=np.uint8)
    gray = np.asarray(work.convert("L"), dtype=np.uint8)
    facts.sharpness = _laplacian_var(gray) if min(gray.shape) > 2 else 0.0
    facts.mean_luma, facts.luma_std = float(gray.mean()), float(gray.std())
    white = float((rgb.min(axis=2) > 235).mean())
    tiny = np.asarray(work.resize((64, 64)), dtype=np.uint8).reshape(-1, 3) // 8
    unique_colours = len({tuple(p) for p in tiny.tolist()})
    facts.document_like = bool(white > 0.5 or unique_colours < 12)
    facts.water_like, facts.row_std = _water_scene(rgb)
    facts.phash = _dhash(work.convert("L"))

    sharp_s = min(facts.sharpness / 150.0, 1.0)
    exposure_s = 1.0 - min(abs(facts.mean_luma - 120.0) / 120.0, 1.0)
    res_s = min(min(img.size) / 1200.0, 1.0)
    water_s = min(facts.water_like / 0.6, 1.0)
    facts.quality_score = round(0.4 * sharp_s + 0.2 * exposure_s + 0.2 * res_s + 0.2 * water_s, 3)
    return facts
