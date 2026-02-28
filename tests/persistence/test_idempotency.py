"""Unit tests for idempotency gate."""
from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import DuplicateKeyError

from src.persistence import idempotency


def test_first_time_returns_false(mocker):
    mocker.patch("src.persistence.idempotency.get_db")
    mocker.patch("src.persistence.idempotency._ensure_index")
    mock_col = mocker.patch("src.persistence.idempotency.get_db").return_value.__getitem__.return_value
    mock_col.insert_one.return_value = MagicMock()

    result = idempotency.is_already_processed("causation-123")
    assert result is False


def test_duplicate_returns_true(mocker):
    mocker.patch("src.persistence.idempotency._ensure_index")
    mock_col = mocker.patch("src.persistence.idempotency.get_db").return_value.__getitem__.return_value
    mock_col.insert_one.side_effect = DuplicateKeyError("dup")

    result = idempotency.is_already_processed("causation-123")
    assert result is True
