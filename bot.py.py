import asyncio
import os
import json
import random
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)

TOKEN = "8315587231:AAGTj-K7CTz8TpfV-BJyDX4qwUFUGve6YoY"

bot = Bot(token=TOKEN)
dp = Dispatcher()

user_data = {}

conn = sqlite3.connect("quiz_bot.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    questions TEXT,
    time_limit INTEGER,
    created_at TEXT
)
""")

conn.commit()


def parse_tests(text):
    tests = []
    blocks = text.split("++++")

    for block in blocks:
        block = block.strip()

        if not block:
            continue

        lines = [line.strip() for line in block.splitlines() if line.strip()]

        question = ""
        options = []
        correct_index = None

        for line in lines:
            if line.replace(" ", "") in ["====", "==="]:
                continue

            if not question:
                question = line
                continue

            if line.startswith("#"):
                option = line.replace("#", "").strip()
                correct_index = len(options)
                options.append(option)
            else:
                options.append(line)

        if question and len(options) >= 2 and correct_index is not None:
            tests.append({
                "question": question,
                "options": options,
                "answer": correct_index
            })

    return tests


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📄 Test yaratish")],
            [KeyboardButton(text="📚 Testlarim")]
        ],
        resize_keyboard=True
    )


def time_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="20 soniya", callback_data="time:20")],
            [InlineKeyboardButton(text="30 soniya", callback_data="time:30")],
            [InlineKeyboardButton(text="1 daqiqa", callback_data="time:60")]
        ]
    )


def make_quiz_keyboard(q_index, questions):
    keyboard = []

    for i in range(len(questions[q_index]["options"])):
        keyboard.append([
            InlineKeyboardButton(
                text=chr(65 + i),
                callback_data=f"answer:{q_index}:{i}"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def format_question(q_index, questions, time_limit):
    q = questions[q_index]

    text = f"❓ Savol {q_index + 1}/{len(questions)}\n"
    text += f"⏱ Vaqt: {time_limit} soniya\n\n"
    text += q["question"] + "\n\n"

    for i, option in enumerate(q["options"]):
        text += f"{chr(65+i)}) {option}\n"

    return text


@dp.message(Command("start"))
async def start(message: types.Message):
    args = message.text.split()

    if len(args) > 1 and args[1].startswith("test_"):
        test_id = int(args[1].replace("test_", ""))
        await start_test(message.from_user.id, message, test_id)
        return

    await message.answer(
        "👋 Salom!\n\n"
        "Bu bot Word yoki TXT fayldan test yaratadi.\n\n"
        "📌 Shablon:\n\n"
        "Savol matni\n"
        "====\n"
        "# To'g'ri javob\n"
        "====\n"
        "Noto'g'ri javob\n"
        "====\n"
        "Noto'g'ri javob\n"
        "++++\n\n"
        "Testni to‘xtatish uchun: /stop",
        reply_markup=main_menu()
    )


@dp.message(Command("stop"))
async def stop_test(message: types.Message):
    user_id = message.from_user.id

    if user_id not in user_data or user_data[user_id].get("mode") != "playing":
        await message.answer("Hozir faol test yo‘q.")
        return

    data = user_data[user_id]
    score = data["score"]
    current = data["current"]
    total = len(data["questions"])

    await message.answer(
        f"⛔ Test to‘xtatildi!\n\n"
        f"📊 Natija: {score}/{total}\n"
        f"✅ Ishlangan savollar: {current}/{total}"
    )

    del user_data[user_id]


@dp.message(lambda message: message.text == "📄 Test yaratish")
async def create_test(message: types.Message):
    user_data[message.from_user.id] = {
        "mode": "waiting_file"
    }

    await message.answer("📄 Word yoki TXT test fayl yuboring.")


@dp.message(lambda message: message.document)
async def handle_file(message: types.Message):
    user_id = message.from_user.id
    file_name = message.document.file_name.lower()

    if not (file_name.endswith(".docx") or file_name.endswith(".txt")):
        await message.answer("❌ Faqat .docx yoki .txt fayl yuboring.")
        return

    file = await bot.get_file(message.document.file_id)

    os.makedirs("files", exist_ok=True)
    path = f"files/{message.document.file_name}"

    await bot.download_file(file.file_path, path)

    if file_name.endswith(".txt"):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        import docx
        doc = docx.Document(path)
        text = "\n".join([p.text for p in doc.paragraphs])

    questions = parse_tests(text)

    if not questions:
        await message.answer("❌ Test topilmadi. Fayl shablonini tekshiring.")
        return

    user_data[user_id] = {
        "mode": "waiting_name",
        "questions": questions
    }

    await message.answer(
        f"✅ {len(questions)} ta test topildi!\n\n"
        f"Endi testga nom bering.\n\n"
        f"Masalan: Bank ishi yakuniy"
    )


@dp.message(lambda message: user_data.get(message.from_user.id, {}).get("mode") == "waiting_name")
async def get_test_name(message: types.Message):
    user_id = message.from_user.id

    user_data[user_id]["name"] = message.text
    user_data[user_id]["mode"] = "waiting_time"

    await message.answer(
        "⏱ Har bir savol uchun vaqt tanlang:",
        reply_markup=time_keyboard()
    )


@dp.callback_query(lambda c: c.data.startswith("time:"))
async def set_time(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if user_id not in user_data:
        await callback.message.answer("Avval test fayl yuboring.")
        return

    time_limit = int(callback.data.split(":")[1])

    name = user_data[user_id]["name"]
    questions = user_data[user_id]["questions"]

    cursor.execute(
        """
        INSERT INTO tests (user_id, name, questions, time_limit, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            name,
            json.dumps(questions, ensure_ascii=False),
            time_limit,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        )
    )

    conn.commit()
    test_id = cursor.lastrowid

    del user_data[user_id]

    bot_info = await bot.get_me()

    await callback.message.answer(
        f"✅ Test saqlandi!\n\n"
        f"📚 Nomi: {name}\n"
        f"❓ Savollar: {len(questions)} ta\n"
        f"⏱ Vaqt: {time_limit} soniya\n\n"
        f"🔗 Havola:\n"
        f"https://t.me/{bot_info.username}?start=test_{test_id}",
        reply_markup=main_menu()
    )

    await callback.answer()


