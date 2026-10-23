# Workspace verification

## 2026-10-23: simple grading and formatted results

The current default is `GRADING_STRATEGY=simple`, immediate release after grading, and `Asia/Tashkent` reporting. The expanded PostgreSQL-enabled suite passed **74 tests**. Coverage includes separate parent/element counts, weighted raw scores not equated to question counts, partial/blank/pending answers, percentages, immediate/manual release, independent answer-review gates, ownership/admin permissions, structured names and preserved registration dates, HTML formatting/escaping/navigation, original image/passage access, three-sheet openpyxl values/formula escaping/timezones, and preserved historical Rasch data and calibration tests.

The new additive migration `d831abf20977` passed upgrade, downgrade to `c72a1483b921`, re-upgrade, and `alembic check` with no schema drift. A before/after snapshot verified unchanged historical display names, registration dates, attempts, submitted answers, raw grades, and Rasch records across that round trip. Snapshot SHA-256: `34100ed7ad72684553f5767992737f76baea0a41a3a636c877b0577462b52cba` (synthetic test data only).

Ruff lint/format checks passed (52 Python files), bytecode compilation passed, and `pip check` found no broken dependencies. No Docker or AI API was required. PostgreSQL 17 on temporary port 55439 and fake Telegram transports were used; the running user bot's database, `.env`, and actual student submissions were not changed. Live deployment still requires stopping the old process, running `alembic upgrade head`, and restarting `python -m quizbot`.

## 2026-10-23: supplied exam import and shared passages

The supplied 15-page scan and answer-key image were transcribed to `exams/19-10-ms-mock.json`: 44 parents, 49 graded elements, three complete shared passages, 80,836 bytes. Source questions, answer keys, passages, and PDF SHA-256 are stored separately in `exams/source/`. The generated import passed schema validation with no unresolved transcription flags.

The expanded PostgreSQL-enabled suite passed **52 tests**, including a complete import/start/49-answer/submission yielding 49/49, explicit written-answer variants, passage linkage/completeness, lossless message splitting, and real aiogram routing with automatic passage delivery, cached delivery, and explicit re-display. Telegram transport remained fake; no live user messages were sent.

The new migration `c72a1483b921` passed upgrade, downgrade to the previous revision, re-upgrade, and `alembic check` with no schema drift. Ruff lint/format and bytecode compilation passed. The user's active database and `.env` were not modified; a temporary PostgreSQL cluster on port 55439 was used for integration checks.

## Initial platform verification

Executed locally on Python **3.14.2**, PostgreSQL **17.11**, using an isolated temporary PostgreSQL cluster and a disposable `quizbot_test` database. Telegram calls were replaced by a fake transport; no real student messages were sent.

Final results:

- **44 tests passed**, none skipped in the PostgreSQL-enabled run.
- `alembic upgrade head`: passed on a clean database.
- `alembic downgrade base` followed by `alembic upgrade head`: passed.
- `alembic check`: no new upgrade operations detected.
- `ruff check .`: passed.
- `ruff format --check .`: all 38 Python files formatted.
- Python bytecode compilation: passed.
- `pip check`: no broken requirements.
- CLI validation: 44 parent questions, 49 elements, 44 requiring source review.
- Startup without `BOT_TOKEN`: exits with a configuration message before polling.

Coverage includes exact grading, normalization, weights, matching, manual review, database ownership checks, concurrent registration/start/submission, persistent FSM/progress, deadlines, missing/foreign parts, publication restrictions, stale calibrations, worker locking/recovery, durable notification state, CSV/Excel formula escaping, simulated Rasch/PCM recovery, EAP extremes/sufficiency, missingness, reproducibility, standardization, thresholds, and real aiogram dispatcher routing with a fake transport.

Not executed locally: Python 3.12 runtime, Docker image build/Compose deployment, live BotFather token/Telegram delivery. CI is configured to run PostgreSQL tests on Python 3.12 and 3.14; CI execution itself has not been observed here.

At the initial implementation, the exam PDF and answer-key image were unavailable. The original `examples/milliy-44.unverified.json` remains a blank template; the subsequently supplied exam is in `exams/19-10-ms-mock.json` as described above.
