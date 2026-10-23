import argparse
import asyncio
import json
from pathlib import Path

from quizbot.config import Settings
from quizbot.db import database
from quizbot.importing import PolicySpec, QuestionSpec, parse_import
from quizbot.services import Platform


def parser():
    p = argparse.ArgumentParser(
        description="Milliy mock-exam administration; all mutations require a configured admin ID"
    )
    p.add_argument("--actor", type=int, required=True, help="Configured administrator Telegram ID")
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("import", "validate"):
        sub = commands.add_parser(name)
        sub.add_argument("file", type=Path)
    for name in ("publish", "unpublish", "close", "calibrate", "stats", "pending", "runs"):
        sub = commands.add_parser(name)
        sub.add_argument("exam", type=int)
    for name in ("question", "policy"):
        sub = commands.add_parser(name)
        sub.add_argument("exam", type=int)
        sub.add_argument("file", type=Path)
    sub = commands.add_parser("edit")
    sub.add_argument("exam", type=int)
    sub.add_argument("--title")
    sub.add_argument("--duration", type=int)
    sub = commands.add_parser("release")
    sub.add_argument("exam", type=int)
    sub.add_argument(
        "version",
        nargs="?",
        default="raw",
        help="Future Rasch run ID, or raw; omitted in simple mode",
    )
    sub = commands.add_parser("grade")
    sub.add_argument("grade_id", type=int)
    sub.add_argument("category", type=int, choices=[0, 1])
    sub.add_argument("note")
    sub = commands.add_parser("export")
    sub.add_argument("exam", type=int)
    sub.add_argument("output", type=Path)
    return p


async def execute(args):
    settings = Settings()
    engine, sessions = database(settings.database_url.get_secret_value())
    service = Platform(sessions, settings)
    service.admin(args.actor)
    try:
        if args.command in {"validate", "import"}:
            if args.file.stat().st_size > 2_000_000:
                raise ValueError("Import exceeds 2 MB")
            spec = parse_import(args.file.read_bytes(), args.file.name)
            if args.command == "validate":
                print(
                    f"Valid schema: {len(spec.questions)} questions; {sum(len(q.parts) for q in spec.questions)} elements; {sum(q.needs_review for q in spec.questions)} questions need source review"
                )
            else:
                exam = await service.import_exam(args.actor, spec)
                print(f"Draft exam #{exam.id}")
        elif args.command in {"publish", "unpublish"}:
            await service.set_published(args.actor, args.exam, args.command == "publish")
        elif args.command == "close":
            await service.close_exam(args.actor, args.exam)
        elif args.command == "calibrate":
            print(json.dumps(await service.run_calibration(args.actor, args.exam), indent=2))
        elif args.command == "release":
            await service.release_results(
                args.actor, args.exam, None if args.version == "raw" else int(args.version)
            )
        elif args.command == "grade":
            await service.review_grade(args.actor, args.grade_id, args.category, args.note)
        elif args.command == "pending":
            print(
                json.dumps(
                    await service.pending_reviews(args.actor, args.exam),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "runs":
            print(
                json.dumps(
                    [
                        {"id": r.id, "status": r.status, "diagnostics": r.diagnostics}
                        for r in await service.calibration_status(args.actor, args.exam)
                    ],
                    indent=2,
                )
            )
        elif args.command == "edit":
            await service.edit_exam(
                args.actor, args.exam, title=args.title, duration_minutes=args.duration
            )
        elif args.command == "question":
            await service.put_question(
                args.actor, args.exam, QuestionSpec.model_validate_json(args.file.read_bytes())
            )
        elif args.command == "policy":
            await service.edit_exam(
                args.actor, args.exam, policy=PolicySpec.model_validate_json(args.file.read_bytes())
            )
        elif args.command == "stats":
            print(
                json.dumps(
                    (await service.report(args.actor, args.exam))["summary"],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "export":
            payload = await service.export_report(
                args.actor, args.exam, args.output.suffix.lstrip(".")
            )
            args.output.write_bytes(payload)
    finally:
        await engine.dispose()


def main():
    asyncio.run(execute(parser().parse_args()))


if __name__ == "__main__":
    main()
