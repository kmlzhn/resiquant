"""LLM client — Perplexity API."""
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import APITimeoutError, OpenAI

load_dotenv()

_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
_MODEL   = os.getenv("PERPLEXITY_MODEL", "sonar-pro")
_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))

# Perplexity sonar-pro pricing per 1M tokens (USD)
_PRICE_INPUT  = 3.0
_PRICE_OUTPUT = 15.0

_client = OpenAI(
    api_key=_API_KEY,
    base_url="https://api.perplexity.ai",
    timeout=httpx.Timeout(_TIMEOUT, connect=5.0),
)


@dataclass
class LLMResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def call_llm(system_prompt: str, user_prompt: str) -> LLMResponse:
    try:
        response = _client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.0,
        )
    except APITimeoutError as e:
        raise TimeoutError(f"Perplexity request timed out after {_TIMEOUT}s") from e

    usage = response.usage
    return LLMResponse(
        content=response.choices[0].message.content or "",
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=usage.total_tokens if usage else 0,
    )


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return round(
        prompt_tokens     / 1_000_000 * _PRICE_INPUT +
        completion_tokens / 1_000_000 * _PRICE_OUTPUT,
        6,
    )


def extract_json_from_response(text: str) -> dict[str, Any]:
    """Strip markdown fences and parse JSON from LLM response."""
    text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON found in response: {text[:200]}")
    return json.loads(text[start:end + 1])
