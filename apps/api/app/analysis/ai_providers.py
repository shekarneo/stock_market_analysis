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
    primary_error_code: str | None = None
    primary_error_message: str | None = None


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
        # Check database credentials store first so operator UI settings and enable/disable toggle take precedence
        try:
            from app.db import get_session_factory
            from app.domain.tables import IntegrationCredential
            from app.integrations.crypto import decrypt_secrets
            from app.settings import get_settings

            session = get_session_factory()()
            try:
                row = session.get(IntegrationCredential, "openai")
                if row is not None:
                    if row.enabled is False:
                        return None
                    if row.ciphertext:
                        secrets = decrypt_secrets(get_settings(), row.ciphertext)
                        db_key = (secrets.get("api_key") or "").strip()
                        if db_key:
                            return db_key
            finally:
                session.close()
        except Exception:
            pass
        env_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        if env_key:
            return env_key
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
                error_message="OpenAI API key is missing, unconfigured, or integration is disabled.",
            )

        start_time = time.monotonic()
        clean_model = (model or "").strip()
        is_reasoning = clean_model.lower().startswith(("o1", "o3"))
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if is_reasoning:
            payload["max_completion_tokens"] = int(max_tokens)
            if not clean_model.lower().startswith(("o1-mini", "o1-preview")):
                payload["response_format"] = {"type": "json_object"}
        else:
            payload["temperature"] = max(0.0, min(2.0, float(temperature)))
            payload["max_tokens"] = int(max_tokens)
            payload["response_format"] = {"type": "json_object"}

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

        usage = body.get("usage") or {}
        p_tok = int(usage.get("prompt_tokens", 0) or 0)
        c_tok = int(usage.get("completion_tokens", 0) or 0)
        t_tok = int(usage.get("total_tokens", p_tok + c_tok) or 0)

        choices = body.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="EMPTY_OUTPUT",
                error_message="OpenAI response contained no choices.",
            )

        if choices[0].get("finish_reason") == "length":
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="TRUNCATED_OUTPUT",
                error_message="OpenAI completion was truncated at token limit.",
            )

        raw_text = (choices[0].get("message") or {}).get("content") or ""
        if not isinstance(raw_text, str) or not raw_text.strip():
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="EMPTY_OUTPUT",
                error_message="OpenAI completion content was empty.",
            )

        try:
            parsed_json = json.loads(raw_text)
        except Exception:
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text=raw_text,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="MALFORMED_OUTPUT",
                error_message="OpenAI completion content was not valid JSON.",
            )

        if not isinstance(parsed_json, dict):
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text=raw_text,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="SCHEMA_MISMATCH",
                error_message="OpenAI JSON output root must be a JSON object.",
            )

        return AICompletionResult(
            ok=True,
            provider=self.name,
            model=model,
            text=raw_text,
            structured_data=parsed_json,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            total_tokens=t_tok,
            latency_ms=round(elapsed, 2),
        )


