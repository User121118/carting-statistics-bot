import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from bot.handlers import (
    cmd_cancel,
    cmd_start,
    handle_confirmation,
    handle_edit_input,
    handle_kart_selection,
    handle_photo,
    my_best_result,
    my_last_race,
)
from bot.states import CONFIRM_RESULT, EDIT_LAP, SELECT_KART
from db.repository import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MENU_LAST = filters.Regex("^🏁 Мой последний заезд$")
MENU_BEST = filters.Regex("^🏆 Мой лучший результат$")


async def post_init(app: Application) -> None:
    logger.info("Initialising database...")
    await init_db()
    logger.info("Database ready.")


def main() -> None:
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.PHOTO, handle_photo),
            MessageHandler(MENU_LAST, my_last_race),
            MessageHandler(MENU_BEST, my_best_result),
        ],
        states={
            SELECT_KART: [
                CallbackQueryHandler(handle_kart_selection, pattern=r"^kart:"),
            ],
            CONFIRM_RESULT: [
                CallbackQueryHandler(handle_confirmation, pattern=r"^confirm:"),
            ],
            EDIT_LAP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_input),
            ],
        },
        fallbacks=[
            MessageHandler(MENU_LAST, my_last_race),
            MessageHandler(MENU_BEST, my_best_result),
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(conv)

    logger.info("Bot is running...")
    # run_polling manages its own event loop — do NOT wrap in asyncio.run()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
