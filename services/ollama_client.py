"""
Local LLM via Ollama HTTP API (no cloud API keys).

Environment:
  OLLAMA_BASE_URL     — default http://localhost:11434
  OLLAMA_TEXT_MODEL   — default qwen2.5:7b (risk, tariff, HS search)
  OLLAMA_VISION_MODEL — default llava (OCR / image); override with e.g. qwen2.5vl:7b
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import httpx

_DEFAULT_BASE = "http://localhost:11434"
_DEFAULT_TEXT = "aya-expanse:latest"
_DEFAULT_VISION = "aya-expanse:latest"


def ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", _DEFAULT_BASE).rstrip("/")


def ollama_text_model() -> str:
    return os.environ.get("OLLAMA_TEXT_MODEL", _DEFAULT_TEXT)


def ollama_vision_model() -> str:
    return os.environ.get("OLLAMA_VISION_MODEL", _DEFAULT_VISION)


def _strip_data_url_base64(b64: str) -> str:
    s = (b64 or "").strip()
    if s.startswith("data:") and "base64," in s:
        return s.split("base64,", 1)[1].strip()
    return s


def _ollama_timeout() -> httpx.Timeout:
    return httpx.Timeout(connect=15.0, read=600.0, write=60.0, pool=15.0)


async def ollama_chat(
    messages: list[dict[str, Any]],
    *,
    model: Optional[str] = None,
    json_mode: bool = False,
) -> str:
    """
    POST /api/chat — returns assistant message content (non-streaming).
    """
    url = f"{ollama_base_url()}/api/chat"
    body: dict[str, Any] = {
        "model": model or ollama_text_model(),
        "messages": messages,
        "stream": False,
    }
    if json_mode:
        body["format"] = "json"

    async with httpx.AsyncClient(timeout=_ollama_timeout()) as client:
        r = await client.post(url, json=body)
        r.raise_for_status()
        data = r.json()

    msg = data.get("message") or {}
    content = msg.get("content")
    if content is None:
        raise RuntimeError(f"Ollama response missing message.content: {str(data)[:500]}")
    return str(content).strip()


async def ollama_chat_text(
    system_prompt: str,
    user_prompt: str,
    *,
    model: Optional[str] = None,
    json_mode: bool = True,
) -> str:
    messages: list[dict[str, Any]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": user_prompt.strip()})
    return await ollama_chat(messages, model=model or ollama_text_model(), json_mode=json_mode)


async def ollama_chat_vision(
    system_prompt: str,
    user_text: str,
    image_base64: str,
    *,
    model: Optional[str] = None,
) -> str:
    """Vision: user message may include `images` (list of base64 strings, no data: prefix)."""
    img = _strip_data_url_base64(image_base64)
    messages: list[dict[str, Any]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append(
        {
            "role": "user",
            "content": user_text.strip(),
            "images": [img],
        }
    )
    # Vision models often ignore JSON schema format; prompt asks for JSON explicitly.
    return await ollama_chat(messages, model=model or ollama_vision_model(), json_mode=False)


def parse_json_response(raw: str) -> dict:
    """Strip markdown fences and parse first JSON object."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return {}
