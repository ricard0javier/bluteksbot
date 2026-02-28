"""File processor — downloads Telegram files and extracts text content."""
import io
import logging
from typing import Optional

import telebot

logger = logging.getLogger(__name__)


def extract_text_from_telegram_file(message: telebot.types.Message) -> Optional[str]:
    """Downloads and extracts text from a Telegram document or photo."""
    bot = _get_bot()
    if not bot:
        return None

    if message.document:
        return _process_document(bot, message.document)
    if message.photo:
        return _process_photo(bot, message.photo)
    return None


def _process_document(bot: telebot.TeleBot, document: telebot.types.Document) -> Optional[str]:
    mime = document.mime_type or ""
    file_info = bot.get_file(document.file_id)
    raw_bytes = bot.download_file(file_info.file_path)

    if "pdf" in mime:
        return _extract_pdf(raw_bytes)
    if "text" in mime:
        return raw_bytes.decode("utf-8", errors="replace")
    if mime in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",):
        return _extract_docx(raw_bytes)

    logger.warning("Unsupported MIME type: %s", mime)
    return None


def _process_photo(bot: telebot.TeleBot, photos: list) -> Optional[str]:
    largest = max(photos, key=lambda p: p.file_size or 0)
    file_info = bot.get_file(largest.file_id)
    raw_bytes = bot.download_file(file_info.file_path)
    return _ocr_image(raw_bytes)


def _extract_pdf(raw_bytes: bytes) -> str:
    # pypdf v6: extract_text() accepts extraction_mode for layout-aware parsing
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw_bytes))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text(extraction_mode="layout") or ""
        pages.append(text)
    return "\n\n".join(pages)


def _extract_docx(raw_bytes: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(raw_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _ocr_image(raw_bytes: bytes) -> str:
    """Basic OCR using pytesseract if available, else returns placeholder."""
    try:
        from PIL import Image
        import pytesseract
        image = Image.open(io.BytesIO(raw_bytes))
        return pytesseract.image_to_string(image)
    except ImportError:
        logger.warning("pytesseract/Pillow not installed — OCR unavailable.")
        return "[Image received — OCR not available]"


def _get_bot() -> Optional[telebot.TeleBot]:
    """Resolve bot instance at call time to avoid circular imports."""
    try:
        from src import config
        return telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=False)
    except Exception:
        logger.error("Could not initialise bot for file download.", exc_info=True)
        return None
