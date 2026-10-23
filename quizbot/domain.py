from enum import StrEnum


class QuestionKind(StrEnum):
    MCQ = "mcq"
    MATCHING = "matching"
    WRITTEN = "written"
    MULTIPART = "multipart"


class DomainError(Exception):
    """Safe, localized error suitable for displaying to the user."""


class Forbidden(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu amal uchun ruxsatingiz yo‘q.")


class CalibrationError(ValueError):
    pass


DISCLAIMER = (
    "Bu mustaqil sinov testi. Natijalar rasmiy davlat sertifikati emas. "
    "Taxminiy daraja kalibrlash sifati va tanlangan guruhga bog‘liq."
)
