import asyncio
import os
import json
import random
import sqlite3
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from dotenv import load_dotenv

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ─── Token ─────────────────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN .env faylda topilmadi!")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ─── Xotira ────────────────────────────────────────────────────────────────────
user_data = {}        # Shaxsiy chat holatlari
group_data = {}       # Guruh holatlari  {chat_id: {...}}

# ─── Database ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect("quiz_bot.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn, conn.cursor()

def init_db():
    conn, cursor = get_db()
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
    conn.close()

init_db()

# ─── Test parsing ──────────────────────────────────────────────────────────────
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

# ─── Klaviaturalar ─────────────────────────────────────────────────────────────
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
            [InlineKeyboardButton(text="1 daqiqa",  callback_data="time:60")]
        ]
    )

def make_quiz_keyboard(q_index, questions, prefix="answer"):
    keyboard = []
    for i in range(len(questions[q_index]["options"])):
        keyboard.append([
            InlineKeyboardButton(
                text=chr(65 + i),
                callback_data=f"{prefix}:{q_index}:{i}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def format_question(q_index, questions, time_limit):
    q = questions[q_index]
    text  = f"❓ Savol {q_index + 1}/{len(questions)}\n"
    text += f"⏱ Vaqt: {time_limit} soniya\n\n"
    text += q["question"] + "\n\n"
    for i, option in enumerate(q["options"]):
        text += f"{chr(65+i)}) {option}\n"
    return text

# ═══════════════════════════════════════════════════════════════════════════════
# SHAXSIY CHAT HANDLERLARI
# ═══════════════════════════════════════════════════════════════════════════════

@dp.message(Command("start"))
async def start(message: types.Message):
    # Guruhda /start ni e'tiborsiz qoldirish
    if message.chat.type in ("group", "supergroup"):
        return

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("test_"):
        try:
            test_id = int(args[1].replace("test_", ""))
            await start_private_test(message.from_user.id, message, test_id)
        except Exception as e:
            logger.error(f"start_test xatosi: {e}")
            await message.answer("❌ Test topilmadi yoki xato havola.")
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
        "Testni to'xtatish uchun: /stop",
        reply_markup=main_menu()
    )

@dp.message(Command("stop"))
async def stop_test(message: types.Message):
    # Guruhda stop bo'lsa — guruh testi to'xtatiladi
    if message.chat.type in ("group", "supergroup"):
        await stop_group_test(message)
        return

    user_id = message.from_user.id
    if user_id not in user_data or user_data[user_id].get("mode") != "playing":
        await message.answer("Hozir faol test yo'q.")
        return

    data  = user_data[user_id]
    score = data["score"]
    total = len(data["questions"])
    current = data["current"]

    await message.answer(
        f"⛔ Test to'xtatildi!\n\n"
        f"📊 Natija: {score}/{total}\n"
        f"✅ Ishlangan savollar: {current}/{total}"
    )
    del user_data[user_id]

@dp.message(F.text == "📄 Test yaratish")
async def create_test(message: types.Message):
    if message.chat.type in ("group", "supergroup"):
        return
    user_data[message.from_user.id] = {"mode": "waiting_file"}
    await message.answer("📄 Word yoki TXT test fayl yuboring.")

@dp.message(F.document)
async def handle_file(message: types.Message):
    if message.chat.type in ("group", "supergroup"):
        return

    user_id   = message.from_user.id
    file_name = message.document.file_name.lower()

    if not (file_name.endswith(".docx") or file_name.endswith(".txt")):
        await message.answer("❌ Faqat .docx yoki .txt fayl yuboring.")
        return

    try:
        file = await bot.get_file(message.document.file_id)
        os.makedirs("files", exist_ok=True)
        path = f"files/{message.document.file_name}"
        await bot.download_file(file.file_path, path)

        if file_name.endswith(".txt"):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            import docx as docxlib
            doc  = docxlib.Document(path)
            text = "\n".join([p.text for p in doc.paragraphs])

        # Faylni o'chirish
        os.remove(path)

        questions = parse_tests(text)

        if not questions:
            await message.answer("❌ Test topilmadi. Fayl shablonini tekshiring.")
            return

        user_data[user_id] = {
            "mode":      "waiting_name",
            "questions": questions
        }

        await message.answer(
            f"✅ {len(questions)} ta test topildi!\n\n"
            f"Endi testga nom bering.\n\nMasalan: Matematika yakuniy"
        )

    except Exception as e:
        logger.error(f"Fayl o'qishda xato: {e}")
        await message.answer("❌ Faylni o'qishda xato yuz berdi. Qayta urinib ko'ring.")

@dp.message(lambda m: user_data.get(m.from_user.id, {}).get("mode") == "waiting_name")
async def get_test_name(message: types.Message):
    if message.chat.type in ("group", "supergroup"):
        return
    user_id = message.from_user.id
    user_data[user_id]["name"] = message.text
    user_data[user_id]["mode"] = "waiting_time"
    await message.answer("⏱ Har bir savol uchun vaqt tanlang:", reply_markup=time_keyboard())

@dp.callback_query(lambda c: c.data.startswith("time:"))
async def set_time(callback: types.CallbackQuery):
    user_id    = callback.from_user.id
    time_limit = int(callback.data.split(":")[1])

    if user_id not in user_data or user_data[user_id].get("mode") != "waiting_time":
        await callback.answer("Avval test fayl yuboring.")
        return

    name      = user_data[user_id]["name"]
    questions = user_data[user_id]["questions"]

    try:
        conn, cursor = get_db()
        cursor.execute(
            "INSERT INTO tests (user_id, name, questions, time_limit, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, name, json.dumps(questions, ensure_ascii=False),
             time_limit, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        conn.commit()
        test_id = cursor.lastrowid
        conn.close()
    except Exception as e:
        logger.error(f"DB saqlashda xato: {e}")
        await callback.message.answer("❌ Testni saqlashda xato yuz berdi.")
        return

    del user_data[user_id]

    bot_info = await bot.get_me()
    await callback.message.answer(
        f"✅ Test saqlandi!\n\n"
        f"📚 Nomi: {name}\n"
        f"❓ Savollar: {len(questions)} ta\n"
        f"⏱ Vaqt: {time_limit} soniya\n\n"
        f"🔗 Shaxsiy test havolasi:\n"
        f"https://t.me/{bot_info.username}?start=test_{test_id}",
        reply_markup=main_menu()
    )
    await callback.answer()

@dp.message(F.text == "📚 Testlarim")
async def my_tests(message: types.Message):
    if message.chat.type in ("group", "supergroup"):
        return
    user_id = message.from_user.id

    try:
        conn, cursor = get_db()
        cursor.execute(
            "SELECT id, name, time_limit, created_at FROM tests WHERE user_id=? ORDER BY id DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"Testlarni olishda xato: {e}")
        await message.answer("❌ Xato yuz berdi.")
        return

    if not rows:
        await message.answer("📭 Sizda hali saqlangan test yo'q.")
        return

    keyboard = []
    for row in rows:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{row['name']} | {row['time_limit']}s",
                callback_data=f"open_test:{row['id']}"
            )
        ])

    await message.answer("📚 Testlaringiz:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(lambda c: c.data.startswith("open_test:"))
async def open_test(callback: types.CallbackQuery):
    test_id = int(callback.data.split(":")[1])

    try:
        conn, cursor = get_db()
        cursor.execute("SELECT name, questions, time_limit FROM tests WHERE id=?", (test_id,))
        row = cursor.fetchone()
        conn.close()
    except Exception as e:
        logger.error(f"Test ochishda xato: {e}")
        await callback.message.answer("❌ Xato yuz berdi.")
        return

    if not row:
        await callback.message.answer("❌ Test topilmadi.")
        return

    questions  = json.loads(row["questions"])
    bot_info   = await bot.get_me()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Testni boshlash", callback_data=f"start_test:{test_id}")]
    ])

    await callback.message.answer(
        f"📚 {row['name']}\n\n"
        f"❓ Savollar: {len(questions)} ta\n"
        f"⏱ Har savolga: {row['time_limit']} soniya\n\n"
        f"🔗 Havola:\n"
        f"https://t.me/{bot_info.username}?start=test_{test_id}",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("start_test:"))
