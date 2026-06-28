"""
Parse a karting race-result photo into structured data.

Table structure (columns = participants by place, rows = laps):
  Row "Место"  : 1  2  3 ... 10   <- place headers
  Row "Инд"    : participant identifier (may be empty)
  Row "Номер"  : Взрослый 10 | Взрослый 8 | ...  <- kart numbers
  Rows 1-N     : lap times per participant
  Row "Отстав.": gap to leader
  Row "Средн." : average lap time
"""
import logging
import os
import re
import tempfile
from datetime import datetime
from typing import Optional

from ocr.preprocessor import preprocess

logger = logging.getLogger(__name__)

_ocr_engine = None


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from img2table.ocr import EasyOCR as Img2EasyOCR
        _ocr_engine = Img2EasyOCR(lang=["ru", "en"])
    return _ocr_engine


def parse_time(raw: str) -> Optional[float]:
    """Convert '44.530' or '1:04.530' to total seconds."""
    s = (raw or "").strip().replace(",", ".")
    m = re.match(r"^(\d+):(\d+\.\d+)$", s)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    m = re.match(r"^(\d{1,3}\.\d{1,3})$", s)
    if m:
        return float(m.group(1))
    return None


def _cell(value) -> str:
    """Stringify a DataFrame cell, treating nan/None as empty."""
    s = str(value).strip()
    return "" if s.lower() in ("nan", "none", "") else s


def _extract_metadata(raw_texts: list) -> dict:
    """Pull race number, date/time and venue from raw easyocr detections."""
    meta = {"race_number": None, "start_time": None, "start_time_dt": None, "venue": None}
    full = " ".join(t[1] for t in raw_texts if len(t) > 1)

    venue_match = re.search(r"([А-ЯЁа-яё][\w\s]{5,}картинг[\w\s]*)", full, re.IGNORECASE)
    if venue_match:
        meta["venue"] = venue_match.group(1).strip()

    rn = re.search(r"заезд\s*[№#]?\s*(\d+)", full, re.IGNORECASE)
    if rn:
        meta["race_number"] = int(rn.group(1))

    dt = re.search(r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2}:\d{2})", full)
    if dt:
        meta["start_time"] = f"{dt.group(1)} {dt.group(2)}"
        try:
            meta["start_time_dt"] = datetime.strptime(meta["start_time"], "%d.%m.%Y %H:%M:%S")
        except ValueError:
            pass

    return meta


def parse_race_photo(image_path: str) -> Optional[dict]:
    """
    Main entry point. Returns structured race data or None on failure.
    This is a CPU-heavy synchronous function — call via asyncio.to_thread().
    """
    processed_path = None
    try:
        from img2table.document import Image as Img2Image

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            processed_path = tmp.name

        preprocess(image_path, processed_path)

        ocr = _get_ocr()
        doc = Img2Image(src=processed_path)

        tables = doc.extract_tables(
            ocr=ocr,
            implicit_rows=False,
            implicit_columns=False,
            borderless_tables=False,
        )

        raw_texts: list = []
        try:
            raw_texts = ocr.reader.readtext(processed_path)
        except Exception:
            pass

        meta = _extract_metadata(raw_texts)

        if not tables:
            logger.warning("No tables found in image")
            return None

        main_table = max(tables, key=lambda t: t.df.shape[1])

        # Reset to integer-based indexing so iloc works regardless of header detection
        df = main_table.df.copy()
        df.columns = range(len(df.columns))
        df = df.reset_index(drop=True)

        participants = _parse_participants(df)
        if not participants:
            return None

        return {**meta, "participants": participants}

    except Exception:
        logger.exception("parse_race_photo failed")
        return None

    finally:
        if processed_path and os.path.exists(processed_path):
            os.unlink(processed_path)


def _parse_participants(df) -> list:
    """Extract participant data from the race results DataFrame."""
    kart_row_idx = None
    for idx in range(len(df)):
        row_text = " ".join(_cell(v) for v in df.iloc[idx].values)
        # Match Cyrillic kart labels or generic "Номер" header
        if re.search(r"взрослый|детский|карт|номер", row_text, re.IGNORECASE):
            kart_row_idx = idx
            break

    if kart_row_idx is None:
        logger.warning("Could not find kart number row in table")
        return []

    kart_row = df.iloc[kart_row_idx]

    col_to_participant: dict = {}
    for col_idx, val in enumerate(kart_row):
        label = _cell(val)
        # Skip header/label cells in the first column
        if label and not re.search(r"^(номер|место|инд)$", label, re.IGNORECASE):
            col_to_participant[col_idx] = {
                "kart_number": label,
                "position": None,
                "lap_times": [],
                "best_lap": None,
                "avg_lap": None,
            }

    if not col_to_participant:
        return []

    for idx in range(kart_row_idx + 1, len(df)):
        row = df.iloc[idx]
        first = _cell(row.iloc[0])

        if re.match(r"отстав|средн|gap|avg", first, re.IGNORECASE):
            break

        if not re.match(r"^\d+$", first):
            continue

        for col_idx, participant in col_to_participant.items():
            if col_idx < len(row):
                t = parse_time(_cell(row.iloc[col_idx]))
                participant["lap_times"].append(t)

    for p in col_to_participant.values():
        valid = [t for t in p["lap_times"] if t is not None]
        if valid:
            p["best_lap"] = min(valid)
            p["avg_lap"] = round(sum(valid) / len(valid), 3)

    participants = list(col_to_participant.values())
    ranked = sorted(
        participants,
        key=lambda p: p["best_lap"] if p["best_lap"] is not None else float("inf"),
    )
    for pos, p in enumerate(ranked, 1):
        p["position"] = pos

    return participants
