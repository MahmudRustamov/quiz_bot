from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from quizbot.bot.keyboards import ADMIN_MENU, STUDENT_MENU, inline, menu, pager, result_buttons
from quizbot.bot.materials import send_materials
from quizbot.domain import DISCLAIMER
from quizbot.services.result_presentation import ResultPresentationService

router = Router(name="students")


class Registration(StatesGroup):
    name = State()
    first_name = State()
    last_name = State()


class Taking(StatesGroup):
    written = State()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, platform):
    await state.clear()
    profile = await platform.profile(message.from_user.id)
    if profile and profile.first_name and profile.last_name:
        await message.answer(
            f"Xush kelibsiz, {profile.full_name}!\n\nBu mustaqil sinov testi. Natijalar rasmiy davlat sertifikati emas.",
            reply_markup=menu(
                message.from_user.id in platform.settings.admin_ids,
                rasch=platform.settings.grading_strategy == "rasch",
            ),
        )
    else:
        await state.set_state(Registration.first_name)
        await message.answer("Ro‘yxatdan o‘tish uchun ismingizni kiriting:")


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext, platform):
    await state.clear()
    await message.answer(
        "Menyu. Testni ro‘yxatdan qayta ochib davom ettirishingiz mumkin.",
        reply_markup=menu(
            message.from_user.id in platform.settings.admin_ids,
            rasch=platform.settings.grading_strategy == "rasch",
        ),
    )


@router.message(Registration.name, F.text, ~F.text.startswith("/"))
async def register(message: Message, state: FSMContext, platform):
    # Compatibility with a registration wizard persisted before this update.
    await platform.register(message.from_user.id, message.text)
    await state.clear()
    await message.answer(
        "Ro‘yxatdan o‘tdingiz.",
        reply_markup=menu(
            message.from_user.id in platform.settings.admin_ids,
            rasch=platform.settings.grading_strategy == "rasch",
        ),
    )


@router.message(Registration.first_name, F.text, ~F.text.startswith("/"))
async def register_first_name(message: Message, state: FSMContext, platform):
    await state.set_data({"first_name": platform.validate_name(message.text)})
    await state.set_state(Registration.last_name)
    await message.answer("Familiyangizni kiriting:")


@router.message(Registration.last_name, F.text, ~F.text.startswith("/"))
async def register_last_name(message: Message, state: FSMContext, platform):
    data = await state.get_data()
    await platform.register(
        message.from_user.id, first_name=data["first_name"], last_name=message.text
    )
    await state.clear()
    await message.answer(
        "✅ Ism va familiyangiz saqlandi. Testni tanlashingiz mumkin.",
        reply_markup=menu(
            message.from_user.id in platform.settings.admin_ids,
            rasch=platform.settings.grading_strategy == "rasch",
        ),
    )


@router.callback_query(F.data == "home")
async def home(callback: CallbackQuery, state: FSMContext, platform):
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        "🏠 Bosh menyu",
        reply_markup=menu(
            callback.from_user.id in platform.settings.admin_ids,
            rasch=platform.settings.grading_strategy == "rasch",
        ),
    )


async def show_exams(message, platform, actor, page=0, ranking=False):
    exams = await platform.list_exams(actor, page)
    prefix = "rankexam" if ranking else "exam"
    rows = [[(f"{e.title[:55]} · {e.duration_minutes} daq.", f"{prefix}:{e.id}")] for e in exams]
    rows += pager("ranklist" if ranking else "exams", page)
    await message.answer(
        "Testni tanlang:" if exams else "Hozircha testlar yo‘q.", reply_markup=inline(rows)
    )


@router.message(F.text.in_({"📝 Test ishlash", "📚 Mavjud testlar", "🏆 Reyting"}))
async def exams(message: Message, platform):
    await show_exams(message, platform, message.from_user.id, ranking=message.text == "🏆 Reyting")


@router.callback_query(F.data.regexp(r"^(exams|ranklist):\d+$"))
async def exam_page(callback: CallbackQuery, platform):
    prefix, page = callback.data.split(":")
    await callback.answer()
    await show_exams(
        callback.message, platform, callback.from_user.id, int(page), prefix == "ranklist"
    )