async def start_saved_test(callback: types.CallbackQuery):
    test_id = int(callback.data.split(":")[1])
    await start_private_test(callback.from_user.id, callback.message, test_id)
    await callback.answer()

# ─── Shaxsiy test o'ynash ──────────────────────────────────────────────────────
async def start_private_test(user_id, message, test_id):
    try:
        conn, cursor = get_db()
        cursor.execute("SELECT name, questions, time_limit FROM tests WHERE id=?", (test_id,))
        row = cursor.fetchone()
        conn.close()
    except Exception as e:
        logger.error(f"start_private_test DB xatosi: {e}")
        await message.answer("❌ Test topilmadi.")
        return

    if not row:
        await message.answer("❌ Test topilmadi.")
        return

    questions = json.loads(row["questions"])
    random.shuffle(questions)

    user_data[user_id] = {
        "mode":       "playing",
        "test_id":    test_id,
        "questions":  questions,
        "score":      0,
        "current":    0,
        "time_limit": row["time_limit"],
        "answered":   False
    }

    await message.answer(f"🚀 Test boshlandi: {row['name']}\n\nTo'xtatish uchun: /stop")
    await send_private_question(user_id, message)

async def send_private_question(user_id, message):
    data       = user_data[user_id]
    q_index    = data["current"]
    questions  = data["questions"]
    time_limit = data["time_limit"]

    data["answered"] = False

    sent = await message.answer(
        format_question(q_index, questions, time_limit),
        reply_markup=make_quiz_keyboard(q_index, questions, prefix="answer")
    )
    data["message_id"] = sent.message_id
    asyncio.create_task(private_question_timer(user_id, sent.chat.id, q_index, time_limit))

