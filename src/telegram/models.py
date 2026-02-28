"""Pydantic models for inbound Telegram update contracts."""
from typing import Optional
from pydantic import BaseModel


class TelegramUser(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    is_bot: bool = False


class TelegramChat(BaseModel):
    id: int
    type: str
    title: Optional[str] = None
    username: Optional[str] = None


class TelegramDocument(BaseModel):
    file_id: str
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None


class TelegramMessage(BaseModel):
    message_id: int
    from_user: Optional[TelegramUser] = None
    chat: TelegramChat
    text: Optional[str] = None
    caption: Optional[str] = None
    document: Optional[TelegramDocument] = None
    photo: Optional[list[dict]] = None
    date: int = 0


class InboundUpdate(BaseModel):
    update_id: int
    message: Optional[TelegramMessage] = None
