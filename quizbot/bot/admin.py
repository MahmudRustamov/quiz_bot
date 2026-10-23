import io

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from quizbot.bot.keyboards import admin_result_buttons, inline, menu, pager
from quizbot.domain import DomainError
from quizbot.importing import ExamSpec, PolicySpec, QuestionSpec, parse_import
from quizbot.services.result_presentation import ResultPresentationService, e

router = Router(name="administrators")


class AdminOnly(BaseMiddleware):
    async def __call__(self, handler, event, data):
        data["platform"].admin(event.from_user.id)
        return await handler(event, data)


router.message.middleware(AdminOnly())
router.callback_query.middleware(AdminOnly())


class Creating(StatesGroup):
    title = State()
    duration = State()


class Uploading(StatesGroup):
    exam = State()
    question = State()
    policy = State()


ADMIN_HELP = (
    "Administrator buyruqlari:\n"
    "/create — test yaratish\n/import — JSON/CSV import\n"
    "/question ID — bitta savol JSON fayli\n/policy ID — siyosat JSON fayli\n"
    "/edit ID DAQIQA NOM — nom va davomiylik\n"
    "/publish ID · /unpublish ID · /close ID\n"
    "/pending ID [SAHIFA] — qo‘lda tekshirish\n"
    "/grade BAHO_ID 0_yoki_1 IZOH — baholash\n"
    "/release ID — oddiy natijalarni e’lon qilish\n"
    "/resultpolicy ID immediate_yoki_manual on_yoki_off — natija va javoblar tartibi\n"
    "/subject ID FAN_NOMI — fan nomi\n"
    "/stats ID · /report ID csv_yoki_xlsx\n"
    "/students [SAHIFA] · /runs ID\n"
    "/cancel — amalni bekor qilish"
)


@router.message(Command("admin"))
async def admin_menu(message: Message, platform):
    await message.answer(
        ADMIN_HELP, reply_markup=menu(True, rasch=platform.settings.grading_strategy == "rasch")
    )


@router.callback_query(F.data == "adminhome")
async def admin_home(callback: CallbackQuery, state: FSMContext, platform):
    await state.clear()
    await callback.answer()
    await admin_menu(callback.message, platform)


@router.message(F.text == "⚙️ Sozlamalar")
async def settings(message: Message, platform):
    await message.answer(
        f"⚙️ Baholash: {'oddiy javoblar bo‘yicha' if platform.settings.grading_strategy == 'simple' else 'Rasch'}\nNatija tartibi: {platform.settings.simple_release_policy}\nHisobot vaqt zonasi: {platform.settings.report_timezone}\n\n{ADMIN_HELP}"
    )


@router.message(Command("create"))
@router.message(F.text == "➕ Test yaratish")
async def create(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Creating.title)
    await message.answer("Test nomini kiriting:")


@router.message(Creating.title, F.text, ~F.text.startswith("/"))
async def create_title(message: Message, state: FSMContext):
    if not 1 <= len(message.text.strip()) <= 200:
        raise DomainError("Nom 1–200 belgi bo‘lsin.")
    await state.update_data(title=message.text.strip())
    await state.set_state(Creating.duration)
    await message.answer("Davomiylikni daqiqada kiriting (1–1440):")


@router.message(Creating.duration, F.text, ~F.text.startswith("/"))
async def create_duration(message: Message, state: FSMContext, platform):
    data = await state.get_data()
    spec = ExamSpec(title=data["title"], duration_minutes=int(message.text))
    exam = await platform.import_exam(message.from_user.id, spec)
    await state.clear()
    await message.answer(
        f"Test yaratildi: #{exam.id}. Savollar uchun /question {exam.id}; to‘liq test uchun /import."
    )


@router.message(Command("import"))
async def import_begin(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Uploading.exam)
    await message.answer(
        "UTF-8 JSON yoki CSV test faylini yuboring (2 MB gacha). Namuna: examples/ katalogi."
    )


@router.message(Command("question", "policy"))
async def upload_begin(message: Message, state: FSMContext):
    command, exam_id = message.text.split()
    await state.clear()
    await state.set_state(
        Uploading.question if command.split("@")[0] == "/question" else Uploading.policy
    )
    await state.set_data({"exam_id": int(exam_id)})
    await message.answer(
        "JSON faylini yoki JSON matnini yuboring. Savol raqami mavjud bo‘lsa almashtiriladi. Rasmlar uchun image_file_id maydonidan foydalaning."
    )


