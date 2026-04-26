from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

from .llm_clients import (
    DOMAIN_CATALOG_PATH,
    DOMAIN_CLASSIFICATION_PROMPT_PATH,
    LITERATURE_RANKING_PROMPT_PATH,
    STRUCTURED_PARSE_PROMPT_PATH,
    complete_json_with_prompt,
    embed_texts,
)
from .schemas import ParsedHypothesis
from .source_adapters import (
    dedupe_candidates,
    query_live_sources,
    reference_to_candidate,
    source_status_dicts,
)
from .web_search import tavily_search


def advanced_qc_ready() -> bool:
    return (
        os.environ.get("AI_SCIENTIST_ADVANCED_QC", "0").strip().lower()
        in {"1", "true", "yes", "on"}
        and bool(os.environ.get("OPENAI_API_KEY", "").strip())
        and bool(os.environ.get("TAVILY_API_KEY", "").strip())
    )


def openai_parse_ready() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def parsed_hypothesis_from_field_classification(
    question: str,
    fallback: ParsedHypothesis,
    field_classification: dict[str, Any],
) -> ParsedHypothesis:
    field = clean_text(field_classification.get("field", "")) or fallback.domain
    specific_domain = clean_text(field_classification.get("specific_domain", "")) or fallback.experiment_type
    rationale = clean_text(field_classification.get("rationale", ""))
    return ParsedHypothesis(
        domain=field,
        experiment_type=slugify(specific_domain),
        intervention=question,
        system=specific_domain or fallback.system,
        outcome="Outcome to evaluate from the submitted question.",
        threshold="Threshold not explicit; define before execution.",
        control="Comparison or baseline should be identified from the literature review.",
        mechanism=rationale or "Mechanistic rationale to be inferred from field-specific evidence.",
    )


def structured_parse_question(question: str, fallback: ParsedHypothesis) -> dict[str, Any]:
    payload = {
        "question": question,
        "fallback_parse": fallback.model_dump(),
    }
    result = complete_json_with_prompt(
        [DOMAIN_CATALOG_PATH, STRUCTURED_PARSE_PROMPT_PATH],
        payload,
        max_tokens=1400,
    )
    structured = sanitize_structured_parse(result)
    structured["needs_confirmation"] = True
    structured["confirmed"] = False
    return structured


def parsed_hypothesis_from_structured_parse(
    question: str,
    fallback: ParsedHypothesis,
    structured_parse: dict[str, Any],
) -> ParsedHypothesis:
    specific_domain = clean_text(structured_parse.get("specific_domain", "")) or fallback.experiment_type
    primary_field = clean_text(structured_parse.get("primary_field", "")) or fallback.domain
    system = (
        clean_text(structured_parse.get("target_subject", ""))
        or clean_text(structured_parse.get("system", ""))
        or specific_domain
        or fallback.system
    )
    outcome = (
        clean_text(structured_parse.get("target_goal", ""))
        or clean_text(structured_parse.get("outcome", ""))
        or fallback.outcome
    )
    constraints = sanitize_string_list(structured_parse.get("constraints", []), 6, 160)
    return ParsedHypothesis(
        domain=primary_field,
        experiment_type=slugify(specific_domain),
        intervention=question,
        system=system,
        outcome=outcome,
        threshold="; ".join(constraints) or fallback.threshold,
        control="Comparison or baseline should be confirmed by the user or literature QC.",
        mechanism=clean_text(structured_parse.get("mechanism_or_rationale", "")) or fallback.mechanism,
    )


