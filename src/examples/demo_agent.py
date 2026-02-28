"""Standalone demo: orchestrator classification without Telegram."""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.utils.logging import setup_logging
from src.llms import client as llm
from src.llms.prompts import ORCHESTRATOR_SYSTEM

setup_logging()


def classify(user_text: str) -> dict:
    messages = [
        {"role": "system", "content": ORCHESTRATOR_SYSTEM},
        {"role": "user", "content": user_text},
    ]
    raw = llm.chat(messages)
    return json.loads(raw)


if __name__ == "__main__":
    samples = [
        "What's the weather in London?",
        "Summarise this PDF for me",
        "Write a Python script to sort a list",
        "Send an email to john@example.com",
        "Remind me to call mom at 5pm",
        "Hello, how are you?",
    ]
    for text in samples:
        result = classify(text)
        print(f"Input:  {text}")
        print(f"Route:  {result}\n")
