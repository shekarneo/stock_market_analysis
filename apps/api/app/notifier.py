"""Notification interface and logging implementation.

Notifications use a Notifier interface that logs until a real notification
channel is configured. This does not assume external messaging credentials.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

log = logging.getLogger("app.notifications")


class Notifier(ABC):
    """Abstract notification interface."""

    @abstractmethod
    def notify(
        self,
        level: str,
        title: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Send a notification."""
        pass


class LoggingNotifier(Notifier):
    """Default notifier that emits structured log entries."""

    def notify(
        self,
        level: str,
        title: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        log_level = getattr(logging, level.upper(), logging.INFO)
        extra = {"notification_title": title, "notification_payload": payload or {}}
        log.log(log_level, "[%s] %s: %s", level.upper(), title, message, extra=extra)
