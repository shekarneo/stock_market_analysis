from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config.schemas import AppConfig
from app.errors import ConfigValidationError


def load_defaults(path: Path) -> AppConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigValidationError(exc.json()) from exc


def parse_document(raw: dict) -> AppConfig:
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigValidationError(exc.json()) from exc
