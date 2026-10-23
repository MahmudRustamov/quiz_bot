# Milliy Sertifikat Quiz Bot

An independent Uzbek Telegram practice-exam platform. **It does not issue government certificates or reproduce official scoring.** Question weights, reference cohorts, model choice, and calibration diagnostics are explicit and versioned.

**The active default is now simple answer-based grading.** Students see correct, incorrect, partial and unanswered parent questions, separate scoring-element counts, percentage, and raw points. No theta, Z/T scores, certificate grades or calibration minimum are used in this mode. See [docs/simple-grading.md](docs/simple-grading.md) for the update and Uzbek operating instructions. Existing responses, raw scores, and Rasch infrastructure are retained.

## Included

- Python 3.12+, aiogram 3, PostgreSQL, async SQLAlchemy 2, Alembic, Pydantic Settings.
- Uzbek student interface: registration, available tests, saved answers, forward/back navigation, unanswered review, timed submission, history, released answer review, pseudonymous raw-score ranking.
- Administrator allowlist, exam creation, question replacement, JSON/CSV import, policies, publish/unpublish, close admission, written-answer review, statistics, calibration, result release, CSV/Excel reports.
- Separate statements/options/parts/keys/rubrics; Telegram image attachments; multipart questions retain their parent IDs. Weights affect raw points only.
- HTML result cards, filtered answer review with navigation, structured first/last names, immediate/manual release policies, and formatted three-sheet openpyxl workbooks in `results/exam_<id>_results.xlsx`.
- Preserved optional marginal maximum likelihood Rasch/PCM services for future activation with `GRADING_STRATEGY=rasch`; disabled by default.
- PostgreSQL FSM, transactional row locking, unique attempts and grades, deadline sweeper, audit log, durable result notification outbox with retries.
- Docker Compose and PostgreSQL-backed tests; no live Telegram calls in tests.

## Local setup

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Set `BOT_TOKEN` from BotFather, `DATABASE_URL`, and `ADMIN_IDS` (JSON array of numeric Telegram user IDs) in `.env`. Use PostgreSQL 17 or another supported SQLAlchemy/asyncpg-compatible version. Create the database and user using your PostgreSQL administration tools. Never commit `.env`.

Existing installations can retain their `.env`. `GRADING_STRATEGY=simple`, `SIMPLE_RELEASE_POLICY=immediate`, `REPORT_TIMEZONE=Asia/Tashkent`, and `RESULTS_DIR=results` are the defaults. Stop the previous bot process before migrating/restarting. Docker and AI APIs are not required.

```sh
alembic upgrade head
python -m quizbot
```

The bot uses long polling. Run **one bot process per database and token**. A database advisory lock prevents a second process on the same database. Do not run a webhook receiver with the same token. No schema is silently created on startup; migrations must succeed first. SIGINT/SIGTERM stop polling and close resources. Unfinished calibration runs are marked failed at the next startup; administrators can retry.

## Docker

Set `POSTGRES_PASSWORD`, `BOT_TOKEN`, and `ADMIN_IDS` in `.env`, then:

```sh
docker compose up --build -d
docker compose logs -f bot
```

Compose starts PostgreSQL, runs migrations once, then starts the bot. Its internal database URL overrides the local `.env` URL. Use a URL-safe database password or URL-encode it in the Compose database URL. The database port binds only to localhost. The bot runs as a non-root user with a read-only root filesystem. Back up the PostgreSQL volume and verify restoration before a real exam.

## Importing your 44-question exam

The supplied **19.10_MS_MOCK_TEST_tahrirlangan.pdf** and answer-key image have been transcribed into **`exams/19-10-ms-mock.json`**: 44 parent questions, 49 scored elements, and three complete reading passages. See [exams/19-10-import-notes.md](exams/19-10-import-notes.md) for Uzbek import instructions, source notes, explicit answer variants, and scoring assumptions. Run `alembic upgrade head` and restart the bot before importing; shared reading materials require the new additive migration. The import creates a new draft and does not replace existing exams.

Reading materials are stored separately from questions and keys, automatically sent on first use, split into Telegram-sized messages, and available again through “📖 Matnni qayta ko‘rish”. The 180-minute duration and one-point-per-element weights are configurable practice defaults, not official exam claims. Source transcriptions, the supplied answer key, and PDF fingerprint are retained in `exams/source/`.

The original blank template remains available for other exams:

`examples/milliy-44.unverified.json` contains exactly 44 parent questions and 49 scored elements:

| Questions | Type | Elements |
| --- | --- | ---: |
| 1–32 | Multiple choice | 32 |
| 33–35 | Matching | 3 |
| 36–39 | Written | 4 |
| 40–44 | Two parts, A/B | 10 |

