"""OpenAI model retrieve and one bounded chat completion.

The model lookup is a credential check. The completion is optional commentary.
Neither call chooses a fallback model.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from app.integrations.http import OPENAI_CHAT_URL, OPENAI_MODELS_URL

TIMEOUT = 10.0
COMPLETION_TIMEOUT = 15.0
MODEL_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
MODEL_PATTERN_MESSAGE = "Model ids use letters, digits, and . _ : - only."


def model_url(model: str) -> str:
    return OPENAI_MODELS_URL + quote(model, safe="")


def retrieve_model(caller, *, api_key: str, model: str):
    return caller.send(
        "GET",
        model_url(model),
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        json_body=None,
        timeout=TIMEOUT,
    )


def classify(result, *, api_key: str, model: str) -> tuple[bool, str, str]:
    body = result.body or {}
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = str(error.get("code") or error.get("type") or "")
    if result.status_code == 401 or result.status_code == 403:
        return False, "INVALID_CREDENTIALS", "OpenAI rejected the API key."
    if result.status_code == 404:
        return False, "MODEL_UNAVAILABLE", "OpenAI does not offer that model to this key."
    if result.status_code == 402 or "insufficient_quota" in code or "billing" in code:
        return False, "QUOTA_EXCEEDED", "OpenAI reported a quota or billing limit."
    if result.status_code == 429:
        return False, "RATE_LIMITED", "OpenAI rate-limited the model request. It was not retried."
    if result.status_code >= 500:
        return False, "PROVIDER_UNAVAILABLE", "OpenAI could not serve the model request."
    if result.status_code == 200 and body.get("id") == model:
        return True, "CONNECTED", "The model record was retrieved. No completion or forecast was requested."
    return False, "SCHEMA_MISMATCH", "The model response did not match the requested model."


def complete_json(caller, *, api_key: str, model: str, messages: list[dict]) -> object:
    """One chat completion. This function does not retry. The allow-list permits only the fixed chat URL."""
    if not MODEL_RE.fullmatch(model or ""):
        raise ValueError("INVALID_MODEL")
    return caller.send(
        "POST",
        OPENAI_CHAT_URL,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "Content-Type": "application/json"},
        json_body={
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": 400,
            "temperature": 0,
        },
        timeout=COMPLETION_TIMEOUT,
    )


def classify_completion(result, *, api_key: str) -> tuple[bool, str, str, dict]:
    body = result.body if isinstance(result.body, dict) else {}
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = str(error.get("code") or error.get("type") or "")
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    meta = {
        "status_code": result.status_code,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
    }
    if result.status_code in {401, 403}:
        return False, "INVALID_CREDENTIALS", "OpenAI rejected the API key.", meta
    if result.status_code == 404:
        return False, "MODEL_UNAVAILABLE", "OpenAI does not offer that model to this key.", meta
    if result.status_code == 402 or "insufficient_quota" in code:
        return False, "QUOTA_EXCEEDED", "OpenAI reported a quota or billing limit.", meta
    if result.status_code == 429:
        return False, "RATE_LIMITED", "OpenAI rate-limited the completion. It was not retried.", meta
    if result.status_code >= 500:
        return False, "PROVIDER_UNAVAILABLE", "OpenAI could not serve the completion.", meta
    if result.status_code != 200:
        return False, "PROVIDER_ERROR", "OpenAI rejected the completion.", meta
    if not isinstance(result.body, dict):
        return False, "SCHEMA_MISMATCH", "The completion body was not a JSON object.", meta
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return False, "SCHEMA_MISMATCH", "The completion had no choice.", meta
    if choices[0].get("finish_reason") == "length":
        return False, "MALFORMED_OUTPUT", "The completion was truncated and was not used.", meta
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    content = message.get("content")
    if content is None or (isinstance(content, str) and not content.strip()):
        return False, "EMPTY_OUTPUT", "The completion content was empty.", meta
    if not isinstance(content, str):
        return False, "MALFORMED_OUTPUT", "The completion content was not text.", meta
    meta["content"] = content
    return True, "COMPLETED", "The completion returned JSON text.", meta