class GeminiModelProvider:
    name: str = "gemini"

    def __init__(self, caller: HttpxCaller | None = None, api_key: str | None = None) -> None:
        self.caller = caller or HttpxCaller()
        self._explicit_key = api_key

    def _resolve_api_keys(self) -> list[str]:
        if self._explicit_key:
            return [self._explicit_key]
        keys: list[str] = []
        # Check database credentials store first so operator UI settings and enable/disable toggle take precedence
        try:
            from app.db import get_session_factory
            from app.domain.tables import IntegrationCredential
            from app.integrations.crypto import decrypt_secrets
            from app.settings import get_settings

            session = get_session_factory()()
            try:
                row = session.get(IntegrationCredential, "gemini")
                if row is not None:
                    if row.enabled is False:
                        return []
                    if row.ciphertext:
                        secrets = decrypt_secrets(get_settings(), row.ciphertext)
                        db_key = (secrets.get("api_key") or "").strip()
                        if db_key:
                            keys.append(db_key)
            finally:
                session.close()
        except Exception:
            pass
        env_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if env_key and env_key not in keys:
            keys.append(env_key)
        env_keys = (os.environ.get("GEMINI_API_KEYS") or "").strip()
        if env_keys:
            for k in env_keys.split(","):
                ks = k.strip()
                if ks and ks not in keys:
                    keys.append(ks)
        return keys

    def _resolve_api_key(self) -> str | None:
        keys = self._resolve_api_keys()
        return keys[0] if keys else None

    def generate(
        self,
        messages: list[dict[str, str]],
        model: str = "gemini-flash-latest",
        temperature: float = 0.0,
        max_tokens: int = 1000,
        timeout: float = 15.0,
    ) -> AICompletionResult:
        api_keys = self._resolve_api_keys()
        if not api_keys:
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                error_code="BLOCKED_PENDING_CREDENTIALS",
                error_message="Gemini API key is missing, unconfigured, or integration is disabled.",
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

        clean_model = model.replace("models/", "")
        effective_max_tokens = (
            max(int(max_tokens), 1024)
            if ("gemini-3" in clean_model or "latest" in clean_model)
            else int(max_tokens)
        )
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": max(0.0, min(2.0, float(temperature))),
                "maxOutputTokens": effective_max_tokens,
                "responseMimeType": "application/json",
            },
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        def _send_once(target_model: str, target_key: str, req_payload: dict[str, Any]):
            target_url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent"
            req_headers = {
                "x-goog-api-key": target_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            return self.caller.send(
                "POST",
                target_url,
                headers=req_headers,
                json_body=req_payload,
                timeout=timeout,
            )

        api_key = api_keys[0]
        resp = None
        try:
            for idx, candidate_key in enumerate(api_keys):
                api_key = candidate_key
                resp = _send_once(clean_model, api_key, payload)
                status_code = getattr(resp, "status_code", 0)
                # If a retired legacy Gemini model (1.5 / 2.0 / 2.5) returns 404 on live API, upgrade to gemini-flash-latest
                if (
                    status_code == 404
                    and self._explicit_key is None
                    and clean_model != "gemini-flash-latest"
                    and any(ver in clean_model for ver in ("1.5", "2.0", "2.5"))
                ):
                    clean_model = "gemini-flash-latest"
                    model = "gemini-flash-latest"
                    payload["generationConfig"]["maxOutputTokens"] = max(int(max_tokens), 1024)
                    resp = _send_once(clean_model, api_key, payload)
                    status_code = getattr(resp, "status_code", 0)
                if status_code == 503 and self._explicit_key is None:
                    alt_model = "gemini-3.8-flash" if clean_model != "gemini-3.8-flash" else "gemini-flash-latest"
                    payload["generationConfig"]["maxOutputTokens"] = max(int(max_tokens), 1024)
                    resp = _send_once(alt_model, api_key, payload)
                    status_code = getattr(resp, "status_code", 0)
                    if status_code == 200:
                        clean_model = alt_model
                        model = alt_model
                if status_code in {429, 503} and idx + 1 < len(api_keys):
                    continue
                break
        except Exception as exc:
            elapsed = (time.monotonic() - start_time) * 1000
            clean_err = redact_text(str(exc), api_keys)
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
            err_msg = redact_text(str(err.get("message") or f"HTTP {status_code}"), api_keys)
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

        meta = body.get("usageMetadata") or {}
        p_tok = int(meta.get("promptTokenCount", 0) or 0)
        c_tok = int(meta.get("candidatesTokenCount", 0) or 0)
        t_tok = int(meta.get("totalTokenCount", p_tok + c_tok) or 0)

        prompt_feedback = body.get("promptFeedback") or {}
        if isinstance(prompt_feedback, dict) and prompt_feedback.get("blockReason"):
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="SAFETY_BLOCKED",
                error_message=f"Gemini blocked prompt: {prompt_feedback.get('blockReason')}",
            )

        candidates = body.get("candidates") or []
        if not candidates or not isinstance(candidates[0], dict):
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="EMPTY_OUTPUT",
                error_message="Gemini response contained no candidates.",
            )

        finish_reason = str(candidates[0].get("finishReason") or "").upper()
        if finish_reason in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="SAFETY_BLOCKED",
                error_message=f"Gemini candidate blocked with finishReason={finish_reason}.",
            )
        if finish_reason == "MAX_TOKENS":
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="TRUNCATED_OUTPUT",
                error_message="Gemini candidate truncated at maxOutputTokens.",
            )

        raw_text = ""
        c_content = candidates[0].get("content") or {}
        parts = c_content.get("parts") or []
        if parts and isinstance(parts[0], dict):
            raw_text = parts[0].get("text") or ""

        if not isinstance(raw_text, str) or not raw_text.strip():
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text="",
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="EMPTY_OUTPUT",
                error_message="Gemini candidate content was empty.",
            )

        try:
            parsed_json = json.loads(raw_text)
        except Exception:
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text=raw_text,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="MALFORMED_OUTPUT",
                error_message="Gemini completion content was not valid JSON.",
            )

        if not isinstance(parsed_json, dict):
            return AICompletionResult(
                ok=False,
                provider=self.name,
                model=model,
                text=raw_text,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                latency_ms=round(elapsed, 2),
                error_code="SCHEMA_MISMATCH",
                error_message="Gemini JSON output root must be a JSON object.",
            )

        return AICompletionResult(
            ok=True,
            provider=self.name,
            model=model,
            text=raw_text,
            structured_data=parsed_json,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            total_tokens=t_tok,
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
        fb_res.primary_error_code = res.error_code
        fb_res.primary_error_message = res.error_message
        return fb_res

