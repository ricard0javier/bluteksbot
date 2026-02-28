"""Unit tests for Telegram consumer access control."""
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.telegram.consumer import TelegramConsumer


@pytest.fixture
def consumer(mocker):
    mocker.patch("telebot.TeleBot.__init__", return_value=None)
    mocker.patch("telebot.TeleBot.message_handler", return_value=lambda f: f)
    stop_event = threading.Event()
    c = TelegramConsumer.__new__(TelegramConsumer)
    c._stop = stop_event
    c._bot = MagicMock()
    return c


def test_allows_when_no_allowlist(consumer):
    consumer._bot = MagicMock()
    with patch("src.telegram.consumer.config") as cfg:
        cfg.TELEGRAM_ALLOWED_USER_IDS = []
        assert consumer._is_allowed(999) is True


def test_blocks_unlisted_user(consumer):
    with patch("src.telegram.consumer.config") as cfg:
        cfg.TELEGRAM_ALLOWED_USER_IDS = [111, 222]
        assert consumer._is_allowed(999) is False


def test_allows_listed_user(consumer):
    with patch("src.telegram.consumer.config") as cfg:
        cfg.TELEGRAM_ALLOWED_USER_IDS = [111, 222]
        assert consumer._is_allowed(111) is True
