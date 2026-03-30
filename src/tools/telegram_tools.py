"""LangChain tools that allow the agent to send media back to the user via Telegram."""

import logging
import os

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


def _chat_id(config: RunnableConfig) -> int:
    return int(config["configurable"]["thread_id"])


@tool
def send_telegram_photo(file_path: str, caption: str, config: RunnableConfig) -> str:
    """Send a photo/image file to the user in the current Telegram chat.

    Args:
        file_path: Absolute or workspace-relative path to the image file
                   (JPEG, PNG, GIF, WebP, etc.).
        caption: Optional caption shown below the photo (can be empty string).
    """
    from src.telegram.state import get_bot

    bot = get_bot()
    chat_id = _chat_id(config)
    if not os.path.isfile(file_path):
        return f"File not found: {file_path}"
    try:
        with open(file_path, "rb") as f:
            bot.send_photo(chat_id, f, caption=caption or None)
        logger.info("Sent photo to chat=%s: %s", chat_id, file_path)
        return "Photo sent."
    except Exception as exc:
        logger.error("Failed to send photo to chat=%s: %s", chat_id, exc)
        return f"Failed to send photo: {exc}"


@tool
def send_telegram_document(file_path: str, caption: str, config: RunnableConfig) -> str:
    """Send any file as a document/attachment to the user in the current Telegram chat.

    Suitable for PDFs, spreadsheets, code files, archives, or any binary/text file.

    Args:
        file_path: Absolute or workspace-relative path to the file.
        caption: Optional caption shown with the document (can be empty string).
    """
    from src.telegram.state import get_bot

    bot = get_bot()
    chat_id = _chat_id(config)
    if not os.path.isfile(file_path):
        return f"File not found: {file_path}"
    try:
        with open(file_path, "rb") as f:
            bot.send_document(chat_id, f, caption=caption or None)
        logger.info("Sent document to chat=%s: %s", chat_id, file_path)
        return "Document sent."
    except Exception as exc:
        logger.error("Failed to send document to chat=%s: %s", chat_id, exc)
        return f"Failed to send document: {exc}"


@tool
def send_telegram_voice(file_path: str, config: RunnableConfig) -> str:
    """Send an audio file as a voice message to the user in the current Telegram chat.

    IMPORTANT:The file must be OGG/Opus format.

    Args:
        file_path: Absolute or workspace-relative path to the audio file.
    """
    from src.telegram.state import get_bot

    bot = get_bot()
    chat_id = _chat_id(config)
    if not os.path.isfile(file_path):
        return f"File not found: {file_path}"
    try:
        with open(file_path, "rb") as f:
            bot.send_voice(chat_id, f)
        logger.info("Sent voice to chat=%s: %s", chat_id, file_path)
        return "Voice message sent."
    except Exception as exc:
        logger.error("Failed to send voice to chat=%s: %s", chat_id, exc)
        return f"Failed to send voice: {exc}"


@tool
def send_telegram_audio(
    file_path: str, title: str, caption: str, config: RunnableConfig
) -> str:
    """Send an audio file as a music track to the user in the current Telegram chat.

    Displayed with a player in Telegram (not as a voice note). Use for music or
    longer audio. For short spoken messages prefer send_telegram_voice.

    Args:
        file_path: Absolute or workspace-relative path to the audio file (MP3, M4A, etc.).
        title: Track title shown in Telegram's audio player.
        caption: Optional caption (can be empty string).
    """
    from src.telegram.state import get_bot

    bot = get_bot()
    chat_id = _chat_id(config)
    if not os.path.isfile(file_path):
        return f"File not found: {file_path}"
    try:
        with open(file_path, "rb") as f:
            bot.send_audio(chat_id, f, title=title or None, caption=caption or None)
        logger.info("Sent audio to chat=%s: %s", chat_id, file_path)
        return "Audio sent."
    except Exception as exc:
        logger.error("Failed to send audio to chat=%s: %s", chat_id, exc)
        return f"Failed to send audio: {exc}"


@tool
def send_telegram_video(file_path: str, caption: str, config: RunnableConfig) -> str:
    """Send a video file to the user in the current Telegram chat.

    Args:
        file_path: Absolute or workspace-relative path to the video file (MP4 preferred).
        caption: Optional caption shown below the video (can be empty string).
    """
    from src.telegram.state import get_bot

    bot = get_bot()
    chat_id = _chat_id(config)
    if not os.path.isfile(file_path):
        return f"File not found: {file_path}"
    try:
        with open(file_path, "rb") as f:
            bot.send_video(chat_id, f, caption=caption or None)
        logger.info("Sent video to chat=%s: %s", chat_id, file_path)
        return "Video sent."
    except Exception as exc:
        logger.error("Failed to send video to chat=%s: %s", chat_id, exc)
        return f"Failed to send video: {exc}"


TELEGRAM_TOOLS = [
    send_telegram_photo,
    send_telegram_document,
    send_telegram_voice,
    send_telegram_audio,
    send_telegram_video,
]
