"""Unit tests for telegram producer classification routing."""

import json
from unittest.mock import MagicMock

import pytest

from src.telegram.producer import TelegramProducer


@pytest.fixture
def telegram_producer():
    bot = MagicMock()
    agent = MagicMock()
    return TelegramProducer(bot=bot, agent=agent)


def test_classify_returns_valid_decision(telegram_producer, mocker):
    mocker.patch(
        "src.telegram.producer.llm.chat",
        return_value=json.dumps({"agent": "search_agent", "task": "latest AI news"}),
    )
    mocker.patch("src.telegram.producer.embed", return_value=[0.1] * 1536)
    mocker.patch("src.telegram.producer.search_memory", return_value=[])

    decision = telegram_producer._classify("latest AI news", "")
    assert decision.agent == "search_agent"
    assert "AI" in decision.task


def test_classify_fallback_on_bad_json(telegram_producer, mocker):
    mocker.patch("src.telegram.producer.llm.chat", return_value="not json")

    decision = telegram_producer._classify("hello", "")
    assert decision.agent == "chat_agent"
