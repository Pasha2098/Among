# amongus_aiogram_bot.py

import asyncio
import json
import os
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, 
                           ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.utils.markdown import hbold
from dotenv import load_dotenv

load_dotenv()

# === Constants ===
MAPS = ["The Skeld", "MIRA HQ", "Polus", "The Airship", "Fungle"]
MODES = ["Классика", "Прятки", "Много ролей", "Моды", "Баг"]
GAMES_FILE = Path("games.json")
games = {}

# === FSM States ===
class RoomState(StatesGroup):
    host = State()
    room = State()
    map = State()
    mode = State()

# === Keyboards ===
main_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="/newroom"), KeyboardButton(text="/list")],
              [KeyboardButton(text="/help"), KeyboardButton(text="/cancel")]],
    resize_keyboard=True
)

maps_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=m)] for m in MAPS] + [[KeyboardButton(text="Отмена")]],
    resize_keyboard=True, one_time_keyboard=True
)

modes_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=m)] for m in MODES] + [[KeyboardButton(text="Изменить карту"), KeyboardButton(text="Отмена")]],
    resize_keyboard=True, one_time_keyboard=True
)

# === Utils ===
def save_games():
    temp = {code: {k: v for k, v in g.items() if k != "task"} for code, g in games.items()}
    with open(GAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(temp, f, ensure_ascii=False, indent=2)

def load_games():
    if GAMES_FILE.exists():
        with open(GAMES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for code, g in data.items():
                g["task"] = asyncio.create_task(auto_delete_game(code))
                games[code] = g

async def auto_delete_game(code: str):
    try:
        await asyncio.sleep(games[code]["duration"])
        if code in games:
            del games[code]
            save_games()
    except asyncio.CancelledError:
        pass

# === Handlers ===

async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать в бот Among Us!\n\n"
        "Команды:\n"
        "/newroom — создать румму\n"
        "/list — показать активные комнаты\n"
        "/help — помощь\n"
        "/cancel — отменить действие",
        reply_markup=main_menu
    )

async def cmd_help(message: types.Message):
    await message.answer("📖 Команды:\n/newroom — создать\n/list — список\n/cancel — отменить\n/help — помощь", reply_markup=main_menu)

async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_menu)

async def newroom(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    for code, g in games.items():
        if g["user_id"] == user_id:
            await message.answer(f"У вас уже есть активная румма с кодом: {hbold(code)}", parse_mode="HTML")
            return
    await state.set_state(RoomState.host)
    await message.answer("Введите имя хоста:", reply_markup=ReplyKeyboardRemove())

async def input_host(message: types.Message, state: FSMContext):
    if len(message.text) > 25:
        await message.answer("Имя не должно превышать 25 символов. Введите заново:")
        return
    await state.update_data(host=message.text)
    await state.set_state(RoomState.room)
    await message.answer("Введите код комнаты (6 заглавных букв):")

async def input_room(message: types.Message, state: FSMContext):
    code = message.text.upper()
    if len(code) != 6 or not code.isalpha():
        await message.answer("Код должен состоять из 6 заглавных букв. Попробуйте снова:")
        return
    if code in games:
        await message.answer("Такая комната уже существует. Введите другой код:")
        return
    await state.update_data(room=code)
    await state.set_state(RoomState.map)
    await message.answer("Выберите карту:", reply_markup=maps_menu)

async def input_map(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        return await cmd_cancel(message, state)
    if message.text not in MAPS:
        await message.answer("Выберите карту из списка:")
        return
    await state.update_data(map=message.text)
    await state.set_state(RoomState.mode)
    await message.answer("Выберите режим:", reply_markup=modes_menu)

async def input_mode(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        return await cmd_cancel(message, state)
    if message.text == "Изменить карту":
        await state.set_state(RoomState.map)
        await message.answer("Выберите карту:", reply_markup=maps_menu)
        return
    if message.text not in MODES:
        await message.answer("Выберите режим из списка:")
        return

    data = await state.get_data()
    room_code = data["room"]
    if (old_task := games.get(room_code, {}).get("task")):
        old_task.cancel()
    task = asyncio.create_task(auto_delete_game(room_code))

    games[room_code] = {
        "host": data["host"],
        "room": room_code,
        "map": data["map"],
        "mode": message.text,
        "user_id": message.from_user.id,
        "duration": 4 * 60 * 60,
        "task": task
    }
    save_games()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{room_code}"),
         InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:{room_code}")],
        [InlineKeyboardButton(text="⏳ Продлить на 1 час", callback_data=f"extend:{room_code}")]
    ])

    await message.answer(
        f"🛸 <b>Новая игра Among Us:</b>\n"
        f"👤 Хост: <b>{data['host']}</b>\n"
        f"🗺 Карта: <b>{data['map']}</b>\n"
        f"🎮 Режим: <b>{message.text}</b>\n\n"
        f"🔑 Код комнаты: <b>{room_code}</b>\n"
        f"⌛ Комната удалится через 4 часа.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.clear()

async def list_rooms(message: types.Message):
    if not games:
        await message.answer("Активных комнат нет.")
        return

    text = "<b>Активные комнаты:</b>\n\n"
    buttons = []
    for code, g in games.items():
        text += f"👤 <b>{g['host']}</b> | 🗺 <b>{g['map']}</b> | 🎮 <b>{g['mode']}</b> | 🔑 <code>{code}</code>\n"
        buttons.append([InlineKeyboardButton(text=code, callback_data=f"copy:{code}")])

    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

async def handle_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = callback.data

    if data.startswith("delete:"):
        code = data.split(":")[1]
        if code in games:
            if (task := games[code].get("task")):
                task.cancel()
            del games[code]
            save_games()
            await callback.message.edit_text("Комната удалена.")

    elif data.startswith("extend:"):
        code = data.split(":")[1]
        if code in games:
            games[code]["duration"] += 3600
            if (task := games[code].get("task")):
                task.cancel()
            games[code]["task"] = asyncio.create_task(auto_delete_game(code))
            save_games()
            await callback.message.answer(f"⏳ Время комнаты <b>{code}</b> продлено.", parse_mode="HTML")

    elif data.startswith("copy:"):
        code = data.split(":")[1]
        if code in games:
            g = games[code]
            await callback.message.answer(
                f"📋 <b>Копия комнаты:</b>\n"
                f"👤 Хост: <b>{g['host']}</b>\n"
                f"🗺 Карта: <b>{g['map']}</b>\n"
                f"🎮 Режим: <b>{g['mode']}</b>\n"
                f"🔑 Код: <code>{code}</code>",
                parse_mode="HTML"
            )

# === Entry point ===

async def main():
    load_games()
    bot = Bot(token=os.getenv("BOT_TOKEN"), parse_mode="HTML")
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.register(cmd_start, F.text == "/start")
    dp.message.register(cmd_help, F.text == "/help")
    dp.message.register(cmd_cancel, F.text == "/cancel")
    dp.message.register(newroom, F.text == "/newroom")
    dp.message.register(list_rooms, F.text == "/list")

    dp.message.register(input_host, RoomState.host)
    dp.message.register(input_room, RoomState.room)
    dp.message.register(input_map, RoomState.map)
    dp.message.register(input_mode, RoomState.mode)

    dp.callback_query.register(handle_callback)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
