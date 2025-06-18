import asyncio
import json
import os
from pathlib import Path
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, ConversationHandler, CallbackQueryHandler, filters
)

# Этапы диалога
HOST, ROOM, MAP, MODE = range(4)

# Карты и режимы
MAPS = ["The Skeld", "MIRA HQ", "Polus", "The Airship", "Fungle"]
MODES = ["Классика", "Прятки", "Много ролей", "Моды", "Баг"]

# Активные игры и путь к файлу
games = {}
GAMES_FILE = Path("games.json")

# Главное меню
MAIN_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("/newroom"), KeyboardButton("/list")],
     [KeyboardButton("/help"), KeyboardButton("/cancel")]],
    resize_keyboard=True
)

# Меню карт
MAPS_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton(m)] for m in MAPS] + [[KeyboardButton("Отмена")]],
    resize_keyboard=True, one_time_keyboard=True
)

# Меню режимов
MODES_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton(m)] for m in MODES] + [[KeyboardButton("Изменить карту"), KeyboardButton("Отмена")]],
    resize_keyboard=True, one_time_keyboard=True
)


def save_games():
    temp = {code: {k: v for k, v in g.items() if k != "task"} for code, g in games.items()}
    with open(GAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(temp, f, ensure_ascii=False, indent=2)


async def auto_delete_game(room_code):
    try:
        await asyncio.sleep(games[room_code]["duration"])
        if room_code in games:
            del games[room_code]
            save_games()
    except asyncio.CancelledError:
        pass


def load_games():
    if GAMES_FILE.exists():
        with open(GAMES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for code, g in data.items():
                g["task"] = asyncio.create_task(auto_delete_game(code))
                games[code] = g


# === Команды и шаги создания комнаты ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Добро пожаловать в бот Among Us!*\n\n"
        "*Команды:*\n"
        "/newroom — создать румму\n"
        "/list — показать активные комнаты\n"
        "/help — помощь\n"
        "/cancel — отменить действие",
        parse_mode="Markdown",
        reply_markup=MAIN_MENU
    )
    return ConversationHandler.END


async def get_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    for room_code, game in games.items():
        if game["user_id"] == user_id:
            await update.message.reply_text(
                f"У вас уже есть активная румма с кодом: *{room_code}*",
                parse_mode="Markdown"
            )
            return ConversationHandler.END
    await update.message.reply_text("Введите имя хоста:", reply_markup=ReplyKeyboardRemove())
    return HOST


async def input_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) > 25:
        await update.message.reply_text("Имя не должно превышать 25 символов. Введите заново:")
        return HOST
    context.user_data["host"] = text
    await update.message.reply_text("Введите код комнаты (6 заглавных букв):")
    return ROOM


async def input_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    if len(code) != 6 or not code.isalpha():
        await update.message.reply_text("Код должен состоять из 6 заглавных букв. Попробуйте снова:")
        return ROOM
    if code in games:
        await update.message.reply_text("Такая комната уже существует. Введите другой код:")
        return ROOM
    context.user_data["room"] = code
    await update.message.reply_text("Выберите карту:", reply_markup=MAPS_MENU)
    return MAP


async def input_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice == "Отмена":
        return await cancel(update, context)
    if choice not in MAPS:
        await update.message.reply_text("Выберите карту из списка:")
        return MAP
    context.user_data["map"] = choice
    await update.message.reply_text("Выберите режим:", reply_markup=MODES_MENU)
    return MODE


async def input_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice == "Отмена":
        return await cancel(update, context)
    if choice == "Изменить карту":
        await update.message.reply_text("Выберите карту:", reply_markup=MAPS_MENU)
        return MAP
    if choice not in MODES:
        await update.message.reply_text("Выберите режим из списка:")
        return MODE

    user_data = context.user_data
    room_code = user_data["room"]

    if (old_task := games.get(room_code, {}).get("task")):
        old_task.cancel()

    task = asyncio.create_task(auto_delete_game(room_code))
    games[room_code] = {
        "host": user_data["host"],
        "room": room_code,
        "map": user_data["map"],
        "mode": choice,
        "user_id": update.effective_user.id,
        "duration": 4 * 60 * 60,
        "task": task
    }
    save_games()

    msg = (
        f"🛸 *Новая игра Among Us:*\n"
        f"👤 Хост: *{user_data['host']}*\n"
        f"🗺 Карта: *{user_data['map']}*\n"
        f"🎮 Режим: *{choice}*\n\n"
        f"🔑 Код комнаты: *{room_code}*\n"
        f"⌛ Комната удалится через 4 часа."
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{room_code}"),
         InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{room_code}")],
        [InlineKeyboardButton("⏳ Продлить на 1 час", callback_data=f"extend:{room_code}")]
    ])

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    return ConversationHandler.END


