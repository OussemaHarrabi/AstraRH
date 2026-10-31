"""The only path to model providers. Packs ask for a tier, never a model.

This API deliberately has no tools parameter: a model reached through it can only return
structured data, so untrusted text can never trigger an action.

Each call: masks identifiers, enforces budgets, checks the cache, falls back between
providers, validates the schema, and records tokens, cost and hashes with no content.
"""

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeVar
from uuid import UUID

from opentelemetry import metrics, trace
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from kernel.ai import pii
from kernel.ai.models import AgentRun, AgentStep, LlmCache
from kernel.ai.providers import LlmResponse, Provider, provider_for, strict_json_schema
from kernel.canonical import canonical_json, sha256_hex
from kernel.errors import BudgetExceeded, ProviderUnavailable, SecurityCheckUnavailable

T = TypeVar("T", bound=BaseModel)

DEFAULT_RUN_TOKEN_BUDGET = 40_000
DEFAULT_TENANT_DAILY_TOKEN_BUDGET = 2_000_000
DEFAULT_MAX_TOKENS = 4096

log = logging.getLogger("astra.gateway")
tracer = trace.get_tracer("astra.gateway")
meter = metrics.get_meter("astra.gateway")
tokens_counter = meter.create_counter("astra.llm.tokens", unit="token")
cost_counter = meter.create_counter("astra.llm.cost", unit="USD")
calls_counter = meter.create_counter("astra.llm.calls")
latency_histogram = meter.create_histogram("astra.llm.latency", unit="ms")


class SchemaFailure(ProviderUnavailable):
    code = "schema_validation_failed"


@dataclass(frozen=True)
class PromptRef:
    name: str
    text: str

    @property
    def hash(self) -> str:
        return sha256_hex(self.text)


def models_for_tier(tier: str) -> list[str]:
    primary = {
        "fast": os.environ["LLM_FAST_MODEL"],
        "standard": os.environ["LLM_STANDARD_MODEL"],
    }[tier]
    fallback = os.environ.get("LLM_FALLBACK_MODEL")
    return [primary, fallback] if fallback and fallback != primary else [primary]


def _budget_guard(session: Session, run_id: UUID | None, run_budget: int) -> None:
    """A database error propagates and denies the call: an unverifiable counter is a no."""
    if run_id is not None:
        run = session.get(AgentRun, run_id)
        if run is not None and run.input_tokens + run.output_tokens >= run_budget:
            raise BudgetExceeded("This agent run has used its token budget")
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = session.scalar(
        select(func.coalesce(func.sum(AgentStep.input_tokens + AgentStep.output_tokens), 0)).where(
            AgentStep.created_at >= today
        )
    )
    limit = int(os.environ.get("LLM_TENANT_DAILY_TOKENS", DEFAULT_TENANT_DAILY_TOKEN_BUDGET))
    if used >= limit:
        raise BudgetExceeded("The daily token budget has been reached")


def _parse(schema: type[T], text: str) -> T:
    try:
        return schema.model_validate_json(text)
    except ValidationError as exc:
        raise SchemaFailure("The model's output did not match the schema") from exc