async def private_question_timer(user_id, chat_id, q_index, time_limit):
    await asyncio.sleep(time_limit)
    if user_id not in user_data:
        return
    data = user_data[user_id]
    if data.get("mode") != "playing" or data.get("current") != q_index or data.get("answered"):
        return

    data["answered"] = True
    questions = data["questions"]
    correct   = questions[q_index]["answer"]
    correct_text = questions[q_index]["options"][correct]

    await bot.send_message(
        chat_id,
        f"⏰ Vaqt tugadi!\n\n✅ To'g'ri javob:\n{chr(65+correct)}) {correct_text}"
    )
    await private_next_question(user_id, chat_id)

@dp.callback_query(lambda c: c.data.startswith("answer:"))
async def private_answer(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_data or user_data[user_id].get("mode") != "playing":
        await callback.answer("Test boshlanmagan.")
        return

    data = user_data[user_id]
    if data.get("answered"):
        await callback.answer("Bu savolga javob berilgan.")
        return

    _, q_index, selected = callback.data.split(":")
    q_index  = int(q_index)
    selected = int(selected)

    if q_index != data["current"]:
        await callback.answer("Bu eski savol.")
        return

    data["answered"] = True
    questions    = data["questions"]
    correct      = questions[q_index]["answer"]
    correct_text = questions[q_index]["options"][correct]

    if selected == correct:
        data["score"] += 1
        await callback.message.answer(
            f"✅ To'g'ri!\n\n✅ To'g'ri javob:\n{chr(65+correct)}) {correct_text}"
        )
    else:
        await callback.message.answer(
            f"❌ Xato!\n\n✅ To'g'ri javob:\n{chr(65+correct)}) {correct_text}"
        )

    await private_next_question(user_id, callback.message.chat.id)
    await callback.answer()

async def private_next_question(user_id, chat_id):
    if user_id not in user_data:
        return
    data = user_data[user_id]
    data["current"] += 1

    if data["current"] < len(data["questions"]):
        await bot.send_message(chat_id, "➡️ Keyingi savol")

        class FakeMessage:
            async def answer(self, text, reply_markup=None):
                return await bot.send_message(chat_id, text, reply_markup=reply_markup)

        await send_private_question(user_id, FakeMessage())
    else:
        score   = data["score"]
        total   = len(data["questions"])
        percent = round(score / total * 100)
        await bot.send_message(
            chat_id,
            f"🏁 Test tugadi!\n\n📊 Natija: {score}/{total}\n📈 Foiz: {percent}%"
        )
        del user_data[user_id]

# ═══════════════════════════════════════════════════════════════════════════════
# GURUH HANDLERLARI
# ═══════════════════════════════════════════════════════════════════════════════

@dp.message(Command("test"))
async def group_test_command(message: types.Message):
    """Guruhda /test <id> buyrug'i bilan test boshlash"""
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Bu buyruq faqat guruhda ishlaydi.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ Test ID kiriting.\n\nMisol: /test 5\n\n"
            "Test ID ni botga shaxsiy yozib, '📚 Testlarim' dan topasiz."
        )
        return

    try:
        test_id = int(args[1])
    except ValueError:
        await message.answer("❌ Test ID raqam bo'lishi kerak. Masalan: /test 5")
        return

    await begin_group_test(message, test_id)

