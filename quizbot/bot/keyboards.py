from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

STUDENT_MENU = [
    "📝 Test ishlash",
    "📚 Mavjud testlar",
    "📊 Natijalarim",
    "🏆 Reyting",
    "👤 Profil",
    "ℹ️ Yordam",
]
ADMIN_MENU = [
    "➕ Test yaratish",
    "📚 Testlarni boshqarish",
    "👥 O‘quvchilar",
    "📊 Statistika",
    "🧮 Rasch tahlili",
    "📤 Hisobotlar",
    "⚙️ Sozlamalar",
]


def menu(admin=False, *, rasch=False):
    values = STUDENT_MENU + (
        [v for v in ADMIN_MENU if rasch or v != "🧮 Rasch tahlili"] if admin else []
    )
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=v) for v in values[i : i + 2]] for i in range(0, len(values), 2)
        ],
        resize_keyboard=True,
    )


def inline(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=callback) for text, callback in row]
            for row in rows
        ]
    )


def pager(prefix, page):
    return (
        [[("⬅️", f"{prefix}:{page - 1}"), ("➡️", f"{prefix}:{page + 1}")]]
        if page > 0
        else [[("➡️", f"{prefix}:1")]]
    )


def result_buttons(attempt_id: int, review_enabled: bool):
    rows = []
    if review_enabled:
        rows += [
            [("❌ Xato javoblarni ko‘rish", f"rv:{attempt_id}:wrong:0")],
            [("✅ To‘g‘ri javoblarni ko‘rish", f"rv:{attempt_id}:correct:0")],
        ]
    rows.append([("🏠 Bosh menyu", "home")])
    return inline(rows)


def admin_result_buttons(exam_id: int):
    return inline(
        [
            [("📥 Excel yuklash", f"act:report:{exam_id}")],
            [("👥 O‘quvchilar natijalari", f"astudents:{exam_id}:0")],
            [("📊 Savollar statistikasi", f"aitems:{exam_id}:0")],
            [("🏠 Admin menyu", "adminhome")],
        ]
    )