class Gateway:
    def __init__(self, provider_factory: Callable[[str], Provider] = provider_for) -> None:
        self._provider_factory = provider_factory

    def structured(
        self,
        session: Session,
        tenant_id: UUID,
        tier: str,
        prompt: PromptRef,
        user: str,
        schema: type[T],
        run_id: UUID | None = None,
        step_name: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        run_budget: int = DEFAULT_RUN_TOKEN_BUDGET,
    ) -> T:
        name = step_name or prompt.name
        with tracer.start_as_current_span(
            f"llm {name}",
            attributes={
                "gen_ai.operation.name": "chat",
                "astra.tier": tier,
                "astra.prompt_hash": prompt.hash,
            },
        ) as span:
            try:
                masked = pii.mask(user)
            except Exception as exc:
                raise SecurityCheckUnavailable("Identifier masking failed") from exc
            span.set_attribute("astra.pii.masked", sum(masked.counts.values()))

            models = models_for_tier(tier)
            json_schema = strict_json_schema(schema.model_json_schema())
            input_hash = sha256_hex(masked.text)
            cache_key = sha256_hex(
                canonical_json(
                    {
                        "prompt": prompt.hash,
                        "input": input_hash,
                        "schema": json_schema,
                        "tier": tier,
                    }
                )
            )

            cached = session.scalar(select(LlmCache).where(LlmCache.key == cache_key))
            if cached is not None:
                try:
                    result = schema.model_validate_json(cached.response)
                except ValidationError:
                    log.warning("Ignoring invalid cache entry for %s", name)
                else:
                    span.set_attribute("astra.cached", True)
                    calls_counter.add(1, {"tier": tier, "cached": True})
                    self._record(
                        session,
                        tenant_id,
                        run_id,
                        name,
                        tier,
                        prompt,
                        input_hash,
                        LlmResponse(cached.response, 0, 0, cached.provider, cached.model),
                        latency_ms=0,
                        cached_hit=True,
                        fallback=False,
                    )
                    return result

            _budget_guard(session, run_id, run_budget)
            response, used_fallback, latency_ms = self._call(
                models, prompt.text, masked.text, json_schema, max_tokens
            )
            result = self._validate_or_retry(
                schema, response, models, prompt.text, masked.text, json_schema, max_tokens
            )
            span.set_attributes(
                {
                    "gen_ai.provider.name": response.provider,
                    "gen_ai.request.model": models[0],
                    "gen_ai.response.model": response.model,
                    "gen_ai.usage.input_tokens": response.input_tokens,
                    "gen_ai.usage.output_tokens": response.output_tokens,
                    "astra.cost_usd": float(response.cost_usd),
                    "astra.fallback": used_fallback,
                    "astra.cached": False,
                }
            )
            labels = {"tier": tier, "model": response.model, "provider": response.provider}
            tokens_counter.add(response.input_tokens, {**labels, "direction": "input"})
            tokens_counter.add(response.output_tokens, {**labels, "direction": "output"})
            cost_counter.add(float(response.cost_usd), labels)
            calls_counter.add(1, {**labels, "cached": False, "fallback": used_fallback})
            latency_histogram.record(latency_ms, labels)

            session.execute(
                insert(LlmCache)
                .values(
                    tenant_id=tenant_id,
                    key=cache_key,
                    provider=response.provider,
                    model=response.model,
                    response=result.model_dump_json(),
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "key"])
            )
            self._record(
                session,
                tenant_id,
                run_id,
                name,
                tier,
                prompt,
                input_hash,
                response,
                latency_ms=latency_ms,
                cached_hit=False,
                fallback=used_fallback,
            )
            return result

    def _call(
        self, models: list[str], system: str, user: str, schema: dict, max_tokens: int
    ) -> tuple[LlmResponse, bool, int]:
        last_error: Exception | None = None
        for index, model in enumerate(models):
            started = time.monotonic()
            try:
                response = self._provider_factory(model).complete(
                    model, system, user, schema, max_tokens
                )
            except (ProviderUnavailable, KeyError) as exc:
                last_error = exc
                log.warning("Provider failed for %s: %s", model, type(exc).__name__)
                continue
            return response, index > 0, int((time.monotonic() - started) * 1000)
        raise ProviderUnavailable("All model providers are unavailable") from last_error

    def _validate_or_retry(
        self,
        schema: type[T],
        response: LlmResponse,
        models: list[str],
        system: str,
        user: str,
        json_schema: dict,
        max_tokens: int,
    ) -> T:
        """Retry once on invalid output, then deny."""
        try:
            return _parse(schema, response.text)
        except SchemaFailure:
            retry, _, _ = self._call(models, system, user, json_schema, max_tokens)
            return _parse(schema, retry.text)

    def _record(
        self,
        session: Session,
        tenant_id: UUID,
        run_id: UUID | None,
        name: str,
        tier: str,
        prompt: PromptRef,
        input_hash: str,
        response: LlmResponse,
        latency_ms: int,
        cached_hit: bool,
        fallback: bool,
    ) -> None:
        cost = Decimal(0) if cached_hit else response.cost_usd
        session.add(
            AgentStep(
                tenant_id=tenant_id,
                run_id=run_id,
                name=name,
                tier=tier,
                provider=response.provider,
                model=response.model,
                prompt_hash=prompt.hash,
                input_hash=input_hash,
                output_hash=sha256_hex(response.text),
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
                cached=cached_hit,
                fallback=fallback,
            )
        )
        if run_id is not None:
            run = session.get(AgentRun, run_id)
            if run is not None:
                run.input_tokens += response.input_tokens
                run.output_tokens += response.output_tokens
                run.cost_usd += cost
        session.flush()


default_gateway = Gateway()