@router.callback_query(F.data.regexp(r"^exam:\d+$"))
async def begin(callback: CallbackQuery, state: FSMContext, platform):
    attempt = await platform.start_attempt(callback.from_user.id, int(callback.data.split(":")[1]))
    await callback.answer()
    await show_question(callback.message, state, platform, callback.from_user.id, attempt.id, 0)


async def show_question(message, state, platform, actor, attempt_id, index):
    view = await platform.question_view(actor, attempt_id, index)
    if view["submitted"]:
        await state.clear()
        await message.answer(
            "Test topshirilgan.", reply_markup=inline([[("Natija", f"result:{attempt_id}")]])
        )
        return
    previous = await state.get_data()
    shown = previous.get("materials_shown", []) if previous.get("attempt_id") == attempt_id else []
    unseen = [m for m in view["materials"] if m["key"] not in shown]
    if unseen:
        await send_materials(message, unseen)
        shown = [*shown, *(m["key"] for m in unseen)]
    await state.set_state(Taking.written)
    await state.set_data(
        {
            "attempt_id": attempt_id,
            "part_id": view["part_id"],
            "index": view["index"],
            "materials_shown": shown,
        }
    )
    if view["image_file_id"]:
        await message.answer_photo(view["image_file_id"])
    remaining = max(0, int((view["deadline"] - datetime.now(UTC)).total_seconds() / 60))
    text = f"{view['number']}{view['label']}-savol · {view['index'] + 1}/{view['count']} · {remaining} daqiqa\n\n{view['statement']}"
    if view["prompt"]:
        text += f"\n{view['prompt']}"
    for label, option in view["options"]:
        text += f"\n{label}) {option}"
    current = view["answer"] or "—"
    text += f"\n\nSaqlangan javob: {current[:150]}"
    rows = []
    if view["materials"]:
        rows.append([("📖 Matnni qayta ko‘rish", f"material:{attempt_id}:{view['index']}")])
    if view["options"]:
        buttons = [
            (label, f"ans:{attempt_id}:{view['part_id']}:{view['index']}:{label}")
            for label, _ in view["options"]
        ]
        rows += [buttons[i : i + 4] for i in range(0, len(buttons), 4)]
    else:
        text += "\nJavobni matn ko‘rinishida yuboring."
    nav = []
    if view["index"] > 0:
        nav.append(("⬅️", f"q:{attempt_id}:{view['index'] - 1}"))
    if view["index"] + 1 < view["count"]:
        nav.append(("➡️", f"q:{attempt_id}:{view['index'] + 1}"))
    if nav:
        rows.append(nav)
    rows += [
        [
            (f"Javobsiz ({len(view['unanswered'])})", f"unanswered:{attempt_id}"),
            ("Topshirish", f"confirm:{attempt_id}"),
        ]
    ]
    await message.answer(text, reply_markup=inline(rows))


@router.callback_query(F.data.regexp(r"^material:\d+:\d+$"))
async def reading_material(callback: CallbackQuery, platform):
    _, attempt_id, index = callback.data.split(":")
    view = await platform.question_view(callback.from_user.id, int(attempt_id), int(index))
    await callback.answer()
    if view["submitted"]:
        await callback.message.answer("Test allaqachon topshirilgan.")
        return
    await send_materials(callback.message, view["materials"])


@router.callback_query(F.data.regexp(r"^q:\d+:\d+$"))
async def navigate(callback: CallbackQuery, state: FSMContext, platform):
    _, attempt, index = callback.data.split(":")
    await callback.answer()
    await show_question(
        callback.message, state, platform, callback.from_user.id, int(attempt), int(index)
    )


@router.callback_query(F.data.regexp(r"^ans:\d+:\d+:\d+:[A-Z]{1,2}$"))
async def answer_choice(callback: CallbackQuery, state: FSMContext, platform):
    _, attempt, part, index, answer = callback.data.split(":")
    await platform.save_answer(callback.from_user.id, int(attempt), int(part), answer)
    await callback.answer("Javob saqlandi.")
    await show_question(
        callback.message, state, platform, callback.from_user.id, int(attempt), int(index) + 1
    )


@router.message(
    Taking.written, F.text, ~F.text.startswith("/"), ~F.text.in_(STUDENT_MENU + ADMIN_MENU)
)
async def answer_written(message: Message, state: FSMContext, platform):
    data = await state.get_data()
    await platform.save_answer(
        message.from_user.id, data["attempt_id"], data["part_id"], message.text
    )
    await message.answer("Javob saqlandi.")
    await show_question(
        message, state, platform, message.from_user.id, data["attempt_id"], data["index"] + 1
    )