All questions have `needs_review: true`, empty statements/options/keys, and source-review notes. One raw point per element is a configurable simplified practice policy, **not an official weighting claim**. The template's 180-minute duration is a placeholder to configure. This template imports as a draft and cannot be published until every question has been populated, checked against the source materials, and marked verified.

Use `/import` to upload UTF-8 JSON/CSV, or the local CLI:

```sh
quiz-admin --actor 123456789 validate examples/milliy-44.unverified.json
quiz-admin --actor 123456789 import examples/milliy-44.unverified.json
```

`examples/demo-exam.json` and `.csv` are synthetic software demonstrations, separate from your exam. JSON schemas, a single-question example, and a policy example are included. For diagrams, send a photo to the bot as an administrator and copy its returned `file_id` into `image_file_id`. Images use Telegram storage rather than arbitrary downloaded URLs.

One CSV row represents a parent question. `title`, `duration_minutes`, optional `policy`, and optional `materials` must match on every row. `options`, `parts`, `rubric`, `needs_review`, `pcm`, `material_keys`, and `materials` are JSON-encoded cells. JSON imports define shared `materials` at the top level and link questions with `material_keys`. Unknown fields, oversized files, invalid keys, duplicate numbers/parts/materials, missing material references, and invalid grade boundaries are rejected. Use `needs_review: true` for uncertain text; do not guess answers. Maximum import size: 2 MB and 500 parent questions. Calibration supports up to 10,000 students and 100 psychometric items.

Published exams must be unpublished before editing. Once anyone starts, question content, duration, and raw grading policies are frozen. Import a new exam version for those changes. Display subject and the independent simple-result visibility policy remain configurable by administrators. Closing admission lets existing students finish and permanently prevents new starts.

## Administration

Administrator actions are checked against `ADMIN_IDS` in both handlers and services. The CLI is a trusted local administrative interface requiring the same configured actor ID; filesystem/database access remains an operator responsibility.

| Command | Purpose |
| --- | --- |
| `/admin` | Admin menu and help |
| `/create` | Name/duration wizard |
| `/import` | Upload full exam JSON/CSV |
| `/question ID` | Upload question JSON; replaces the same number |
| `/policy ID` | Upload policy JSON |
| `/edit ID MINUTES TITLE` | Edit metadata before attempts exist |
| `/publish ID`, `/unpublish ID` | Show/hide test |
| `/close ID` | Permanently close new admission |
| `/students [PAGE]` | Registered students |
| `/pending ID [PAGE]` | Responses awaiting manual grading |
| `/grade GRADE_ID 0_OR_1 NOTE` | Grade a part with audit reason |
| `/stats ID` | Formatted statistics, student/question views, Excel button |
| `/subject ID SUBJECT` | Set the displayed subject, including on existing exams |
| `/resultpolicy ID immediate on` | Show reviewed simple results immediately, enable answer review |
| `/resultpolicy ID manual off` | Hold simple results for manual release, disable answer review |
| `/release ID` | Publish simple results without cohort/calibration restrictions |
| `/calibrate ID`, `/runs ID`, `/release ID RUN_ID` | Future Rasch mode only |
| `/report ID csv`, `/report ID xlsx` | Detailed reports |
| `/cancel` | Exit wizard, preserving exam progress |

`quiz-admin --help` exposes the existing local administration commands; the release version argument is optional in simple mode. Simple Excel exports use **Students**, **Individual Answers**, and **Exam Summary** sheets, with filters, frozen headers, explicit timezone/UTC offsets, observed parent-question statistics, and formula escaping. Student rankings use anonymous attempt IDs and raw points; detailed files are administrative only.

## Scoring and release workflow

1. Import and verify questions/policy; publish.
2. Students start once each. Every response is persisted. Exam/attempt locks and uniqueness constraints serialize competing saves/submissions. A sweeper or the next interaction grades expired attempts; late answers are rejected.
3. Automatic grading uses exact NFKC Unicode and whitespace normalization with configurable case folding. There is no semantic/fuzzy matching or automatic apostrophe replacement. Accepted variants are explicit. Blank/unanswered parts earn zero raw points. `manual_review: true` queues nonblank responses for review.
4. By default, fully reviewed simple results open immediately after submission. A pending manual grade displays “Tekshirilmoqda” and keeps scores/keys hidden until complete.
5. Use `/resultpolicy ID manual on` to hold results for `/release ID`. Simple release does not require closing the exam or calibrating a cohort. A published result remains available even if the policy subsequently becomes manual. Answer review can independently be disabled with `off`.
6. Students receive HTML summaries and separate wrong/correct review buttons. Multipart A/B elements are reviewed individually; images and shared reading passages remain accessible. The percentage is fully correct parent questions / all parent questions, not weighted raw percentage. Wrong-answer review excludes unanswered elements; blanks are separately counted in the summary and exported answers.
7. A durable notification outbox retries transient failures, stopping after eight attempts or when blocked. Delivery is at least once: a crash after sending can duplicate a notification. History remains available.

