"""Structured failures for the visual assistant. Messages stay free of media and secrets."""
from __future__ import annotations


class AssistantError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def scrub(message: str, secret: str) -> str:
    if secret and secret in message:
        return 'Gemini could not complete the request.'
    return message
