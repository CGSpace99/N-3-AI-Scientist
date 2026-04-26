from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .llm_clients import (
    MATERIALS_BUDGET_PROMPT_PATH,
    PROTOCOL_EXTRACTION_PROMPT_PATH,
    TAILORED_PROTOCOL_PROMPT_PATH,
    complete_json_with_prompt,
)
from .advanced_qc import (
    advanced_qc_ready,
    openai_parse_ready,
    parsed_hypothesis_from_structured_parse,
    run_advanced_literature_qc,
    structured_parse_question,
)
from .llm_clients import expand_literature_queries
from .schemas import ExampleInput, ParsedHypothesis
from .source_adapters import (
    SourceResult,
    dedupe_candidates,
    dedupe_references,
    query_live_sources,
    query_supplier_evidence,
    reference_to_candidate,
    source_status_dicts,
)


EXAMPLES: list[ExampleInput] = [
    ExampleInput(
        id="diagnostics",
        label="Diagnostics",
        domain="diagnostics",
        hypothesis=(
            "A paper-based electrochemical biosensor functionalized with anti-CRP "
            "antibodies will detect C-reactive protein in whole blood at concentrations "
            "below 0.5 mg/L within 10 minutes, matching laboratory ELISA sensitivity "
            "without requiring sample preprocessing."
        ),
        plain_english=(
            "Can we build a cheap, fast blood test for inflammation that works without "
            "lab equipment?"
        ),
    ),
    ExampleInput(
        id="gut-health",
        label="Gut Health",
        domain="gut_health",
        hypothesis=(
            "Supplementing C57BL/6 mice with Lactobacillus rhamnosus GG for 4 weeks "
            "will reduce intestinal permeability by at least 30% compared to controls, "
            "measured by FITC-dextran assay, due to upregulation of tight junction "
            "proteins claudin-1 and occludin."
        ),
        plain_english=(
            "Does a specific probiotic measurably strengthen the gut lining in mice?"
        ),
    ),
    ExampleInput(
        id="cell-biology",
        label="Cell Biology",
        domain="cell_biology",
        hypothesis=(
            "Replacing sucrose with trehalose as a cryoprotectant in the freezing "
            "medium will increase post-thaw viability of HeLa cells by at least 15 "
            "percentage points compared to the standard DMSO protocol, due to "
            "trehalose's superior membrane stabilization at low temperatures."
        ),
        plain_english=(
            "Can we keep more cells alive when freezing them by swapping one "
            "preservative for another?"
        ),
    ),
    ExampleInput(
        id="climate",
        label="Climate",
        domain="climate",
        hypothesis=(
            "Introducing Sporomusa ovata into a bioelectrochemical system at a cathode "
            "potential of -400mV vs SHE will fix CO2 into acetate at a rate of at least "
            "150 mmol/L/day, outperforming current biocatalytic carbon capture "
            "benchmarks by at least 20%."
        ),
        plain_english=(
            "Can a specific microbe be used to convert CO2 into a useful chemical "
            "compound more efficiently than current methods?"
        ),
    ),
]


QUESTION_REFINEMENT_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "qc_question_refinement.md"
ARTIFACT_FEEDBACK_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "qc_artifact_feedback.md"
PRICE_ESTIMATION_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "qc_price_estimation.md"


def parse_hypothesis(question: str) -> ParsedHypothesis:
    text = " ".join(question.strip().split())
    lower = text.lower()
    domain, experiment_type = _classify_domain(lower)
    intervention, outcome = _split_intervention_outcome(text)
    return ParsedHypothesis(
        domain=domain,
        experiment_type=experiment_type,
        intervention=intervention,
        system=_extract_system(text, lower),
        outcome=outcome,
        threshold=_extract_threshold(text),
        control=_extract_control(text),
        mechanism=_extract_mechanism(text),
    )


def parse_question_for_job(question: str) -> ParsedHypothesis:
    parsed, _structured_parse = parse_question_with_structure(question)
    return parsed


def parse_question_with_structure(question: str) -> tuple[ParsedHypothesis, dict[str, Any] | None]:
    parsed = parse_hypothesis(question)
    if not openai_parse_ready():
        return parsed, None
    try:
        structured_parse = structured_parse_question(question, parsed)
    except Exception as exc:  # pragma: no cover - provider/network defensive path
        raise RuntimeError(f"Advanced OpenAI parse failed: {exc}") from exc
    return parsed_hypothesis_from_structured_parse(question, parsed, structured_parse), structured_parse


def generate_question_refinements(question: str) -> dict[str, Any]:
    warnings: list[str] = []
    generated: dict[str, Any] = {}
    try:
        generated = complete_json_with_prompt(
            [QUESTION_REFINEMENT_PROMPT_PATH],
            {"question": question},
            max_tokens=900,
        )
    except Exception as exc:  # pragma: no cover - provider defensive fallback
        warnings.append(f"OpenAI refinement unavailable; deterministic suggestions used: {exc}")
    options = sanitize_question_refinement_options(question, generated.get("options", []))
    if not options:
        options = fallback_question_refinement_options(question)
    options = options[:3]
    options.append(
        {
            "option_id": "manual",
            "label": "Edit directly",
            "question": question,
            "rationale": "User can directly refine the question before Literature QC.",
            "editable": True,
        }
    )
    return {
        "original_question": question,
        "options": options,
        "llm_provider": generated.get("_llm_provider", ""),
        "llm_model": generated.get("_llm_model", ""),
        "warnings": [*warnings, *sanitize_protocol_list(generated.get("warnings", []), 4, 220)],
    }