@router.message(Uploading.exam, F.document)
@router.message(Uploading.question, F.document | (F.text & ~F.text.startswith("/")))
@router.message(Uploading.policy, F.document | (F.text & ~F.text.startswith("/")))
async def upload(message: Message, state: FSMContext, platform, bot):
    if message.text and message.text.startswith("/"):
        return
    if message.document:
        if (message.document.file_size or 0) > 2_000_000:
            raise DomainError("Fayl 2 MB dan oshmasin.")
        target = io.BytesIO()
        await bot.download(message.document, destination=target, timeout=30)
        payload, filename = target.getvalue(), message.document.file_name or ""
    else:
        payload, filename = message.text.encode(), "data.json"
    current = await state.get_state()
    data = await state.get_data()
    if current == Uploading.exam.state:
        spec = parse_import(payload, filename)
        exam = await platform.import_exam(message.from_user.id, spec)
        response = f"Test import qilindi: #{exam.id}; savollar: {len(spec.questions)}. E’lon qilish: /publish {exam.id}"
    elif current == Uploading.question.state:
        spec = QuestionSpec.model_validate_json(payload)
        await platform.put_question(message.from_user.id, data["exam_id"], spec)
        response = "Savol va javob kaliti saqlandi."
    else:
        spec = PolicySpec.model_validate_json(payload)
        await platform.edit_exam(message.from_user.id, data["exam_id"], policy=spec)
        response = "Baholash siyosati saqlandi."
    await state.clear()
    await message.answer(response)


async def manage_list(message, platform, actor, page=0):
    exams = await platform.list_exams(actor, page, administration=True)
    rows = [[(f"#{e.id} {e.title[:45]}", f"manage:{e.id}")] for e in exams] + pager(
        "managepage", page
    )
    await message.answer("Boshqarish uchun testni tanlang:", reply_markup=inline(rows))


@router.message(
    F.text.in_({"📚 Testlarni boshqarish", "📊 Statistika", "🧮 Rasch tahlili", "📤 Hisobotlar"})
)
async def manage(message: Message, platform):
    await manage_list(message, platform, message.from_user.id)


@router.callback_query(F.data.regexp(r"^managepage:\d+$"))
async def manage_page(callback: CallbackQuery, platform):
    await callback.answer()
    await manage_list(
        callback.message, platform, callback.from_user.id, int(callback.data.split(":")[1])
    )


@router.callback_query(F.data.regexp(r"^manage:\d+$"))
async def manage_exam(callback: CallbackQuery, platform):
    exam_id = int(callback.data.split(":")[1])
    report = await platform.report(callback.from_user.id, exam_id)
    await callback.answer()
    rows = [
        [
            ("E’lon qilish", f"act:publish:{exam_id}"),
            ("E’londan olish", f"act:unpublish:{exam_id}"),
        ],
        [("Kirishni yopish", f"act:close:{exam_id}"), ("Tekshiruv", f"act:pending:{exam_id}")],
        [
            ("Statistika", f"act:stats:{exam_id}"),
            ("Natijani e’lon qilish", f"act:release:{exam_id}"),
        ],
        [("📥 Excel yuklash", f"act:report:{exam_id}")],
        [
            ("👥 O‘quvchilar natijalari", f"astudents:{exam_id}:0"),
            ("📊 Savollar", f"aitems:{exam_id}:0"),
        ],
        [("🏠 Admin menyu", "adminhome")],
    ]
    if platform.settings.grading_strategy == "rasch":
        rows.insert(2, [("Kalibrlash", f"act:calibrate:{exam_id}")])
    await callback.message.answer(
        ResultPresentationService.admin(report["summary"]),
        parse_mode="HTML",
        reply_markup=inline(rows),
    )


async def perform(message, platform, actor, action, exam_id):
    if action in {"publish", "unpublish"}:
        await platform.set_published(actor, exam_id, action == "publish")
    elif action == "close":
        await platform.close_exam(actor, exam_id)
    elif action == "calibrate":
        if platform.settings.grading_strategy != "rasch":
            raise DomainError("Hozir oddiy baholash yoqilgan. Kalibrlash talab qilinmaydi.")
        await message.answer("Kalibrlash boshlandi. Hisoblash tugagach holat yuboriladi.")
        result = await platform.run_calibration(actor, exam_id)
        await message.answer(
            f"🧮 Kalibrlash #{result['run_id']}\nHolat: {e(result['status'])}", parse_mode="HTML"
        )
        return
    elif action == "stats":
        report = await platform.report(actor, exam_id)
        await message.answer(
            ResultPresentationService.admin(report["summary"]),
            parse_mode="HTML",
            reply_markup=admin_result_buttons(exam_id),
        )
        return
    elif action == "pending":
        await show_pending(message, platform, actor, exam_id, 0)
        return
    elif action == "report":
        payload = await platform.export_report(actor, exam_id)
        await message.answer_document(
            BufferedInputFile(payload, filename=f"exam_{exam_id}_results.xlsx")
        )
        return
    elif action == "release":
        await platform.release_results(actor, exam_id)
    await message.answer("Amal bajarildi.")


