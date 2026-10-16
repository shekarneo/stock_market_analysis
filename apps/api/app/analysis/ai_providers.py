"""Configurable AI Model Provider abstraction supporting OpenAI and Google Gemini.

Supports extensible model identifiers, temperature, token limits, timeouts,
per-provider error classification, and explicit fallback handling.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.integrations.http import HttpxCaller, OPENAI_CHAT_URL
from app.security.redact import redact_text

log = logging.getLogger("imm.ai_providers")


@dataclass
class AICompletionResult:
    ok: bool
    provider: str
    model: str
    text: str
    structured_data: dict[str, Any] | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
    fallback_used: bool = False


class BaseAIModelProvider(Protocol):
    name: str

    def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1000,
        timeout: float = 15.0,
    ) -> AICompletionResult:
        ...


class OpenAIModelProvider:
    name: str = "openai"

    def __init__(self, caller: HttpxCaller | None = None, api_key: str | None = None) -> None:
        self.caller = caller or HttpxCaller()
        self._explicit_key = api_key

    def _resolve_api_key(self) -> str | None:
        if self._explicit_key:
            return self._explicit_key
        env_key = os.environ.get("OPENAI_API_KEY")
        if env_key:
            return env_key
        # Check database credentials store
        try:
            from app.db import get_session_factory
            from app.domain.tables import IntegrationCredential
            from app.integrations.crypto import decrypt_secrets
            from app.settings import get_settings

            session = get_session_factory()()
            try:
                row = session.get(IntegrationCredential, "openai")
                if row and row.ciphertext:
                    secrets = decrypt_secrets(get_settings(), row.ciphertext)
                    return secrets.get("api_key")
            finally:
                session.close()
        except Exception:
            pass
        return None

    def generate(
        self,
        messages: list[dict[str, str]],
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        max_tokens: int = 1000,
        timeout: float = 15.0,
    ) -> AICompletionResult:
        api_key = self._resolve_api_key()
        if not api_key:
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                error_code="BLOCKED_PENDING_CREDENTIALS",
                error_message="OpenAI API key is missing or unconfigured.",
            )

        start_time = time.monotonic()
        payload = {
            "model": model,
            "messages": messages,
            "temperature": max(0.0, min(2.0, float(temperature))),
            "max_tokens": int(max_tokens),
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            resp = self.caller.send(
                "POST",
                OPENAI_CHAT_URL,
                headers=headers,
                json_body=payload,
                timeout=timeout,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start_time) * 1000
            clean_err = redact_text(str(exc), [api_key])
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                latency_ms=round(elapsed, 2),
                error_code="PROVIDER_CONNECTION_FAILED",
                error_message=f"OpenAI request failed: {clean_err}",
            )

        elapsed = (time.monotonic() - start_time) * 1000
        body = getattr(resp, "body", {}) or {}
        status_code = getattr(resp, "status_code", 0)

        if status_code != 200:
            err = body.get("error", {}) if isinstance(body.get("error"), dict) else {}
            err_msg = redact_text(str(err.get("message") or f"HTTP {status_code}"), [api_key])
            err_code = str(err.get("code") or f"HTTP_{status_code}")
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                latency_ms=round(elapsed, 2),
                error_code=err_code,
                error_message=err_msg,
            )

        choices = body.get("choices") or []
        raw_text = ""
        if choices and isinstance(choices[0], dict):
            raw_text = (choices[0].get("message") or {}).get("content") or ""

        parsed_json = None
        try:
            parsed_json = json.loads(raw_text) if raw_text else None
        except Exception:
            pass

        usage = body.get("usage") or {}
        return AICompletionResult(
            ok=True,
            provider=self.name,
            model=model,
            text=raw_text,
            structured_data=parsed_json,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            latency_ms=round(elapsed, 2),
        )


class GeminiModelProvider:
    name: str = "gemini"

    def __init__(self, caller: HttpxCaller | None = None, api_key: str | None = None) -> None:
        self.caller = caller or HttpxCaller()
        self._explicit_key = api_key

    def _resolve_api_key(self) -> str | None:
        if self._explicit_key:
            return self._explicit_key
        env_key = os.environ.get("GEMINI_API_KEY")
        if env_key:
            return env_key
        try:
            from app.db import get_session_factory
            from app.domain.tables import IntegrationCredential
            from app.integrations.crypto import decrypt_secrets
            from app.settings import get_settings

            session = get_session_factory()()
            try:
                row = session.get(IntegrationCredential, "gemini")
                if row and row.ciphertext:
                    secrets = decrypt_secrets(get_settings(), row.ciphertext)
                    return secrets.get("api_key")
            finally:
                session.close()
        except Exception:
            pass
        return None

    def generate(
        self,
        messages: list[dict[str, str]],
        model: str = "gemini-1.5-pro",
        temperature: float = 0.0,
        max_tokens: int = 1000,
        timeout: float = 15.0,
    ) -> AICompletionResult:
        api_key = self._resolve_api_key()
        if not api_key:
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                error_code="BLOCKED_PENDING_CREDENTIALS",
                error_message="Gemini API key is missing or unconfigured.",
            )

        start_time = time.monotonic()
        # Format messages into Gemini contents structure
        contents = []
        system_instruction = None
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                system_instruction = {"parts": [{"text": content}]}
            else:
                g_role = "model" if role in {"assistant", "model"} else "user"
                contents.append({"role": g_role, "parts": [{"text": content}]})

        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Generate summary"}]}]

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": max(0.0, min(2.0, float(temperature))),
                "maxOutputTokens": int(max_tokens),
                "responseMimeType": "application/json",
            },
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        clean_model = model.replace("models/", "")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent"
        headers = {
            "x-goog-api-key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            resp = self.caller.send(
                "POST",
                url,
                headers=headers,
                json_body=payload,
                timeout=timeout,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start_time) * 1000
            clean_err = redact_text(str(exc), [api_key])
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                latency_ms=round(elapsed, 2),
                error_code="PROVIDER_CONNECTION_FAILED",
                error_message=f"Gemini request failed: {clean_err}",
            )

        elapsed = (time.monotonic() - start_time) * 1000
        body = getattr(resp, "body", {}) or {}
        status_code = getattr(resp, "status_code", 0)

        if status_code != 200:
            err = body.get("error", {}) if isinstance(body.get("error"), dict) else {}
            err_msg = redact_text(str(err.get("message") or f"HTTP {status_code}"), [api_key])
            err_code = str(err.get("code") or f"HTTP_{status_code}")
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                latency_ms=round(elapsed, 2),
                error_code=err_code,
                error_message=err_msg,
            )

        candidates = body.get("candidates") or []
        raw_text = ""
        if candidates and isinstance(candidates[0], dict):
            c_content = candidates[0].get("content") or {}
            parts = c_content.get("parts") or []
            if parts and isinstance(parts[0], dict):
                raw_text = parts[0].get("text") or ""

        parsed_json = None
        try:
            parsed_json = json.loads(raw_text) if raw_text else None
        except Exception:
            pass

        meta = body.get("usageMetadata") or {}
        return AICompletionResult(
            ok=True,
            provider=self.name,
            model=model,
            text=raw_text,
            structured_data=parsed_json,
            prompt_tokens=meta.get("promptTokenCount", 0),
            completion_tokens=meta.get("candidatesTokenCount", 0),
            total_tokens=meta.get("totalTokenCount", 0),
            latency_ms=round(elapsed, 2),
        )


class AIProviderRegistry:
    """Registry managing available AI model provider instances."""

    _providers: dict[str, BaseAIModelProvider] = {}

    @classmethod
    def get_provider(cls, name: str) -> BaseAIModelProvider:
        clean = name.lower().strip()
        if clean in cls._providers:
            return cls._providers[clean]

        if clean in {"openai", "chatgpt"}:
            provider = OpenAIModelProvider()
        elif clean in {"gemini", "google"}:
            provider = GeminiModelProvider()
        else:
            raise ValueError(f"Unsupported AI model provider '{name}'. Must be 'openai' or 'gemini'.")

        cls._providers[clean] = provider
        return provider

    @classmethod
    def register_provider(cls, name: str, provider: BaseAIModelProvider) -> None:
        cls._providers[name.lower().strip()] = provider

    @classmethod
    def generate_with_fallback(
        cls,
        primary_provider: str,
        primary_model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1000,
        timeout: float = 15.0,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
    ) -> AICompletionResult:
        """Attempt completion with primary provider/model; fall back cleanly if configured and needed."""
        p_provider = cls.get_provider(primary_provider)
        res = p_provider.generate(
            messages=messages,
            model=primary_model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        if res.ok or not fallback_provider or not fallback_model:
            return res

        log.warning(
            "Primary AI provider %s/%s failed (%s: %s). Attempting configured fallback %s/%s",
            primary_provider,
            primary_model,
            res.error_code,
            res.error_message,
            fallback_provider,
            fallback_model,
        )
        fb_provider = cls.get_provider(fallback_provider)
        fb_res = fb_provider.generate(
            messages=messages,
            model=fallback_model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        fb_res.fallback_used = True
        return fb_res
