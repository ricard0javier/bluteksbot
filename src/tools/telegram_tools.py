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
    """
    Upload an image from disk and show it as a photo in the current Telegram chat (optional caption).
    Use when the user should see a picture inline (screenshots, charts, JPEG/PNG/GIF/WebP). Prefer send_telegram_document if they need the original file as a generic attachment without photo handling, or for non-images. Do not use for video, voice notes, or music—use send_telegram_video, send_telegram_voice, or send_telegram_audio.
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
    """
    Send a file from disk as a Telegram document (downloadable attachment) in the current chat.
    Use for PDFs, archives, spreadsheets, source files, or any path that should arrive as a file, not inline media. Prefer send_telegram_photo for images meant to display as a picture, send_telegram_video for video, send_telegram_voice/send_telegram_audio for audio. Not for email—use send_email_tool if the user asked for email delivery.
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
    """
    Send a voice note from disk (Telegram expects OGG Opus) in the current chat.
    Use for short spoken-style messages that should appear as a voice bubble. Prefer send_telegram_audio for music or longer tracks with a player UI (MP3/M4A, title metadata). Do not use for images, video, or arbitrary documents.
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
    """
    Send an audio file as a music-style message with player UI and optional title/caption in the current chat.
    Use for songs, podcasts, or longer audio where Telegram should show a player (typical formats e.g. MP3/M4A). Prefer send_telegram_voice for short voice-note style OGG Opus clips. Do not use for video or still images.
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
    """
    Upload a video file from disk and play it in the current Telegram chat (optional caption; MP4 is typical).
    Use when the user should receive motion/video, not a static image or audio-only file. Prefer send_telegram_photo for images, send_telegram_document if they need the raw file without inline playback, send_telegram_audio/send_telegram_voice for sound-only.
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
