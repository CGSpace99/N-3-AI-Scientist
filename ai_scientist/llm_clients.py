from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from .schemas import ParsedHypothesis


PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "qc_paraphrase.md"
DOMAIN_CATALOG_PATH = Path(__file__).parent.parent / "prompts" / "qc_domain_catalog.md"
DOMAIN_CLASSIFICATION_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "qc_domain_classification.md"
LITERATURE_RANKING_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "qc_literature_ranking.md"
STRUCTURED_PARSE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "qc_structured_parse.md"
PROTOCOL_EXTRACTION_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "qc_protocol_extraction.md"
MATERIALS_BUDGET_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "qc_materials_budget.md"
TAILORED_PROTOCOL_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "qc_tailored_protocol.md"
DEFAULT_TIMEOUT_SECONDS = 15.0


def expand_literature_queries(
    question: str,
    parsed: ParsedHypothesis,
    deterministic_profile: dict[str, Any],
    *,
    force: bool = False,
    structured_parse: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not force and not llm_query_expansion_enabled():
        return _disabled_metadata("disabled", "LLM query expansion disabled.")

    provider = os.environ.get("AI_SCIENTIST_LLM_PROVIDER", "openai").strip().lower()
    if provider not in {"openai", "anthropic", "claude"}:
        return _disabled_metadata(provider, f"Unsupported LLM provider: {provider}.")

    api_key = _api_key_for_provider(provider)
    if not api_key:
        return _disabled_metadata(provider, f"No API key configured for {provider}.")

    prompt = _load_prompt()
    if not prompt:
        return _disabled_metadata(provider, f"Prompt file missing or empty: {PROMPT_PATH}.")

    model = _model_for_provider(provider)
    payload = {
        "original_question": question,
        "parsed_hypothesis": parsed.model_dump(),
        "structured_parse": structured_parse or {},
        "deterministic_query_profile": deterministic_profile,
        "required_output_schema": {
            "paraphrased_question": "string",
            "search_queries": [{"kind": "string", "query": "string"}],
            "keywords": ["string"],
            "warnings": ["string"],
        },
    }

    try:
        with httpx.Client(timeout=_timeout_seconds()) as client:
            if provider == "openai":
                content = _call_openai(client, api_key, model, prompt, payload)
            else:
                content = _call_anthropic(client, api_key, model, prompt, payload)
    except Exception as exc:  # pragma: no cover - network/provider defensive path
        return _disabled_metadata(provider, f"LLM query expansion failed: {exc}", model=model)

    parsed_payload = _parse_json_object(content)
    if parsed_payload is None:
        return _disabled_metadata(provider, "LLM did not return valid JSON.", model=model)

    search_queries = _sanitize_search_queries(parsed_payload.get("search_queries", []))
    if not search_queries:
        return _disabled_metadata(provider, "LLM returned no usable search queries.", model=model)

    return {
        "used": True,
        "provider": _public_provider_name(provider),
        "model": model,
        "prompt_path": str(PROMPT_PATH),
        "paraphrased_question": _clean_text(parsed_payload.get("paraphrased_question", ""))[:500],
        "query_variants": search_queries,
        "keywords": _sanitize_keywords(parsed_payload.get("keywords", [])),
        "warnings": _sanitize_warnings(parsed_payload.get("warnings", [])),
        "error": "",
    }


def llm_query_expansion_enabled() -> bool:
    return os.environ.get("AI_SCIENTIST_LLM_QUERY_EXPANSION", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def complete_json_with_prompt(
    prompt_paths: list[Path],
    payload: dict[str, Any],
    *,
    max_tokens: int = 1600,
) -> dict[str, Any]:
    provider = os.environ.get("AI_SCIENTIST_LLM_PROVIDER", "openai").strip().lower()
    if provider not in {"openai", "anthropic", "claude"}:
        raise RuntimeError(f"Unsupported LLM provider: {provider}.")

    api_key = _api_key_for_provider(provider)
    if not api_key:
        raise RuntimeError(f"No API key configured for {provider}.")

    prompt = "\n\n".join(_load_prompt_path(path) for path in prompt_paths).strip()
    if not prompt:
        raise RuntimeError("No prompt guidance found for LLM request.")

    model = _model_for_provider(provider)
    with httpx.Client(timeout=_timeout_seconds()) as client:
        if provider == "openai":
            content = _call_openai(
                client,
                api_key,
                model,
                prompt,
                payload,
                max_tokens=max_tokens,
            )
        else:
            content = _call_anthropic(
                client,
                api_key,
                model,
                prompt,
                payload,
                max_tokens=max_tokens,
            )

    parsed = _parse_json_object(content)
    if parsed is None:
        raise RuntimeError("LLM did not return valid JSON.")
    parsed["_llm_provider"] = _public_provider_name(provider)
    parsed["_llm_model"] = model
    return parsed


def embed_texts(texts: list[str]) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for advanced QC embeddings.")
    model = os.environ.get("AI_SCIENTIST_EMBEDDING_MODEL", "text-embedding-3-small").strip()
    payload: dict[str, Any] = {
        "model": model,
        "input": texts,
    }
    dimensions = _embedding_dimensions()
    if dimensions is not None:
        payload["dimensions"] = dimensions

    with httpx.Client(timeout=_timeout_seconds()) as client:
        response = client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    embeddings = [item["embedding"] for item in sorted(data.get("data", []), key=lambda item: item["index"])]
    if len(embeddings) != len(texts):
        raise RuntimeError("Embedding response did not include all requested texts.")
    return {"model": data.get("model", model), "embeddings": embeddings}


def _call_openai(
    client: httpx.Client,
    api_key: str,
    model: str,
    prompt: str,
    payload: dict[str, Any],
    *,
    max_tokens: int = 1200,
) -> str:
    request_json: dict[str, Any] = {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
        ],
    }
    if _uses_completion_token_limit(model):
        request_json["max_completion_tokens"] = max_tokens
    else:
        request_json["max_tokens"] = max_tokens
        request_json["temperature"] = 0.1

    response = client.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=request_json,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _uses_completion_token_limit(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized.startswith("gpt-5") or normalized.startswith("o")


def _call_anthropic(
    client: httpx.Client,
    api_key: str,
    model: str,
    prompt: str,
    payload: dict[str, Any],
    *,
    max_tokens: int = 1200,
) -> str:
    response = client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0.1,
            "system": prompt,
            "messages": [
                {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
            ],
        },
    )
    response.raise_for_status()
    content = response.json().get("content", [])
    return "".join(block.get("text", "") for block in content if block.get("type") == "text")


def _api_key_for_provider(provider: str) -> str:
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY", "").strip()
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def _model_for_provider(provider: str) -> str:
    configured = os.environ.get("AI_SCIENTIST_LLM_MODEL", "").strip()
    if configured:
        return configured
    if provider == "openai":
        return "gpt-4o-mini"
    return "claude-3-5-haiku-20241022"


def _load_prompt() -> str:
    return _load_prompt_path(PROMPT_PATH)


def _load_prompt_path(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _timeout_seconds() -> float:
    try:
        return float(os.environ.get("AI_SCIENTIST_LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _parse_json_object(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if match is None:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _sanitize_search_queries(items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    queries: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = _clean_text(item.get("kind", ""))[:48] or "llm_expanded"
        query = _clean_text(item.get("query", ""))[:240]
        key = query.lower()
        if len(query) < 3 or key in seen:
            continue
        seen.add(key)
        queries.append({"kind": kind, "query": query})
        if len(queries) >= _max_llm_queries():
            break
    return queries


def _sanitize_keywords(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    keywords = [_clean_text(item)[:80] for item in items if _clean_text(item)]
    return list(dict.fromkeys(keywords))[:16]


def _sanitize_warnings(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    warnings = [_clean_text(item)[:240] for item in items if _clean_text(item)]
    return list(dict.fromkeys(warnings))[:6]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _max_llm_queries() -> int:
    try:
        return max(1, min(8, int(os.environ.get("AI_SCIENTIST_LLM_MAX_QUERIES", "5"))))
    except ValueError:
        return 5


def _embedding_dimensions() -> int | None:
    raw = os.environ.get("AI_SCIENTIST_EMBEDDING_DIMENSIONS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _disabled_metadata(
    provider: str,
    message: str,
    model: str = "",
) -> dict[str, Any]:
    return {
        "used": False,
        "provider": _public_provider_name(provider),
        "model": model,
        "prompt_path": str(PROMPT_PATH),
        "paraphrased_question": "",
        "query_variants": [],
        "keywords": [],
        "warnings": [],
        "error": message,
    }


def _public_provider_name(provider: str) -> str:
    if provider in {"anthropic", "claude"}:
        return "anthropic"
    return provider
