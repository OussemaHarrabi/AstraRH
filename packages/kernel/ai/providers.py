"""Model providers. SDKs are imported lazily: only the worker image has them installed."""

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from kernel.errors import KernelError, ProviderUnavailable

# USD per million tokens.
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "openai/gpt-oss-20b": (Decimal("0.075"), Decimal("0.30")),
    "openai/gpt-oss-120b": (Decimal("0.15"), Decimal("0.60")),
}
ANTHROPIC_MODEL_PREFIX = "claude-"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
REQUEST_TIMEOUT_SECONDS = 60


class ModelRefused(KernelError):
    """The model declined. Not a provider outage, so no fallback is attempted."""

    status_code = 422
    code = "model_refused"


@dataclass(frozen=True)
class LlmResponse:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    model: str

    @property
    def cost_usd(self) -> Decimal:
        price_in, price_out = PRICES.get(self.model, (Decimal(0), Decimal(0)))
        return (price_in * self.input_tokens + price_out * self.output_tokens) / Decimal(1_000_000)


class Provider(Protocol):
    def complete(
        self, model: str, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> LlmResponse: ...


def strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a Pydantic schema acceptable to strict structured outputs."""
    node = json.loads(json.dumps(schema))

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            item.pop("title", None)
            item.pop("default", None)
            if item.get("type") == "object" or "properties" in item:
                item["additionalProperties"] = False
                item["required"] = list(item.get("properties", {}))
            for value in item.values():
                visit(value)
        elif isinstance(item, list):
            for value in item:
                visit(value)

    visit(node)
    return node


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic

        self._sdk = anthropic
        self._client = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=2,
        )

    def complete(
        self, model: str, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> LlmResponse:
        sdk = self._sdk
        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except (
            sdk.RateLimitError,
            sdk.AuthenticationError,
            sdk.PermissionDeniedError,
            sdk.APIConnectionError,
        ) as exc:
            raise ProviderUnavailable(f"Anthropic: {type(exc).__name__}") from exc
        except sdk.APIStatusError as exc:
            # A 400 can mean exhausted credit, which the fallback can still serve.
            raise ProviderUnavailable(f"Anthropic: HTTP {exc.status_code}") from exc
        if response.stop_reason == "refusal":
            raise ModelRefused("The model declined this request")
        if response.stop_reason == "max_tokens":
            raise ProviderUnavailable("Anthropic: response cut off at max_tokens")
        text = next((block.text for block in response.content if block.type == "text"), "")
        return LlmResponse(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            provider=self.name,
            model=model,
        )


class GroqProvider:
    name = "groq"

    def __init__(self) -> None:
        import openai

        self._sdk = openai
        self._client = openai.OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url=GROQ_BASE_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=2,
        )

    def complete(
        self, model: str, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> LlmResponse:
        try:
            response = self._client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "output", "strict": True, "schema": schema},
                },
            )
        except self._sdk.APIError as exc:
            raise ProviderUnavailable(f"Groq: {type(exc).__name__}") from exc
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ProviderUnavailable("Groq: response cut off at max tokens")
        return LlmResponse(
            text=choice.message.content or "",
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            provider=self.name,
            model=model,
        )


def provider_for(model: str) -> Provider:
    if model.startswith(ANTHROPIC_MODEL_PREFIX):
        return AnthropicProvider()
    return GroqProvider()