@dp.message(lambda m: m.chat.type in ("group", "supergroup") and
            m.text and m.text.startswith("/start") and "test_" in m.text)
async def group_start_with_link(message: types.Message):
    """Guruhda /start test_ID havola orqali test boshlash"""
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("test_"):
        try:
            test_id = int(args[1].replace("test_", ""))
            await begin_group_test(message, test_id)
        except Exception:
            await message.answer("❌ Xato havola.")

async def begin_group_test(message: types.Message, test_id: int):
    """Guruhda test boshlash"""
    chat_id = message.chat.id

    # Allaqachon test bormi?
    if chat_id in group_data and group_data[chat_id].get("active"):
        await message.answer(
            "⚠️ Guruhda hozir test davom etmoqda!\n"
            "Avvalgi test tugaguncha yangi test boshlab bo'lmaydi.\n\n"
            "To'xtatish uchun: /stoptест"
        )
        return

    try:
        conn, cursor = get_db()
        cursor.execute("SELECT name, questions, time_limit FROM tests WHERE id=?", (test_id,))
        row = cursor.fetchone()
        conn.close()
    except Exception as e:
        logger.error(f"begin_group_test DB xatosi: {e}")
        await message.answer("❌ Xato yuz berdi.")
        return

    if not row:
        await message.answer("❌ Test topilmadi. Test ID ni tekshiring.")
        return

    questions = json.loads(row["questions"])
    random.shuffle(questions)

    group_data[chat_id] = {
        "active":     True,
        "test_id":    test_id,
        "name":       row["name"],
        "questions":  questions,
        "current":    0,
        "time_limit": row["time_limit"],
        "answered":   False,
        "scores":     {},   # {user_id: {"name": "...", "score": N}}
        "participants": set()
    }

    await message.answer(
        f"🚀 Guruh testi boshlandi!\n\n"
        f"📚 Test: {row['name']}\n"
        f"❓ Savollar: {len(questions)} ta\n"
        f"⏱ Har savolga: {row['time_limit']} soniya\n\n"
        f"Barcha qatnashuvchilar quyidagi tugmalarni bosing! 👇\n"
        f"To'xtatish: /stoptest"
    )

    await send_group_question(chat_id)

async def send_group_question(chat_id: int):
    if chat_id not in group_data:
        return

    data       = group_data[chat_id]
    q_index    = data["current"]
    questions  = data["questions"]
    time_limit = data["time_limit"]

    data["answered"] = False

    sent = await bot.send_message(
        chat_id,
        format_question(q_index, questions, time_limit),
        reply_markup=make_quiz_keyboard(q_index, questions, prefix="ganswer")
    )
    data["message_id"] = sent.message_id

    asyncio.create_task(group_question_timer(chat_id, q_index, time_limit))

async def group_question_timer(chat_id: int, q_index: int, time_limit: int):
    await asyncio.sleep(time_limit)

    if chat_id not in group_data:
        return
    data = group_data[chat_id]

    if not data.get("active"):
        return
    if data.get("current") != q_index:
        return
    if data.get("answered"):
        return

    data["answered"] = True
    questions    = data["questions"]
    correct      = questions[q_index]["answer"]
    correct_text = questions[q_index]["options"][correct]

    await bot.send_message(
        chat_id,
        f"⏰ Vaqt tugadi!\n\n✅ To'g'ri javob: {chr(65+correct)}) {correct_text}"
    )
    await group_next_question(chat_id)