Simple release uses separate exam/attempt metadata; the original Rasch `results_released` and released calibration pointer remain intact. Published attempt grades are immutable through services. Existing students with missing structured names are asked to enter first name and surname through `/start`; legacy display names and registration timestamps are preserved. No historical answers or raw points are rewritten by the migration.

## Future Rasch mode

Enable `GRADING_STRATEGY=rasch` explicitly to restore the existing calibrated workflow. It requires a closed, completed/reviewed cohort, valid calibration, and deliberate administrator release. None of the following psychometric calculations run in the default simple strategy.

See [docs/psychometrics.md](docs/psychometrics.md) for assumptions, diagnostics, uncertainty limits, and reference rules. Calibration estimates item/step parameters from joint cohort responses under a fixed-discrimination model.

The reference cohort is all submitted, reviewed attempts in a closed exam. Its EAP ability mean and population SD (`ddof=0`) define `Z=(theta-mean)/sd`, `T=50+10Z`. Single-student or zero-variance cohorts cannot define standardized scores. PostgreSQL retains full precision; Telegram rounds for display. T scores are not capped, equated across exams, percent-correct scores, or official certification points.

Default T thresholds: A+ ≥70, A ≥65, B+ ≥60, B ≥55, C+ ≥50, C ≥46, otherwise Below C. Policies store boundaries in the database. A run stores its exact matrix, attempts, item mapping, policy, snapshot hash, algorithm/library versions, parameters, ability/posterior SD, cohort mean/SD, scores, and diagnostics. Publication references one run.

## Tests and operations

Run grading, import, simulated Rasch/PCM and standardization tests without a database:

```sh
pytest -q
```

Integration tests skip unless `TEST_DATABASE_URL` is set. For a **disposable** PostgreSQL database whose name contains `test`:

```sh
export DATABASE_URL=postgresql+asyncpg://quiz:password@localhost:5432/quizbot_test
export TEST_DATABASE_URL="$DATABASE_URL"
alembic upgrade head
alembic check
pytest -q
ruff check .
ruff format --check .
```

Fixtures truncate that test database. Run tests serially. CI provisions PostgreSQL, tests migrations, and runs on Python 3.12/3.14. Tests exercise a real aiogram Dispatcher with a fake Telegram transport; no network sends are needed.

Workspace verification used Python 3.14 and temporary PostgreSQL 17. Docker is unavailable here, so container build/Compose startup have not been executed. Telegram verification used fake transports; the running user bot and its production database were not used for testing.

The latest PostgreSQL-enabled run passed **74 tests**, covering simple counts, weighted/multipart/blank/pending answers, release rules, HTML, review access/images/passages, names, Excel data/timezones/formula escaping, the 44-question import, and preserved Rasch calibration. See [docs/verification.md](docs/verification.md) for the verification scope.

Configure credentials, deployment resources, backups/retention, operator access, and actual exam content before use. Structured logs avoid SQL parameters and answer text. Rate limits allow a burst of eight actions, refilling two actions/second/user. Calibration admits one job at a time with a process timeout; interrupted jobs can be retried. Statistical fit screens require expert assessment of the instrument and cohort.

## Source map

| Path | Responsibility |
| --- | --- |
| `quizbot/db/models.py`, `migrations/` | Normalized database and migration |
| `quizbot/bot/` | Uzbek routers, FSM storage, keyboards, guards |
| `quizbot/services/` | Authorization, transactions, workflows, reports, notifications |
| `quizbot/services/simple_grading.py`, `result_presentation.py`, `excel_export.py`, `scoring.py` | Simple strategy, response metrics, HTML cards, formatted workbook export, strategy interface |
| `quizbot/grading.py`, `quizbot/importing.py` | Raw grading and validated imports/policies |
| `quizbot/psychometrics/`, `quizbot/calibration_worker.py` | Estimation, diagnostics, standardization |
| `quizbot/cli.py`, `quizbot/__main__.py` | CLI and polling lifecycle |
| `examples/`, `tests/`, `.github/workflows/` | Schemas/templates, tests, PostgreSQL CI |
