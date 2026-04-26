from __future__ import annotations

from typing import Any


def normalize_frontend_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized = []
    for message in messages or []:
        raw_role = str(message.get("role", "")).strip().lower()
        role = "assistant" if raw_role == "character" else raw_role
        if role not in {"user", "assistant"}:
            role = "assistant"
        normalized.append({"role": role, "text": str(message.get("text", ""))})
    return normalized


def latest_user_message(messages: list[dict[str, Any]]) -> str:
    for message in reversed(normalize_frontend_messages(messages)):
        if str(message.get("role", "")).lower() == "user":
            text = str(message.get("text", "")).strip()
            if text:
                return text
    return ""


def novelty_flag(signal: str) -> str:
    mapping = {
        "not_found": "novel_gap",
        "similar_work_exists": "similar_work_exists",
        "exact_match_found": "direct_replication",
    }
    return mapping.get(signal or "", "similar_work_exists")


def to_frontend_papers(qc: dict[str, Any]) -> list[dict[str, Any]]:
    papers = []
    for candidate in (qc.get("top_candidates", []) or [])[:10]:
        authors = ", ".join(candidate.get("authors", []) or [])
        papers.append(
            {
                "title": str(candidate.get("title", "")),
                "authors": authors,
                "journal": str(candidate.get("source", "")),
                "year": int(candidate.get("year") or 0),
                "similarity": max(0, min(100, round(float(candidate.get("final_score") or 0) * 100))),
                "doi": f"doi:{candidate.get('doi')}" if candidate.get("doi") else "",
                "url": str(candidate.get("url", "")),
            }
        )
    return papers


def parse_trail_steps(structured_parse: dict[str, Any] | None) -> list[dict[str, str]]:
    parse = structured_parse or {}
    primary_field = str(parse.get("primary_field", "")).strip()
    entities = [str(item).strip() for item in (parse.get("entities", []) or []) if str(item).strip()]
    confidence = float(parse.get("confidence") or 0.0)
    return [
        {
            "label": "Parsed hypothesis domain",
            "detail": f"Identified as: {primary_field or 'unknown'}",
        },
        {
            "label": "Extracted key entities",
            "detail": ", ".join(entities) if entities else "No entities extracted.",
        },
        {
            "label": "Assessed confidence",
            "detail": f"Parse confidence: {round(confidence * 100)}%",
        },
    ]


def source_trail_steps(qc: dict[str, Any]) -> list[dict[str, str]]:
    steps = []
    for source in (qc.get("source_statuses", []) or []):
        steps.append(
            {
                "label": f"{source.get('source', 'source')} — {source.get('result_count', 0)} results",
                "detail": str(source.get("message", "")),
            }
        )
    return steps


