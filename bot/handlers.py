import asyncio
import logging
import os
import tempfile
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

import db.repository as repo
from bot.keyboards import confirm, kart_numbers, main_menu
from bot.states import CONFIRM_RESULT, SELECT_KART
from db.models import RaceResult
from ocr.parser import parse_race_photo

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_time(t) -> str:
    return f"{t:.3f} с" if t is not None else "—"


def _format_result(result: RaceResult, title: str) -> str:
    laps = result.lap_times or []
    laps_str = "\n".join(
        f"  Круг {i + 1}: {_fmt_time(t)}"
        for i, t in enumerate(laps)
    )
    return (
        f"🏁 *{title}*\n\n"
        f"🛺 Карт: `{result.kart_number}`\n"
        f"🏆 Позиция: {result.position or '—'}\n"
        f"⚡ Лучший круг: `{_fmt_time(result.best_lap)}`\n"
        f"📊 Средний круг: `{_fmt_time(result.avg_lap)}`\n\n"
        f"🕐 Все круги:\n{laps_str}"
    )


def _format_participant(participant: dict, race_data: dict) -> str:
    laps = participant.get("lap_times") or []
    laps_str = "\n".join(
        f"  Круг {i + 1}: {_fmt_time(t)}"
        for i, t in enumerate(laps)
    )
    race_no = race_data.get("race_number") or "?"
    start = race_data.get("start_time") or "?"
    return (
        f"📋 *Карт {participant['kart_number']}*\n\n"
        f"🏁 Заезд №{race_no}\n"
        f"📅 Старт: {start}\n"
        f"🏆 Позиция: {participant.get('position') or '—'}\n"
        f"⚡ Лучший круг: `{_fmt_time(participant.get('best_lap'))}`\n"
        f"📊 Средний круг: `{_fmt_time(participant.get('avg_lap'))}`\n\n"
        f"🕐 Все круги:\n{laps_str}\n\n"
        f"Данные верны?"
    )


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Привет! Отправь фото результатов заезда, чтобы сохранить свой результат.",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Отменено.", reply_markup=main_menu())
    return ConversationHandler.END


# ── Menu buttons ───────────────────────────────────────────────────────────────

async def my_last_race(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    result = await repo.get_last_result(update.effective_user.id)
    if not result:
        await update.message.reply_text(
            "У вас ещё нет сохранённых результатов.\nОтправьте фото заезда!",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END
    await update.message.reply_text(
        _format_result(result, "Последний заезд"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


async def my_best_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    result = await repo.get_best_result(update.effective_user.id)
    if not result:
        await update.message.reply_text(
            "У вас ещё нет сохранённых результатов.\nОтправьте фото заезда!",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END
    await update.message.reply_text(
        _format_result(result, "Лучший результат"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


# ── Photo flow ─────────────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = await update.message.reply_text("Обрабатываю фото... ⏳")

    photo_file = await update.message.photo[-1].get_file()

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        await photo_file.download_to_drive(tmp.name)
        tmp_path = tmp.name

    try:
        # OCR is CPU-heavy — run in thread pool to not block the event loop
        race_data = await asyncio.to_thread(parse_race_photo, tmp_path)
    finally:
        os.unlink(tmp_path)

    try:
        await msg.delete()
    except Exception:
        pass

    if not race_data or not race_data.get("participants"):
        await update.message.reply_text(
            "Не удалось распознать таблицу 😔\n"
            "Попробуйте сфотографировать ровнее, без наклона.",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    context.user_data["pending_race"] = race_data

    numbers = [p["kart_number"] for p in race_data["participants"]]
    await update.message.reply_text(
        "Фото обработано! Выберите ваш номер карта:",
        reply_markup=kart_numbers(numbers),
    )
    return SELECT_KART


async def handle_kart_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    kart = query.data.split(":", 1)[1]
    race_data: Optional[dict] = context.user_data.get("pending_race")

    if not race_data:
        await query.edit_message_text("Сессия устарела. Отправьте фото заново.")
        return ConversationHandler.END

    participant = next(
        (p for p in race_data["participants"] if p["kart_number"] == kart),
        None,
    )
    if not participant:
        await query.edit_message_text("Карт не найден. Отправьте фото заново.")
        return ConversationHandler.END

    context.user_data["selected_participant"] = participant

    await query.edit_message_text(
        _format_participant(participant, race_data),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=confirm(),
    )
    return CONFIRM_RESULT


async def handle_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    answer = query.data.split(":", 1)[1]

    if answer == "no":
        context.user_data.clear()
        await query.edit_message_text("Отменено.")
        await query.message.reply_text("Отправьте фото заново.", reply_markup=main_menu())
        return ConversationHandler.END

    race_data = context.user_data.get("pending_race")
    participant = context.user_data.get("selected_participant")

    if not race_data or not participant:
        await query.edit_message_text("Сессия устарела. Отправьте фото заново.")
        return ConversationHandler.END

    tg_user = update.effective_user
    db_user = await repo.get_or_create_user(
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
    )
    race = await repo.create_race(
        race_number=race_data.get("race_number"),
        start_time=race_data.get("start_time_dt"),
        venue=race_data.get("venue"),
    )
    await repo.save_result(
        user_id=db_user.id,
        race_id=race.id,
        kart_number=participant["kart_number"],
        position=participant.get("position"),
        best_lap=participant.get("best_lap"),
        avg_lap=participant.get("avg_lap"),
        lap_times=participant.get("lap_times", []),
    )

    context.user_data.clear()
    await query.edit_message_text("✅ Результат сохранён!")
    await query.message.reply_text("Что дальше?", reply_markup=main_menu())
    return ConversationHandler.END
