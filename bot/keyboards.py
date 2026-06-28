from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["🏁 Мой последний заезд"],
            ["🏆 Мой лучший результат"],
            ["🥇 Топ 5 месяца"],
            ["👤 Моё имя"],
        ],
        resize_keyboard=True,
    )


def kart_numbers(numbers: list[str]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(n, callback_data=f"kart:{n}")] for n in numbers]
    return InlineKeyboardMarkup(buttons)


def confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Сохранить", callback_data="confirm:yes"),
                InlineKeyboardButton("❌ Отмена", callback_data="confirm:no"),
            ],
            [
                InlineKeyboardButton("✏️ Редактировать круг", callback_data="confirm:edit"),
            ],
        ]
    )
