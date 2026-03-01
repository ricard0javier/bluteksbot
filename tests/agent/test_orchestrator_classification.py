"""Unit tests for orchestrator classification routing."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agent.orchestrator import Orchestrator


@pytest.fixture
def orchestrator():
    bot = MagicMock()
    return Orchestrator(bot=bot)


def test_classify_returns_valid_decision(orchestrator, mocker):
    mocker.patch(
        "src.agent.orchestrator.llm.chat",
        return_value=json.dumps({"agent": "search_agent", "task": "latest AI news"}),
    )
    mocker.patch("src.agent.orchestrator.embed", return_value=[0.1] * 1536)
    mocker.patch("src.agent.orchestrator.search_memory", return_value=[])

    decision = orchestrator._classify("latest AI news", "")
    assert decision.agent == "search_agent"
    assert "AI" in decision.task


def test_classify_fallback_on_bad_json(orchestrator, mocker):
    mocker.patch("src.agent.orchestrator.llm.chat", return_value="not json")

    decision = orchestrator._classify("hello", "")
    assert decision.agent == "chat_agent"