@router.callback_query(F.data.regexp(r"^unanswered:\d+(?::\d+)?$"))
async def unanswered(callback: CallbackQuery, platform):
    parts = callback.data.split(":")
    attempt = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    view = await platform.question_view(callback.from_user.id, attempt)
    rows = [
        [(f"{i + 1}-element", f"q:{attempt}:{i}")]
        for i in view.get("unanswered", [])[page * 40 : (page + 1) * 40]
    ]
    if rows:
        rows += pager(f"unanswered:{attempt}", page)
    await callback.answer()
    await callback.message.answer(
        "Javobsiz elementlar:" if rows else "Javobsiz elementlar yo‘q.",
        reply_markup=inline(rows) if rows else None,
    )


@router.callback_query(F.data.regexp(r"^confirm:\d+$"))
async def confirm(callback: CallbackQuery, platform):
    attempt = int(callback.data.split(":")[1])
    await platform.question_view(callback.from_user.id, attempt)
    await callback.answer()
    await callback.message.answer(
        "Testni topshirasizmi? Shundan so‘ng javoblar o‘zgarmaydi.",
        reply_markup=inline(
            [[("Ha, topshirish", f"submit:{attempt}"), ("Davom etish", f"q:{attempt}:0")]]
        ),
    )


@router.callback_query(F.data.regexp(r"^submit:\d+$"))
async def submit(callback: CallbackQuery, state: FSMContext, platform):
    attempt = int(callback.data.split(":")[1])
    await platform.submit_attempt(callback.from_user.id, attempt)
    await state.clear()
    await callback.answer("Test topshirildi.")
    await show_result(callback.message, platform, callback.from_user.id, attempt)


async def show_result(message, platform, actor, attempt_id):
    result = await platform.result(actor, attempt_id)
    if platform.settings.grading_strategy == "simple":
        buttons = result_buttons(attempt_id, result["review_enabled"])
        if result["status"] != "submitted":
            buttons = inline([[("Davom etish", f"q:{attempt_id}:0")], [("🏠 Bosh menyu", "home")]])
        await message.answer(
            ResultPresentationService.student(result), parse_mode="HTML", reply_markup=buttons
        )
        return
    if result["status"] != "submitted":
        await message.answer(
            "Test hali tugallanmagan.",
            reply_markup=inline([[("Davom etish", f"q:{attempt_id}:0")]]),
        )
        return
    text = f"{result['title']}\n"
    text += (
        "Yozma javoblar tekshirilmoqda.\n"
        if result["raw"] is None
        else f"Xom ball: {result['raw']:g} / {result['maximum']:g}\n"
    )
    if result["calibrated"]:
        grade = "C dan past" if result["grade"] == "Below C" else result["grade"]
        text += f"θ: {result['theta']:.3f} (posterior SD {result['posterior_sd']:.3f})\nZ: {result['z']:.3f}\nT: {result['t']:.2f}\nTaxminiy daraja: {grade}\nKalibrlash versiyasi: {result['run_id']}\n"
    else:
        text += "θ, Z va T: mavjud emas. Kalibrlangan natija e’lon qilinmagan.\n"
    text += f"\n{DISCLAIMER}"
    rows = [[("Javoblarni ko‘rish", f"review:{attempt_id}:0")]] if result["released"] else []
    await message.answer(text, reply_markup=inline(rows) if rows else None)


@router.callback_query(F.data.regexp(r"^result:\d+$"))
async def result(callback: CallbackQuery, platform):
    await callback.answer()
    await show_result(
        callback.message, platform, callback.from_user.id, int(callback.data.split(":")[1])
    )


async def show_history(message, platform, actor, page=0):
    history = await platform.history(actor, page)
    rows = [[(r["title"][:55], f"result:{r['id']}")] for r in history] + pager("history", page)
    await message.answer(
        "Natijalaringiz:" if history else "Hozircha urinishlar yo‘q.", reply_markup=inline(rows)
    )


@router.message(F.text == "📊 Natijalarim")
async def history(message: Message, platform):
    await show_history(message, platform, message.from_user.id)


@router.callback_query(F.data.regexp(r"^history:\d+$"))
async def history_page(callback: CallbackQuery, platform):
    await callback.answer()
    await show_history(
        callback.message, platform, callback.from_user.id, int(callback.data.split(":")[1])
    )