def run_advanced_literature_qc(
    question: str,
    parsed: ParsedHypothesis,
    query_profile: dict[str, Any],
    structured_parse: dict[str, Any] | None = None,
    llm_expansion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    field_classification = classify_question_field(question, parsed, query_profile, structured_parse)
    query_profile = merge_structured_query_expansion(query_profile, structured_parse, field_classification)
    source_result = collect_advanced_candidates(question, parsed, query_profile, field_classification)
    source_statuses = aggregate_source_statuses(source_result["source_statuses"])
    candidates = prioritize_candidates_for_advanced_review(
        dedupe_candidates(source_result["candidates"]),
        _max_advanced_results(),
    )
    embedding_model = score_candidate_embeddings(question, candidates)
    ranked_payload = rank_with_llm(question, field_classification, candidates)
    ranked_candidates = apply_llm_ranking(candidates, ranked_payload)
    ranked_candidates = sorted(
        ranked_candidates,
        key=lambda item: (
            item.get("final_score") or 0.0,
            item.get("source_quality_score") or 0.0,
            item.get("embedding_similarity") or 0.0,
            item.get("web_score") or 0.0,
        ),
        reverse=True,
    )

    novelty_signal = novelty_from_ranked_candidates(ranked_candidates, structured_parse)
    confidence = confidence_from_ranked_candidates(ranked_candidates, novelty_signal)
    references = candidates_to_references(ranked_candidates)[:10]
    public_candidates = public_candidate_list(ranked_candidates)
    return {
        "advanced_qc_used": True,
        "advanced_qc_error": "",
        "field_classification": field_classification,
        "embedding_model": embedding_model,
        "literature_review_summary": ranked_payload.get("literature_review_summary", ""),
        "original_query": question,
        "scientific_query": query_profile["scientific_query"],
        "keywords": query_profile["keywords"],
        "query_variants": query_profile["query_variants"] + field_classification.get("search_queries", []),
        "llm_query_expansion_used": bool(llm_expansion and llm_expansion.get("used")),
        "llm_provider": ranked_payload.get("_llm_provider", "") or (llm_expansion or {}).get("provider", ""),
        "llm_model": ranked_payload.get("_llm_model", ""),
        "llm_prompt_path": str(LITERATURE_RANKING_PROMPT_PATH),
        "llm_paraphrased_question": (llm_expansion or {}).get("paraphrased_question", ""),
        "llm_warnings": list(
            dict.fromkeys(
                field_classification.get("warnings", [])
                + (llm_expansion or {}).get("warnings", [])
                + ranked_payload.get("warnings", [])
            )
        ),
        "llm_error": (llm_expansion or {}).get("error", ""),
        "novelty_signal": novelty_signal,
        "confidence": confidence,
        "summary": summary_for_signal(novelty_signal, ranked_candidates, field_classification),
        "references": references,
        "source_statuses": source_statuses,
        "candidate_count": len(candidates),
        "source_coverage": source_coverage(source_statuses, len(candidates)),
        "top_candidates": public_candidates[:10],
        "ranking_explanation": ranked_payload.get(
            "ranking_explanation",
            "Advanced QC combined field-aware search, embedding similarity, and LLM relevance review.",
        ),
    }


def classify_question_field(
    question: str,
    parsed: ParsedHypothesis,
    query_profile: dict[str, Any],
    structured_parse: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "question": question,
        "parsed_hypothesis": parsed.model_dump(),
        "query_profile": query_profile,
        "structured_parse": structured_parse or {},
    }
    result = complete_json_with_prompt(
        [DOMAIN_CATALOG_PATH, DOMAIN_CLASSIFICATION_PROMPT_PATH],
        payload,
        max_tokens=1200,
    )
    field = clean_text(result.get("field", "general_web")) or "general_web"
    search_queries = sanitize_query_variants(result.get("search_queries", []))
    if not search_queries:
        search_queries = [{"kind": "broad_web", "query": question[:240]}]
    return {
        "field": structured_parse.get("primary_field", field) if structured_parse else field,
        "specific_domain": clean_text(result.get("specific_domain", ""))[:120],
        "confidence": clamp_float(result.get("confidence"), 0.0, 1.0, 0.5),
        "rationale": clean_text(result.get("rationale", ""))[:300],
        "use_bio_protocol_sources": bool(result.get("use_bio_protocol_sources", False)),
        "recommended_sources": sanitize_string_list(result.get("recommended_sources", []), 12, 80),
        "search_queries": search_queries,
        "structured_parse": structured_parse or {},
        "warnings": sanitize_string_list(result.get("warnings", []), 6, 240),
        "llm_provider": result.get("_llm_provider", ""),
        "llm_model": result.get("_llm_model", ""),
    }


def merge_structured_query_expansion(
    query_profile: dict[str, Any],
    structured_parse: dict[str, Any] | None,
    field_classification: dict[str, Any],
) -> dict[str, Any]:
    if not structured_parse:
        return query_profile
    facet_terms = structured_search_terms(structured_parse)
    query_variants = []
    for variant in query_profile.get("query_variants", []):
        if not placeholder_query(variant.get("query", "")):
            query_variants.append(variant)
    for idx, query in enumerate(structured_query_variants(structured_parse, field_classification), start=1):
        if not placeholder_query(query):
            query_variants.append({"kind": f"confirmed_parse_search_{idx}", "query": query})
    return {
        **query_profile,
        "keywords": list(dict.fromkeys(query_profile.get("keywords", []) + facet_terms)),
        "query_variants": dedupe_query_variants(query_variants),
    }


def placeholder_query(query: str) -> bool:
    lower = query.lower()
    return any(
        marker in lower
        for marker in [
            "experimental system inferred",
            "outcome must",
            "threshold not explicit",
            "matched negative and positive controls",
        ]
    )


def collect_advanced_candidates(
    question: str,
    parsed: ParsedHypothesis,
    query_profile: dict[str, Any],
    field_classification: dict[str, Any],
) -> dict[str, Any]:
    source_statuses: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    search_queries = advanced_search_queries(question, query_profile, field_classification)
    per_query_limit = max(2, min(5, _max_advanced_results()))
    tasks = []
    with ThreadPoolExecutor(max_workers=min(6, len(search_queries) + 2)) as executor:
        for query in search_queries:
            tasks.append(
                executor.submit(
                    collect_tavily_candidates,
                    query,
                    field_classification["field"],
                    per_query_limit,
                )
            )
        tasks.append(
            executor.submit(
                collect_scholarly_candidates,
                question,
                parsed,
                search_queries[0],
                "scholarly",
            )
        )
        if should_query_bio_sources(field_classification):
            tasks.append(
                executor.submit(
                    collect_scholarly_candidates,
                    question,
                    parsed,
                    search_queries[0],
                    "all",
                )
            )
        for future in as_completed(tasks):
            result = future.result()
            source_statuses.extend(result["source_statuses"])
            candidates.extend(result["candidates"])

    return {"source_statuses": source_statuses, "candidates": dedupe_candidates(candidates)}


def collect_tavily_candidates(query: str, field: str, max_results: int) -> dict[str, Any]:
    result = tavily_search(query, field=field, max_results=max_results)
    return {"source_statuses": result.source_statuses, "candidates": result.candidates}


def collect_scholarly_candidates(
    question: str,
    parsed: ParsedHypothesis,
    search_query: str,
    adapter_group: str,
) -> dict[str, Any]:
    result = query_live_sources(question, parsed, search_query=search_query, adapter_group=adapter_group)
    candidates = list(result.candidates)
    candidates.extend(reference_to_candidate(ref) for ref in result.references)
    return {"source_statuses": source_status_dicts(result.source_statuses), "candidates": candidates}


def aggregate_source_statuses(statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for status in statuses:
        key = (status.get("source", "unknown"), status.get("status", "unknown"))
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = dict(status)
            continue
        existing["result_count"] = int(existing.get("result_count", 0)) + int(status.get("result_count", 0))
        messages = [existing.get("message", ""), status.get("message", "")]
        existing["message"] = " | ".join(dict.fromkeys(message for message in messages if message))[:500]
    return list(grouped.values())


def advanced_search_queries(
    question: str,
    query_profile: dict[str, Any],
    field_classification: dict[str, Any],
) -> list[str]:
    queries = [item["query"] for item in field_classification.get("search_queries", []) if item.get("query")]
    queries.extend(variant["query"] for variant in query_profile.get("query_variants", []) if variant.get("query"))
    queries.append(question)
    return list(dict.fromkeys(clean_text(query)[:240] for query in queries if clean_text(query)))[:4]


def structured_query_variants(
    structured_parse: dict[str, Any],
    field_classification: dict[str, Any],
) -> list[str]:
    entities = sanitize_string_list(structured_parse.get("entities", []), 8, 80)
    technologies = sanitize_string_list(structured_parse.get("technologies", []), 8, 80)
    fields = sanitize_string_list(
        [structured_parse.get("primary_field", ""), *structured_parse.get("secondary_fields", [])],
        5,
        80,
    )
    context = clean_text(structured_parse.get("application_context", ""))
    outcome = clean_text(structured_parse.get("outcome", ""))
    target_subject = clean_text(structured_parse.get("target_subject", ""))
    target_goal = clean_text(structured_parse.get("target_goal", ""))
    target_methodology = clean_text(structured_parse.get("target_methodology", ""))
    target_readout = clean_text(structured_parse.get("target_readout", ""))
    target_parameters = clean_text(structured_parse.get("target_parameters", ""))
    optimized_query = clean_text(structured_parse.get("optimized_query", ""))
    base_terms = entities + technologies
    variants = [
        optimized_query,
        " ".join([target_subject, target_methodology, target_readout]),
        " ".join([target_subject, target_parameters, target_goal]),
        " ".join(base_terms + [context]),
        " ".join(fields + base_terms),
        " ".join(base_terms + [outcome]),
    ]
    variants.extend(item.get("query", "") for item in field_classification.get("search_queries", []))
    return list(dict.fromkeys(clean_text(query)[:240] for query in variants if clean_text(query)))[:5]


def structured_search_terms(structured_parse: dict[str, Any]) -> list[str]:
    terms = []
    for key in [
        "primary_field",
        "specific_domain",
        "application_context",
        "system",
        "outcome",
        "optimized_query",
        "target_subject",
        "target_goal",
        "target_methodology",
        "target_readout",
        "target_parameters",
    ]:
        value = clean_text(structured_parse.get(key, ""))
        if value:
            terms.append(value)
    for key in ["secondary_fields", "entities", "technologies", "constraints"]:
        terms.extend(sanitize_string_list(structured_parse.get(key, []), 10, 80))
    return list(dict.fromkeys(terms))


def should_query_bio_sources(field_classification: dict[str, Any]) -> bool:
    return bool(field_classification.get("use_bio_protocol_sources")) or field_classification.get("field") in {
        "life_sciences",
        "medicine_health",
    }


def score_candidate_embeddings(question: str, candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return os.environ.get("AI_SCIENTIST_EMBEDDING_MODEL", "text-embedding-3-small")
    texts = [question] + [candidate_embedding_text(candidate) for candidate in candidates]
    result = embed_texts(texts)
    embeddings = result["embeddings"]
    query_embedding = embeddings[0]
    for candidate, embedding in zip(candidates, embeddings[1:], strict=False):
        similarity = cosine_similarity(query_embedding, embedding)
        candidate["embedding_similarity"] = round(similarity, 3)
        candidate["final_score"] = round(max(0.0, min(1.0, similarity)), 3)
    return result["model"]


def rank_with_llm(
    question: str,
    field_classification: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    structured_parse = field_classification.get("structured_parse", {})
    payload = {
        "question": question,
        "field_classification": field_classification,
        "target_framework": target_framework_from_structured_parse(structured_parse),
        "candidates": [candidate_for_llm(candidate) for candidate in candidates[:10]],
    }
    return complete_json_with_prompt([LITERATURE_RANKING_PROMPT_PATH], payload, max_tokens=2600)


def target_framework_from_structured_parse(structured_parse: dict[str, Any]) -> dict[str, str]:
    if not isinstance(structured_parse, dict):
        return {}
    return {
        "optimized_query": clean_text(structured_parse.get("optimized_query", "")),
        "target_subject": clean_text(structured_parse.get("target_subject", ""))
        or clean_text(structured_parse.get("system", "")),
        "target_goal": clean_text(structured_parse.get("target_goal", ""))
        or clean_text(structured_parse.get("outcome", "")),
        "target_methodology": clean_text(structured_parse.get("target_methodology", "")),
        "target_readout": clean_text(structured_parse.get("target_readout", "")),
        "target_parameters": clean_text(structured_parse.get("target_parameters", "")),
    }


FACET_SCORE_WEIGHTS = {
    "topic_relevance": 0.15,
    "system_match": 0.20,
    "intervention_match": 0.20,
    "outcome_match": 0.15,
    "comparison_match": 0.10,
    "claim_or_threshold_match": 0.10,
    "protocol_or_method_match": 0.05,
    "evidence_quality": 0.05,
}


def apply_llm_ranking(
    candidates: list[dict[str, Any]],
    ranked_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    for item in ranked_payload.get("ranked_candidates", []):
        candidate = by_id.get(item.get("candidate_id"))
        if candidate is None:
            continue
        llm_score = clamp_float(item.get("llm_relevance_score"), 0.0, 1.0, 0.0)
        embedding_score = candidate.get("embedding_similarity") or 0.0
        web_score = candidate.get("web_score") or 0.0
        facet_scores = normalized_facet_scores(item, llm_score)
        candidate["llm_relevance_score"] = llm_score
        candidate["llm_score"] = llm_score
        candidate["facet_scores"] = facet_scores
        candidate["llm_relevance_reason"] = clean_text(item.get("llm_relevance_reason", ""))[:500]
        source_quality = source_quality_score(candidate)
        candidate["source_quality_score"] = source_quality
        candidate["final_score"] = source_adjusted_final_score(
            facet_gated_final_score(facet_scores, embedding_score, web_score),
            source_quality,
        )
        candidate["match_classification"] = facet_gated_classification(
            facet_scores,
            candidate["final_score"],
            clean_text(item.get("match_classification", "")),
        )
    for candidate in candidates:
        if candidate.get("match_classification") == "unranked":
            embedding_score = candidate.get("embedding_similarity") or 0.0
            web_score = candidate.get("web_score") or 0.0
            facet_scores = normalized_facet_scores({}, min(0.45, max(embedding_score, web_score)))
            candidate["facet_scores"] = facet_scores
            source_quality = source_quality_score(candidate)
            candidate["source_quality_score"] = source_quality
            candidate["final_score"] = source_adjusted_final_score(
                facet_gated_final_score(facet_scores, embedding_score, web_score),
                source_quality,
            )
            candidate["match_classification"] = "weak_background_reference"
            candidate["llm_relevance_reason"] = "Not explicitly ranked by the LLM; retained by embedding/web similarity."
    return candidates


def prioritize_candidates_for_advanced_review(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    for candidate in candidates:
        candidate["source_quality_score"] = source_quality_score(candidate)
    return sorted(
        candidates,
        key=lambda item: (
            item.get("source_quality_score") or 0.0,
            item.get("year") or 0,
            item.get("web_score") or 0.0,
        ),
        reverse=True,
    )[:limit]


def source_adjusted_final_score(base_score: float, source_quality: float) -> float:
    # Trusted scholarly/protocol APIs can keep their full facet score. Tavily and
    # other web-only discovery results remain visible but should not outrank
    # comparable peer-reviewed or curated protocol sources.
    quality = max(0.0, min(1.0, source_quality))
    adjusted = (0.82 * base_score) + (0.18 * quality)
    if quality <= 0.45:
        adjusted = min(adjusted, 0.74)
    return round(max(0.0, min(1.0, adjusted)), 3)


def source_quality_score(candidate: dict[str, Any]) -> float:
    source = clean_text(candidate.get("source", "")).lower()
    source_type = clean_text(candidate.get("source_type", "")).lower()
    url = clean_text(candidate.get("url", "")).lower()
    hostname = urlparse(url).netloc.removeprefix("www.")

    if source in {"ncbi pubmed", "europe pmc", "semantic scholar", "crossref", "nature protocols"}:
        return 1.0
    if source_type == "paper":
        return 0.95
    if source_type == "protocol" or source in {"protocols.io", "bio-protocol", "jove", "openwetware"}:
        return 0.9
    if source_type == "standard" or source == "miqe guidelines":
        return 0.88
    if source == "tavily":
        if trusted_scholarly_host(hostname):
            return 0.78
        if trusted_supplier_or_documentation_host(hostname):
            return 0.58
        return 0.4
    if source_type == "supplier_note":
        return 0.55
    return 0.5


def trusted_scholarly_host(hostname: str) -> bool:
    return any(
        marker in hostname
        for marker in [
            "pubmed.ncbi.nlm.nih.gov",
            "ncbi.nlm.nih.gov",
            "europepmc.org",
            "semanticscholar.org",
            "crossref.org",
            "doi.org",
            "nature.com",
            "science.org",
            "cell.com",
            "springer.com",
            "wiley.com",
            "sciencedirect.com",
            "frontiersin.org",
            "mdpi.com",
            "plos.org",
            "arxiv.org",
        ]
    )


def trusted_supplier_or_documentation_host(hostname: str) -> bool:
    return any(
        marker in hostname
        for marker in [
            "thermofisher.com",
            "sigmaaldrich.com",
            "promega.com",
            "qiagen.com",
            "idtdna.com",
            "atcc.org",
            "addgene.org",
            "protocols.io",
            "bio-protocol.org",
            "jove.com",
        ]
    )


def normalized_facet_scores(item: dict[str, Any], fallback_score: float) -> dict[str, float]:
    raw_scores = item.get("facet_scores", {})
    if not isinstance(raw_scores, dict):
        raw_scores = {}
    scores = {
        facet: clamp_float(raw_scores.get(facet), 0.0, 1.0, -1.0)
        for facet in FACET_SCORE_WEIGHTS
    }
    if all(value < 0 for value in scores.values()):
        fallback = clamp_float(fallback_score, 0.0, 1.0, 0.0)
        return legacy_facet_scores(fallback)
    return {
        facet: (0.0 if value < 0 else value)
        for facet, value in scores.items()
    }


def legacy_facet_scores(score: float) -> dict[str, float]:
    # Old prompt responses only returned one score. Make those conservative so
    # they can rank background results but cannot easily satisfy exact gates.
    return {
        "topic_relevance": score,
        "system_match": min(score, 0.55),
        "intervention_match": min(score, 0.55),
        "outcome_match": min(score, 0.50),
        "comparison_match": min(score, 0.35),
        "claim_or_threshold_match": min(score, 0.35),
        "protocol_or_method_match": min(score, 0.45),
        "evidence_quality": min(score, 0.60),
    }


def facet_gated_final_score(
    facet_scores: dict[str, float],
    embedding_score: float,
    web_score: float,
) -> float:
    facet_score = sum(
        FACET_SCORE_WEIGHTS[facet] * facet_scores.get(facet, 0.0)
        for facet in FACET_SCORE_WEIGHTS
    )
    # Give a slightly larger lift to semantic and retrieval relevance signals so
    # genuinely related papers are less likely to collapse into "not_found."
    support = (0.14 * max(0.0, min(1.0, embedding_score))) + (0.08 * max(0.0, min(1.0, web_score)))
    score = (0.85 * facet_score) + support
    if weak_core_facets(facet_scores):
        score = min(score, 0.66)
    if very_weak_core_facets(facet_scores):
        score = min(score, 0.42)
    return round(max(0.0, min(1.0, score)), 3)


def facet_gated_classification(
    facet_scores: dict[str, float],
    final_score: float,
    llm_classification: str,
) -> str:
    if exact_match_gates_pass(facet_scores, final_score):
        return "exact_match"
    if close_match_gates_pass(facet_scores, final_score):
        return "close_similar_work"
    if final_score >= 0.25 or facet_scores.get("topic_relevance", 0.0) >= 0.45:
        return "weak_background_reference"
    if llm_classification == "irrelevant":
        return "irrelevant"
    return "weak_background_reference"


def exact_match_gates_pass(facet_scores: dict[str, float], final_score: float) -> bool:
    return (
        final_score >= 0.85
        and facet_scores.get("system_match", 0.0) >= 0.8
        and facet_scores.get("intervention_match", 0.0) >= 0.8
        and facet_scores.get("outcome_match", 0.0) >= 0.75
        and facet_scores.get("comparison_match", 0.0) >= 0.6
        and facet_scores.get("claim_or_threshold_match", 0.0) >= 0.6
    )


def close_match_gates_pass(facet_scores: dict[str, float], final_score: float) -> bool:
    core_matches = sum(
        1
        for facet in ["system_match", "intervention_match", "outcome_match"]
        if facet_scores.get(facet, 0.0) >= 0.65
    )
    method_or_claim = max(
        facet_scores.get("protocol_or_method_match", 0.0),
        facet_scores.get("claim_or_threshold_match", 0.0),
        facet_scores.get("comparison_match", 0.0),
    )
    return final_score >= 0.64 and core_matches >= 2 and method_or_claim >= 0.42


def weak_core_facets(facet_scores: dict[str, float]) -> bool:
    return sum(
        1
        for facet in ["system_match", "intervention_match", "outcome_match"]
        if facet_scores.get(facet, 0.0) >= 0.55
    ) < 2


def very_weak_core_facets(facet_scores: dict[str, float]) -> bool:
    return max(
        facet_scores.get("system_match", 0.0),
        facet_scores.get("intervention_match", 0.0),
        facet_scores.get("outcome_match", 0.0),
    ) < 0.45


def novelty_from_ranked_candidates(
    candidates: list[dict[str, Any]],
    structured_parse: dict[str, Any] | None = None,
) -> str:
    if any(
        candidate.get("match_classification") == "exact_match"
        and (candidate.get("final_score") or 0.0) >= 0.85
        and exact_match_gates_pass(candidate.get("facet_scores", {}), candidate.get("final_score") or 0.0)
        and candidate_matches_required_facets(candidate, structured_parse)
        for candidate in candidates[:5]
    ):
        return "exact_match_found"
    if any(
        candidate.get("match_classification") == "close_similar_work"
        and (candidate.get("final_score") or 0.0) >= 0.64
        and close_match_gates_pass(candidate.get("facet_scores", {}), candidate.get("final_score") or 0.0)
        and candidate_matches_required_facets(candidate, structured_parse)
        for candidate in candidates[:5]
    ):
        return "similar_work_exists"
    return "not_found"


def candidate_matches_required_facets(
    candidate: dict[str, Any],
    structured_parse: dict[str, Any] | None,
) -> bool:
    if not structured_parse:
        return True
    required_terms = facet_match_terms(structured_parse)
    if len(required_terms) <= 1:
        return True
    candidate_text = " ".join(
        [
            candidate.get("title", ""),
            candidate.get("abstract_or_snippet", ""),
            candidate.get("llm_relevance_reason", ""),
        ]
    ).lower()
    matches = sum(1 for term in required_terms if facet_term_present(term, candidate_text))
    return matches >= min(3, len(required_terms))


def facet_term_present(term: str, candidate_text: str) -> bool:
    normalized = term.lower()
    if normalized not in candidate_text:
        return False
    negated_markers = [
        f"not {normalized}",
        f"without {normalized}",
        f"no {normalized}",
        f"not related to {normalized}",
    ]
    return not any(marker in candidate_text for marker in negated_markers)


def facet_match_terms(structured_parse: dict[str, Any]) -> list[str]:
    terms = []
    for key in ["entities", "technologies"]:
        terms.extend(sanitize_string_list(structured_parse.get(key, []), 8, 80))
    if not terms:
        terms = sanitize_string_list(
            [
                structured_parse.get("primary_field", ""),
                *structured_parse.get("secondary_fields", []),
                structured_parse.get("specific_domain", ""),
            ],
            8,
            80,
        )
    return list(dict.fromkeys(term for term in terms if len(term) >= 4))


def confidence_from_ranked_candidates(candidates: list[dict[str, Any]], novelty_signal: str) -> float:
    if not candidates:
        return 0.2
    best = max(candidate.get("final_score") or 0.0 for candidate in candidates)
    if novelty_signal == "not_found":
        # High generic similarity is not high confidence in novelty; it means background exists.
        return round(max(0.2, min(0.55, 0.25 + (0.25 * best))), 3)
    if novelty_signal == "similar_work_exists":
        return round(max(0.45, min(0.85, 0.35 + (0.5 * best))), 3)
    return round(max(0.05, min(0.95, 0.25 + (0.7 * best))), 3)


def summary_for_signal(
    novelty_signal: str,
    candidates: list[dict[str, Any]],
    field_classification: dict[str, Any],
) -> str:
    if novelty_signal == "not_found":
        return (
            f"Advanced QC searched {field_classification.get('specific_domain') or field_classification.get('field')} "
            "sources and found background candidates, but no result matched enough required facets for a close-match claim."
        )
    return f"Advanced QC found {len(candidates[:10])} candidate result(s) for review in {field_classification.get('field')}."


def source_coverage(statuses: list[dict[str, Any]], candidate_count: int) -> dict[str, Any]:
    searched = len(statuses)
    successful = sum(1 for status in statuses if status["status"] == "queried")
    failed = sum(1 for status in statuses if status["status"] == "error")
    needs_key = sum(1 for status in statuses if status["status"] == "needs_key")
    disabled = sum(1 for status in statuses if status["status"] == "disabled")
    effective = max(1, searched - disabled)
    return {
        "searched_source_count": searched,
        "successful_source_count": successful,
        "failed_source_count": failed,
        "needs_key_source_count": needs_key,
        "candidate_count": candidate_count,
        "coverage_score": round(successful / effective, 3),
        "notes": coverage_notes(failed, needs_key, disabled, candidate_count),
    }


def coverage_notes(failed: int, needs_key: int, disabled: int, candidate_count: int) -> list[str]:
    notes = []
    if needs_key:
        notes.append(f"{needs_key} advanced source(s) need credentials.")
    if failed:
        notes.append(f"{failed} advanced source(s) failed or rate-limited.")
    if disabled:
        notes.append("Some sources were disabled.")
    if candidate_count == 0:
        notes.append("No advanced QC candidates were retrieved.")
    return notes


def candidates_to_references(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    references = []
    for candidate in candidates:
        if candidate.get("match_classification") == "irrelevant":
            continue
        references.append(
            {
                "title": candidate["title"],
                "authors": candidate.get("authors", []),
                "year": candidate.get("year"),
                "source": candidate["source"],
                "url": candidate["url"],
                "relevance_reason": candidate.get("llm_relevance_reason")
                or f"Advanced QC score {candidate.get('final_score', 0)}.",
            }
        )
    return references


def candidate_embedding_text(candidate: dict[str, Any]) -> str:
    return clean_text(
        " ".join(
            [
                candidate.get("title", ""),
                candidate.get("abstract_or_snippet", ""),
                candidate.get("raw_content", "")[:1200],
            ]
        )
    )[:2000]


def candidate_for_llm(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "title": candidate.get("title", ""),
        "url": candidate.get("url", ""),
        "source": candidate.get("source", ""),
        "source_type": candidate.get("source_type", ""),
        "snippet": candidate.get("abstract_or_snippet", ""),
        "raw_content_excerpt": candidate.get("raw_content", "")[:1200],
        "embedding_similarity": candidate.get("embedding_similarity"),
        "facet_scores": candidate.get("facet_scores", {}),
        "web_score": candidate.get("web_score"),
    }


def public_candidate_list(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public = []
    for candidate in candidates:
        item = dict(candidate)
        item.pop("raw_content", None)
        public.append(item)
    return public


def sanitize_query_variants(items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    variants = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = clean_text(item.get("kind", ""))[:48] or "advanced_search"
        query = clean_text(item.get("query", ""))[:240]
        if len(query) < 3 or query.lower() in seen:
            continue
        seen.add(query.lower())
        variants.append({"kind": kind, "query": query})
        if len(variants) >= 5:
            break
    return variants


def dedupe_query_variants(items: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped = []
    seen = set()
    for item in items:
        query = clean_text(item.get("query", ""))
        if not query or query.lower() in seen:
            continue
        seen.add(query.lower())
        deduped.append({"kind": clean_text(item.get("kind", "")) or "search", "query": query})
    return deduped


def sanitize_structured_parse(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary_field": clean_text(payload.get("primary_field", ""))[:80],
        "secondary_fields": sanitize_string_list(payload.get("secondary_fields", []), 6, 80),
        "specific_domain": clean_text(payload.get("specific_domain", ""))[:160],
        "entities": sanitize_string_list(payload.get("entities", []), 12, 80),
        "technologies": sanitize_string_list(payload.get("technologies", []), 12, 80),
        "application_context": clean_text(payload.get("application_context", ""))[:240],
        "system": clean_text(payload.get("system", ""))[:240],
        "outcome": clean_text(payload.get("outcome", ""))[:240],
        "optimized_query": clean_text(payload.get("optimized_query", ""))[:160],
        "target_subject": clean_text(payload.get("target_subject", ""))[:240],
        "target_goal": clean_text(payload.get("target_goal", ""))[:240],
        "target_methodology": clean_text(payload.get("target_methodology", ""))[:240],
        "target_readout": clean_text(payload.get("target_readout", ""))[:240],
        "target_parameters": clean_text(payload.get("target_parameters", ""))[:240],
        "constraints": sanitize_string_list(payload.get("constraints", []), 8, 160),
        "mechanism_or_rationale": clean_text(payload.get("mechanism_or_rationale", ""))[:300],
        "search_intent": clean_text(payload.get("search_intent", ""))[:300],
        "missing_information": sanitize_string_list(payload.get("missing_information", []), 8, 160),
        "confirmation_question": clean_text(payload.get("confirmation_question", ""))[:240],
        "confidence": clamp_float(payload.get("confidence"), 0.0, 1.0, 0.0),
    }


def sanitize_string_list(items: Any, max_items: int, max_length: int) -> list[str]:
    if not isinstance(items, list):
        return []
    values = [clean_text(item)[:max_length] for item in items if clean_text(item)]
    return list(dict.fromkeys(values))[:max_items]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, numeric))


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def slugify(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in cleaned.split("_") if part)[:80] or "field_specific_review"


def _max_advanced_results() -> int:
    try:
        return max(1, min(20, int(os.environ.get("AI_SCIENTIST_ADVANCED_QC_MAX_RESULTS", "10"))))
    except ValueError:
        return 10
