"""Telegram HTML rendering only. No database access or score estimation."""

from html import escape

from quizbot.bot.materials import split_material


def e(value) -> str:
    return escape(str(value), quote=False)


class ResultPresentationService:
    @staticmethod
    def student(result: dict) -> str:
        lines = [
            "🏆 <b>MILLIY SERTIFIKAT MOCK</b>",
            "",
            f"👤 O‘quvchi: <b>{e(result['full_name'])}</b>",
            f"📚 Fan: {e(result['subject'] or 'Ko‘rsatilmagan')}",
            f"📝 Test: {e(result['title'])}",
            "",
            "📊 <b>TEST NATIJALARI</b>",
        ]
        state = result["release_state"]
        if state != "released":
            lines += [
                "",
                {
                    "in_progress": "📝 Test hali tugallanmagan.",
                    "reviewing": "⏳ <b>Tekshirilmoqda</b>\nYozma javoblar tekshirilgach natijangiz ochiladi.",
                    "held": "🕓 Natijangiz tayyor. Administrator e’lon qilishini kuting.",
                }[state],
            ]
            return "\n".join(lines)
        m = result["metrics"]
        lines += [
            "",
            f"✅ To‘g‘ri: <b>{m['correct_questions']} ta</b>",
            f"❌ Xato: <b>{m['incorrect_questions']} ta</b>",
            f"🟡 Qisman to‘g‘ri: <b>{m['partial_questions']} ta</b>",
            f"⚪ Javobsiz: <b>{m['unanswered_questions']} ta</b>",
            f"📌 Jami: <b>{m['total_questions']} ta savol</b>",
            "",
            f"📈 Natija: <b>{m['percentage']:.1f}%</b>",
            "<i>Foiz barcha qismlari to‘g‘ri bo‘lgan savollar bo‘yicha.</i>",
            "",
            f"🎯 Xom ball: <b>{m['raw_score']:g} / {m['maximum_raw_score']:g}</b>",
            f"🔢 Javob elementlari: {m['total_elements']} ta",
            f"✅ {m['correct_elements']} to‘g‘ri · ❌ {m['incorrect_elements']} xato · ⚪ {m['unanswered_elements']} javobsiz",
            "",
            "<i>Mustaqil sinov natijasi. Rasmiy davlat sertifikati emas.</i>",
        ]
        return "\n".join(lines)

    @staticmethod
    def admin(summary: dict) -> str:
        average = summary.get("average_percentage")
        raw = summary.get("average_raw")
        return "\n".join(
            [
                "📊 <b>TEST STATISTIKASI</b>",
                "",
                f"📝 Test: <b>{e(summary['title'])}</b>",
                f"🆔 Test raqami: {summary['exam_id']}",
                f"👥 Ishtirokchilar: <b>{summary['participants']}</b>",
                f"✅ Topshirilgan: <b>{summary['submitted']}</b>",
                f"⏳ Tekshirilmoqda: <b>{summary['pending_manual_review']}</b>",
                f"📈 O‘rtacha natija: <b>{f'{average:.1f}%' if average is not None else '—'}</b>",
                f"🎯 O‘rtacha xom ball: <b>{f'{raw:g}' if raw is not None else '—'}</b>",
                "",
                f"📤 Natija tartibi: {'darhol' if summary.get('release_policy') == 'immediate' else 'administrator e’lon qiladi'}",
                "<i>Foizlar haqiqiy javoblardan hisoblanadi.</i>",
            ]
        )

    @staticmethod
    def review(page: dict) -> list[str]:
        a = page["answer"]
        if a is None:
            return ["Bu bo‘limda javoblar yo‘q."]
        icon = {"correct": "✅", "incorrect": "❌", "unanswered": "⚪", "pending": "⏳"}[a.state]
        label = f" · {e(a.label)} qism" if a.label else ""
        # Escape small text fragments before wrapping; never split an HTML entity/tag.
        blocks = [
            f"{icon} <b>{a.number}-SAVOL{label}</b>\n<i>{page['index'] + 1}/{page['count']}</i>"
        ]
        content = a.statement
        if a.prompt:
            content += f"\n\n{a.label}) {a.prompt}"
        if page["options"]:
            content += "\n\n" + "\n".join(f"{key}) {value}" for key, value in page["options"])
        for title, value in [
            ("Savol", content),
            ("Sizning javobingiz", a.answer or "Javob berilmagan"),
            ("To‘g‘ri javob", a.accepted[0] if a.accepted else "Qo‘lda baholangan"),
            ("Izoh", a.explanation),
        ]:
            if value:
                for piece in split_material(value, limit=600):
                    blocks.append(f"<b>{title}:</b> {e(piece)}")
        messages, current = [], ""
        for block in blocks:
            if len(current) + len(block) + 2 > 3900:
                messages.append(current)
                current = block
            else:
                current += ("\n\n" if current else "") + block
        if current:
            messages.append(current)
        return messages