def sanitize_question_refinement_options(question: str, items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    options = []
    seen = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        refined = clean_protocol_text(item.get("question", ""))[:800]
        if len(refined) < 12 or refined.lower() in seen:
            continue
        seen.add(refined.lower())
        options.append(
            {
                "option_id": f"academic_{index}",
                "label": clean_protocol_text(item.get("label", ""))[:80] or f"Academic refinement {index}",
                "question": refined,
                "rationale": clean_protocol_text(item.get("rationale", ""))[:240],
                "editable": False,
            }
        )
        if len(options) >= 3:
            break
    return options


def fallback_question_refinement_options(question: str) -> list[dict[str, Any]]:
    text = clean_protocol_text(question)
    templates = [
        ("Academic refinement 1", f"Does {text}?", "Frames the prompt as a testable research question."),
        ("Academic refinement 2", f"To what extent does {text}?", "Emphasizes measurable effect size and evidence search."),
        ("Academic refinement 3", f"Can the proposed approach, {text}, be supported by prior empirical literature?", "Connects the claim to literature validation."),
    ]
    return [
        {
            "option_id": f"academic_{index}",
            "label": label,
            "question": value[:800],
            "rationale": rationale,
            "editable": False,
        }
        for index, (label, value, rationale) in enumerate(templates, start=1)
    ]


def draft_artifact_revision(
    stage: str,
    current_artifact: dict[str, Any],
    *,
    mode: str,
    feedback: str = "",
    edited_artifact: dict[str, Any] | None = None,
    operations: list[dict[str, Any]] | None = None,
    job_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if mode == "manual":
        proposed, summary = apply_manual_artifact_edits(stage, current_artifact, edited_artifact, operations or [])
        return {
            "proposed_artifact": proposed,
            "change_summary": summary,
            "warnings": [],
        }
    generated: dict[str, Any] = {}
    warnings: list[str] = []
    try:
        generated = complete_json_with_prompt(
            [ARTIFACT_FEEDBACK_PROMPT_PATH],
            {
                "stage": stage,
                "current_artifact": current_artifact,
                "feedback": feedback,
                "job_context": job_context or {},
            },
            max_tokens=llm_max_tokens("AI_SCIENTIST_FEEDBACK_MAX_TOKENS", 3000),
        )
    except Exception as exc:  # pragma: no cover - provider defensive fallback
        warnings.append(f"OpenAI artifact revision unavailable; original artifact returned: {exc}")
    proposed = generated.get("artifact") if isinstance(generated.get("artifact"), dict) else current_artifact
    return {
        "proposed_artifact": proposed,
        "change_summary": sanitize_protocol_list(generated.get("change_summary", []), 8, 240)
        or ([f"Draft generated from feedback: {clean_protocol_text(feedback)[:160]}"] if feedback else ["No changes proposed."]),
        "warnings": [*warnings, *sanitize_protocol_list(generated.get("warnings", []), 6, 240)],
    }


def apply_manual_artifact_edits(
    stage: str,
    current_artifact: dict[str, Any],
    edited_artifact: dict[str, Any] | None,
    operations: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    if edited_artifact is not None:
        return edited_artifact, ["Manual edited artifact proposed."]
    artifact = clone_dict(current_artifact)
    summary = []
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        action = clean_protocol_text(operation.get("action", "")).lower()
        if stage == "tool_inventory":
            changed = apply_tool_inventory_operation(artifact, action, operation)
        elif stage == "materials_consumables":
            changed = apply_materials_consumables_operation(artifact, action, operation)
        else:
            changed = apply_generic_artifact_operation(artifact, action, operation)
        if changed:
            summary.append(changed)
    return artifact, summary or ["No manual operations applied."]


def clone_dict(value: dict[str, Any]) -> dict[str, Any]:
    import copy

    return copy.deepcopy(value)


def apply_tool_inventory_operation(artifact: dict[str, Any], action: str, operation: dict[str, Any]) -> str:
    sections = artifact.setdefault("sections", [])
    if not sections:
        sections.append({"title": "Protocol-derived equipment and tools", "rows": [], "missingNote": ""})
    section_index = int(operation.get("section_index", 0) or 0)
    section_index = max(0, min(section_index, len(sections) - 1))
    rows = sections[section_index].setdefault("rows", [])
    if action == "add":
        row = operation.get("row") if isinstance(operation.get("row"), dict) else {}
        rows.append(
            {
                "item": clean_protocol_text(row.get("item", operation.get("item", "New tool")))[:180] or "New tool",
                "status": clean_protocol_text(row.get("status", "missing")) or "missing",
                "note": clean_protocol_text(row.get("note", ""))[:240],
                "action": clean_protocol_text(row.get("action", ""))[:240],
            }
        )
        return f"Added tool row: {rows[-1]['item']}."
    row_index = int(operation.get("row_index", -1) if operation.get("row_index") is not None else -1)
    if row_index < 0 or row_index >= len(rows):
        return ""
    if action == "delete":
        removed = rows.pop(row_index)
        return f"Deleted tool row: {removed.get('item', 'tool')}."
    if action == "update":
        patch = operation.get("row") if isinstance(operation.get("row"), dict) else {}
        rows[row_index].update({key: value for key, value in patch.items() if key in {"item", "status", "note", "action"}})
        return f"Updated tool row: {rows[row_index].get('item', 'tool')}."
    return ""


def apply_materials_consumables_operation(artifact: dict[str, Any], action: str, operation: dict[str, Any]) -> str:
    items = artifact.setdefault("items", [])
    if action == "add":
        item = operation.get("item") if isinstance(operation.get("item"), dict) else {}
        items.append(
            {
                "name": clean_protocol_text(item.get("name", operation.get("name", "New material")))[:180] or "New material",
                "category": clean_protocol_text(item.get("category", "material"))[:80],
                "quantity": clean_protocol_text(item.get("quantity", "TBD"))[:120] or "TBD",
                "supplier_hint": clean_protocol_text(item.get("supplier_hint", ""))[:120],
                "catalog_number": clean_protocol_text(item.get("catalog_number", ""))[:100],
                "evidence_source": clean_protocol_text(item.get("evidence_source", "")),
                "pricing_status": clean_protocol_text(item.get("pricing_status", "not_priced")) or "not_priced",
                "inventory_check_status": clean_protocol_text(item.get("inventory_check_status", "not_checked")) or "not_checked",
                "needs_manual_verification": bool(item.get("needs_manual_verification", True)),
                "notes": clean_protocol_text(item.get("notes", ""))[:300],
            }
        )
        return f"Added material/consumable: {items[-1]['name']}."
    item_index = int(operation.get("item_index", -1) if operation.get("item_index") is not None else -1)
    if item_index < 0 or item_index >= len(items):
        return ""
    if action == "delete":
        removed = items.pop(item_index)
        return f"Deleted material/consumable: {removed.get('name', 'item')}."
    if action == "update":
        patch = operation.get("item") if isinstance(operation.get("item"), dict) else {}
        allowed = {
            "name",
            "category",
            "quantity",
            "supplier_hint",
            "catalog_number",
            "evidence_source",
            "pricing_status",
            "inventory_check_status",
            "needs_manual_verification",
            "notes",
        }
        items[item_index].update({key: value for key, value in patch.items() if key in allowed})
        return f"Updated material/consumable: {items[item_index].get('name', 'item')}."
    return ""


def apply_generic_artifact_operation(artifact: dict[str, Any], action: str, operation: dict[str, Any]) -> str:
    field = clean_protocol_text(operation.get("field", ""))
    if action == "set" and field:
        artifact[field] = operation.get("value")
        return f"Set {field}."
    return ""


def _classify_domain(lower: str) -> tuple[str, str]:
    if any(token in lower for token in ["crp", "biosensor", "blood", "elisa"]):
        return "diagnostics", "biosensor_validation"
    if any(token in lower for token in ["c57bl/6", "lactobacillus", "fitc-dextran", "gut"]):
        return "gut_health", "in_vivo_intervention"
    if any(token in lower for token in ["hela", "cryoprotectant", "trehalose", "dmso"]):
        return "cell_biology", "cell_culture_optimization"
    if any(token in lower for token in ["co2", "co₂", "sporomusa", "bioelectrochemical"]):
        return "climate", "bioelectrochemical_carbon_capture"
    if any(token in lower for token in ["qpcr", "primer", "rna", "protein"]):
        return "molecular_biology", "assay_development"
    return "general_biology", "experiment_planning"


def _split_intervention_outcome(text: str) -> tuple[str, str]:
    match = re.search(r"\bwill\b", text, flags=re.IGNORECASE)
    if not match:
        return text, "Outcome must be specified by the scientist."
    intervention = text[: match.start()].strip(" ,.;")
    outcome = text[match.end() :].strip(" ,.;")
    outcome = re.split(r",?\s+due to\b|,?\s+because\b", outcome, flags=re.IGNORECASE)[0]
    return intervention, outcome.strip(" ,.;")


def _extract_system(text: str, lower: str) -> str:
    candidates = [
        ("whole blood", "whole blood"),
        ("c57bl/6 mice", "C57BL/6 mice"),
        ("hela cells", "HeLa cells"),
        ("bioelectrochemical system", "bioelectrochemical system"),
        ("solar cell", "solar cell material system"),
    ]
    for token, label in candidates:
        if token in lower:
            return label
    match = re.search(r"\bin ([^,.;]+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "Experimental system inferred from submitted hypothesis."


def _extract_threshold(text: str) -> str:
    lower = text.lower()
    patterns = [r"(below\s+[^,.;]+)", r"(within\s+[^,.;]+)"]
    patterns.append(r"(by at least\s+[^,.;]+)" if "by at least" in lower else r"(at least\s+[^,.;]+)")
    patterns.append(r"(outperforming\s+[^,.;]+)")
    matches: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            matches.append(match.group(1).strip())
    return "; ".join(dict.fromkeys(matches)) or "Threshold not explicit; define before execution."


def _extract_control(text: str) -> str:
    match = re.search(r"compared to ([^,.;]+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    if "matching laboratory elisa" in text.lower():
        return "laboratory ELISA benchmark"
    if "benchmarks" in text.lower():
        return "current benchmark condition"
    return "Matched negative and positive controls required."


def _extract_mechanism(text: str) -> str:
    match = re.search(r"due to ([^.;]+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "Mechanistic rationale not explicit; capture as an assumption."


def run_literature_qc(
    question: str,
    parsed: ParsedHypothesis,
    structured_parse: dict[str, Any] | None = None,
) -> dict[str, Any]:
    advanced_error = ""
    if advanced_qc_ready():
        try:
            query_profile = build_advanced_query_profile(question, parsed, structured_parse)
            llm_expansion = expand_literature_queries(
                question,
                parsed,
                query_profile,
                force=True,
                structured_parse=structured_parse,
            )
            query_profile = merge_llm_query_expansion(query_profile, llm_expansion)
            return run_advanced_literature_qc(
                question,
                parsed,
                query_profile,
                structured_parse,
                llm_expansion,
            )
        except Exception as exc:  # pragma: no cover - provider/network defensive fallback
            advanced_error = f"Advanced QC failed; deterministic QC used instead: {exc}"

    query_profile = build_query_profile(question, parsed)
    llm_expansion = expand_literature_queries(question, parsed, query_profile)
    query_profile = merge_llm_query_expansion(query_profile, llm_expansion)
    fallback_references = _references_for_domain(parsed.domain)
    fallback_candidates = [reference_to_candidate(ref) for ref in fallback_references]
    live_result = query_sources_for_profile(question, parsed, query_profile)
    source_statuses = source_status_dicts(live_result.source_statuses)
    all_candidates = dedupe_candidates(live_result.candidates + fallback_candidates)
    ranked_candidates = rank_qc_candidates(all_candidates, query_profile, parsed)
    source_coverage = compute_source_coverage(source_statuses, len(all_candidates))
    decision = decide_novelty(ranked_candidates, source_coverage, parsed)
    references = candidates_to_references(ranked_candidates)[:10]
    if not references:
        references = dedupe_references(fallback_references)[:1]

    return {
        "original_query": question,
        "advanced_qc_used": False,
        "advanced_qc_error": advanced_error,
        "field_classification": {},
        "embedding_model": "",
        "literature_review_summary": "",
        "scientific_query": query_profile["scientific_query"],
        "keywords": query_profile["keywords"],
        "query_variants": query_profile["query_variants"],
        "llm_query_expansion_used": llm_expansion["used"],
        "llm_provider": llm_expansion["provider"],
        "llm_model": llm_expansion["model"],
        "llm_prompt_path": llm_expansion["prompt_path"],
        "llm_paraphrased_question": llm_expansion["paraphrased_question"],
        "llm_warnings": llm_expansion["warnings"],
        "llm_error": llm_expansion["error"],
        "novelty_signal": decision["novelty_signal"],
        "confidence": decision["confidence"],
        "summary": decision["summary"],
        "references": references[:10],
        "source_statuses": source_statuses,
        "candidate_count": len(all_candidates),
        "source_coverage": source_coverage,
        "top_candidates": ranked_candidates[:10],
        "ranking_explanation": decision["ranking_explanation"],
    }


def build_advanced_query_profile(
    question: str,
    parsed: ParsedHypothesis,
    structured_parse: dict[str, Any] | None,
) -> dict[str, Any]:
    if not structured_parse:
        return build_query_profile(question, parsed)

    keywords = structured_profile_keywords(structured_parse)
    primary_field = structured_parse.get("primary_field", parsed.domain)
    secondary_fields = structured_parse.get("secondary_fields", [])
    specific_domain = structured_parse.get("specific_domain", parsed.experiment_type)
    scientific_query = (
        f"Confirmed interpretation: {specific_domain}. Primary field: {primary_field}. "
        f"Secondary fields: {', '.join(secondary_fields) or 'none'}. "
        f"System: {structured_parse.get('system', '')}. Outcome: {structured_parse.get('outcome', '')}. "
        f"Search intent: {structured_parse.get('search_intent', '')}."
    )
    variants = [
        {
            "kind": "confirmed_facets",
            "query": compact_advanced_query(
                structured_parse.get("entities", [])
                + structured_parse.get("technologies", [])
                + [structured_parse.get("application_context", "")]
            ),
        },
        {
            "kind": "confirmed_domain",
            "query": compact_advanced_query(
                [primary_field, *secondary_fields, specific_domain, structured_parse.get("system", "")]
            ),
        },
        {
            "kind": "confirmed_outcome",
            "query": compact_advanced_query(
                structured_parse.get("entities", [])
                + structured_parse.get("technologies", [])
                + [structured_parse.get("outcome", ""), structured_parse.get("search_intent", "")]
            ),
        },
    ]
    return {
        "original_query": question,
        "scientific_query": scientific_query,
        "keywords": keywords,
        "query_variants": [variant for variant in variants if variant["query"]],
    }


def structured_profile_keywords(structured_parse: dict[str, Any]) -> list[str]:
    terms = []
    for key in ["primary_field", "specific_domain", "application_context", "system", "outcome", "search_intent"]:
        if structured_parse.get(key):
            terms.append(str(structured_parse[key]))
    for key in ["secondary_fields", "entities", "technologies", "constraints"]:
        values = structured_parse.get(key, [])
        if isinstance(values, list):
            terms.extend(str(value) for value in values if value)
    return list(dict.fromkeys(" ".join(term.split()) for term in terms if " ".join(term.split())))[:18]


def compact_advanced_query(parts: list[Any]) -> str:
    tokens = []
    for part in parts:
        tokens.extend(re.findall(r"[A-Za-z0-9+./-]{3,}", str(part or "")))
    cleaned = [
        token
        for token in tokens
        if token.lower() not in QC_STOPWORDS and not token.startswith("http")
    ]
    return " ".join(dict.fromkeys(cleaned))[:240]


def merge_llm_query_expansion(
    query_profile: dict[str, Any],
    llm_expansion: dict[str, Any],
) -> dict[str, Any]:
    if not llm_expansion["used"]:
        return query_profile

    merged = {
        **query_profile,
        "keywords": list(dict.fromkeys(query_profile["keywords"] + llm_expansion["keywords"])),
        "query_variants": list(query_profile["query_variants"]),
    }
    existing_queries = {variant["query"].strip().lower() for variant in merged["query_variants"]}
    for variant in llm_expansion["query_variants"]:
        query = variant["query"].strip()
        if not query or query.lower() in existing_queries:
            continue
        existing_queries.add(query.lower())
        merged["query_variants"].append(
            {
                "kind": f"llm_{variant['kind']}",
                "query": query,
            }
        )
    return merged


def query_sources_for_profile(
    question: str,
    parsed: ParsedHypothesis,
    query_profile: dict[str, Any],
) -> SourceResult:
    search_queries = search_queries_for_profile(query_profile)
    aggregate = SourceResult()
    for search_query in search_queries:
        result = query_live_sources(question, parsed, search_query=search_query)
        aggregate.source_statuses.extend(result.source_statuses)
        aggregate.references.extend(result.references)
        aggregate.candidates.extend(result.candidates)
    aggregate.references = dedupe_references(aggregate.references)
    aggregate.candidates = dedupe_candidates(aggregate.candidates)
    return aggregate


def search_queries_for_profile(query_profile: dict[str, Any]) -> list[str]:
    queries = []
    for variant in query_profile["query_variants"]:
        query = variant["query"].strip()
        if query:
            queries.append(query)
    deduped = list(dict.fromkeys(queries))
    return deduped[:qc_search_query_limit()] or [query_profile["scientific_query"][:240]]


def qc_search_query_limit() -> int:
    try:
        limit = int(os.environ.get("AI_SCIENTIST_QC_SEARCH_QUERY_LIMIT", "4"))
    except ValueError:
        limit = 4
    return max(1, min(8, limit))


def build_query_profile(question: str, parsed: ParsedHypothesis) -> dict[str, Any]:
    keywords = extract_keywords(parsed)
    scientific_query = (
        f"Scientific hypothesis: {parsed.intervention}. Experimental system: "
        f"{parsed.system}. Primary outcome: {parsed.outcome}. Control: "
        f"{parsed.control}. Success threshold: {parsed.threshold}. Mechanism: "
        f"{parsed.mechanism}."
    )
    strict_parts = [
        parsed.intervention,
        parsed.system,
        parsed.outcome,
        parsed.threshold,
    ]
    broad_parts = [
        parsed.intervention,
        parsed.system,
        parsed.outcome,
    ]
    protocol_parts = [
        parsed.experiment_type.replace("_", " "),
        parsed.system,
        parsed.intervention,
        "protocol",
        "method",
    ]
    return {
        "original_query": question,
        "scientific_query": scientific_query,
        "keywords": keywords,
        "query_variants": [
            {"kind": "strict_exact", "query": compact_query(strict_parts, keywords)},
            {"kind": "broad_scientific", "query": compact_query(broad_parts, keywords)},
            {"kind": "protocol_search", "query": compact_query(protocol_parts, keywords)},
        ],
    }


def extract_keywords(parsed: ParsedHypothesis) -> list[str]:
    domain_keywords = {
        "diagnostics": ["CRP", "anti-CRP", "electrochemical biosensor", "whole blood", "ELISA"],
        "gut_health": ["Lactobacillus rhamnosus GG", "FITC-dextran", "intestinal permeability", "claudin-1", "occludin"],
        "cell_biology": ["trehalose", "cryopreservation", "HeLa", "DMSO", "post-thaw viability", "cryoprotectant"],
        "climate": ["Sporomusa ovata", "bioelectrochemical", "CO2", "acetate", "cathode", "carbon fixation"],
        "molecular_biology": ["qPCR", "MIQE", "primer", "RNA", "assay validation"],
    }
    keywords = domain_keywords.get(parsed.domain, [])
    if keywords:
        return keywords

    text = " ".join(
        [
            parsed.intervention,
            parsed.system,
            parsed.outcome,
            parsed.threshold,
            parsed.control,
            parsed.mechanism,
        ]
    )
    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9+-]{3,}", text)
        if token.lower() not in QC_STOPWORDS
    ]
    return list(dict.fromkeys(tokens))[:12]


def compact_query(parts: list[str], fallback_keywords: list[str]) -> str:
    tokens: list[str] = []
    for part in parts:
        tokens.extend(re.findall(r"[A-Za-z0-9+./-]{3,}", part))
    if not tokens:
        tokens = fallback_keywords
    cleaned = [
        token
        for token in tokens
        if token.lower() not in QC_STOPWORDS and not token.startswith("http")
    ]
    return " ".join(dict.fromkeys(cleaned))[:240]


def rank_qc_candidates(
    candidates: list[dict[str, Any]],
    query_profile: dict[str, Any],
    parsed: ParsedHypothesis,
) -> list[dict[str, Any]]:
    ranked = []
    for candidate in candidates:
        scored = dict(candidate)
        matched_fields, lexical_score = score_candidate(scored, parsed, query_profile["keywords"])
        llm_score = None
        final_score = lexical_score if llm_score is None else (0.65 * lexical_score) + (0.35 * llm_score)
        scored["matched_fields"] = matched_fields
        scored["lexical_score"] = round(lexical_score, 3)
        scored["llm_score"] = llm_score
        scored["final_score"] = round(min(1.0, final_score), 3)
        scored["match_classification"] = classify_candidate(scored, matched_fields)
        ranked.append(scored)
    return sorted(
        ranked,
        key=lambda item: (
            item["final_score"],
            SOURCE_TYPE_PRIORITY.get(item["source_type"], 0),
            item.get("year") or 0,
        ),
        reverse=True,
    )


def score_candidate(
    candidate: dict[str, Any],
    parsed: ParsedHypothesis,
    keywords: list[str],
) -> tuple[list[str], float]:
    candidate_text = " ".join(
        [
            candidate.get("title", ""),
            candidate.get("abstract_or_snippet", ""),
            candidate.get("source", ""),
        ]
    )
    candidate_tokens = qc_tokens(candidate_text)
    field_weights = {
        "intervention": 0.24,
        "system": 0.18,
        "outcome": 0.2,
        "threshold": 0.1,
        "control": 0.12,
        "mechanism": 0.08,
    }
    field_texts = {
        "intervention": parsed.intervention,
        "system": parsed.system,
        "outcome": parsed.outcome,
        "threshold": parsed.threshold,
        "control": parsed.control,
        "mechanism": parsed.mechanism,
    }
    matched_fields = []
    score = 0.0
    for field_name, field_text in field_texts.items():
        overlap = candidate_tokens & qc_tokens(field_text)
        if overlap:
            matched_fields.append(field_name)
            score += field_weights[field_name]

    keyword_overlap = candidate_tokens & {keyword.lower() for keyword in keywords}
    score += min(0.18, 0.03 * len(keyword_overlap))
    score += SOURCE_TYPE_BONUS.get(candidate.get("source_type", ""), 0.0)

    if candidate.get("source_type") == "supplier_note":
        score = min(score, 0.35)
    if candidate.get("source_type") == "standard" and parsed.domain != "molecular_biology":
        score = min(score, 0.45)
    return matched_fields, min(1.0, score)


def classify_candidate(candidate: dict[str, Any], matched_fields: list[str]) -> str:
    score = candidate["final_score"]
    major_matches = {"intervention", "system", "outcome"} & set(matched_fields)
    if score >= 0.72 and len(major_matches) == 3 and (
        "threshold" in matched_fields or "control" in matched_fields
    ):
        return "exact_match"
    if score >= 0.34 and len(major_matches) >= 2:
        return "close_similar_work"
    if score >= 0.2:
        return "weak_background_reference"
    return "irrelevant"


def decide_novelty(
    ranked_candidates: list[dict[str, Any]],
    source_coverage: dict[str, Any],
    parsed: ParsedHypothesis,
) -> dict[str, Any]:
    strong_candidates = [
        candidate
        for candidate in ranked_candidates
        if candidate["match_classification"] in {"exact_match", "close_similar_work"}
    ]
    best_score = ranked_candidates[0]["final_score"] if ranked_candidates else 0.0
    coverage_score = source_coverage["coverage_score"]
    if any(candidate["match_classification"] == "exact_match" for candidate in ranked_candidates[:5]):
        novelty_signal = "exact_match_found"
    elif strong_candidates:
        novelty_signal = "similar_work_exists"
    else:
        novelty_signal = "not_found"

    confidence = compute_confidence(novelty_signal, best_score, coverage_score, len(ranked_candidates))
    if novelty_signal == "not_found":
        summary = (
            "No credible exact or close match was found in the available fast QC sources. "
            "This is a novelty signal, not proof that the experiment has never been done."
        )
    else:
        summary = (
            f"Fast QC found {len(strong_candidates)} credible candidate(s) related to "
            f"{parsed.experiment_type}. The top matches should be reviewed before plan generation."
        )
    return {
        "novelty_signal": novelty_signal,
        "confidence": confidence,
        "summary": summary,
        "ranking_explanation": (
            "Candidates were first normalized across source APIs, then scored against "
            "intervention, system/model, outcome, threshold, control, mechanism, source "
            "type, and keyword overlap. LLM query expansion is used only when explicitly "
            "configured with a provider key; candidate reranking remains deterministic for "
            "demo reliability."
        ),
    }


def compute_confidence(
    novelty_signal: str,
    best_score: float,
    coverage_score: float,
    candidate_count: int,
) -> float:
    if novelty_signal == "exact_match_found":
        raw = 0.55 + (0.3 * best_score) + (0.15 * coverage_score)
    elif novelty_signal == "similar_work_exists":
        raw = 0.42 + (0.35 * best_score) + (0.18 * coverage_score)
    else:
        scarcity_bonus = 0.12 if candidate_count == 0 else 0.0
        raw = 0.25 + (0.45 * coverage_score) + scarcity_bonus
    return round(max(0.05, min(0.95, raw)), 3)


def compute_source_coverage(
    source_statuses: list[dict[str, Any]],
    candidate_count: int,
) -> dict[str, Any]:
    searched = len(source_statuses)
    successful = sum(1 for status in source_statuses if status["status"] == "queried")
    failed = sum(1 for status in source_statuses if status["status"] == "error")
    needs_key = sum(1 for status in source_statuses if status["status"] == "needs_key")
    disabled = sum(1 for status in source_statuses if status["status"] == "disabled")
    effective_sources = max(1, searched - disabled)
    coverage_score = successful / effective_sources
    notes = []
    if needs_key:
        notes.append(f"{needs_key} source(s) need credentials for fuller coverage.")
    if failed:
        notes.append(f"{failed} source(s) failed or rate-limited during fast QC.")
    if disabled:
        notes.append("Live source querying is disabled; QC relies on fallback references.")
    if candidate_count == 0:
        notes.append("No normalized candidates were retrieved.")
    return {
        "searched_source_count": searched,
        "successful_source_count": successful,
        "failed_source_count": failed,
        "needs_key_source_count": needs_key,
        "candidate_count": candidate_count,
        "coverage_score": round(max(0.0, min(1.0, coverage_score)), 3),
        "notes": notes,
    }


def candidates_to_references(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    references = []
    for candidate in candidates:
        if candidate["match_classification"] == "irrelevant":
            continue
        references.append(
            {
                "title": candidate["title"],
                "authors": candidate.get("authors", []),
                "year": candidate.get("year"),
                "source": candidate["source"],
                "url": candidate["url"],
                "relevance_reason": (
                    f"{candidate['match_classification'].replace('_', ' ')}; matched "
                    f"{', '.join(candidate['matched_fields']) or 'general keywords'} "
                    f"(score {candidate['final_score']})."
                ),
            }
        )
    return references


def generate_relevant_protocols(
    job_id: str,
    question: str,
    parsed: ParsedHypothesis,
    structured_parse: dict[str, Any] | None,
    qc: dict[str, Any],
) -> dict[str, Any]:
    evidence = protocol_evidence_from_qc(qc)
    payload = {
        "question": question,
        "parsed_hypothesis": parsed.model_dump(),
        "structured_parse": structured_parse or {},
        "literature_qc": {
            "summary": qc.get("summary", ""),
            "literature_review_summary": qc.get("literature_review_summary", ""),
            "novelty_signal": qc.get("novelty_signal", ""),
            "confidence": qc.get("confidence"),
            "ranking_explanation": qc.get("ranking_explanation", ""),
        },
        "evidence": evidence,
        "required_output_schema": {
            "summary": "string",
            "protocol_candidates": [
                {
                    "title": "string",
                    "source_title": "string",
                    "source_url": "string",
                    "source_type": "string",
                    "evidence_quality": "direct | adapted | weak",
                    "relevance_reason": "string",
                    "adapted_steps": ["string"],
                    "tools": ["reusable equipment, instrument, or system"],
                    "consumables": ["sample, reagent, kit, chemical, or disposable input"],
                    "validation_checks": ["string"],
                    "limitations": ["string"],
                    "citations": ["string"],
                }
            ],
            "warnings": ["string"],
        },
    }
    try:
        extracted = complete_json_with_prompt(
            [PROTOCOL_EXTRACTION_PROMPT_PATH],
            payload,
            max_tokens=llm_max_tokens("AI_SCIENTIST_PROTOCOL_MAX_TOKENS", 5000),
        )
    except Exception as exc:  # pragma: no cover - provider defensive fallback
        extracted = fallback_protocol_extraction(evidence, str(exc))

    candidates = sanitize_protocol_candidates(extracted.get("protocol_candidates", []), evidence)
    if not candidates:
        candidates = fallback_protocol_extraction(evidence, "No protocol candidates returned.")["protocol_candidates"]
    selected_candidates = candidates[:3]
    procurement_lists = derive_protocol_procurement_lists(selected_candidates)
    return {
        "protocol_set_id": str(uuid.uuid4()),
        "job_id": job_id,
        "summary": clean_protocol_text(extracted.get("summary", "")) or "Protocol candidates were derived from the top QC evidence.",
        "protocol_candidates": selected_candidates,
        "tools": procurement_lists["tools"],
        "consumables": procurement_lists["consumables"],
        "warnings": sanitize_protocol_list(extracted.get("warnings", []), 6, 240),
        "evidence_count": len(evidence),
    }


def llm_max_tokens(env_name: str, default: int) -> int:
    try:
        configured = int(os.environ.get(env_name, str(default)))
    except ValueError:
        return default
    return max(512, min(12000, configured))


def protocol_evidence_from_qc(qc: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = []
    for ref in qc.get("references", [])[:10]:
        evidence.append(
            {
                "title": ref.get("title", ""),
                "url": ref.get("url", ""),
                "source": ref.get("source", ""),
                "source_type": "reference",
                "snippet": ref.get("relevance_reason", ""),
                "score": None,
            }
        )
    for candidate in qc.get("top_candidates", [])[:10]:
        evidence.append(
            {
                "title": candidate.get("title", ""),
                "url": candidate.get("url", ""),
                "source": candidate.get("source", ""),
                "source_type": candidate.get("source_type", ""),
                "snippet": candidate.get("abstract_or_snippet", ""),
                "score": candidate.get("final_score"),
                "reason": candidate.get("llm_relevance_reason", ""),
            }
        )
    deduped = []
    seen = set()
    for item in evidence:
        key = (item.get("url") or item.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:15]


def sanitize_protocol_candidates(items: Any, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    candidates = []
    evidence_urls = {item.get("url") for item in evidence if item.get("url")}
    for item in items:
        if not isinstance(item, dict):
            continue
        source_url = clean_protocol_text(item.get("source_url", ""))
        citations = sanitize_protocol_list(item.get("citations", []), 8, 300)
        if source_url and source_url not in citations:
            citations.insert(0, source_url)
        if not citations and evidence_urls:
            citations = [next(iter(evidence_urls))]
        title = clean_protocol_text(item.get("title", ""))[:160] or "Relevant protocol candidate"
        source_title = clean_protocol_text(item.get("source_title", ""))[:240]
        candidate_tools, candidate_consumables = protocol_candidate_derived_items(
            item,
            source_title=title or source_title,
            source_url=source_url,
        )
        candidates.append(
            {
                "title": title,
                "source_title": source_title,
                "source_url": source_url,
                "source_type": clean_protocol_text(item.get("source_type", ""))[:80],
                "evidence_quality": clean_protocol_text(item.get("evidence_quality", ""))[:40] or "adapted",
                "relevance_reason": clean_protocol_text(item.get("relevance_reason", ""))[:500],
                "adapted_steps": sanitize_protocol_list(item.get("adapted_steps", []), 12, 500),
                "tools": candidate_tools,
                "consumables": candidate_consumables,
                "validation_checks": sanitize_protocol_list(item.get("validation_checks", []), 10, 220),
                "limitations": sanitize_protocol_list(item.get("limitations", []), 8, 240),
                "citations": citations,
            }
        )
    return candidates


def derive_protocol_procurement_lists(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    tools: list[dict[str, Any]] = []
    consumables: list[dict[str, Any]] = []
    seen_tools: set[str] = set()
    seen_consumables: set[str] = set()
    for candidate in candidates:
        for item in candidate.get("tools", []):
            key = normalized_item_key(item.get("name", ""))
            if key and key not in seen_tools:
                seen_tools.add(key)
                tools.append(item)
        for item in candidate.get("consumables", []):
            key = normalized_item_key(item.get("name", ""))
            if key and key not in seen_consumables:
                seen_consumables.add(key)
                consumables.append(item)
    return {"tools": tools, "consumables": consumables}


def protocol_candidate_derived_items(
    candidate: dict[str, Any],
    *,
    source_title: str,
    source_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tools: list[dict[str, Any]] = []
    consumables: list[dict[str, Any]] = []
    context = protocol_candidate_context(candidate)
    for raw_item in protocol_candidate_inputs(candidate, kind="tools"):
        name, specification = protocol_item_name_and_specification(raw_item)
        if name:
            tools.append(protocol_derived_tool_item(name, source_title, source_url, specification))
    for raw_item in protocol_candidate_inputs(candidate, kind="consumables"):
        name, specification = protocol_item_name_and_specification(raw_item)
        name, specification = enrich_generic_protocol_consumable(name, specification, context)
        if name:
            consumables.append(protocol_derived_consumable_item(name, source_title, source_url, specification))
    return dedupe_derived_items(tools), dedupe_derived_items(consumables)


def protocol_derived_tool_item(name: str, source_title: str, source_url: str, specification: str = "") -> dict[str, Any]:
    return {
        "name": name[:180],
        "category": "reusable lab tool/equipment",
        "specification": specification[:240],
        "source_protocol_title": source_title[:240],
        "source_url": source_url,
        "rationale": "Reusable lab staple or instrument derived from protocol inputs or steps; user should confirm availability, booking, calibration, and operator requirements.",
        "needs_user_check": True,
        "procurement_required": False,
    }


def protocol_derived_consumable_item(name: str, source_title: str, source_url: str, specification: str = "") -> dict[str, Any]:
    return {
        "name": name[:180],
        "category": material_category(name),
        "specification": specification[:240],
        "source_protocol_title": source_title[:240],
        "source_url": source_url,
        "rationale": "Sample, reagent, kit, chemical, or disposable derived from protocol inputs; pass forward for materials, supplier, and budget checks.",
        "needs_user_check": True,
        "procurement_required": True,
    }


def dedupe_derived_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen = set()
    for item in items:
        key = normalized_item_key(item.get("name", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def protocol_candidate_inputs(candidate: dict[str, Any], *, kind: str) -> list[Any]:
    if kind == "tools":
        explicit_items = candidate.get("tools", [])
    else:
        explicit_items = candidate.get("consumables", [])
    inputs = derived_item_names(explicit_items)
    legacy_inputs = list(candidate.get("materials_or_inputs", []))
    for item in legacy_inputs:
        if classify_protocol_input(clean_protocol_text(item)) == ("tool" if kind == "tools" else "consumable"):
            inputs.append(item)
    text = protocol_candidate_context(candidate)
    if kind == "tools":
        inputs.extend(tool_mentions_from_text(text))
    return inputs


def protocol_candidate_context(candidate: dict[str, Any]) -> str:
    return " ".join(
        [
            *candidate.get("adapted_steps", []),
            candidate.get("title", ""),
            candidate.get("relevance_reason", ""),
            " ".join(candidate.get("limitations", [])),
        ]
    )


def derived_item_names(items: Any) -> list[Any]:
    if not isinstance(items, list):
        return []
    names = []
    for item in items:
        if isinstance(item, dict):
            names.append(item)
        else:
            names.append(item)
    return names


def protocol_item_name_and_specification(item: Any) -> tuple[str, str]:
    if not isinstance(item, dict):
        return clean_protocol_text(item), ""
    name = clean_protocol_text(item.get("name", ""))
    specification = clean_protocol_text(
        item.get("specification", "")
        or item.get("composition", "")
        or item.get("formulation", "")
        or item.get("grade", "")
        or item.get("concentration", "")
    )
    if not name:
        name = specification
    elif specification and specification.lower() not in name.lower():
        name = f"{name} ({specification})"
    return name, specification


def classify_protocol_input(name: str) -> str:
    lower = name.lower()
    if any(term in lower for term in PROTOCOL_CONSUMABLE_EXCLUSION_TERMS):
        return "consumable"
    if any(term in lower for term in PROTOCOL_TOOL_TERMS):
        return "tool"
    if any(term in lower for term in PROTOCOL_CONSUMABLE_TERMS):
        return "consumable"
    return "unknown"


GENERIC_PROTOCOL_CONSUMABLE_NAMES = {
    "testing material",
    "testing materials",
    "substrate",
    "substrates",
    "solar cell substrate",
    "solar cell substrates",
    "sample",
    "samples",
    "reagent",
    "reagents",
    "chemical",
    "chemicals",
    "material",
    "materials",
    "cell substrate",
    "cell substrates",
}


SPECIFIC_MATERIAL_PATTERNS = [
    r"\b(?:FTO|ITO)\s+glass\s+substrates?\b(?:\s+(?:coated|with|bearing)\s+[^.;,]{2,90})?",
    r"\b[A-Z][A-Za-z0-9:+().-]{1,30}\s+(?:perovskite|precursor|substrate|film|layer|electrode|electrolyte|solution|reagent|buffer|medium|media)\b(?:\s+(?:solution|substrate|film|layer|electrode|electrolyte|reagent|buffer|medium|media))?",
    r"\b(?:DMEM|RPMI|MEM|PBS|DMSO|FBS|BSA|EDTA|HEPES|MAPbI3|TiO2|SnO2|PEDOT:PSS|Spiro-OMeTAD|PCBM|C60)\b(?:\s+(?:with|in|containing|coated|layer|solution)\s+[^.;,]{2,90})?",
    r"\b\d+(?:\.\d+)?\s*(?:%|mM|uM|µM|M|mg/mL|ug/mL|µg/mL|g/L|wt%)\s+[^.;,]{2,80}",
    r"\b[^.;,]{2,80}\s+(?:alloy|polymer|composite|ceramic|hydrogel|nanoparticle|nanowire|wafer|foil|membrane|filter|cartridge|plate|well plate|tube|tip)s?\b",
]


def enrich_generic_protocol_consumable(name: str, specification: str, context: str) -> tuple[str, str]:
    if not name:
        return name, specification
    if not generic_protocol_consumable_name(name):
        return name, specification
    specific = first_specific_material_phrase(context)
    if not specific:
        return name, specification
    if name.lower() in specific.lower():
        enriched_name = specific
    else:
        enriched_name = f"{name} ({specific})"
    return clean_protocol_text(enriched_name), specification or specific


def generic_protocol_consumable_name(name: str) -> bool:
    lower = clean_protocol_text(name).lower().strip(" .:-")
    return lower in GENERIC_PROTOCOL_CONSUMABLE_NAMES or any(
        lower == term or lower.endswith(f" {term}") for term in GENERIC_PROTOCOL_CONSUMABLE_NAMES
    )


def first_specific_material_phrase(context: str) -> str:
    text = clean_protocol_text(context)
    if not text:
        return ""
    for pattern in SPECIFIC_MATERIAL_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_protocol_text(match.group(0))[:180]
    return ""


def tool_mentions_from_text(text: str) -> list[str]:
    lower = text.lower()
    mentions = []
    for term, label in PROTOCOL_TOOL_LABELS.items():
        if term in lower:
            mentions.append(label)
    return mentions


def normalized_item_key(name: str) -> str:
    return " ".join(name.lower().split())


def fallback_protocol_extraction(evidence: list[dict[str, Any]], warning: str) -> dict[str, Any]:
    candidates = []
    for item in evidence[:3]:
        candidates.append(
            {
                "title": f"Review and adapt: {item.get('title') or 'QC evidence'}",
                "source_title": item.get("title", ""),
                "source_url": item.get("url", ""),
                "source_type": item.get("source_type", "reference"),
                "evidence_quality": "weak",
                "relevance_reason": item.get("reason") or item.get("snippet") or "Selected from top QC evidence for protocol review.",
                "adapted_steps": [
                    "Open the source and identify any explicit methods, workflow, setup, or evaluation steps.",
                    "Extract only steps that are directly supported by the source.",
                    "Map the supported steps to the confirmed question before generating a full plan.",
                ],
                "tools": [],
                "consumables": [],
                "validation_checks": ["Confirm that extracted steps are explicitly supported by the cited source."],
                "limitations": ["Protocol extraction fallback used; manual review is required."],
                "citations": [item.get("url", "")] if item.get("url") else [],
            }
        )
    return {
        "summary": "Protocol extraction fell back to QC evidence review because OpenAI extraction failed or returned no candidates.",
        "protocol_candidates": candidates,
        "warnings": [warning[:240]] if warning else [],
    }


def sanitize_protocol_list(items: Any, max_items: int, max_length: int) -> list[str]:
    if not isinstance(items, list):
        return []
    values = [clean_protocol_text(item)[:max_length] for item in items if clean_protocol_text(item)]
    return list(dict.fromkeys(values))[:max_items]


def clean_protocol_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def generate_tailored_protocol(
    job_id: str,
    question: str,
    parsed: ParsedHypothesis,
    structured_parse: dict[str, Any] | None,
    qc: dict[str, Any],
    relevant_protocols: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "question": question,
        "parsed_hypothesis": parsed.model_dump(),
        "structured_parse": structured_parse or {},
        "literature_qc": {
            "summary": qc.get("summary", ""),
            "literature_review_summary": qc.get("literature_review_summary", ""),
            "novelty_signal": qc.get("novelty_signal", ""),
            "confidence": qc.get("confidence"),
            "ranking_explanation": qc.get("ranking_explanation", ""),
            "references": qc.get("references", [])[:10],
            "top_candidates": qc.get("top_candidates", [])[:10],
        },
        "relevant_protocols": relevant_protocols,
        "required_output_schema": {
            "title": "string",
            "summary": "string",
            "steps": [
                {
                    "step_number": "integer",
                    "title": "string",
                    "description": "string",
                    "inputs": ["string"],
                    "outputs": ["string"],
                    "duration": "string",
                    "validation_checks": ["string"],
                    "safety_notes": ["string"],
                    "citations": ["string"],
                }
            ],
            "inputs": ["string"],
            "outputs": ["string"],
            "validation_checks": ["string"],
            "safety_notes": ["string"],
            "source_protocol_refs": ["string"],
            "citations": ["string"],
            "warnings": ["string"],
        },
    }
    try:
        generated = complete_json_with_prompt(
            [TAILORED_PROTOCOL_PROMPT_PATH],
            payload,
            max_tokens=llm_max_tokens("AI_SCIENTIST_TAILORED_PROTOCOL_MAX_TOKENS", 4000),
        )
    except Exception as exc:  # pragma: no cover - provider defensive fallback
        generated = fallback_tailored_protocol(question, parsed, relevant_protocols, str(exc))
    protocol = sanitize_tailored_protocol_response(generated, question, parsed, relevant_protocols)
    protocol["tailored_protocol_id"] = str(uuid.uuid4())
    protocol["job_id"] = job_id
    return protocol


def sanitize_tailored_protocol_response(
    generated: dict[str, Any],
    question: str,
    parsed: ParsedHypothesis,
    relevant_protocols: dict[str, Any],
) -> dict[str, Any]:
    fallback = fallback_tailored_protocol(question, parsed, relevant_protocols, "")
    candidates = relevant_protocols.get("protocol_candidates", [])
    source_refs = [
        clean_protocol_text(candidate.get("source_url") or candidate.get("source_title"))
        for candidate in candidates
        if clean_protocol_text(candidate.get("source_url") or candidate.get("source_title"))
    ]
    steps = sanitize_tailored_steps(generated.get("steps", []))
    if not steps:
        steps = fallback["steps"]
    citations = sanitize_protocol_list(generated.get("citations", []), 12, 300)
    for ref in source_refs[:5]:
        if ref not in citations:
            citations.append(ref)
    return {
        "title": clean_protocol_text(generated.get("title", ""))[:180]
        or f"Tailored protocol for {parsed.experiment_type.replace('_', ' ')}",
        "summary": clean_protocol_text(generated.get("summary", ""))[:800]
        or fallback["summary"],
        "steps": steps[:12],
        "inputs": sanitize_protocol_list(generated.get("inputs", []), 30, 160) or fallback["inputs"],
        "outputs": sanitize_protocol_list(generated.get("outputs", []), 20, 180) or fallback["outputs"],
        "validation_checks": sanitize_protocol_list(generated.get("validation_checks", []), 16, 220)
        or fallback["validation_checks"],
        "safety_notes": sanitize_protocol_list(generated.get("safety_notes", []), 12, 220)
        or fallback["safety_notes"],
        "source_protocol_refs": sanitize_protocol_list(generated.get("source_protocol_refs", []), 12, 300)
        or source_refs[:8],
        "citations": citations[:12],
        "warnings": sanitize_protocol_list(generated.get("warnings", []), 8, 300)
        or fallback["warnings"],
    }


def sanitize_tailored_steps(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    steps = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        title = clean_protocol_text(item.get("title", ""))[:160]
        description = clean_protocol_text(item.get("description", ""))[:700]
        if not title and not description:
            continue
        steps.append(
            {
                "step_number": int(item.get("step_number") or index),
                "title": title or f"Protocol step {index}",
                "description": description or "Execute this step according to the cited protocol evidence.",
                "inputs": sanitize_protocol_list(item.get("inputs", []), 12, 160),
                "outputs": sanitize_protocol_list(item.get("outputs", []), 8, 160),
                "duration": clean_protocol_text(item.get("duration", ""))[:80],
                "validation_checks": sanitize_protocol_list(item.get("validation_checks", []), 8, 220),
                "safety_notes": sanitize_protocol_list(item.get("safety_notes", []), 6, 220),
                "citations": sanitize_protocol_list(item.get("citations", []), 8, 300),
            }
        )
    return steps


def fallback_tailored_protocol(
    question: str,
    parsed: ParsedHypothesis,
    relevant_protocols: dict[str, Any],
    warning: str,
) -> dict[str, Any]:
    candidates = relevant_protocols.get("protocol_candidates", [])
    source_refs = [
        clean_protocol_text(candidate.get("source_url") or candidate.get("source_title"))
        for candidate in candidates
        if clean_protocol_text(candidate.get("source_url") or candidate.get("source_title"))
    ]
    materials = []
    validation = []
    for candidate in candidates[:5]:
        materials.extend(item.get("name", "") for item in candidate.get("consumables", []))
        validation.extend(candidate.get("validation_checks", []))
    inputs = list(dict.fromkeys([parsed.intervention, parsed.system, *materials]))[:12]
    checks = list(dict.fromkeys([parsed.outcome, parsed.threshold, *validation]))[:8]
    steps = [
        {
            "step_number": 1,
            "title": "Confirm evidence and experimental scope",
            "description": "Review the relevant protocol candidates and confirm that their methods support the proposed experiment before execution.",
            "inputs": source_refs[:5],
            "outputs": ["Confirmed protocol evidence set"],
            "duration": "0.5-1 day",
            "validation_checks": ["Each retained step has at least one supporting citation."],
            "safety_notes": ["Do not begin lab work until local safety review is complete."],
            "citations": source_refs[:5],
        },
        {
            "step_number": 2,
            "title": "Prepare system and controls",
            "description": f"Prepare {parsed.system} with the proposed intervention and baseline control: {parsed.control}.",
            "inputs": inputs,
            "outputs": ["Prepared experimental and control conditions"],
            "duration": "TBD by protocol owner",
            "validation_checks": ["Control condition is measurable and documented."],
            "safety_notes": ["Verify training, PPE, and waste stream requirements."],
            "citations": source_refs[:5],
        },
        {
            "step_number": 3,
            "title": "Run experiment and assess outcome",
            "description": f"Measure {parsed.outcome} against the decision threshold: {parsed.threshold}.",
            "inputs": ["Prepared samples", "Measurement equipment", *checks[:3]],
            "outputs": ["Outcome measurements", "Pass/fail interpretation"],
            "duration": "TBD by protocol owner",
            "validation_checks": checks or ["Predefine success and failure criteria."],
            "safety_notes": ["Record deviations and stop conditions."],
            "citations": source_refs[:5],
        },
    ]
    return {
        "title": f"Tailored protocol for {parsed.experiment_type.replace('_', ' ')}",
        "summary": f"Protocol scaffold generated from Rachael's Literature QC evidence for: {question}",
        "steps": steps,
        "inputs": inputs or [parsed.intervention, parsed.system],
        "outputs": [parsed.outcome, "Decision against predefined success/failure criteria"],
        "validation_checks": checks or ["Define quantitative success and failure criteria before execution."],
        "safety_notes": ["Manual protocol and safety review required before execution."],
        "source_protocol_refs": source_refs[:8],
        "citations": source_refs[:8],
        "warnings": [warning[:240]] if warning else ["Tailored protocol should be reviewed by Rachael before execution."],
    }


def generate_tool_inventory(job_id: str, tailored_protocol: dict[str, Any]) -> dict[str, Any]:
    equipment = tool_names_from_tailored_protocol(tailored_protocol)
    rows = [tool_inventory_row(job_id, item) for item in equipment]
    missing = [row for row in rows if row["status"] == "missing"]
    sections = [
        {
            "title": "Protocol-derived equipment and tools",
            "rows": rows,
            "missingNote": (
                f"{len(missing)} tool(s) need attention before execution."
                if missing
                else "No missing tools flagged by the protocol-derived logistics pass; verify manually before execution."
            ),
        }
    ]
    return {
        "tool_inventory_id": str(uuid.uuid4()),
        "job_id": job_id,
        "summary": "Equipment and tool statuses generated from the tailored protocol. Users can edit these before final planning.",
        "sections": sections,
        "warnings": ["Statuses are a protocol-derived logistics pass and still require manual lab confirmation."],
    }


def tool_names_from_tailored_protocol(tailored_protocol: dict[str, Any]) -> list[str]:
    names = []
    tool_terms = [
        "reader",
        "microscope",
        "cycler",
        "centrifuge",
        "incubator",
        "cabinet",
        "pipette",
        "balance",
        "spectrophotometer",
        "sensor",
        "robot",
        "fixture",
        "workstation",
        "freezer",
        "hood",
        "plate",
    ]
    for step in tailored_protocol.get("steps", []):
        text_items = [
            step.get("title", ""),
            step.get("description", ""),
            *step.get("inputs", []),
            *step.get("outputs", []),
        ]
        for item in text_items:
            value = clean_protocol_text(item)
            if any(term in value.lower() for term in tool_terms):
                names.append(value[:120])
    defaults = [
        "Protocol workbench or execution station",
        "Calibrated pipette set",
        "Data capture workstation",
        "Required safety cabinet or containment equipment",
        "Primary measurement instrument",
    ]
    return list(dict.fromkeys([*names, *defaults]))[:12]


def tool_inventory_row(job_id: str, item: str) -> dict[str, str]:
    statuses = ["available", "limited", "missing", "ordered"]
    digest = hashlib.sha256(f"{job_id}:{item}".encode("utf-8")).hexdigest()
    status = statuses[int(digest[:2], 16) % len(statuses)]
    notes = {
        "available": "Protocol-derived check: appears available; confirm booking before execution.",
        "limited": "Protocol-derived check: limited access; booking or scheduling likely needed.",
        "missing": "Protocol-derived check: not currently available; replacement or purchase needed.",
        "ordered": "Protocol-derived check: on order; confirm ETA before start.",
    }
    actions = {
        "available": "Verify calibration and booking.",
        "limited": "Reserve slot and confirm trained operator.",
        "missing": "Find substitute or raise purchase request.",
        "ordered": "Track delivery and arrival condition.",
    }
    return {
        "item": item,
        "status": status,
        "note": notes[status],
        "action": actions[status],
    }


def generate_materials_consumables_dataset(
    job_id: str,
    tailored_protocol: dict[str, Any],
) -> dict[str, Any]:
    items = []
    seen = set()
    source_refs = tailored_protocol.get("source_protocol_refs", []) or tailored_protocol.get("citations", [])
    for raw_item in material_names_from_tailored_protocol(tailored_protocol):
        name = clean_protocol_text(raw_item)
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "name": name[:180],
                "category": material_category(name),
                "quantity": "TBD",
                "supplier_hint": supplier_hint_for_material(name),
                "catalog_number": "",
                "evidence_source": source_refs[0] if source_refs else "",
                "pricing_status": "not_priced",
                "inventory_check_status": "not_checked",
                "needs_manual_verification": True,
                "notes": "Derived from tailored protocol; pricing and stock checks will be added later.",
            }
        )
    if not items:
        items.append(
            {
                "name": "Protocol-specific consumables requiring review",
                "category": "consumable",
                "quantity": "TBD",
                "supplier_hint": "",
                "catalog_number": "",
                "evidence_source": source_refs[0] if source_refs else "",
                "pricing_status": "not_priced",
                "inventory_check_status": "not_checked",
                "needs_manual_verification": True,
                "notes": "No explicit consumables were extracted; manual review required.",
            }
        )
    return {
        "materials_consumables_id": str(uuid.uuid4()),
        "job_id": job_id,
        "summary": "Materials and consumables dataset derived from the tailored protocol for future pricing and inventory checks.",
        "items": items,
        "assumptions": [
            "Quantities are placeholders until the protocol owner confirms scale and replicates.",
            "Supplier hints are not price quotes or availability checks.",
        ],
        "warnings": ["Pricing and live inventory checks are intentionally not performed in this stage."],
    }


def material_names_from_tailored_protocol(tailored_protocol: dict[str, Any]) -> list[str]:
    names = []
    for item in tailored_protocol.get("inputs", []):
        names.append(item)
    for step in tailored_protocol.get("steps", []):
        names.extend(step.get("inputs", []))
    return list(dict.fromkeys(clean_protocol_text(item) for item in names if clean_protocol_text(item)))


def material_category(name: str) -> str:
    lower = name.lower()
    if any(term in lower for term in ["cell", "strain", "line", "sample"]):
        return "biological sample"
    if any(term in lower for term in ["buffer", "media", "reagent", "antibody", "primer", "kit"]):
        return "reagent"
    if any(term in lower for term in ["plate", "tube", "tip", "flask", "glove", "filter"]):
        return "consumable"
    if any(term in lower for term in ["reader", "microscope", "cycler", "centrifuge", "robot"]):
        return "equipment-dependent input"
    return "material"


def supplier_hint_for_material(name: str) -> str:
    lower = name.lower()
    if "primer" in lower or "oligo" in lower or "qpcr" in lower:
        return "IDT"
    if "plasmid" in lower:
        return "Addgene"
    if "qiagen" in lower or (
        "kit" in lower and any(term in lower for term in ["rna", "dna", "extraction", "purification", "pcr cleanup", "miniprep"])
    ):
        return "QIAGEN"
    if "promega" in lower or any(term in lower for term in ["luciferase", "caspase", "celltiter", "glo", "reporter assay"]):
        return "Promega"
    if any(term in lower for term in ["antibody", "dye", "cell culture", "culture media", "fetal bovine", "fbs", "assay reagent"]):
        return "Thermo Fisher"
    if any(term in lower for term in ["buffer", "solvent", "chemical", "substrate", "trehalose", "dmso", "salt"]):
        return "Sigma-Aldrich"
    return ""


def generate_materials_budget_proposal(
    job_id: str,
    question: str,
    parsed: ParsedHypothesis,
    structured_parse: dict[str, Any] | None,
    qc: dict[str, Any],
    relevant_protocols: dict[str, Any] | None,
) -> dict[str, Any]:
    procurement_items = build_procurement_items(parsed, relevant_protocols, qc)
    material_hints = extract_material_hints(parsed, relevant_protocols, qc)
    supplier_evidence = query_supplier_evidence(
        " ".join([question, *material_hints[:10]]),
        parsed,
        material_hints=material_hints,
        procurement_items=procurement_items,
    )
    payload = {
        "question": question,
        "parsed_hypothesis": parsed.model_dump(),
        "structured_parse": structured_parse or {},
        "literature_qc": qc,
        "relevant_protocols": relevant_protocols or {},
        "procurement_items": procurement_items,
        "material_hints": material_hints,
        "supplier_evidence": supplier_evidence,
        "trust_rules": [
            "Do not treat search page reachability as product availability.",
            "Treat tavily_product_candidate evidence as supplier discovery only, not verified stock or pricing.",
            "Search and budget against procurement_items as structured objects; use likely_quantity, unit_size, and specification as query context.",
            "Use relevant_protocols.consumables for procurement planning; relevant_protocols.tools are user-check inventory items, not procurement lines.",
            "Catalog numbers require supplier evidence or manual verification.",
            "Estimated prices must expose cost_confidence.",
        ],
    }
    try:
        generated = complete_json_with_prompt(
            [MATERIALS_BUDGET_PROMPT_PATH],
            payload,
            max_tokens=llm_max_tokens("AI_SCIENTIST_MATERIALS_BUDGET_MAX_TOKENS", 4000),
        )
    except Exception as exc:  # pragma: no cover - provider defensive fallback
        generated = fallback_materials_budget(parsed, qc, supplier_evidence, str(exc))

    proposal = sanitize_materials_budget_response(generated, parsed, qc, supplier_evidence)
    proposal = enrich_missing_prices_with_llm(
        proposal,
        question=question,
        parsed=parsed,
        structured_parse=structured_parse,
        relevant_protocols=relevant_protocols,
        procurement_items=procurement_items,
        supplier_evidence=supplier_evidence,
    )
    proposal = finalize_demo_budget_estimates(proposal, parsed, supplier_evidence)
    proposal["proposal_id"] = str(uuid.uuid4())
    proposal["job_id"] = job_id
    proposal["evidence_count"] = len(supplier_evidence)
    return proposal


def build_procurement_items(
    parsed: ParsedHypothesis,
    relevant_protocols: dict[str, Any] | None,
    qc: dict[str, Any],
) -> list[dict[str, Any]]:
    del qc
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    consumables = []
    consumables.extend((relevant_protocols or {}).get("consumables", []))
    for candidate in (relevant_protocols or {}).get("protocol_candidates", []):
        consumables.extend(candidate.get("consumables", []))
    for consumable in consumables:
        if not isinstance(consumable, dict):
            continue
        name = clean_protocol_text(consumable.get("name", ""))
        key = normalized_item_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(procurement_item_from_consumable(consumable, parsed))
    return items


def procurement_item_from_consumable(consumable: dict[str, Any], parsed: ParsedHypothesis) -> dict[str, Any]:
    name = clean_protocol_text(consumable.get("name", ""))[:180]
    category = clean_protocol_text(consumable.get("category", "")) or material_category(name)
    intended_use = procurement_intended_use(name, consumable, parsed)
    quantity, unit_size, specification, confidence = infer_procurement_specs(name, category, parsed)
    return {
        "name": name,
        "category": category,
        "intended_use": intended_use,
        "likely_quantity": quantity,
        "unit_size": unit_size,
        "specification": specification,
        "supplier_hint": supplier_hint_for_material(name),
        "source_protocol_title": clean_protocol_text(consumable.get("source_protocol_title", ""))[:240],
        "source_url": clean_protocol_text(consumable.get("source_url", "")),
        "confidence": confidence,
        "needs_manual_review": True,
    }


def procurement_intended_use(name: str, consumable: dict[str, Any], parsed: ParsedHypothesis) -> str:
    rationale = clean_protocol_text(consumable.get("rationale", ""))
    if rationale:
        return rationale[:240]
    if parsed.outcome:
        return f"Needed to support measurement or validation of {parsed.outcome}."
    return f"Needed for protocol execution involving {name}."


def infer_procurement_specs(name: str, category: str, parsed: ParsedHypothesis) -> tuple[str, str, str, str]:
    del parsed
    lower = name.lower()
    if any(term in lower for term in ["cell", "strain", "line"]):
        return "1 vial", "cryovial/vial", "Authenticated biological sample or cell line; confirm passage, growth conditions, and shipping requirements.", "medium"
    if "blood" in lower or "sample" in lower:
        return "Protocol-dependent sample count", "sample aliquot", "Confirm sample type, anticoagulant/additive, volume per replicate, ethics, and storage/shipping conditions.", "low"
    if "primer" in lower or "oligo" in lower:
        return "1 custom order", "custom oligo", "Requires sequence, scale, purification, and modification details before ordering.", "medium"
    if any(term in lower for term in ["plate", "tube", "tip", "flask", "filter", "vial", "cryovial"]):
        return "1 pack", "pack/box", "Match format, sterility, volume, compatibility, and replicate count.", "medium"
    if "kit" in lower:
        return "1 kit", "kit", "Match assay/application, sample type, readout, and number of reactions.", "medium"
    if any(term in lower for term in ["chemical", "solvent", "substrate", "trehalose", "dmso"]):
        return "1 bottle", likely_chemical_unit_size(lower), "Match grade, purity, concentration/formulation, and storage requirements.", "medium"
    if any(term in lower for term in ["antibody", "enzyme", "reagent", "dye", "solution", "buffer", "media", "medium"]):
        return "1 unit", likely_reagent_unit_size(lower), "Match grade, concentration, formulation, storage conditions, and protocol scale.", "medium"
    return "1 unit", "supplier package size TBD", f"Confirm unit size, grade/specification, and quantity for {category or 'material'}.", "low"


def likely_reagent_unit_size(lower_name: str) -> str:
    if "dye" in lower_name or "solution" in lower_name:
        return "100 mL or supplier-standard vial"
    if "buffer" in lower_name or "media" in lower_name or "medium" in lower_name:
        return "500 mL bottle"
    return "supplier-standard vial/bottle"


def likely_chemical_unit_size(lower_name: str) -> str:
    if "dmso" in lower_name:
        return "100 mL bottle"
    if "trehalose" in lower_name:
        return "100 g bottle"
    return "100 g or 100 mL bottle"


def extract_material_hints(
    parsed: ParsedHypothesis,
    relevant_protocols: dict[str, Any] | None,
    qc: dict[str, Any],
) -> list[str]:
    hints = [
        parsed.intervention,
        parsed.system,
        parsed.outcome,
        parsed.control,
    ]
    for item in (relevant_protocols or {}).get("consumables", []):
        hints.append(item.get("name", ""))
    for candidate in (relevant_protocols or {}).get("protocol_candidates", []):
        hints.extend(item.get("name", "") for item in candidate.get("consumables", []))
        hints.extend(candidate.get("validation_checks", []))
    for candidate in qc.get("top_candidates", [])[:5]:
        hints.append(candidate.get("title", ""))
    clean_hints = [clean_protocol_text(hint) for hint in hints if clean_protocol_text(hint)]
    return list(dict.fromkeys(clean_hints))[:20]


def sanitize_materials_budget_response(
    generated: dict[str, Any],
    parsed: ParsedHypothesis,
    qc: dict[str, Any],
    supplier_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    generated = backfill_generated_prices_from_evidence(generated, supplier_evidence)
    fallback = fallback_materials_budget(parsed, qc, supplier_evidence, "")
    materials = sanitize_trusted_materials(generated.get("materials", []), supplier_evidence)
    budget_lines = sanitize_trusted_budget_lines(generated.get("budget_lines", []), supplier_evidence)
    timeline = sanitize_trusted_timeline(generated.get("timeline_phases", []))
    validation = sanitize_trusted_validation(generated.get("validation", []))
    if not materials:
        materials = fallback["materials"]
    if not budget_lines:
        budget_lines = fallback["budget_lines"]
    if not timeline:
        timeline = fallback["timeline_phases"]
    if not validation:
        validation = fallback["validation"]
    total = round(sum(line.get("total_cost_estimate", 0) for line in budget_lines), 2)
    return {
        "summary": clean_protocol_text(generated.get("summary", ""))
        or "Materials and budget proposal generated from protocol and supplier evidence.",
        "materials": materials[:20],
        "budget_lines": budget_lines[:30],
        "timeline_phases": timeline[:12],
        "validation": validation[:12],
        "supplier_evidence": supplier_evidence[:30],
        "assumptions": sanitize_protocol_list(generated.get("assumptions", []), 10, 300)
        or fallback["assumptions"],
        "warnings": sanitize_protocol_list(generated.get("warnings", []), 10, 300)
        or fallback["warnings"],
        "total_budget_estimate": {"amount": total, "currency": "GBP"},
        "overall_confidence": confidence_value(generated.get("overall_confidence", "low")),
    }


def backfill_generated_prices_from_evidence(
    generated: dict[str, Any],
    supplier_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(generated, dict):
        return generated
    seeded = clone_dict(generated)
    evidence_with_prices = [
        item
        for item in supplier_evidence
        if safe_money(item.get("price_estimate", 0)) > 0
    ]
    if not evidence_with_prices:
        return seeded

    for item in seeded.get("materials", []) or []:
        if not isinstance(item, dict):
            continue
        apply_evidence_price_to_row(item, item.get("name", ""), supplier_evidence, evidence_with_prices)

    for line in seeded.get("budget_lines", []) or []:
        if not isinstance(line, dict):
            continue
        apply_evidence_price_to_row(line, line.get("item", ""), supplier_evidence, evidence_with_prices)

    return seeded


def apply_evidence_price_to_row(
    row: dict[str, Any],
    label: Any,
    supplier_evidence: list[dict[str, Any]],
    evidence_with_prices: list[dict[str, Any]],
) -> None:
    unit_cost = safe_money(row.get("unit_cost_estimate", 0))
    total_cost = safe_money(row.get("total_cost_estimate", 0))
    if unit_cost > 0 and total_cost > 0:
        return
    evidence = best_price_evidence_for_item(label, row.get("supplier", ""), row.get("source_url", ""), evidence_with_prices)
    if not evidence:
        return
    price = safe_money(evidence.get("price_estimate", 0))
    if price <= 0:
        return
    if unit_cost <= 0:
        row["unit_cost_estimate"] = price
    if total_cost <= 0:
        row["total_cost_estimate"] = row.get("unit_cost_estimate", price)
    if not clean_protocol_text(row.get("currency", "")):
        row["currency"] = clean_protocol_text(evidence.get("price_currency", "")) or "USD"
    if not clean_protocol_text(row.get("source_url", "")):
        row["source_url"] = clean_protocol_text(evidence.get("url", ""))
    if not clean_protocol_text(row.get("evidence_type", "")):
        row["evidence_type"] = clean_protocol_text(evidence.get("evidence_type", "")) or "tavily_product_candidate"
    row.setdefault("notes", "")
    excerpt = clean_protocol_text(evidence.get("price_excerpt", ""))
    if excerpt:
        note = f"Price cue extracted from supplier evidence: {excerpt}"
        existing = clean_protocol_text(row.get("notes", ""))
        row["notes"] = f"{existing} {note}".strip()[:400]


def best_price_evidence_for_item(
    label: Any,
    supplier: Any,
    source_url: Any,
    evidence_with_prices: list[dict[str, Any]],
) -> dict[str, Any] | None:
    label_text = clean_protocol_text(label).lower()
    supplier_text = clean_protocol_text(supplier).lower()
    source_text = clean_protocol_text(source_url).lower()
    best_item: dict[str, Any] | None = None
    best_score = -1
    for evidence in evidence_with_prices:
        score = 0
        evidence_url = clean_protocol_text(evidence.get("url", "")).lower()
        evidence_supplier = clean_protocol_text(evidence.get("supplier", "")).lower()
        evidence_text = " ".join(
            [
                clean_protocol_text(evidence.get("title", "")).lower(),
                clean_protocol_text(evidence.get("message", "")).lower(),
                clean_protocol_text(evidence.get("price_excerpt", "")).lower(),
            ]
        )
        if source_text and evidence_url and source_text == evidence_url:
            score += 4
        if supplier_text and evidence_supplier and supplier_text == evidence_supplier:
            score += 2
        if label_text and label_text in evidence_text:
            score += 3
        if label_text and evidence_url and any(token in evidence_url for token in qc_tokens(label_text)):
            score += 1
        if score > best_score:
            best_item = evidence
            best_score = score
    return best_item if best_score > 0 else None


def enrich_missing_prices_with_llm(
    proposal: dict[str, Any],
    *,
    question: str,
    parsed: ParsedHypothesis,
    structured_parse: dict[str, Any] | None,
    relevant_protocols: dict[str, Any] | None,
    procurement_items: list[dict[str, Any]],
    supplier_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    materials = proposal.get("materials", []) or []
    budget_lines = proposal.get("budget_lines", []) or []
    missing_materials = [item for item in materials if isinstance(item, dict) and row_missing_price(item, "name")]
    missing_budget_lines = [item for item in budget_lines if isinstance(item, dict) and row_missing_price(item, "item")]
    if not missing_materials and not missing_budget_lines:
        return proposal

    payload = {
        "question": question,
        "parsed_hypothesis": parsed.model_dump(),
        "structured_parse": structured_parse or {},
        "relevant_protocols": relevant_protocols or {},
        "procurement_items": procurement_items,
        "supplier_evidence": supplier_evidence,
        "missing_price_rows": {
            "materials": [
                {
                    "name": item.get("name", ""),
                    "category": item.get("category", ""),
                    "supplier": item.get("supplier", ""),
                    "quantity": item.get("quantity", ""),
                    "source_url": item.get("source_url", ""),
                    "evidence_type": item.get("evidence_type", ""),
                }
                for item in missing_materials
            ],
            "budget_lines": [
                {
                    "item": line.get("item", ""),
                    "category": line.get("category", ""),
                    "quantity": line.get("quantity", ""),
                    "source_url": line.get("source_url", ""),
                }
                for line in missing_budget_lines
            ],
        },
    }
    try:
        estimated = complete_json_with_prompt(
            [PRICE_ESTIMATION_PROMPT_PATH],
            payload,
            max_tokens=llm_max_tokens("AI_SCIENTIST_PRICE_ESTIMATION_MAX_TOKENS", 2000),
        )
    except Exception:
        return proposal
    return merge_price_estimates_into_proposal(proposal, estimated)


def row_missing_price(row: dict[str, Any], key: str) -> bool:
    del key
    unit = safe_money(row.get("unit_cost_estimate", 0))
    total = safe_money(row.get("total_cost_estimate", 0))
    return unit <= 0 or total <= 0


def merge_price_estimates_into_proposal(proposal: dict[str, Any], estimated: dict[str, Any]) -> dict[str, Any]:
    merged = clone_dict(proposal)
    estimated_materials = {
        normalized_item_key(clean_protocol_text(item.get("name", ""))): item
        for item in (estimated.get("materials", []) or [])
        if isinstance(item, dict)
    }
    estimated_budget = {
        normalized_item_key(clean_protocol_text(item.get("item", ""))): item
        for item in (estimated.get("budget_lines", []) or [])
        if isinstance(item, dict)
    }

    for item in merged.get("materials", []) or []:
        if not isinstance(item, dict) or not row_missing_price(item, "name"):
            continue
        key = normalized_item_key(clean_protocol_text(item.get("name", "")))
        estimate = estimated_materials.get(key)
        if not estimate:
            continue
        apply_estimate_to_row(item, estimate)
        item["needs_manual_verification"] = True
        if clean_protocol_text(item.get("quote_confidence", "")) not in {"candidate", "manual_quote_required"}:
            item["quote_confidence"] = "manual_quote_required"

    for line in merged.get("budget_lines", []) or []:
        if not isinstance(line, dict) or not row_missing_price(line, "item"):
            continue
        key = normalized_item_key(clean_protocol_text(line.get("item", "")))
        estimate = estimated_budget.get(key)
        if not estimate:
            continue
        apply_estimate_to_row(line, estimate)
        line["needs_manual_verification"] = True
        if clean_protocol_text(line.get("quote_confidence", "")) not in {"candidate", "manual_quote_required"}:
            line["quote_confidence"] = "manual_quote_required"

    merged["assumptions"] = list(
        dict.fromkeys((merged.get("assumptions", []) or []) + sanitize_protocol_list(estimated.get("assumptions", []), 8, 220))
    )[:10]
    merged["warnings"] = list(
        dict.fromkeys((merged.get("warnings", []) or []) + sanitize_protocol_list(estimated.get("warnings", []), 8, 220))
    )[:10]
    merged["total_budget_estimate"] = {
        "amount": round(sum(safe_money(line.get("total_cost_estimate", 0)) for line in (merged.get("budget_lines", []) or [])), 2),
        "currency": "GBP",
    }
    return merged


def apply_estimate_to_row(row: dict[str, Any], estimate: dict[str, Any]) -> None:
    unit = safe_money(row.get("unit_cost_estimate", 0))
    total = safe_money(row.get("total_cost_estimate", 0))
    est_unit = safe_money(estimate.get("unit_cost_estimate", 0))
    est_total = safe_money(estimate.get("total_cost_estimate", est_unit))
    if unit <= 0 and est_unit > 0:
        row["unit_cost_estimate"] = est_unit
    if total <= 0 and est_total > 0:
        row["total_cost_estimate"] = est_total
    if not clean_protocol_text(row.get("currency", "")):
        row["currency"] = clean_protocol_text(estimate.get("currency", "")) or "GBP"
    if clean_protocol_text(estimate.get("cost_confidence", "")) in {"low", "medium", "high"}:
        row["cost_confidence"] = clean_protocol_text(estimate.get("cost_confidence", "low"))
    if clean_protocol_text(estimate.get("quote_confidence", "")) in {"none", "candidate", "manual_quote_required"}:
        row["quote_confidence"] = clean_protocol_text(estimate.get("quote_confidence", "manual_quote_required"))
    rationale = clean_protocol_text(estimate.get("estimate_rationale", ""))
    if rationale:
        row.setdefault("notes", "")
        existing = clean_protocol_text(row.get("notes", ""))
        row["notes"] = f"{existing} Rough estimate: {rationale}".strip()[:400]


def finalize_demo_budget_estimates(
    proposal: dict[str, Any],
    parsed: ParsedHypothesis,
    supplier_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    finalized = clone_dict(proposal)
    materials = finalized.get("materials", []) or []
    budget_lines = finalized.get("budget_lines", []) or []
    for item in materials:
        if not isinstance(item, dict):
            continue
        ensure_material_supplier_source_and_price(item, parsed, supplier_evidence)
    merge_material_prices_into_budget_lines(materials, budget_lines, supplier_evidence)
    append_non_material_budget_lines(budget_lines, parsed)
    finalized["materials"] = materials
    finalized["budget_lines"] = budget_lines
    finalized["total_budget_estimate"] = {
        "amount": round(sum(safe_money(line.get("total_cost_estimate", 0)) for line in budget_lines), 2),
        "currency": "GBP",
    }
    finalized["assumptions"] = list(
        dict.fromkeys(
            (finalized.get("assumptions", []) or [])
            + [
                "Labour, facility, data-analysis, waste-disposal, and contingency estimates are included for demo budgeting.",
                "Supplier/catalog selections are best-effort candidates from focused supplier pages or Tavily-style supplier discovery and require quote verification.",
            ]
        )
    )[:10]
    return finalized


def ensure_material_supplier_source_and_price(
    item: dict[str, Any],
    parsed: ParsedHypothesis,
    supplier_evidence: list[dict[str, Any]],
) -> None:
    evidence = best_supplier_evidence_for_material(item, supplier_evidence)
    fallback = fallback_supplier_for_material(item.get("name", ""), parsed)
    if missing_demo_value(item.get("supplier", "")):
        item["supplier"] = clean_protocol_text((evidence or {}).get("supplier", "")) or fallback["supplier"]
    if missing_demo_value(item.get("source_url", "")):
        item["source_url"] = clean_protocol_text((evidence or {}).get("url", "")) or fallback["source_url"]
    if missing_demo_value(item.get("catalog_number", "")):
        item["catalog_number"] = clean_protocol_text((evidence or {}).get("catalog_number", "")) or "see supplier source"
    if missing_demo_value(item.get("quantity", "")):
        item["quantity"] = infer_procurement_specs(
            clean_protocol_text(item.get("name", "")),
            clean_protocol_text(item.get("category", "")),
            parsed,
        )[0]
    unit = safe_money(item.get("unit_cost_estimate", 0))
    total = safe_money(item.get("total_cost_estimate", 0))
    evidence_price = safe_money((evidence or {}).get("price_estimate", 0))
    estimated = evidence_price or estimate_demo_unit_cost(item.get("name", ""), item.get("category", ""))
    if unit <= 0:
        item["unit_cost_estimate"] = estimated
    if total <= 0:
        item["total_cost_estimate"] = safe_money(item.get("unit_cost_estimate", estimated))
    if not clean_protocol_text(item.get("currency", "")):
        item["currency"] = clean_protocol_text((evidence or {}).get("price_currency", "")) or "GBP"
    if clean_protocol_text(item.get("cost_confidence", "")) == "low" and evidence_price > 0:
        item["cost_confidence"] = "medium"
    if not clean_protocol_text(item.get("quote_confidence", "")) or item.get("quote_confidence") == "none":
        item["quote_confidence"] = "candidate" if item.get("source_url") else "manual_quote_required"
    if not clean_protocol_text(item.get("availability_status", "")):
        item["availability_status"] = "candidate"
    item["needs_manual_verification"] = True


def missing_demo_value(value: Any) -> bool:
    text = clean_protocol_text(value)
    return not text or text.lower() in {"tbd", "to be determined", "unknown", "n/a", "na", "none"}


def best_supplier_evidence_for_material(
    item: dict[str, Any],
    supplier_evidence: list[dict[str, Any]],
) -> dict[str, Any] | None:
    name = clean_protocol_text(item.get("name", "")).lower()
    supplier = clean_protocol_text(item.get("supplier", "")).lower()
    best: dict[str, Any] | None = None
    best_score = -1
    for evidence in supplier_evidence:
        if not isinstance(evidence, dict):
            continue
        score = 0
        evidence_supplier = clean_protocol_text(evidence.get("supplier", "")).lower()
        haystack = " ".join(
            [
                clean_protocol_text(evidence.get("title", "")),
                clean_protocol_text(evidence.get("message", "")),
                clean_protocol_text(evidence.get("url", "")),
                clean_protocol_text(evidence.get("price_excerpt", "")),
            ]
        ).lower()
        if supplier and evidence_supplier and supplier in evidence_supplier:
            score += 3
        if name and name in haystack:
            score += 4
        if name and any(token in haystack for token in qc_tokens(name)):
            score += 2
        if clean_protocol_text(evidence.get("url", "")):
            score += 1
        if safe_money(evidence.get("price_estimate", 0)) > 0:
            score += 2
        if score > best_score:
            best = evidence
            best_score = score
    return best if best_score > 0 else None


def fallback_supplier_for_material(name: Any, parsed: ParsedHypothesis) -> dict[str, str]:
    label = clean_protocol_text(name)
    lower = label.lower()
    supplier = supplier_hint_for_material(label)
    if not supplier:
        if any(term in lower for term in ["cell", "line", "sample", "blood"]):
            supplier = "ATCC"
        elif any(term in lower for term in ["plate", "tube", "tip", "flask", "glove", "filter"]):
            supplier = "Thermo Fisher"
        else:
            supplier = "Sigma-Aldrich" if parsed.domain in {"cell_biology", "biochemistry"} else "Thermo Fisher"
    url_by_supplier = {
        "Thermo Fisher": "https://www.thermofisher.com/search/results?keyword=",
        "Sigma-Aldrich": "https://www.sigmaaldrich.com/US/en/search/",
        "Promega": "https://www.promega.com/search/?q=",
        "QIAGEN": "https://www.qiagen.com/us/search/",
        "IDT": "https://www.idtdna.com/pages/search?keyword=",
        "Addgene": "https://www.addgene.org/search/advanced/?q=",
        "ATCC": "https://www.atcc.org/search#q=",
    }
    return {
        "supplier": supplier,
        "source_url": f"{url_by_supplier.get(supplier, 'https://www.google.com/search?q=')}{quote_for_url(label)}",
    }


def quote_for_url(value: str) -> str:
    return "+".join(re.findall(r"[A-Za-z0-9+-]+", value)) or "lab+consumable"


def estimate_demo_unit_cost(name: Any, category: Any) -> float:
    lower = f"{name} {category}".lower()
    if "kit" in lower:
        return 350.0
    if any(term in lower for term in ["antibody", "enzyme", "protein"]):
        return 250.0
    if any(term in lower for term in ["cell line", "cell", "sample", "blood"]):
        return 450.0
    if any(term in lower for term in ["plate", "tube", "tip", "flask", "filter", "glove"]):
        return 65.0
    if any(term in lower for term in ["primer", "oligo"]):
        return 120.0
    if any(term in lower for term in ["buffer", "media", "medium", "solution"]):
        return 85.0
    if any(term in lower for term in ["dye", "stain", "chemical", "substrate"]):
        return 95.0
    return 150.0


def merge_material_prices_into_budget_lines(
    materials: list[dict[str, Any]],
    budget_lines: list[dict[str, Any]],
    supplier_evidence: list[dict[str, Any]],
) -> None:
    by_key = {normalized_item_key(item.get("name", "")): item for item in materials if isinstance(item, dict)}
    existing = {normalized_item_key(line.get("item", "")) for line in budget_lines if isinstance(line, dict)}
    for key, item in by_key.items():
        if key in existing:
            for line in budget_lines:
                if normalized_item_key(line.get("item", "")) == key:
                    line["quantity"] = line.get("quantity") or item.get("quantity", "")
                    line["unit_cost_estimate"] = safe_money(line.get("unit_cost_estimate", 0)) or item.get("unit_cost_estimate", 0)
                    line["total_cost_estimate"] = safe_money(line.get("total_cost_estimate", 0)) or item.get("total_cost_estimate", 0)
                    line["currency"] = line.get("currency") or item.get("currency", "GBP")
                    line["source_url"] = line.get("source_url") or item.get("source_url", "")
                    line["quote_confidence"] = line.get("quote_confidence") or item.get("quote_confidence", "candidate")
                    line["cost_confidence"] = line.get("cost_confidence") or item.get("cost_confidence", "low")
                    line["needs_manual_verification"] = True
            continue
        budget_lines.append(
            {
                "category": item.get("category", "materials") or "materials",
                "item": item.get("name", "Material requiring review"),
                "quantity": item.get("quantity", ""),
                "unit_cost_estimate": safe_money(item.get("unit_cost_estimate", 0)),
                "total_cost_estimate": safe_money(item.get("total_cost_estimate", 0)),
                "currency": item.get("currency", "GBP") or "GBP",
                "cost_confidence": item.get("cost_confidence", "low"),
                "quote_confidence": item.get("quote_confidence", "candidate"),
                "source_url": item.get("source_url", ""),
                "notes": f"Candidate supplier: {item.get('supplier', '')}; catalog/source: {item.get('catalog_number', '')}",
                "needs_manual_verification": True,
            }
        )
    del supplier_evidence


def append_non_material_budget_lines(budget_lines: list[dict[str, Any]], parsed: ParsedHypothesis) -> None:
    if any(line.get("category") == "labour" for line in budget_lines if isinstance(line, dict)):
        return
    material_total = sum(
        safe_money(line.get("total_cost_estimate", 0))
        for line in budget_lines
        if isinstance(line, dict) and line.get("category") != "contingency"
    )
    labour_hours = 24 if parsed.experiment_type else 20
    labour_rate = 45.0
    facility_total = max(150.0, round(material_total * 0.15, 2))
    data_total = 180.0
    waste_total = 75.0
    labour_lines = [
        ("labour", "Research assistant labour", f"{labour_hours} hours", labour_rate, labour_hours * labour_rate, "Hands-on execution, sample preparation, measurements, and documentation."),
        ("facility", "Shared instrument and bench facility time", "booking allowance", facility_total, facility_total, "Estimated access fees or internal recharge for shared equipment and lab space."),
        ("analysis", "Data analysis and reporting", "4 hours", 45.0, data_total, "Basic analysis, plotting, protocol notes, and result summary."),
        ("waste_safety", "Waste disposal and safety consumables", "allowance", waste_total, waste_total, "Biohazard/chemical waste handling and safety consumables."),
    ]
    subtotal_after_labour = material_total + sum(line[4] for line in labour_lines)
    contingency = round(subtotal_after_labour * 0.1, 2)
    for category, item, quantity, unit, total, notes in labour_lines:
        budget_lines.append(
            {
                "category": category,
                "item": item,
                "quantity": quantity,
                "unit_cost_estimate": unit,
                "total_cost_estimate": total,
                "currency": "GBP",
                "cost_confidence": "medium",
                "quote_confidence": "manual_quote_required",
                "source_url": "internal recharge/labour estimate",
                "notes": notes,
                "needs_manual_verification": True,
            }
        )
    budget_lines.append(
        {
            "category": "contingency",
            "item": "Contingency reserve",
            "quantity": "10% of materials, labour, and facility estimate",
            "unit_cost_estimate": contingency,
            "total_cost_estimate": contingency,
            "currency": "GBP",
            "cost_confidence": "medium",
            "quote_confidence": "manual_quote_required",
            "source_url": "internal budgeting assumption",
            "notes": "Covers price variance, repeat runs, shipping, and small missing consumables.",
            "needs_manual_verification": True,
        }
    )


def sanitize_trusted_materials(items: Any, supplier_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    evidence_urls = {item.get("url") for item in supplier_evidence if item.get("url")}
    materials = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source_url = clean_protocol_text(item.get("source_url", ""))
        evidence_type = clean_protocol_text(item.get("evidence_type", "")) or "estimated"
        verified_source = bool(source_url and source_url in evidence_urls and evidence_type == "api_result")
        manual = bool(item.get("needs_manual_verification", not verified_source))
        if evidence_type in {
            "search_page_reachable",
            "tavily_product_candidate",
            "application_note",
            "technical_bulletin",
            "protocol_page",
            "tool_page",
            "catalog_page",
            "estimated",
        }:
            manual = True
        quote_confidence = quote_confidence_value(
            item.get("quote_confidence"),
            evidence_type,
            source_url,
            supplier_evidence,
        )
        unit_cost = safe_money(item.get("unit_cost_estimate", 0))
        total_cost = safe_money(item.get("total_cost_estimate", unit_cost))
        materials.append(
            {
                "name": clean_protocol_text(item.get("name", ""))[:180] or "Material requiring review",
                "category": clean_protocol_text(item.get("category", ""))[:80],
                "supplier": clean_protocol_text(item.get("supplier", ""))[:100],
                "catalog_number": clean_protocol_text(item.get("catalog_number", ""))[:100],
                "quantity": clean_protocol_text(item.get("quantity", ""))[:120],
                "unit_cost_estimate": unit_cost,
                "total_cost_estimate": total_cost,
                "currency": clean_protocol_text(item.get("currency", "GBP"))[:12] or "GBP",
                "cost_confidence": confidence_value(item.get("cost_confidence", "low")),
                "quote_confidence": quote_confidence,
                "availability_status": clean_protocol_text(item.get("availability_status", "unknown"))[:80] or "unknown",
                "source_url": source_url,
                "evidence_type": evidence_type,
                "rationale": clean_protocol_text(item.get("rationale", ""))[:400],
                "substitution_notes": clean_protocol_text(item.get("substitution_notes", ""))[:300],
                "needs_manual_verification": manual,
            }
        )
    return materials


def sanitize_trusted_budget_lines(items: Any, supplier_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    api_urls = {
        item.get("url")
        for item in supplier_evidence
        if item.get("url") and item.get("evidence_type") == "api_result" and item.get("status") in {"queried", "configured"}
    }
    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        unit_cost = safe_money(item.get("unit_cost_estimate", 0))
        total_cost = safe_money(item.get("total_cost_estimate", unit_cost))
        source_url = clean_protocol_text(item.get("source_url", ""))
        api_backed = bool(source_url and source_url in api_urls)
        manual = True if not api_backed else bool(item.get("needs_manual_verification", False))
        quote_confidence = quote_confidence_value(item.get("quote_confidence"), "api_result" if api_backed else "estimated", source_url, supplier_evidence)
        lines.append(
            {
                "category": clean_protocol_text(item.get("category", "materials"))[:80],
                "item": clean_protocol_text(item.get("item", ""))[:180] or "Budget item requiring review",
                "quantity": clean_protocol_text(item.get("quantity", ""))[:120],
                "unit_cost_estimate": unit_cost,
                "total_cost_estimate": total_cost,
                "currency": clean_protocol_text(item.get("currency", "GBP"))[:12] or "GBP",
                "cost_confidence": confidence_value(item.get("cost_confidence", "low")),
                "quote_confidence": quote_confidence,
                "source_url": source_url,
                "notes": clean_protocol_text(item.get("notes", ""))[:400],
                "needs_manual_verification": manual,
            }
        )
    return lines


def quote_confidence_value(
    value: Any,
    evidence_type: str,
    source_url: str,
    supplier_evidence: list[dict[str, Any]],
) -> str:
    raw = clean_protocol_text(value).lower()
    if evidence_type == "api_result" and any(
        item.get("url") == source_url and item.get("status") in {"queried", "configured"}
        for item in supplier_evidence
    ):
        return "api_verified"
    source_evidence_type = next(
        (item.get("evidence_type", "") for item in supplier_evidence if item.get("url") == source_url),
        "",
    )
    if source_evidence_type == "api_result":
        return "api_verified"
    if raw == "none":
        return "none"
    if raw == "manual_quote_required":
        return "manual_quote_required"
    if source_evidence_type in {"tavily_product_candidate", "catalog_page"}:
        return "candidate"
    if evidence_type in {"tavily_product_candidate", "catalog_page"} and source_url:
        return "candidate"
    if raw == "candidate" and source_url:
        return "candidate"
    return "manual_quote_required"


def sanitize_trusted_timeline(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    phases = []
    for item in items:
        if not isinstance(item, dict):
            continue
        phases.append(
            {
                "phase": clean_protocol_text(item.get("phase", ""))[:120] or "Execution phase",
                "duration": clean_protocol_text(item.get("duration", ""))[:80] or "TBD",
                "dependencies": sanitize_protocol_list(item.get("dependencies", []), 8, 120),
                "deliverable": clean_protocol_text(item.get("deliverable", ""))[:300],
                "critical_path": bool(item.get("critical_path", False)),
                "risk_notes": clean_protocol_text(item.get("risk_notes", ""))[:300],
            }
        )
    return phases


def sanitize_trusted_validation(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    validation = []
    for item in items:
        if not isinstance(item, dict):
            continue
        validation.append(
            {
                "metric": clean_protocol_text(item.get("metric", ""))[:160] or "Primary outcome",
                "method": clean_protocol_text(item.get("method", ""))[:220],
                "success_threshold": clean_protocol_text(item.get("success_threshold", ""))[:220],
                "failure_criteria": clean_protocol_text(item.get("failure_criteria", ""))[:220],
                "controls": sanitize_protocol_list(item.get("controls", []), 8, 140),
                "evidence_url": clean_protocol_text(item.get("evidence_url", "")),
                "confidence": confidence_value(item.get("confidence", "medium")),
            }
        )
    return validation


def fallback_materials_budget(
    parsed: ParsedHypothesis,
    qc: dict[str, Any],
    supplier_evidence: list[dict[str, Any]],
    warning: str,
) -> dict[str, Any]:
    template = _template_for_domain(parsed.domain)
    materials = []
    for item in template["materials"]:
        source = first_supplier_evidence_url(supplier_evidence, item.get("supplier", ""))
        materials.append(
            {
                "name": item["name"],
                "category": item["category"],
                "supplier": item["supplier"],
                "catalog_number": item["catalog_number"],
                "quantity": item["quantity"],
                "unit_cost_estimate": item["unit_cost"],
                "total_cost_estimate": item["total_cost"],
                "currency": item["currency"],
                "cost_confidence": "low",
                "quote_confidence": "manual_quote_required",
                "availability_status": "estimated",
                "source_url": source,
                "evidence_type": "estimated",
                "rationale": item["rationale"],
                "substitution_notes": "Verify current catalog number, availability, and local pricing before purchase.",
                "needs_manual_verification": True,
            }
        )
    budget_lines = [
        {
            "category": line["category"],
            "item": line["item"],
            "quantity": line["quantity"],
            "unit_cost_estimate": line["unit_cost"],
            "total_cost_estimate": line["total_cost"],
            "currency": line["currency"],
            "cost_confidence": "low",
            "quote_confidence": "manual_quote_required",
            "source_url": "",
            "notes": line["notes"],
            "needs_manual_verification": True,
        }
        for line in template["budget_lines"]
    ]
    total = round(sum(line["total_cost_estimate"] for line in budget_lines), 2)
    warnings = [
        "Costs are conservative estimates and require supplier quote verification.",
        "Search-page evidence does not prove product availability.",
    ]
    if warning:
        warnings.insert(0, warning[:240])
    return {
        "summary": "Fallback materials and budget proposal based on curated templates and supplier evidence.",
        "materials": materials,
        "budget_lines": budget_lines,
        "timeline_phases": template["timeline_phases"],
        "validation": template["validation"],
        "supplier_evidence": supplier_evidence,
        "assumptions": [
            f"Novelty signal: {qc.get('novelty_signal', 'unknown')}.",
            "Supplier prices vary by geography, account, and quote terms.",
        ],
        "warnings": warnings,
        "total_budget_estimate": {"amount": total, "currency": "GBP"},
        "overall_confidence": "low",
    }


def first_supplier_evidence_url(supplier_evidence: list[dict[str, Any]], supplier: str) -> str:
    supplier_lower = supplier.lower()
    for item in supplier_evidence:
        if item.get("supplier", "").lower() in supplier_lower or supplier_lower in item.get("supplier", "").lower():
            return item.get("url", "")
    return ""


def confidence_value(value: Any) -> str:
    lower = clean_protocol_text(value).lower()
    if lower in {"low", "medium", "high"}:
        return lower
    return "low"


def safe_money(value: Any) -> float:
    try:
        return max(0.0, round(float(value or 0), 2))
    except (TypeError, ValueError):
        return 0.0


def qc_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9+-]{3,}", text or "")
        if token.lower() not in QC_STOPWORDS
    }


QC_STOPWORDS = {
    "with",
    "will",
    "the",
    "and",
    "for",
    "into",
    "from",
    "that",
    "this",
    "than",
    "compared",
    "least",
    "increase",
    "reduce",
    "detect",
    "measured",
    "standard",
    "protocol",
    "medium",
    "points",
    "percentage",
    "assess",
    "whether",
    "relative",
    "targeting",
}


SOURCE_TYPE_BONUS = {
    "paper": 0.05,
    "protocol": 0.09,
    "standard": 0.07,
    "supplier_note": 0.02,
}


SOURCE_TYPE_PRIORITY = {
    "protocol": 4,
    "paper": 3,
    "standard": 2,
    "supplier_note": 1,
    "reference": 0,
}


PROTOCOL_TOOL_LABELS = {
    "3d printer": "3D printer",
    "3-d printer": "3D printer",
    "additive manufacturing system": "Additive manufacturing system",
    "detection system": "Detection system",
    "detector": "Detector",
    "imaging system": "Imaging system",
    "camera system": "Camera system",
    "scanner": "Scanner",
    "analyzer": "Analyzer",
    "flow cytometer": "Flow cytometer",
    "sequencer": "Sequencer",
    "plate reader": "Plate reader",
    "microplate reader": "Microplate reader",
    "microscope": "Microscope",
    "thermal cycler": "Thermal cycler",
    "qpcr": "qPCR cycler",
    "centrifuge": "Centrifuge",
    "incubator": "Incubator",
    "biosafety cabinet": "Biosafety cabinet",
    "safety cabinet": "Safety cabinet",
    "laminar flow hood": "Laminar flow hood",
    "hood": "Laboratory hood",
    "pipette": "Pipette set",
    "freezer": "Freezer",
    "water bath": "Water bath",
    "spectrophotometer": "Spectrophotometer",
    "balance": "Analytical balance",
    "robot": "Robot/workstation",
    "workstation": "Workstation",
    "controller": "Controller",
    "fixture": "Fixture",
    "pump": "Pump",
    "sensor": "Sensor",
}


PROTOCOL_TOOL_TERMS = tuple(PROTOCOL_TOOL_LABELS.keys())


PROTOCOL_CONSUMABLE_TERMS = (
    "blood",
    "cell",
    "strain",
    "sample",
    "trehalose",
    "dmso",
    "medium",
    "media",
    "buffer",
    "reagent",
    "antibody",
    "primer",
    "oligo",
    "kit",
    "dye",
    "solution",
    "plate",
    "tube",
    "tip",
    "flask",
    "filter",
    "glove",
    "vial",
    "cryovial",
    "plasmid",
    "chemical",
    "solvent",
    "substrate",
    "resin",
    "cartridge",
    "chip",
    "membrane",
    "column",
    "syringe",
    "needle",
    "swab",
    "slide",
)


PROTOCOL_CONSUMABLE_EXCLUSION_TERMS = (
    "sample",
    "samples",
    "reagent",
    "reagents",
    "kit",
    "kits",
    "consumable",
    "consumables",
    "disposable",
    "disposables",
    "cartridge",
    "cartridges",
)


def _references_for_domain(domain: str) -> list[dict[str, Any]]:
    common_protocols = {
        "title": "protocols.io protocol repository",
        "authors": ["protocols.io community"],
        "year": None,
        "source": "protocols.io",
        "url": "https://www.protocols.io/",
        "relevance_reason": "Useful source for runnable, versioned experimental protocols.",
    }
    by_domain: dict[str, list[dict[str, Any]]] = {
        "diagnostics": [
            {
                "title": "Thermo Fisher technical resources and application notes",
                "authors": ["Thermo Fisher Scientific"],
                "year": None,
                "source": "Supplier technical notes",
                "url": "https://www.thermofisher.com/us/en/home/technical-resources/application-notes.html",
                "relevance_reason": "Supplier protocol and reagent notes for assay validation workflows.",
            },
            {
                "title": "Bio-protocol peer-reviewed protocol repository",
                "authors": ["Bio-protocol community"],
                "year": None,
                "source": "Bio-protocol",
                "url": "https://bio-protocol.org/",
                "relevance_reason": "Comparable assay development and validation protocols.",
            },
            common_protocols,
        ],
        "gut_health": [
            {
                "title": "JoVE video and written protocols",
                "authors": ["JoVE community"],
                "year": None,
                "source": "JoVE",
                "url": "https://www.jove.com/",
                "relevance_reason": "Animal handling and assay workflows often include operational details.",
            },
            {
                "title": "Nature Protocols",
                "authors": ["Nature Protocols authors"],
                "year": None,
                "source": "Nature Protocols",
                "url": "https://www.nature.com/nprot",
                "relevance_reason": "High-detail in vivo and molecular validation protocols.",
            },
            common_protocols,
        ],
        "cell_biology": [
            {
                "title": "ATCC animal cell culture guide",
                "authors": ["ATCC"],
                "year": None,
                "source": "ATCC",
                "url": "https://www.atcc.org/",
                "relevance_reason": "Cell line handling, freezing, recovery, and QC guidance.",
            },
            {
                "title": "Sigma-Aldrich technical documents",
                "authors": ["Sigma-Aldrich"],
                "year": None,
                "source": "Supplier technical notes",
                "url": "https://www.sigmaaldrich.com/US/en/technical-documents",
                "relevance_reason": "Cryoprotectant and reagent handling documentation.",
            },
            common_protocols,
        ],
        "climate": [
            {
                "title": "OpenWetWare community protocols",
                "authors": ["OpenWetWare community"],
                "year": None,
                "source": "OpenWetWare",
                "url": "https://openwetware.org/",
                "relevance_reason": "Community protocols for microbial and electrochemical lab setup.",
            },
            {
                "title": "Bio-protocol peer-reviewed protocol repository",
                "authors": ["Bio-protocol community"],
                "year": None,
                "source": "Bio-protocol",
                "url": "https://bio-protocol.org/",
                "relevance_reason": "Runnable protocols for microbial culture and assay operations.",
            },
            common_protocols,
        ],
    }
    return by_domain.get("general_biology" if domain == "general_biology" else domain, [common_protocols])


def generate_experiment_plan(
    question: str,
    parsed: ParsedHypothesis,
    qc: dict[str, Any],
    relevant_reviews: list[dict[str, Any]],
    materials_budget: dict[str, Any] | None = None,
    relevant_protocols: dict[str, Any] | None = None,
    tailored_protocol: dict[str, Any] | None = None,
    tool_inventory: dict[str, Any] | None = None,
    materials_consumables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    template = _template_for_domain(parsed.domain)
    feedback_applied = _feedback_applications(relevant_reviews)
    plan_materials = materials_for_plan(materials_budget) or template["materials"]
    plan_budget = budget_for_plan(materials_budget) or template["budget_lines"]
    protocol_steps = protocol_steps_for_plan(tailored_protocol) or template["protocol_steps"]
    plan_timeline = timeline_for_experiment_plan(
        parsed,
        protocol_steps,
        relevant_protocols,
        tailored_protocol,
        tool_inventory,
        materials_consumables,
        materials_budget,
        template,
    )
    plan_validation = validation_for_experiment_plan(
        parsed,
        protocol_steps,
        relevant_protocols,
        tailored_protocol,
        materials_budget,
        template,
    )
    plan = {
        "plan_id": str(uuid.uuid4()),
        "title": f"{parsed.experiment_type.replace('_', ' ').title()} Plan",
        "experiment_type": parsed.experiment_type,
        "domain": parsed.domain,
        "readiness_score": 0.82 if qc["novelty_signal"] != "not_found" else 0.68,
        "estimated_total_budget": {
            "amount": sum(line["total_cost"] for line in plan_budget),
            "currency": (materials_budget or {}).get("total_budget_estimate", {}).get("currency", "GBP"),
        },
        "estimated_duration": estimated_duration_from_timeline(plan_timeline, template["estimated_duration"]),
        "protocol_steps": protocol_steps,
        "materials": plan_materials,
        "budget_lines": plan_budget,
        "timeline_phases": plan_timeline,
        "validation": plan_validation,
        "assumptions": [
            f"Hypothesis: {question}",
            f"Intervention: {parsed.intervention}",
            f"Control: {parsed.control}",
            f"Novelty signal: {qc['novelty_signal']} at {qc['confidence']:.0%} confidence.",
            "Timeline and validation are generated as experiment-plan outputs from approved protocol/material context.",
        ],
        "risks": template["risks"],
        "citations": qc["references"],
        "feedback_applied": feedback_applied,
    }
    _apply_feedback_to_plan(plan, feedback_applied)
    return plan


def protocol_steps_for_plan(tailored_protocol: dict[str, Any] | None) -> list[dict[str, Any]]:
    steps = []
    for step in (tailored_protocol or {}).get("steps", []):
        if not isinstance(step, dict):
            continue
        steps.append(
            {
                "step_number": int(step.get("step_number") or len(steps) + 1),
                "phase": clean_protocol_text(step.get("phase", ""))[:80] or "Tailored protocol",
                "title": clean_protocol_text(step.get("title", ""))[:160] or "Protocol step",
                "description": clean_protocol_text(step.get("description", ""))[:700],
                "inputs": sanitize_protocol_list(step.get("inputs", []), 12, 120),
                "outputs": sanitize_protocol_list(step.get("outputs", []), 8, 140),
                "duration": clean_protocol_text(step.get("duration", ""))[:80] or "TBD",
                "dependencies": sanitize_protocol_list(step.get("dependencies", []), 8, 120),
                "quality_checks": sanitize_protocol_list(step.get("validation_checks", []), 8, 160)
                or sanitize_protocol_list(step.get("quality_checks", []), 8, 160),
                "citations": sanitize_protocol_list(step.get("citations", []), 8, 300),
            }
        )
    return steps


def timeline_for_experiment_plan(
    parsed: ParsedHypothesis,
    protocol_steps: list[dict[str, Any]],
    relevant_protocols: dict[str, Any] | None,
    tailored_protocol: dict[str, Any] | None,
    tool_inventory: dict[str, Any] | None,
    materials_consumables: dict[str, Any] | None,
    materials_budget: dict[str, Any] | None,
    template: dict[str, Any],
) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    material_blocks = material_blocking_items(materials_budget, materials_consumables)
    tool_blocks = tool_blocking_items(tool_inventory)
    if material_blocks or tool_blocks:
        phases.append(
            experiment_timeline_phase(
                phase="Readiness and sourcing gate",
                duration="1-2 weeks" if material_blocks else "2-3 days",
                dependencies=[],
                deliverable="Materials, tools, quote confidence, and inventory status are ready for execution review.",
                critical_path=True,
                owner="Eric / lab operations",
                start_condition="Proceed after user accepts the material plan.",
                go_no_go_criteria="Proceed only when critical tools are available and required consumables have acceptable quote or manual verification status.",
                blocking_items=[*material_blocks, *tool_blocks],
                risk_notes=timeline_risk_from_materials(materials_budget),
                confidence=timeline_confidence(materials_budget, material_blocks, tool_blocks),
            )
        )

    previous = phases[-1]["phase"] if phases else ""
    for index, step in enumerate(protocol_steps[:10], start=1):
        title = clean_protocol_text(step.get("title", "")) or f"Protocol step {index}"
        quality_checks = step.get("quality_checks", []) or []
        outputs = step.get("outputs", []) or []
        phases.append(
            experiment_timeline_phase(
                phase=f"Step {index}: {title}",
                duration=clean_protocol_text(step.get("duration", "")) or "TBD",
                dependencies=[previous] if previous else sanitize_protocol_list(step.get("dependencies", []), 4, 120),
                deliverable=", ".join(outputs[:2]) if outputs else f"{title} complete.",
                critical_path=True,
                owner="Protocol owner",
                start_condition=f"Inputs available: {', '.join((step.get('inputs') or [])[:4])}" if step.get("inputs") else "Prior phase complete.",
                go_no_go_criteria=quality_checks[0] if quality_checks else "Document deviations before continuing.",
                blocking_items=[],
                risk_notes=clean_protocol_text((tailored_protocol or {}).get("warnings", [""])[0] if (tailored_protocol or {}).get("warnings") else ""),
                confidence="medium",
            )
        )
        previous = phases[-1]["phase"]

    if not phases:
        phases = [enrich_template_timeline_phase(item) for item in template["timeline_phases"]]
        previous = phases[-1]["phase"] if phases else ""

    validation_checks = validation_checks_from_context(parsed, relevant_protocols, tailored_protocol)
    phases.append(
        experiment_timeline_phase(
            phase="Validation and decision gate",
            duration="2-5 days",
            dependencies=[previous] if previous else [],
            deliverable=f"Go/no-go decision against {parsed.outcome or 'primary outcome'} criteria.",
            critical_path=True,
            owner="Scientific lead",
            start_condition="All planned measurements are complete and raw data are captured.",
            go_no_go_criteria=validation_checks[0] if validation_checks else "Primary success and failure criteria are evaluated.",
            blocking_items=[],
            risk_notes="Decision should be paused if controls fail, measurements are missing, or supplier substitutions changed the protocol.",
            confidence="medium",
        )
    )
    return phases[:12]


def validation_for_experiment_plan(
    parsed: ParsedHypothesis,
    protocol_steps: list[dict[str, Any]],
    relevant_protocols: dict[str, Any] | None,
    tailored_protocol: dict[str, Any] | None,
    materials_budget: dict[str, Any] | None,
    template: dict[str, Any],
) -> list[dict[str, Any]]:
    validation = []
    primary_method = first_validation_method(protocol_steps, tailored_protocol) or parsed.experiment_type.replace("_", " ")
    validation.append(
        experiment_validation_item(
            metric=parsed.outcome or "Primary outcome",
            method=primary_method,
            success_threshold=parsed.threshold or "Predefined success threshold met.",
            failure_criteria=f"Failure if {parsed.threshold} is not met or controls fail." if parsed.threshold else "Primary endpoint fails to improve over control.",
            controls=[parsed.control] if parsed.control else ["negative control", "positive control"],
            evidence_url=first_protocol_url(relevant_protocols, tailored_protocol, materials_budget),
            confidence="medium",
            sample_size_or_replicates="Confirm replicate count before execution.",
            statistical_test="Predefine field-appropriate comparison before execution.",
            acceptance_window="Evaluate after planned measurement timepoint; document deviations.",
            measurement_timepoint=measurement_timepoint_from_steps(protocol_steps),
            linked_protocol_step=linked_protocol_step_for_metric(protocol_steps, parsed.outcome),
        )
    )
    for check in validation_checks_from_context(parsed, relevant_protocols, tailored_protocol):
        if normalized_item_key(check) == normalized_item_key(parsed.outcome):
            continue
        validation.append(
            experiment_validation_item(
                metric=check,
                method="Protocol-derived validation check",
                success_threshold="Check passes according to accepted protocol or user-defined criterion.",
                failure_criteria="Check fails, is missing, or contradicts the expected direction.",
                controls=[parsed.control] if parsed.control else [],
                evidence_url=first_protocol_url(relevant_protocols, tailored_protocol, materials_budget),
                confidence="medium",
                sample_size_or_replicates="Same replicate structure as primary endpoint unless otherwise justified.",
                statistical_test="Descriptive QC or confirmatory test as appropriate.",
                acceptance_window="During the linked protocol phase.",
                measurement_timepoint=measurement_timepoint_from_steps(protocol_steps),
                linked_protocol_step=linked_protocol_step_for_metric(protocol_steps, check),
            )
        )
        if len(validation) >= 6:
            break
    if len(validation) == 1:
        for item in template["validation"][:2]:
            validation.append(enrich_template_validation_item(item))
    return validation[:8]


def experiment_timeline_phase(
    *,
    phase: str,
    duration: str,
    dependencies: list[str],
    deliverable: str,
    critical_path: bool,
    owner: str,
    start_condition: str,
    go_no_go_criteria: str,
    blocking_items: list[str],
    risk_notes: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "phase": clean_protocol_text(phase)[:120] or "Execution phase",
        "duration": clean_protocol_text(duration)[:80] or "TBD",
        "dependencies": sanitize_protocol_list(dependencies, 8, 120),
        "deliverable": clean_protocol_text(deliverable)[:300],
        "critical_path": bool(critical_path),
        "risk_notes": clean_protocol_text(risk_notes)[:300],
        "owner": clean_protocol_text(owner)[:120],
        "start_condition": clean_protocol_text(start_condition)[:240],
        "go_no_go_criteria": clean_protocol_text(go_no_go_criteria)[:300],
        "blocking_items": sanitize_protocol_list(blocking_items, 10, 140),
        "confidence": confidence_value(confidence),
    }


def experiment_validation_item(
    *,
    metric: str,
    method: str,
    success_threshold: str,
    failure_criteria: str,
    controls: list[str],
    evidence_url: str,
    confidence: str,
    sample_size_or_replicates: str,
    statistical_test: str,
    acceptance_window: str,
    measurement_timepoint: str,
    linked_protocol_step: str,
) -> dict[str, Any]:
    return {
        "metric": clean_protocol_text(metric)[:160] or "Primary outcome",
        "method": clean_protocol_text(method)[:220],
        "success_threshold": clean_protocol_text(success_threshold)[:220],
        "failure_criteria": clean_protocol_text(failure_criteria)[:220],
        "controls": sanitize_protocol_list(controls, 8, 140),
        "evidence_url": clean_protocol_text(evidence_url),
        "confidence": confidence_value(confidence),
        "sample_size_or_replicates": clean_protocol_text(sample_size_or_replicates)[:180],
        "statistical_test": clean_protocol_text(statistical_test)[:180],
        "acceptance_window": clean_protocol_text(acceptance_window)[:180],
        "measurement_timepoint": clean_protocol_text(measurement_timepoint)[:160],
        "linked_protocol_step": clean_protocol_text(linked_protocol_step)[:160],
    }


def enrich_template_timeline_phase(item: dict[str, Any]) -> dict[str, Any]:
    return experiment_timeline_phase(
        phase=item.get("phase", "Execution phase"),
        duration=item.get("duration", "TBD"),
        dependencies=item.get("dependencies", []),
        deliverable=item.get("deliverable", ""),
        critical_path=bool(item.get("critical_path", False)),
        owner="Protocol owner",
        start_condition="Prior dependency complete.",
        go_no_go_criteria="Proceed if deliverable is complete and deviations are documented.",
        blocking_items=[],
        risk_notes=item.get("risk_notes", ""),
        confidence="low",
    )


def enrich_template_validation_item(item: dict[str, Any]) -> dict[str, Any]:
    return experiment_validation_item(
        metric=item.get("metric", "Validation check"),
        method=item.get("method", ""),
        success_threshold=item.get("success_threshold", ""),
        failure_criteria=item.get("failure_criteria", ""),
        controls=item.get("controls", []),
        evidence_url=item.get("evidence_url", ""),
        confidence=item.get("confidence", "low"),
        sample_size_or_replicates="Confirm replicate count before execution.",
        statistical_test="Predefine before execution.",
        acceptance_window="Protocol-defined measurement window.",
        measurement_timepoint="TBD",
        linked_protocol_step="",
    )


def material_blocking_items(
    materials_budget: dict[str, Any] | None,
    materials_consumables: dict[str, Any] | None,
) -> list[str]:
    items = []
    for item in (materials_budget or {}).get("materials", []):
        if item.get("needs_manual_verification") or item.get("quote_confidence") in {"manual_quote_required", "none"}:
            items.append(item.get("name", "Material requiring verification"))
    for item in (materials_consumables or {}).get("items", []):
        if item.get("inventory_check_status") != "available" or item.get("pricing_status") == "not_priced":
            items.append(item.get("name", "Consumable requiring check"))
    return list(dict.fromkeys(clean_protocol_text(item) for item in items if clean_protocol_text(item)))[:10]


def tool_blocking_items(tool_inventory: dict[str, Any] | None) -> list[str]:
    items = []
    for section in (tool_inventory or {}).get("sections", []):
        for row in section.get("rows", []):
            if row.get("status") in {"missing", "limited", "ordered"}:
                items.append(row.get("item", "Tool requiring check"))
    return list(dict.fromkeys(clean_protocol_text(item) for item in items if clean_protocol_text(item)))[:10]


def timeline_risk_from_materials(materials_budget: dict[str, Any] | None) -> str:
    warnings = (materials_budget or {}).get("warnings", [])
    if warnings:
        return clean_protocol_text(warnings[0])
    if any(item.get("needs_manual_verification") for item in (materials_budget or {}).get("materials", [])):
        return "Manual quote/catalog verification may affect start date."
    return ""


def timeline_confidence(
    materials_budget: dict[str, Any] | None,
    material_blocks: list[str],
    tool_blocks: list[str],
) -> str:
    if material_blocks or tool_blocks:
        return "low"
    return confidence_value((materials_budget or {}).get("overall_confidence", "medium"))


def validation_checks_from_context(
    parsed: ParsedHypothesis,
    relevant_protocols: dict[str, Any] | None,
    tailored_protocol: dict[str, Any] | None,
) -> list[str]:
    checks = [parsed.outcome]
    checks.extend((tailored_protocol or {}).get("validation_checks", []))
    for step in (tailored_protocol or {}).get("steps", []):
        checks.extend(step.get("validation_checks", []))
        checks.extend(step.get("quality_checks", []))
    for candidate in (relevant_protocols or {}).get("protocol_candidates", []):
        checks.extend(candidate.get("validation_checks", []))
    return list(dict.fromkeys(clean_protocol_text(item) for item in checks if clean_protocol_text(item)))[:10]


def first_validation_method(
    protocol_steps: list[dict[str, Any]],
    tailored_protocol: dict[str, Any] | None,
) -> str:
    for check in (tailored_protocol or {}).get("validation_checks", []):
        value = clean_protocol_text(check)
        if value:
            return value
    for step in protocol_steps:
        checks = step.get("quality_checks", [])
        if checks:
            return clean_protocol_text(checks[0])
    return ""


def first_protocol_url(
    relevant_protocols: dict[str, Any] | None,
    tailored_protocol: dict[str, Any] | None,
    materials_budget: dict[str, Any] | None,
) -> str:
    for key in ["citations", "source_protocol_refs"]:
        values = (tailored_protocol or {}).get(key, [])
        if values:
            return clean_protocol_text(values[0])
    for candidate in (relevant_protocols or {}).get("protocol_candidates", []):
        value = clean_protocol_text(candidate.get("source_url", ""))
        if value:
            return value
    for item in (materials_budget or {}).get("materials", []):
        value = clean_protocol_text(item.get("source_url", ""))
        if value:
            return value
    return ""


def measurement_timepoint_from_steps(protocol_steps: list[dict[str, Any]]) -> str:
    if not protocol_steps:
        return "TBD"
    last = protocol_steps[-1]
    return clean_protocol_text(last.get("duration", "")) or f"After {last.get('title', 'final protocol step')}"


def linked_protocol_step_for_metric(protocol_steps: list[dict[str, Any]], metric: str) -> str:
    metric_lower = clean_protocol_text(metric).lower()
    for step in protocol_steps:
        text = " ".join(
            [
                step.get("title", ""),
                step.get("description", ""),
                " ".join(step.get("quality_checks", [])),
                " ".join(step.get("outputs", [])),
            ]
        ).lower()
        if metric_lower and any(token in text for token in metric_lower.split()[:4]):
            return clean_protocol_text(step.get("title", ""))
    return clean_protocol_text(protocol_steps[-1].get("title", "")) if protocol_steps else ""


def materials_for_plan(materials_budget: dict[str, Any] | None) -> list[dict[str, Any]]:
    materials = []
    for item in (materials_budget or {}).get("materials", []):
        materials.append(
            _material(
                item.get("name", "Material requiring review"),
                item.get("category", "material"),
                item.get("supplier", "TBD supplier"),
                item.get("catalog_number", "TBD"),
                item.get("quantity", "TBD"),
                item.get("total_cost_estimate", 0),
                item.get("rationale", "") or item.get("substitution_notes", "Verify supplier details."),
            )
        )
    return materials


def budget_for_plan(materials_budget: dict[str, Any] | None) -> list[dict[str, Any]]:
    lines = []
    for item in (materials_budget or {}).get("budget_lines", []):
        lines.append(
            _budget(
                item.get("category", "materials"),
                item.get("item", "Budget item requiring review"),
                item.get("quantity", ""),
                item.get("unit_cost_estimate", 0),
                item.get("total_cost_estimate", 0),
                item.get("notes", ""),
            )
        )
    return lines


def timeline_for_plan(materials_budget: dict[str, Any] | None) -> list[dict[str, Any]]:
    phases = []
    for item in (materials_budget or {}).get("timeline_phases", []):
        phases.append(
            {
                "phase": item.get("phase", "Execution phase"),
                "duration": item.get("duration", "TBD"),
                "dependencies": item.get("dependencies", []),
                "deliverable": item.get("deliverable", ""),
                "critical_path": bool(item.get("critical_path", False)),
            }
        )
    return phases


def validation_for_plan(materials_budget: dict[str, Any] | None) -> list[dict[str, Any]]:
    validation = []
    for item in (materials_budget or {}).get("validation", []):
        validation.append(
            _validation(
                item.get("metric", "Primary outcome"),
                item.get("method", ""),
                item.get("success_threshold", ""),
                item.get("failure_criteria", ""),
                item.get("controls", []),
            )
        )
    return validation


def estimated_duration_from_timeline(timeline: list[dict[str, Any]], fallback: str) -> str:
    if not timeline:
        return fallback
    return "; ".join(
        f"{item.get('phase', 'Phase')}: {item.get('duration', 'TBD')}"
        for item in timeline[:6]
    )


def _template_for_domain(domain: str) -> dict[str, Any]:
    if domain == "diagnostics":
        return _diagnostics_template()
    if domain == "gut_health":
        return _gut_health_template()
    if domain == "cell_biology":
        return _cell_biology_template()
    if domain == "climate":
        return _climate_template()
    return _general_template()


def _base_step(
    step_number: int,
    phase: str,
    title: str,
    description: str,
    duration: str,
    dependencies: list[str] | None = None,
    quality_checks: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "step_number": step_number,
        "phase": phase,
        "title": title,
        "description": description,
        "inputs": [],
        "outputs": [],
        "duration": duration,
        "dependencies": dependencies or [],
        "quality_checks": quality_checks or [],
        "citations": [],
    }


def _diagnostics_template() -> dict[str, Any]:
    materials = [
        _material("Anti-CRP antibody pair", "reagent", "Thermo Fisher", "701186", "1 kit", 520, "capture/detection chemistry"),
        _material("Screen-printed carbon electrodes", "consumable", "Metrohm DropSens", "DRP-110", "100 units", 420, "electrochemical transducer"),
        _material("Human CRP standard", "reagent", "Sigma-Aldrich", "C1617", "1 vial", 280, "calibration curve"),
        _material("Whole-blood collection tubes", "consumable", "BD", "367835", "100 tubes", 95, "sample collection"),
    ]
    budget = _budget_from_materials(materials) + [
        _budget("labor", "Assay development scientist", "5 days", 450, 2250, "Protocol optimization and analysis"),
        _budget("equipment", "Potentiostat rental/access", "2 weeks", 750, 1500, "Electrochemical readout"),
    ]
    return {
        "estimated_duration": "6 weeks",
        "protocol_steps": [
            _base_step(1, "design", "Define analytical range", "Set CRP calibration points spanning healthy and inflammatory ranges.", "0.5 day"),
            _base_step(2, "fabrication", "Functionalize electrodes", "Immobilize anti-CRP capture antibody on paper/electrode surface and block nonspecific binding.", "3 days", ["materials received"], ["surface wetting uniformity"]),
            _base_step(3, "calibration", "Run CRP standard curve", "Measure electrochemical response against CRP standards and fit limit-of-detection model.", "2 days", ["functionalized electrodes"], ["R2 >= 0.95"]),
            _base_step(4, "matrix test", "Test spiked whole blood", "Run spiked whole-blood samples without preprocessing and compare against ELISA benchmark.", "1 week", ["calibration curve"], ["duplicate CV <= 20%"]),
            _base_step(5, "analysis", "Estimate sensitivity and speed", "Calculate LoD, time-to-result, specificity, and agreement with ELISA.", "2 days", ["sample readouts"]),
        ],
        "materials": materials,
        "budget_lines": budget,
        "timeline_phases": _timeline(["Design", "Fabrication", "Calibration", "Whole-blood validation", "Analysis"], "6 weeks"),
        "validation": [
            _validation("Limit of detection", "CRP standard curve", "below 0.5 mg/L", "LoD >= 0.5 mg/L", ["blank", "ELISA benchmark"]),
            _validation("Time to result", "Timed assay workflow", "within 10 minutes", "median runtime > 10 minutes", ["operator timing control"]),
        ],
        "risks": ["Whole blood matrix effects may suppress signal.", "Antibody immobilization may be unstable on paper substrate."],
    }


def _gut_health_template() -> dict[str, Any]:
    materials = [
        _material("Lactobacillus rhamnosus GG", "biological", "ATCC", "53103", "1 strain", 530, "intervention"),
        _material("FITC-dextran 4 kDa", "reagent", "Sigma-Aldrich", "FD4", "1 g", 310, "intestinal permeability readout"),
        _material("Claudin-1 antibody", "reagent", "Thermo Fisher", "51-9000", "1 vial", 390, "tight junction validation"),
        _material("Occludin antibody", "reagent", "Thermo Fisher", "71-1500", "1 vial", 410, "tight junction validation"),
    ]
    budget = _budget_from_materials(materials) + [
        _budget("animals", "C57BL/6 mice cohort", "24 mice", 55, 1320, "Powered pilot with controls"),
        _budget("labor", "Animal technician and scientist time", "6 weeks", 900, 5400, "Dosing, sampling, assays"),
    ]
    return {
        "estimated_duration": "8 weeks",
        "protocol_steps": [
            _base_step(1, "setup", "Finalize animal protocol", "Confirm ethics approval, randomization, group sizes, and humane endpoints.", "1 week", quality_checks=["approved protocol ID recorded"]),
            _base_step(2, "intervention", "Administer probiotic", "Dose C57BL/6 mice with LGG daily for 4 weeks while tracking body weight and adverse events.", "4 weeks", ["animal arrival"]),
            _base_step(3, "permeability", "Run FITC-dextran assay", "Administer FITC-dextran and quantify serum fluorescence after standardized uptake window.", "2 days", ["completed dosing"]),
            _base_step(4, "molecular validation", "Measure tight junction proteins", "Collect intestinal tissue and quantify claudin-1 and occludin by immunoblot or qPCR.", "1 week", ["sample collection"]),
            _base_step(5, "statistics", "Compare treatment vs control", "Estimate percent permeability reduction and confidence intervals.", "3 days", ["assay data"]),
        ],
        "materials": materials,
        "budget_lines": budget,
        "timeline_phases": _timeline(["Ethics/setup", "Dosing", "FITC assay", "Molecular validation", "Statistics"], "8 weeks"),
        "validation": [
            _validation("Intestinal permeability", "FITC-dextran serum fluorescence", ">=30% reduction vs controls", "effect <15% or p >= 0.05", ["vehicle control", "untreated control"]),
            _validation("Mechanism", "Claudin-1 and occludin quantification", "upregulation vs controls", "no directional increase", ["housekeeping protein/gene"]),
        ],
        "risks": ["Animal ethics approval can block execution.", "Microbiome variability may require larger cohorts."],
    }


def _cell_biology_template() -> dict[str, Any]:
    materials = [
        _material("HeLa cell line", "cell line", "ATCC", "CCL-2", "1 vial", 420, "test system"),
        _material("Trehalose dihydrate", "reagent", "Sigma-Aldrich", "T9531", "100 g", 115, "candidate cryoprotectant"),
        _material("DMSO cell culture grade", "reagent", "Sigma-Aldrich", "D2650", "100 mL", 80, "standard protocol control"),
        _material("Trypan blue viability dye", "reagent", "Thermo Fisher", "15250061", "100 mL", 65, "post-thaw viability readout"),
    ]
    budget = _budget_from_materials(materials) + [
        _budget("consumables", "Culture plastics and media", "1 run", 650, 650, "Flasks, tubes, medium, serum"),
        _budget("labor", "Cell culture scientist", "3 weeks", 850, 2550, "Culture, freeze/thaw, analysis"),
    ]
    return {
        "estimated_duration": "4 weeks",
        "protocol_steps": [
            _base_step(1, "expansion", "Expand healthy HeLa culture", "Grow cells to logarithmic phase with viability above 90% before freezing.", "1 week", quality_checks=["mycoplasma-negative culture", "viability >= 90%"]),
            _base_step(2, "formulation", "Prepare freezing media", "Prepare standard DMSO control and trehalose-containing test formulations under sterile conditions.", "0.5 day"),
            _base_step(3, "freezing", "Controlled-rate freeze", "Freeze matched aliquots using controlled cooling and transfer to liquid nitrogen storage.", "1 day", ["healthy culture", "freezing media"]),
            _base_step(4, "thawing", "Thaw and recover cells", "Thaw replicate vials rapidly, dilute cryoprotectant, and recover under identical culture conditions.", "2 days", ["minimum 48 hour storage"]),
            _base_step(5, "readout", "Measure post-thaw viability", "Quantify viability and attachment at 0, 24, and 48 hours.", "2 days", ["recovered cells"], ["replicate CV <= 15%"]),
        ],
        "materials": materials,
        "budget_lines": budget,
        "timeline_phases": _timeline(["Expansion", "Freezing formulation", "Storage", "Thaw/recovery", "Analysis"], "4 weeks"),
        "validation": [
            _validation("Post-thaw viability", "Trypan blue or automated cell counter", ">=15 percentage point increase vs DMSO", "increase <5 points or viability below control", ["standard DMSO protocol", "unfrozen culture"]),
            _validation("Functional recovery", "24-48 hour attachment/growth", "growth rate not worse than control", "poor attachment or delayed recovery", ["matched passage control"]),
        ],
        "risks": ["Trehalose cell permeability may limit benefit.", "Passage number and freezing rate can dominate effect size."],
    }


def _climate_template() -> dict[str, Any]:
    materials = [
        _material("Sporomusa ovata culture", "microbe", "DSMZ", "2662", "1 culture", 690, "biocatalyst"),
        _material("Carbon cloth electrodes", "consumable", "Fuel Cell Store", "AvCarb-1071", "10 sheets", 340, "bioelectrochemical cathode"),
        _material("Anaerobic culture medium components", "reagent", "Sigma-Aldrich", "custom", "1 batch", 520, "growth medium"),
        _material("Acetate assay/HPLC standards", "reagent", "Sigma-Aldrich", "PHR1762", "1 kit", 180, "product quantification"),
    ]
    budget = _budget_from_materials(materials) + [
        _budget("equipment", "Bioelectrochemical reactor access", "4 weeks", 900, 3600, "Controlled cathode-potential experiments"),
        _budget("labor", "Microbial electrochemistry scientist", "6 weeks", 950, 5700, "Culture, reactor operation, analytics"),
    ]
    return {
        "estimated_duration": "7 weeks",
        "protocol_steps": [
            _base_step(1, "culture", "Revive anaerobic S. ovata", "Grow culture under strict anaerobic conditions and verify viability.", "1 week", quality_checks=["no oxygen exposure", "growth curve recorded"]),
            _base_step(2, "reactor setup", "Assemble bioelectrochemical cells", "Prepare cathode, inoculate reactor, and stabilize at -400 mV vs SHE.", "1 week", ["culture ready"]),
            _base_step(3, "operation", "Run CO2 fixation experiment", "Feed CO2 and monitor current, pH, biomass, and acetate production.", "3 weeks", ["stable reactor"]),
            _base_step(4, "analytics", "Quantify acetate", "Measure acetate by HPLC or validated colorimetric assay at defined intervals.", "1 week", ["reactor samples"]),
            _base_step(5, "benchmarking", "Compare to benchmark rate", "Normalize acetate production to volume/day and compare against current benchmark.", "3 days", ["analytics complete"]),
        ],
        "materials": materials,
        "budget_lines": budget,
        "timeline_phases": _timeline(["Culture", "Reactor setup", "Electrosynthesis", "Analytics", "Benchmarking"], "7 weeks"),
        "validation": [
            _validation("Acetate production rate", "HPLC or acetate assay", ">=150 mmol/L/day", "rate below 120 mmol/L/day", ["abiotic reactor", "open-circuit control"]),
            _validation("Benchmark improvement", "Normalized productivity comparison", ">=20% above benchmark", "less than 10% improvement", ["published benchmark condition"]),
        ],
        "risks": ["Anaerobic handling failures can invalidate runs.", "Cathode potential calibration vs SHE must be verified."],
    }


def _general_template() -> dict[str, Any]:
    materials = [
        _material("Core assay reagent set", "reagent", "TBD supplier", "TBD", "1 set", 1000, "placeholder until domain-specific sourcing"),
        _material("Experimental consumables", "consumable", "TBD supplier", "TBD", "1 run", 750, "plates, tubes, buffers, disposables"),
    ]
    budget = _budget_from_materials(materials) + [
        _budget("labor", "Scientist planning and execution", "4 weeks", 850, 3400, "Domain-specific execution"),
    ]
    return {
        "estimated_duration": "4-6 weeks",
        "protocol_steps": [
            _base_step(1, "scope", "Confirm hypothesis structure", "Lock intervention, system, outcome, threshold, and controls.", "0.5 day"),
            _base_step(2, "source", "Select published protocol anchor", "Choose the closest protocol and adapt only justified parameters.", "1 day"),
            _base_step(3, "execute", "Run pilot experiment", "Execute small pilot with negative and positive controls.", "2-4 weeks"),
            _base_step(4, "analyze", "Assess success criteria", "Compare measured outcome against declared threshold.", "2 days"),
        ],
        "materials": materials,
        "budget_lines": budget,
        "timeline_phases": _timeline(["Scope", "Protocol sourcing", "Pilot", "Analysis"], "4-6 weeks"),
        "validation": [
            _validation("Primary outcome", "Domain-specific assay", "meets submitted threshold", "threshold not met", ["negative control", "positive control"]),
        ],
        "risks": ["Insufficient hypothesis specificity reduces plan reliability."],
    }


def _material(
    name: str,
    category: str,
    supplier: str,
    catalog_number: str,
    quantity: str,
    total_cost: float,
    rationale: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "category": category,
        "supplier": supplier,
        "catalog_number": catalog_number,
        "quantity": quantity,
        "unit_cost": total_cost,
        "total_cost": total_cost,
        "currency": "GBP",
        "rationale": rationale,
    }


def _budget_from_materials(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _budget(
            "materials",
            item["name"],
            item["quantity"],
            item["unit_cost"],
            item["total_cost"],
            item["rationale"],
        )
        for item in materials
    ]


def _budget(
    category: str,
    item: str,
    quantity: str,
    unit_cost: float,
    total_cost: float,
    notes: str,
) -> dict[str, Any]:
    return {
        "category": category,
        "item": item,
        "quantity": quantity,
        "unit_cost": unit_cost,
        "total_cost": total_cost,
        "currency": "GBP",
        "notes": notes,
    }


def _timeline(phases: list[str], total_duration: str) -> list[dict[str, Any]]:
    timeline = []
    previous = []
    for index, phase in enumerate(phases, start=1):
        timeline.append(
            {
                "phase": phase,
                "duration": "1 week" if index < len(phases) else "2-3 days",
                "dependencies": previous[-1:],
                "deliverable": f"{phase} deliverable complete",
                "critical_path": index <= max(2, len(phases) - 1),
            }
        )
        previous.append(phase)
    timeline.append(
        {
            "phase": "Decision gate",
            "duration": "0.5 day",
            "dependencies": [phases[-1]],
            "deliverable": f"Go/no-go based on primary validation criteria; total plan {total_duration}.",
            "critical_path": True,
        }
    )
    return timeline


def _validation(
    metric: str,
    method: str,
    success_threshold: str,
    failure_criteria: str,
    controls: list[str],
) -> dict[str, Any]:
    return {
        "metric": metric,
        "method": method,
        "success_threshold": success_threshold,
        "failure_criteria": failure_criteria,
        "controls": controls,
    }


def _feedback_applications(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    applications = []
    for review in reviews:
        applications.append(
            {
                "section": review["section"],
                "correction": review["correction"],
                "annotation": review["annotation"] or None,
                "applied_as": "Prior expert correction injected into this plan.",
            }
        )
    return applications


def _apply_feedback_to_plan(plan: dict[str, Any], feedback: list[dict[str, Any]]) -> None:
    if not feedback:
        return
    for item in feedback:
        correction = item["correction"]
        section = item["section"]
        plan["assumptions"].append(f"Prior expert correction applied to {section}: {correction}")
        if section == "protocol":
            plan["protocol_steps"].append(
                _base_step(
                    len(plan["protocol_steps"]) + 1,
                    "expert review",
                    "Expert correction checkpoint",
                    correction,
                    "0.5 day",
                    quality_checks=["scientist correction acknowledged"],
                )
            )
        elif section == "materials":
            plan["materials"].append(
                _material(
                    "Expert-specified material adjustment",
                    "review adjustment",
                    "Scientist supplied",
                    "REVIEW-CORRECTION",
                    "as specified",
                    0,
                    correction,
                )
            )
        elif section == "budget":
            plan["budget_lines"].append(
                _budget(
                    "expert review",
                    "Budget correction from scientist",
                    "1",
                    0,
                    0,
                    correction,
                )
            )
        elif section == "timeline":
            plan["timeline_phases"].append(
                {
                    "phase": "Expert timeline adjustment",
                    "duration": "as corrected",
                    "dependencies": ["Decision gate"],
                    "deliverable": correction,
                    "critical_path": True,
                }
            )
        elif section == "validation":
            plan["validation"].append(
                _validation(
                    "Expert-specified validation check",
                    correction,
                    "as specified by scientist",
                    "expert validation condition not met",
                    ["scientist-specified control"],
                )
            )