@dp.callback_query(lambda c: c.data.startswith("ganswer:"))
async def group_answer(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    if chat_id not in group_data or not group_data[chat_id].get("active"):
        await callback.answer("Test tugagan.")
        return

    data = group_data[chat_id]

    # Har bir savol uchun faqat 1 marta javob berish
    answered_key = f"answered_{data['current']}"
    if user_id in data.get(answered_key, set()):
        await callback.answer("Bu savolga allaqachon javob berdingiz!", show_alert=False)
        return

    _, q_index, selected = callback.data.split(":")
    q_index  = int(q_index)
    selected = int(selected)

    if q_index != data["current"]:
        await callback.answer("Bu eski savol.")
        return

    # Foydalanuvchini ro'yxatga qo'shish
    if answered_key not in data:
        data[answered_key] = set()
    data[answered_key].add(user_id)
    data["participants"].add(user_id)

    # Ismni olish
    user_name = callback.from_user.first_name or f"User{user_id}"
    if callback.from_user.last_name:
        user_name += f" {callback.from_user.last_name}"

    if user_id not in data["scores"]:
        data["scores"][user_id] = {"name": user_name, "score": 0}

    questions    = data["questions"]
    correct      = questions[q_index]["answer"]

    if selected == correct:
        data["scores"][user_id]["score"] += 1
        await callback.answer("✅ To'g'ri!", show_alert=False)
    else:
        correct_text = questions[q_index]["options"][correct]
        await callback.answer(f"❌ Xato! To'g'ri: {chr(65+correct)}) {correct_text}", show_alert=True)

async def group_next_question(chat_id: int):
    if chat_id not in group_data:
        return

    data = group_data[chat_id]
    data["current"] += 1

    if data["current"] < len(data["questions"]):
        await bot.send_message(chat_id, "➡️ Keyingi savol...")
        await send_group_question(chat_id)
    else:
        await finish_group_test(chat_id)

async def finish_group_test(chat_id: int):
    if chat_id not in group_data:
        return

    data   = group_data[chat_id]
    scores = data["scores"]
    total  = len(data["questions"])

    if not scores:
        await bot.send_message(chat_id, "🏁 Test tugadi!\n\n😔 Hech kim qatnashmadi.")
        del group_data[chat_id]
        return

    # Reytingni tartiblash
    sorted_scores = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)

    medals = ["🥇", "🥈", "🥉"]
    text   = f"🏁 Test tugadi! — {data['name']}\n\n"
    text  += f"📊 Natijalar ({len(sorted_scores)} ishtirokchi):\n\n"

    for i, (uid, info) in enumerate(sorted_scores):
        medal   = medals[i] if i < 3 else f"{i+1}."
        percent = round(info["score"] / total * 100)
        text   += f"{medal} {info['name']} — {info['score']}/{total} ({percent}%)\n"

    await bot.send_message(chat_id, text)
    del group_data[chat_id]
    logger.info(f"Guruh testi tugadi: chat_id={chat_id}")

@dp.message(Command("stoptest"))
async def stop_group_test(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    chat_id = message.chat.id

    if chat_id not in group_data or not group_data[chat_id].get("active"):
        await message.answer("Hozir faol guruh testi yo'q.")
        return

    data  = group_data[chat_id]
    total = len(data["questions"])
    done  = data["current"]

    await message.answer(
        f"⛔ Guruh testi to'xtatildi!\n\n"
        f"✅ O'tilgan savollar: {done}/{total}"
    )

    # Natijalarni ko'rsatish
    if data["scores"]:
        await finish_group_test(chat_id)
    else:
        if chat_id in group_data:
            del group_data[chat_id]

@dp.message(Command("help"))
async def help_command(message: types.Message):
    if message.chat.type in ("group", "supergroup"):
        await message.answer(
            "🤖 Guruh buyruqlari:\n\n"
            "/test <id> — Test boshlash (masalan: /test 5)\n"
            "/stoptest — Testni to'xtatish\n\n"
            "Test ID ni shaxsiy chatdan '📚 Testlarim' orqali topasiz."
        )
    else:
        await message.answer(
            "🤖 Bot buyruqlari:\n\n"
            "📄 Test yaratish — Fayl yuborish\n"
            "📚 Testlarim — Saqlangan testlar\n"
            "/stop — Testni to'xtatish\n"
            "/help — Yordam"
        )

# ─── Main ──────────────────────────────────────────────────────────────────────
async def main():
    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