def inventory_sections_from_tool_and_materials(
    tool_inventory: dict[str, Any] | None,
    materials_consumables: dict[str, Any] | None = None,
    current_inventory: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    sections = []
    for section in (tool_inventory or {}).get("sections", []) or []:
        sections.append(
            {
                "title": str(section.get("title", "")),
                "rows": [
                    {
                        "item": str(row.get("item", "")),
                        "qty": str(row.get("qty", "") or ""),
                        "status": str(row.get("status", "missing")),
                        "note": str(row.get("note", "")),
                        "action": str(row.get("action", "") or ""),
                    }
                    for row in (section.get("rows", []) or [])
                ],
                "missingNote": str(section.get("missingNote", "") or ""),
            }
        )
    material_rows = []
    for item in (materials_consumables or {}).get("items", []) or []:
        material_rows.append(
            {
                "item": str(item.get("name", "")),
                "qty": str(item.get("quantity", "") or ""),
                "status": "missing" if bool(item.get("needs_manual_verification", True)) else "available",
                "note": (
                    f"{item.get('category', '')} · {item.get('supplier_hint', '')} · "
                    f"{item.get('pricing_status', '')}"
                ).strip(" ·"),
                "action": "Verify supplier, quantity, and stock" if bool(item.get("needs_manual_verification", True)) else "",
            }
        )
    if material_rows:
        sections.append(
            {
                "title": "Materials and consumables",
                "rows": material_rows,
                "missingNote": "Pricing and inventory checks are intentionally deferred.",
            }
        )
    return merge_inventory_status(sections, current_inventory or [])


def inventory_sections_from_tool_and_budget(
    tool_inventory: dict[str, Any] | None,
    materials_budget: dict[str, Any] | None,
    current_inventory: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    sections = inventory_sections_from_tool_and_materials(tool_inventory, None, current_inventory)
    material_rows = []
    for item in (materials_budget or {}).get("materials", []) or []:
        supplier = str(item.get("supplier", "") or "Supplier search pending")
        catalog = str(item.get("catalog_number", "") or item.get("source_url", "") or "Catalog/source search pending")
        unit = float(item.get("unit_cost_estimate") or 0)
        total = float(item.get("total_cost_estimate") or 0)
        currency = str(item.get("currency", "") or "GBP")
        price_note = f"{currency} {unit:g} unit / {currency} {total:g} total" if unit or total else "Price estimate pending"
        material_rows.append(
            {
                "item": str(item.get("name", "")),
                "qty": str(item.get("quantity", "") or "Quantity estimate pending"),
                "status": "missing" if bool(item.get("needs_manual_verification", True)) else "available",
                "note": (
                    f"{item.get('category', '')} · {supplier} · {catalog} · {price_note} · "
                    f"{item.get('cost_confidence', 'low')} confidence"
                ).strip(" ·"),
                "action": str(item.get("source_url", "") or item.get("substitution_notes", "") or "Confirm supplier, catalog number, stock, and quote."),
            }
        )
    if material_rows:
        total = (materials_budget or {}).get("total_budget_estimate", {}) or {}
        amount = total.get("amount", 0)
        currency = total.get("currency", "GBP")
        sections.append(
            {
                "title": "Materials, consumables, and budget",
                "rows": material_rows,
                "missingNote": f"Estimated total: {currency} {amount}. Confirm supplier quotes before purchasing.",
            }
        )
    return merge_inventory_status(sections, current_inventory or [])


def merge_inventory_status(generated: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_by_key = {}
    for section in current or []:
        section_title = str(section.get("title", ""))
        for row in section.get("rows", []) or []:
            key = (section_title.lower(), str(row.get("item", "")).lower())
            current_by_key[key] = row
    merged = []
    for section in generated:
        section_title = str(section.get("title", ""))
        rows = []
        for row in section.get("rows", []) or []:
            key = (section_title.lower(), str(row.get("item", "")).lower())
            existing = current_by_key.get(key, {})
            rows.append(
                {
                    **row,
                    "status": str(existing.get("status", row.get("status", "missing"))),
                    "note": str(existing.get("note", row.get("note", ""))),
                    "action": str(existing.get("action", row.get("action", ""))),
                    "qty": str(existing.get("qty", row.get("qty", ""))),
                }
            )
        merged.append({**section, "rows": rows})
    return merged


def plan_data_from_plan(plan: dict[str, Any], question: str) -> dict[str, str]:
    currency = ((plan.get("estimated_total_budget") or {}).get("currency") or "GBP")
    controls_steps = "\n\n".join(
        [
            f"{step.get('step_number', i + 1)}. {step.get('title', '')} ({step.get('duration', 'TBD')})\n{step.get('description', '')}".strip()
            for i, step in enumerate((plan.get("protocol_steps", []) or []))
        ]
    )
    validation_block = "\n\n".join(
        [
            (
                f"- {item.get('metric', '')}\n"
                f"  Pass: {item.get('success_threshold', '')}\n"
                f"  Fail: {item.get('failure_criteria', '')}\n"
                f"  Controls: {', '.join(item.get('controls', []) or [])}"
            ).strip()
            for item in (plan.get("validation", []) or [])
        ]
    )
    risks_block = "\n".join([f"- {risk}" for risk in (plan.get("risks", []) or [])])
    equipment_block = "\n".join(
        [
            f"- {material.get('name', '')} — {material.get('supplier', '')} ({material.get('catalog_number', '')}), {material.get('quantity', '')}".strip()
            for material in (plan.get("materials", []) or [])
        ]
    )
    budget_lines = [
        f"- {line.get('item', '')}: {currency} {int(line.get('total_cost', 0)) if isinstance(line.get('total_cost', 0), int) else line.get('total_cost', 0)}"
        for line in (plan.get("budget_lines", []) or [])
    ]
    total_amount = (plan.get("estimated_total_budget") or {}).get("amount", 0)
    budget_block = "\n".join([*budget_lines, "", f"Total estimated cost: {currency} {total_amount}"]).strip()
    timeline_block = "\n".join(
        [
            f"{i + 1}. {phase.get('phase', '')} — {phase.get('duration', '')}".strip()
            for i, phase in enumerate((plan.get("timeline_phases", []) or []))
        ]
    )
    title = str(plan.get("title", "")).strip()
    readiness = round(float(plan.get("readiness_score") or 0) * 100)
    return {
        "hypothesis": question or title,
        "controls": controls_steps,
        "falsifiability": f"{validation_block}\n\nRisks\n\n{risks_block}".strip(),
        "equipment": equipment_block,
        "budget": budget_block,
        "timeline": timeline_block,
        "impact": (
            f"{title}\n\nReadiness score: {readiness}%. "
            "This plan has been reviewed for scientific rigour, lab logistics, and experiment design."
        ).strip(),
    }


def is_approval(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ["ok", "okay", "yes", "continue", "proceed", "approved", "approve", "go ahead"])


def is_change_request(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ["change", "revise", "not happy", "different", "wrong", "go back", "redo", "modify", "rework", "unhappy"])
