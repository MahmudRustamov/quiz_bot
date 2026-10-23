from quizbot.services.attempts import AttemptService
from quizbot.services.calibration import CalibrationService
from quizbot.services.exams import ExamService
from quizbot.services.excel_export import ExcelExportService
from quizbot.services.notifications import NotificationService
from quizbot.services.reports import ReportService
from quizbot.services.simple_grading import SimpleGradingService


class Platform(
    ExamService,
    AttemptService,
    CalibrationService,
    ReportService,
    NotificationService,
    SimpleGradingService,
    ExcelExportService,
):
    """Transaction boundaries live in services; Telegram and CLI share authorization."""
