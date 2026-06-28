"""
Parse a karting race-result photo using Groq Vision API (Llama 4 Scout).
"""
import base64
import json
import logging
from datetime import datetime
from typing import Optional

from groq import Groq

import config

logger = logging.getLogger(__name__)

_client = Groq(api_key=config.GROQ_API_KEY)

_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

_PROMPT = """Ты парсер результатов картингового заезда.
На фото таблица. Извлеки данные и верни ТОЛЬКО валидный JSON без пояснений.

Структура таблицы:
- Строка "Место": номера позиций колонок (1, 2, 3…)
- Строка "Номер": тип карта для каждой колонки ("Взрослый 10", "Взрослый 8" и т.д.)
- Строки 1..N: времена кругов участников
- Строка "Отстав.": отставание — игнорируй
- Строка "Средн.": среднее — игнорируй

Заголовок над таблицей может содержать название площадки, номер заезда и время старта.

Верни JSON строго такой структуры:
{
  "race_number": <целое число или null>,
  "start_time": "<DD.MM.YYYY HH:MM:SS> или null",
  "venue": "<название площадки> или null",
  "participants": [
    {
      "kart_number": "<название карта, например Взрослый 10>",
      "lap_times": [<секунды float>, ...]
    }
  ]
}

Правила:
- Времена кругов — число секунд с точкой (44.658, не 44,658)
- Если ячейка затемнена/закрашена — читай текст как обычно, фон игнорируй
- Если ячейка пустая или нечитаема — используй null в массиве
- Пустые колонки участников (без карта) не включай
- ТОЛЬКО JSON, никакого другого текста"""


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def parse_race_photo(image_path: str) -> Optional[dict]:
    """
    Parse race result photo via Groq Vision API.
    Synchronous — call via asyncio.to_thread() from async handlers.
    """
    try:
        image_b64 = _encode_image(image_path)

        response = _client.chat.completions.create(
            model=_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            },
                        },
                        {
                            "type": "text",
                            "text": _PROMPT,
                        },
                    ],
                }
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )

        data = json.loads(response.choices[0].message.content)

        participants = _build_participants(data.get("participants") or [])
        if not participants:
            logger.warning("Groq returned no participants")
            return None

        return {
            "race_number": data.get("race_number"),
            "start_time": data.get("start_time"),
            "start_time_dt": _parse_dt(data.get("start_time")),
            "venue": data.get("venue"),
            "participants": participants,
        }

    except Exception:
        logger.exception("parse_race_photo failed")
        return None


def _build_participants(raw: list) -> list:
    participants = []
    for p in raw:
        kart = (p.get("kart_number") or "").strip()
        if not kart:
            continue

        lap_times = [
            float(t) if t is not None else None
            for t in (p.get("lap_times") or [])
        ]
        valid = [t for t in lap_times if t is not None]

        participants.append({
            "kart_number": kart,
            "position": None,
            "lap_times": lap_times,
            "best_lap": min(valid) if valid else None,
            "avg_lap": round(sum(valid) / len(valid), 3) if valid else None,
        })

    ranked = sorted(participants, key=lambda p: p["best_lap"] or float("inf"))
    for pos, p in enumerate(ranked, 1):
        p["position"] = pos

    return participants


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d.%m.%Y %H:%M:%S")
    except ValueError:
        return None
