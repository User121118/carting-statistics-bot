"""
Parse a karting race-result photo using raw EasyOCR output.

Instead of relying on img2table (which needs straight table lines),
we cluster OCR bounding boxes into rows/columns by coordinate proximity.
This works even on slightly angled photos.

Table structure (columns = participants, rows = laps):
  Row "Место"  : 1  2  3 ...     <- place numbers
  Row "Номер"  : Взрослый 10 | Взрослый 8 | ...
  Rows 1-N     : lap times
  Row "Отстав.": gap to leader
  Row "Средн." : average lap
"""
import logging
import os
import re
import tempfile
from datetime import datetime
from typing import Optional

from ocr.preprocessor import preprocess

logger = logging.getLogger(__name__)

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(["ru", "en"], gpu=False)
    return _reader


# ── Geometry helpers ───────────────────────────────────────────────────────────

def _cy(bbox) -> float:
    """Y center of a bounding box [[x,y], ...]."""
    return sum(p[1] for p in bbox) / len(bbox)


def _cx(bbox) -> float:
    """X center of a bounding box."""
    return sum(p[0] for p in bbox) / len(bbox)


def _height(bbox) -> float:
    ys = [p[1] for p in bbox]
    return max(ys) - min(ys)


# ── Row / column clustering ────────────────────────────────────────────────────

def _cluster_rows(detections: list, tolerance_ratio: float = 0.7) -> list[list]:
    """
    Group (bbox, text, conf) detections into rows by Y-center proximity.
    tolerance_ratio: fraction of avg char height used as row-merge threshold.
    Returns list of rows, each row sorted left→right.
    """
    if not detections:
        return []

    avg_h = sum(_height(d[0]) for d in detections) / len(detections) or 20
    tol = avg_h * tolerance_ratio

    by_y = sorted(detections, key=lambda d: _cy(d[0]))

    rows: list[list] = []
    cur = [by_y[0]]
    cur_y = _cy(by_y[0][0])

    for det in by_y[1:]:
        y = _cy(det[0])
        if abs(y - cur_y) <= tol:
            cur.append(det)
        else:
            rows.append(sorted(cur, key=lambda d: _cx(d[0])))
            cur = [det]
            cur_y = y

    rows.append(sorted(cur, key=lambda d: _cx(d[0])))
    return rows


def _assign_to_column(item_x: float, col_centers: list[float]) -> Optional[int]:
    """
    Return index of the nearest column center, or None if too far away.
    Tolerance = half the minimum gap between adjacent columns.
    """
    if not col_centers:
        return None

    sorted_cx = sorted(col_centers)
    if len(sorted_cx) > 1:
        gaps = [sorted_cx[i + 1] - sorted_cx[i] for i in range(len(sorted_cx) - 1)]
        tol = min(gaps) * 0.55
    else:
        tol = 150  # single column fallback

    nearest_idx = min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - item_x))
    if abs(col_centers[nearest_idx] - item_x) <= tol:
        return nearest_idx
    return None


# ── Time parsing ───────────────────────────────────────────────────────────────

def parse_time(raw: str) -> Optional[float]:
    """Convert '44.530' or '1:04.530' → seconds."""
    s = (raw or "").strip().replace(",", ".")
    m = re.match(r"^(\d+):(\d+\.\d+)$", s)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    m = re.match(r"^(\d{1,3}\.\d{1,3})$", s)
    if m:
        return float(m.group(1))
    return None


# ── Metadata extraction ────────────────────────────────────────────────────────