@dp.message(lambda message: message.text == "📚 Testlarim")
async def my_tests(message: types.Message):
    user_id = message.from_user.id

    cursor.execute(
        "SELECT id, name, time_limit, created_at FROM tests WHERE user_id=? ORDER BY id DESC",
        (user_id,)
    )

    rows = cursor.fetchall()

    if not rows:
        await message.answer("📭 Sizda hali saqlangan test yo‘q.")
        return

    keyboard = []

    for row in rows:
        test_id, name, time_limit, created_at = row

        keyboard.append([
            InlineKeyboardButton(
                text=f"{name} | {time_limit}s",
                callback_data=f"open_test:{test_id}"
            )
        ])

    await message.answer(
        "📚 Testlaringiz:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@dp.callback_query(lambda c: c.data.startswith("open_test:"))
async def open_test(callback: types.CallbackQuery):
    test_id = int(callback.data.split(":")[1])

    cursor.execute(
        "SELECT name, questions, time_limit FROM tests WHERE id=?",
        (test_id,)
    )

    row = cursor.fetchone()

    if not row:
        await callback.message.answer("❌ Test topilmadi.")
        return

    name, questions_json, time_limit = row
    questions = json.loads(questions_json)

    bot_info = await bot.get_me()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Testni boshlash", callback_data=f"start_test:{test_id}")]
        ]
    )

    await callback.message.answer(
        f"📚 {name}\n\n"
        f"❓ Savollar: {len(questions)} ta\n"
        f"⏱ Har savolga: {time_limit} soniya\n\n"
        f"🔗 Havola:\n"
        f"https://t.me/{bot_info.username}?start=test_{test_id}",
        reply_markup=keyboard
    )

    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("start_test:"))
async def start_saved_test(callback: types.CallbackQuery):
    test_id = int(callback.data.split(":")[1])

    await start_test(callback.from_user.id, callback.message, test_id)
    await callback.answer()