@router.callback_query(
    F.data.regexp(r"^act:(publish|unpublish|close|calibrate|stats|pending|report|release):\d+$")
)
async def action_callback(callback: CallbackQuery, platform):
    _, action, exam = callback.data.split(":")
    await callback.answer()
    await perform(callback.message, platform, callback.from_user.id, action, int(exam))


@router.message(Command("publish", "unpublish", "close", "calibrate", "stats"))
async def command_action(message: Message, platform):
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        command = args[0].split("@")[0]
        raise DomainError(f"Test raqamini yozing. Masalan: {command} 2")
    action, exam = args
    await perform(message, platform, message.from_user.id, action.split("@")[0][1:], int(exam))


@router.message(Command("edit"))
async def edit(message: Message, platform):
    _, exam, minutes, title = message.text.split(maxsplit=3)
    await platform.edit_exam(
        message.from_user.id, int(exam), title=title, duration_minutes=int(minutes)
    )
    await message.answer("Test yangilandi.")


async def show_pending(message, platform, actor, exam, page):
    rows = await platform.pending_reviews(actor, exam, page)
    text = "\n\n".join(
        f"Baho ID: {r['id']} · urinish #{r['attempt_id']} · {r['number']}{r['label']}\nJavob: {(r['answer'] or '—')[:300]}\nMezon: {str(r['rubric'].get('grading_policy', 'Administrator belgilagan mezon'))[:250]}\n/grade {r['id']} 0_yoki_1 IZOH"
        for r in rows
    )
    await message.answer(
        text or "Tekshiriladigan javoblar yo‘q.",
        reply_markup=inline(pager(f"pending:{exam}", page)),
    )


@router.message(Command("pending"))
async def pending(message: Message, platform):
    args = message.text.split()
    await show_pending(
        message, platform, message.from_user.id, int(args[1]), int(args[2]) if len(args) > 2 else 0
    )


@router.callback_query(F.data.regexp(r"^pending:\d+:\d+$"))
async def pending_page(callback: CallbackQuery, platform):
    _, exam, page = callback.data.split(":")
    await callback.answer()
    await show_pending(callback.message, platform, callback.from_user.id, int(exam), int(page))


@router.message(Command("grade"))
async def grade(message: Message, platform):
    _, grade_id, category, note = message.text.split(maxsplit=3)
    await platform.review_grade(message.from_user.id, int(grade_id), int(category), note)
    await message.answer("✅ Baholash saqlandi.")


@router.message(Command("release"))
async def release(message: Message, platform):
    args = message.text.split()
    if len(args) not in (2, 3) or not args[1].isdigit():
        raise DomainError("Test raqamini yozing. Masalan: /release 4")
    exam, version = args[1], args[2] if len(args) == 3 else "raw"
    await platform.release_results(
        message.from_user.id, int(exam), None if version == "raw" else int(version)
    )
    await message.answer(
        "Natijalar e’lon qilindi. O‘quvchilar «Natijalarim» bo‘limida ko‘rishi mumkin."
    )


@router.message(Command("runs"))
async def runs(message: Message, platform):
    if platform.settings.grading_strategy == "simple":
        await message.answer(
            "Hozir oddiy baholash rejimi yoqilgan. Rasch tahlili vaqtincha o‘chirilgan."
        )
        return
    rows = await platform.calibration_status(message.from_user.id, int(message.text.split()[1]))
    await message.answer(
        "\n".join(f"#{r.id}: {r.status} · {r.model}" for r in rows) or "Kalibrlash hali yo‘q."
    )


@router.message(Command("report"))
async def report(message: Message, platform):
    args = message.text.split()
    exam, format = int(args[1]), args[2] if len(args) > 2 else "xlsx"
    payload = await platform.export_report(message.from_user.id, exam, format)
    await message.answer_document(
        BufferedInputFile(payload, filename=f"exam_{exam}_results.{format}")
    )