# === Просмотр и редактирование ===

async def list_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not games:
        await update.message.reply_text("Активных комнат нет.")
        return

    text = "*Активные комнаты:*\n\n"
    buttons = []
    for code, g in games.items():
        text += f"👤 *{g['host']}* | 🗺 *{g['map']}* | 🎮 *{g['mode']}* | 🔑 `{code}`\n"
        buttons.append([InlineKeyboardButton(code, callback_data=f"copy_room:{code}")])

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("delete:"):
        code = data.split(":")[1]
        if code in games:
            if (task := games[code].get("task")):
                task.cancel()
            del games[code]
            save_games()
            await query.edit_message_text("Комната удалена.")

    elif data.startswith("extend:"):
        code = data.split(":")[1]
        if code in games:
            if (old_task := games[code].get("task")):
                old_task.cancel()
            games[code]["duration"] += 3600
            games[code]["task"] = asyncio.create_task(auto_delete_game(code))
            save_games()
            await query.message.reply_text(f"⏳ Время комнаты *{code}* продлено.", parse_mode="Markdown")

    elif data.startswith("copy_room:"):
        code = data.split(":")[1]
        if code in games:
            g = games[code]
            await query.message.reply_text(
                f"📋 *Копия комнаты:*\n"
                f"👤 Хост: *{g['host']}*\n"
                f"🗺 Карта: *{g['map']}*\n"
                f"🎮 Режим: *{g['mode']}*\n"
                f"🔑 Код: `{code}`",
                parse_mode="Markdown"
            )

    elif data.startswith("edit:"):
        code = data.split(":")[1]
        if code in games and games[code]["user_id"] == update.effective_user.id:
            context.user_data["edit_room"] = code
            await query.message.reply_text("Выберите новую карту:", reply_markup=MAPS_MENU)
            return MAP


async def edit_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = context.user_data.get("edit_room")
    if not code or code not in games:
        return await cancel(update, context)
    choice = update.message.text.strip()
    if choice not in MAPS:
        await update.message.reply_text("Выберите карту из списка.")
        return MAP
    context.user_data["new_map"] = choice
    await update.message.reply_text("Выберите новый режим:", reply_markup=MODES_MENU)
    return MODE


async def edit_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = context.user_data.get("edit_room")
    if not code or code not in games:
        return await cancel(update, context)
    mode = update.message.text.strip()
    if mode not in MODES:
        await update.message.reply_text("Выберите режим из списка.")
        return MODE

    games[code]["map"] = context.user_data["new_map"]
    games[code]["mode"] = mode
    save_games()

    await update.message.reply_text(
        f"Комната обновлена:\n🗺 Карта: {games[code]['map']}\n🎮 Режим: {games[code]['mode']}",
        reply_markup=MAIN_MENU
    )
    context.user_data.clear()
    return ConversationHandler.END


# === Прочее ===

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Действие отменено.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Команды:*\n"
        "/newroom — создать комнату\n"
        "/list — список активных\n"
        "/cancel — отменить\n"
        "/help — помощь",
        parse_mode="Markdown", reply_markup=MAIN_MENU
    )


# === Главная функция ===

def main():
    if not GAMES_FILE.exists():
        GAMES_FILE.write_text("{}", encoding="utf-8")
    load_games()

    token = os.getenv("BOT_TOKEN")
    if not token:
        print("❌ Переменная окружения BOT_TOKEN не установлена.")
        return

    app = ApplicationBuilder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("newroom", get_host)],
        states={
            HOST: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_host)],
            ROOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_room)],
            MAP: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_map)],
            MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_mode)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    edit_conv = ConversationHandler(
        entry_points=[],
        states={
            MAP: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_map)],
            MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_mode)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    app.add_handler(conv)
    app.add_handler(edit_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_games))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(handle_callback))

    app.run_polling()


if __name__ == "__main__":
    main()