async def start_test(user_id, message, test_id):
    cursor.execute(
        "SELECT name, questions, time_limit FROM tests WHERE id=?",
        (test_id,)
    )

    row = cursor.fetchone()

    if not row:
        await message.answer("❌ Test topilmadi.")
        return

    name, questions_json, time_limit = row
    questions = json.loads(questions_json)

    random.shuffle(questions)

    user_data[user_id] = {
        "mode": "playing",
        "test_id": test_id,
        "questions": questions,
        "score": 0,
        "current": 0,
        "time_limit": time_limit,
        "answered": False
    }

    await message.answer(
        f"🚀 Test boshlandi: {name}\n\n"
        f"To‘xtatish uchun: /stop"
    )

    await send_question(user_id, message)


async def send_question(user_id, message):
    data = user_data[user_id]

    q_index = data["current"]
    questions = data["questions"]
    time_limit = data["time_limit"]

    data["answered"] = False

    sent = await message.answer(
        format_question(q_index, questions, time_limit),
        reply_markup=make_quiz_keyboard(q_index, questions)
    )

    data["message_id"] = sent.message_id

    asyncio.create_task(
        question_timer(user_id, sent.chat.id, q_index, time_limit)
    )


async def question_timer(user_id, chat_id, q_index, time_limit):
    await asyncio.sleep(time_limit)

    if user_id not in user_data:
        return

    data = user_data[user_id]

    if data.get("mode") != "playing":
        return

    if data.get("current") != q_index:
        return

    if data.get("answered"):
        return

    data["answered"] = True

    questions = data["questions"]
    correct = questions[q_index]["answer"]
    correct_text = questions[q_index]["options"][correct]

    await bot.send_message(
        chat_id,
        f"⏰ Vaqt tugadi!\n\n"
        f"✅ To‘g‘ri javob:\n"
        f"{chr(65+correct)}) {correct_text}"
    )

    await next_question(user_id, chat_id)


@dp.callback_query(lambda c: c.data.startswith("answer:"))
async def answer(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if user_id not in user_data:
        await callback.answer("Test boshlanmagan.")
        return

    data = user_data[user_id]

    if data.get("mode") != "playing":
        await callback.answer("Hozir test ishlamayapti.")
        return

    if data.get("answered"):
        await callback.answer("Bu savolga javob berilgan.")
        return

    _, q_index, selected = callback.data.split(":")

    q_index = int(q_index)
    selected = int(selected)

    if q_index != data["current"]:
        await callback.answer("Bu eski savol.")
        return

    data["answered"] = True

    questions = data["questions"]
    correct = questions[q_index]["answer"]
    correct_text = questions[q_index]["options"][correct]

    if selected == correct:
        data["score"] += 1
        await callback.message.answer(
            f"✅ To‘g‘ri javob!\n\n"
            f"To‘g‘ri variant:\n"
            f"{chr(65+correct)}) {correct_text}"
        )
    else:
        await callback.message.answer(
            f"❌ Xato!\n\n"
            f"✅ To‘g‘ri javob:\n"
            f"{chr(65+correct)}) {correct_text}"
        )

    await next_question(user_id, callback.message.chat.id)
    await callback.answer()


async def next_question(user_id, chat_id):
    if user_id not in user_data:
        return

    data = user_data[user_id]
    data["current"] += 1

    if data["current"] < len(data["questions"]):
        await bot.send_message(chat_id, "➡️ Keyingi savol")

        class FakeMessage:
            async def answer(self, text, reply_markup=None):
                return await bot.send_message(
                    chat_id,
                    text,
                    reply_markup=reply_markup
                )

        await send_question(user_id, FakeMessage())

    else:
        score = data["score"]
        total = len(data["questions"])
        percent = round(score / total * 100)

        await bot.send_message(
            chat_id,
            f"🏁 Test tugadi!\n\n"
            f"📊 Natija: {score}/{total}\n"
            f"📈 Foiz: {percent}%"
        )

        del user_data[user_id]


async def main():
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