def _extract_metadata(rows: list) -> dict:
    meta = {"race_number": None, "start_time": None, "start_time_dt": None, "venue": None}

    # Use all text from the top 15 rows for header info
    header_text = " ".join(d[1] for row in rows[:15] for d in row)

    venue = re.search(r"([А-ЯЁа-яё][\w\s]{5,}картинг[\w\s]*)", header_text, re.IGNORECASE)
    if venue:
        meta["venue"] = venue.group(1).strip()

    rn = re.search(r"заезд\s*[№#]?\s*(\d+)", header_text, re.IGNORECASE)
    if rn:
        meta["race_number"] = int(rn.group(1))

    dt = re.search(r"(\d{2}\.\d{2}\.\d{4})\s*(\d{2}:\d{2}:\d{2})", header_text)
    if dt:
        meta["start_time"] = f"{dt.group(1)} {dt.group(2)}"
        try:
            meta["start_time_dt"] = datetime.strptime(meta["start_time"], "%d.%m.%Y %H:%M:%S")
        except ValueError:
            pass

    return meta


# ── Participant parsing ────────────────────────────────────────────────────────

def _parse_participants(rows: list) -> list:
    # Find the row with kart labels ("Взрослый 10", "Детский 8", …)
    kart_row_idx = None
    for idx, row in enumerate(rows):
        row_text = " ".join(d[1] for d in row)
        if re.search(r"взрослый|детский|карт", row_text, re.IGNORECASE):
            kart_row_idx = idx
            break

    if kart_row_idx is None:
        logger.warning("Kart number row not found")
        return []

    kart_row = rows[kart_row_idx]

    # Collect participant columns: skip generic header cells
    participants: list[dict] = []
    col_centers: list[float] = []

    for det in kart_row:
        label = det[1].strip()
        if re.match(r"^(номер|место|инд\.?)$", label, re.IGNORECASE):
            continue
        if not label:
            continue
        col_centers.append(_cx(det[0]))
        participants.append({
            "kart_number": label,
            "position": None,
            "lap_times": [],
            "best_lap": None,
            "avg_lap": None,
        })

    if not participants:
        logger.warning("No participant columns found in kart row")
        return []

    # Collect lap times from subsequent rows
    for row in rows[kart_row_idx + 1:]:
        row_text = " ".join(d[1] for d in row)

        # Stop at summary rows
        if re.search(r"отстав|средн", row_text, re.IGNORECASE):
            break

        # Only process rows whose first token is a lap number
        first = row[0][1].strip() if row else ""
        if not re.match(r"^\d+$", first):
            continue

        # Assign each token to the nearest participant column
        for det in row[1:]:
            col_idx = _assign_to_column(_cx(det[0]), col_centers)
            if col_idx is not None:
                participants[col_idx]["lap_times"].append(parse_time(det[1].strip()))

    # Calculate best / avg, assign positions
    for p in participants:
        valid = [t for t in p["lap_times"] if t is not None]
        if valid:
            p["best_lap"] = min(valid)
            p["avg_lap"] = round(sum(valid) / len(valid), 3)

    ranked = sorted(participants, key=lambda p: p["best_lap"] or float("inf"))
    for pos, p in enumerate(ranked, 1):
        p["position"] = pos

    return participants


# ── Main entry point ───────────────────────────────────────────────────────────

def parse_race_photo(image_path: str) -> Optional[dict]:
    """
    CPU-heavy synchronous function — call via asyncio.to_thread() from async code.
    Returns structured race data or None on failure.
    """
    processed_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            processed_path = tmp.name

        preprocess(image_path, processed_path)

        reader = _get_reader()
        raw = reader.readtext(processed_path, detail=1, paragraph=False)

        # Lower threshold captures shaded/highlighted cells that OCR is less confident about
        detections = [(bbox, text, conf) for bbox, text, conf in raw if conf > 0.15]

        if not detections:
            logger.warning("EasyOCR returned no detections")
            return None

        rows = _cluster_rows(detections)
        meta = _extract_metadata(rows)
        participants = _parse_participants(rows)

        if not participants:
            logger.warning("No participants parsed from rows")
            return None

        return {**meta, "participants": participants}

    except Exception:
        logger.exception("parse_race_photo failed")
        return None

    finally:
        if processed_path and os.path.exists(processed_path):
            os.unlink(processed_path)