@router.callback_query(F.data.regexp(r"^review:\d+:\d+$"))
async def review(callback: CallbackQuery, platform):
    _, attempt, page = callback.data.split(":")
    await callback.answer()
    await show_review(
        callback.message, platform, callback.from_user.id, int(attempt), "all", int(page) * 5
    )


async def show_review(message, platform, actor, attempt_id, kind, index):
    page = await platform.review_page(actor, attempt_id, kind, index)
    rows, navigation = [], []
    if page["index"] > 0:
        navigation.append(("⬅️ Oldingi", f"rv:{attempt_id}:{kind}:{page['index'] - 1}"))
    if page["index"] + 1 < page["count"]:
        navigation.append(("Keyingi ➡️", f"rv:{attempt_id}:{kind}:{page['index'] + 1}"))
    if navigation:
        rows.append(navigation)
    if page["materials"]:
        rows.append([("📖 O‘qish matni", f"rmat:{attempt_id}:{kind}:{page['index']}")])
    rows += [[("📊 Natijaga qaytish", f"result:{attempt_id}")], [("🏠 Bosh menyu", "home")]]
    if page["answer"] and page["answer"].image_file_id:
        await message.answer_photo(page["answer"].image_file_id)
    messages = ResultPresentationService.review(page)
    for i, text in enumerate(messages):
        await message.answer(
            text, parse_mode="HTML", reply_markup=inline(rows) if i == len(messages) - 1 else None
        )


@router.callback_query(F.data.regexp(r"^rv:\d+:(wrong|correct|all):\d+$"))
async def review_filtered(callback: CallbackQuery, platform):
    _, attempt, kind, index = callback.data.split(":")
    await callback.answer()
    await show_review(
        callback.message, platform, callback.from_user.id, int(attempt), kind, int(index)
    )


@router.callback_query(F.data.regexp(r"^rmat:\d+:(wrong|correct|all):\d+$"))
async def review_reading(callback: CallbackQuery, platform):
    _, attempt, kind, index = callback.data.split(":")
    materials = await platform.review_materials(
        callback.from_user.id, int(attempt), kind, int(index)
    )
    await callback.answer()
    await send_materials(callback.message, materials)
    await callback.message.answer(
        "Javobga qaytish:", reply_markup=inline([[("⬅️ Javob", f"rv:{attempt}:{kind}:{index}")]])
    )


@router.callback_query(F.data.regexp(r"^rankexam:\d+(?::\d+)?$"))
async def rank(callback: CallbackQuery, platform):
    parts = callback.data.split(":")
    exam_id, page = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    rows = await platform.leaderboard(callback.from_user.id, exam_id, page)
    await callback.answer()
    await callback.message.answer(
        "\n".join(
            f"{page * 10 + i + 1}. Ishtirokchi #{r['attempt_id']} · {r['raw']:g} ball"
            for i, r in enumerate(rows)
        )
        or "Natijalar yo‘q.",
        reply_markup=inline(pager(f"rankexam:{exam_id}", page)),
    )


@router.message(F.text == "👤 Profil")
async def profile(message: Message, state: FSMContext, platform):
    user = await platform.profile(message.from_user.id)
    if not user or not user.first_name or not user.last_name:
        await start(message, state, platform)
        return
    await message.answer(
        f"Ism-familiya: {user.full_name}\nTelegram ID: {user.telegram_id}\nIsmni o‘zgartirish: /name"
        if user
        else "Avval /start buyrug‘ini bosing."
    )


@router.message(Command("name"))
async def rename(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Registration.first_name)
    await message.answer("Ismingizni kiriting:")


@router.message(F.text == "ℹ️ Yordam")
@router.message(Command("help"))
async def help_message(message: Message, platform):
    await message.answer(
        "Testni tanlang va javoblarni yuboring. Javoblar har safar saqlanadi. Vaqt tugaganda test avtomatik topshiriladi. /cancel — menyuga qaytish; /start — boshlash.\n\nNatijalarim bo‘limidan tekshiruv va e’lon holatini ko‘ring.\n\n"
        + (
            "Bu mustaqil sinov testi. Natijalar rasmiy davlat sertifikati emas."
            if platform.settings.grading_strategy == "simple"
            else DISCLAIMER
        )
    )
