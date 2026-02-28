"""Shared pytest fixtures."""
import threading
import pytest


@pytest.fixture
def stop_event() -> threading.Event:
    return threading.Event()


@pytest.fixture(autouse=True)
def mock_mongo(mocker):
    mocker.patch("src.persistence.client.get_client")
    mocker.patch("src.persistence.client.get_db")