@router.message(Command("resultpolicy"))
async def result_policy(message: Message, platform):
    args = message.text.split()
    if len(args) not in (3, 4) or (len(args) == 4 and args[3] not in {"on", "off"}):
        raise DomainError("Namuna: /resultpolicy 4 immediate on yoki /resultpolicy 4 manual off")
    await platform.set_result_policy(
        message.from_user.id, int(args[1]), args[2], len(args) == 3 or args[3] == "on"
    )
    await message.answer("✅ Natijani chiqarish va javoblarni ko‘rish tartibi saqlandi.")


@router.message(Command("subject"))
async def subject(message: Message, platform):
    args = message.text.split(maxsplit=2)
    if len(args) != 3:
        raise DomainError("Namuna: /subject 4 Ona tili va adabiyot")
    await platform.set_subject(message.from_user.id, int(args[1]), args[2])
    await message.answer("✅ Fan nomi saqlandi.")


@router.callback_query(F.data.regexp(r"^astudents:\d+:\d+$"))
async def student_results(callback: CallbackQuery, platform):
    _, exam, page = callback.data.split(":")
    exam, page = int(exam), int(page)
    report = await platform.simple_report(callback.from_user.id, exam)
    participants = report["participants"][page * 3 : (page + 1) * 3]
    lines = ["👥 <b>O‘QUVCHILAR NATIJALARI</b>"]
    for p in participants:
        lines += ["", f"👤 <b>{e(p['full_name'])}</b>"]
        if p["percentage"] is None:
            lines.append(f"⏳ {e(p['manual_review_status'])}")
        else:
            lines.append(
                f"✅ {p['correct_questions']} · ❌ {p['incorrect_questions']} · 🟡 {p['partial_questions']} · ⚪ {p['unanswered_questions']}\n📈 {p['percentage']:.1f}% · 🎯 {p['raw_score']:g}/{p['maximum_raw_score']:g}"
            )
    await callback.answer()
    await callback.message.answer(
        "\n".join(lines) if participants else "Bu sahifada natijalar yo‘q.",
        parse_mode="HTML",
        reply_markup=inline(
            pager(f"astudents:{exam}", page) + [[("📊 Statistikaga qaytish", f"act:stats:{exam}")]]
        ),
    )


@router.callback_query(F.data.regexp(r"^aitems:\d+:\d+$"))
async def question_statistics(callback: CallbackQuery, platform):
    _, exam, page = callback.data.split(":")
    exam, page = int(exam), int(page)
    report = await platform.simple_report(callback.from_user.id, exam)
    rows = report["items"][page * 8 : (page + 1) * 8]
    lines = [
        "📊 <b>SAVOLLAR STATISTIKASI</b>",
        "<i>Ko‘rsatkich — kuzatilgan to‘liq to‘g‘ri javoblar foizi.</i>",
    ]
    for row in rows:
        percentage = row["observed_percent_correct"]
        lines += [
            "",
            f"<b>{row['question']}-savol</b> · {f'{percentage:.1f}%' if percentage is not None else '—'}",
            f"✅ {row['correct']} · ❌ {row['incorrect']} · 🟡 {row['partial']} · ⚪ {row['unanswered']} · ⏳ {row['pending']}",
        ]
    await callback.answer()
    await callback.message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=inline(
            pager(f"aitems:{exam}", page) + [[("📊 Statistikaga qaytish", f"act:stats:{exam}")]]
        ),
    )


@router.message(Command("students"))
@router.message(F.text == "👥 O‘quvchilar")
async def students(message: Message, platform):
    args = message.text.split()
    page = int(args[1]) if message.text.startswith("/students") and len(args) > 1 else 0
    await show_students(message, platform, message.from_user.id, page)


async def show_students(message, platform, actor, page):
    rows = await platform.students(actor, page)
    await message.answer(
        "\n".join(f"{u.telegram_id}: {u.full_name}" for u in rows) or "O‘quvchilar yo‘q.",
        reply_markup=inline(pager("studentspage", page)),
    )


@router.callback_query(F.data.regexp(r"^studentspage:\d+$"))
async def students_page(callback: CallbackQuery, platform):
    await callback.answer()
    await show_students(
        callback.message, platform, callback.from_user.id, int(callback.data.split(":")[1])
    )


@router.message(F.photo)
async def image_id(message: Message):
    await message.answer(
        f"Rasm uchun Telegram file_id:\n{message.photo[-1].file_id}\nSavol JSON faylining image_file_id maydoniga kiriting."
    )
