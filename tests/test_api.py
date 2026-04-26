from __future__ import annotations

from fastapi.testclient import TestClient

import ai_scientist.advanced_qc as advanced_qc
import ai_scientist.source_adapters as source_adapters
from ai_scientist.app import create_app
from ai_scientist.services import (
    build_advanced_query_profile,
    build_query_profile,
    compute_source_coverage,
    decide_novelty,
    build_procurement_items,
    generate_experiment_plan,
    generate_materials_budget_proposal,
    generate_materials_consumables_dataset,
    generate_relevant_protocols,
    generate_tool_inventory,
    merge_llm_query_expansion,
    parse_question_for_job,
    parse_hypothesis,
    rank_qc_candidates,
    sanitize_materials_budget_response,
    sanitize_protocol_candidates,
    search_queries_for_profile,
)
from ai_scientist.source_adapters import SourceResult
from ai_scientist.web_search import WebSearchResult


CELL_QUESTION = (
    "Replacing sucrose with trehalose as a cryoprotectant in the freezing medium "
    "will increase post-thaw viability of HeLa cells by at least 15 percentage "
    "points compared to the standard DMSO protocol, due to trehalose's superior "
    "membrane stabilization at low temperatures."
)


def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("AI_SCIENTIST_LOAD_DOTENV", "0")
    monkeypatch.setenv("AI_SCIENTIST_LIVE_QC", "0")
    monkeypatch.setenv("AI_SCIENTIST_LLM_QUERY_EXPANSION", "0")
    monkeypatch.setenv("AI_SCIENTIST_ADVANCED_QC", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    app = create_app(str(tmp_path / "test.sqlite3"))
    return TestClient(app)


def test_full_flow_returns_frontend_safe_shapes(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)

    question_response = test_client.post("/api/questions", json={"question": CELL_QUESTION})
    assert question_response.status_code == 200
    job = question_response.json()
    assert job["status"] == "question_received"
    assert job["parsed_hypothesis"]["domain"] == "cell_biology"
    assert job["parsed_hypothesis"]["control"] == "the standard DMSO protocol"

    qc_response = test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")
    assert qc_response.status_code == 200
    qc = qc_response.json()
    assert qc["novelty_signal"] in {
        "not_found",
        "similar_work_exists",
        "exact_match_found",
    }
    assert 1 <= len(qc["references"]) <= 10
    assert qc["source_statuses"][0]["status"] == "disabled"
    assert qc["original_query"] == CELL_QUESTION
    assert qc["scientific_query"]
    assert qc["keywords"]
    assert [variant["kind"] for variant in qc["query_variants"]] == [
        "strict_exact",
        "broad_scientific",
        "protocol_search",
    ]
    assert qc["llm_query_expansion_used"] is False
    assert qc["advanced_qc_used"] is False
    assert qc["field_classification"] == {}
    assert qc["literature_review_summary"] == ""
    assert qc["llm_provider"]
    assert qc["llm_paraphrased_question"] == ""
    assert qc["llm_error"]
    assert qc["candidate_count"] >= 1
    assert qc["source_coverage"]["coverage_score"] == 0
    assert qc["top_candidates"]
    assert qc["ranking_explanation"]

    protocols_response = test_client.post(f"/api/jobs/{job['job_id']}/protocols")
    assert protocols_response.status_code == 200
    protocols = protocols_response.json()
    assert protocols["protocol_set_id"]
    assert protocols["job_id"] == job["job_id"]
    assert protocols["summary"]
    assert protocols["protocol_candidates"]
    assert protocols["evidence_count"] >= 1
    first_protocol = protocols["protocol_candidates"][0]
    assert first_protocol["title"]
    assert "adapted_steps" in first_protocol
    assert "tools" in first_protocol
    assert "consumables" in first_protocol
    assert "validation_checks" in first_protocol
    assert "limitations" in first_protocol
    assert "citations" in first_protocol

    def fake_generate_materials(job_id, question, parsed, structured_parse, qc, relevant_protocols):
        return {
            "proposal_id": "materials-1",
            "job_id": job_id,
            "summary": "Materials and budget proposal.",
            "materials": [
                {
                    "name": "HeLa cell line",
                    "category": "cell line",
                    "supplier": "ATCC",
                    "catalog_number": "CCL-2",
                    "quantity": "1 vial",
                    "unit_cost_estimate": 420,
                    "total_cost_estimate": 420,
                    "currency": "GBP",
                    "cost_confidence": "low",
                    "availability_status": "estimated",
                    "source_url": "https://www.atcc.org/",
                    "evidence_type": "estimated",
                    "rationale": "Test system.",
                    "substitution_notes": "Verify availability.",
                    "needs_manual_verification": True,
                }
            ],
            "budget_lines": [
                {
                    "category": "materials",
                    "item": "HeLa cell line",
                    "quantity": "1 vial",
                    "unit_cost_estimate": 420,
                    "total_cost_estimate": 420,
                    "currency": "GBP",
                    "cost_confidence": "low",
                    "source_url": "https://www.atcc.org/",
                    "notes": "Estimate only.",
                    "needs_manual_verification": True,
                }
            ],
            "timeline_phases": [
                {
                    "phase": "Sourcing",
                    "duration": "1 week",
                    "dependencies": [],
                    "deliverable": "Materials ordered.",
                    "critical_path": True,
                    "risk_notes": "Supplier lead time.",
                }
            ],
            "validation": [
                {
                    "metric": "Post-thaw viability",
                    "method": "Trypan blue",
                    "success_threshold": ">=15 point increase",
                    "failure_criteria": "<5 point increase",
                    "controls": ["DMSO control"],
                    "evidence_url": "",
                    "confidence": "medium",
                }
            ],
            "supplier_evidence": [],
            "assumptions": [],
            "warnings": ["Verify supplier quote."],
            "total_budget_estimate": {"amount": 420, "currency": "GBP"},
            "evidence_count": 0,
            "overall_confidence": "low",
        }

    monkeypatch.setattr("ai_scientist.app.generate_materials_budget_proposal", fake_generate_materials)
    materials_response = test_client.post(f"/api/jobs/{job['job_id']}/materials-budget")
    assert materials_response.status_code == 200
    materials = materials_response.json()
    assert materials["proposal_id"] == "materials-1"
    assert materials["materials"][0]["needs_manual_verification"] is True
    assert materials["budget_lines"][0]["cost_confidence"] == "low"
    assert materials["timeline_phases"]
    assert materials["validation"]

    plan_response = test_client.post(f"/api/jobs/{job['job_id']}/plans")
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["plan_id"]
    assert plan["estimated_total_budget"]["currency"] == "GBP"
    assert plan["protocol_steps"]
    assert plan["materials"]
    assert plan["budget_lines"]
    assert plan["timeline_phases"]
    assert plan["validation"]
    assert plan["citations"]

    review_response = test_client.post(
        f"/api/plans/{plan['plan_id']}/reviews",
        json={
            "section": "validation",
            "rating": 4,
            "correction": "Add a 24-hour post-thaw attachment metric.",
            "annotation": "Viability alone is not enough for HeLa recovery.",
        },
    )
    assert review_response.status_code == 200
    review = review_response.json()
    assert review["domain"] == "cell_biology"
    assert review["experiment_type"] == "cell_culture_optimization"

    job_response = test_client.get(f"/api/jobs/{job['job_id']}")
    assert job_response.status_code == 200
    hydrated = job_response.json()
    assert hydrated["literature_qc"] is not None
    assert hydrated["relevant_protocols"] is not None
    assert hydrated["materials_budget"] is not None
    assert hydrated["experiment_plan"] is not None
    assert hydrated["status"] == "review_saved"


def test_plan_requires_literature_qc(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()

    response = test_client.post(f"/api/jobs/{job['job_id']}/plans")

    assert response.status_code == 409
    assert "Run literature QC" in response.json()["detail"]

    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")
    before_materials = test_client.post(f"/api/jobs/{job['job_id']}/plans")
    assert before_materials.status_code == 409
    assert "Generate materials and budget" in before_materials.json()["detail"]


def test_question_refinements_return_three_academic_options_plus_manual(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)

    def fake_complete_json(prompt_paths, payload, *, max_tokens=1600):
        return {
            "options": [
                {
                    "label": "Mechanistic hypothesis",
                    "question": "Does trehalose improve post-thaw viability of HeLa cells relative to DMSO control?",
                    "rationale": "Clarifies intervention, system, and comparator.",
                },
                {
                    "label": "Outcome-focused hypothesis",
                    "question": "To what extent does trehalose alter HeLa post-thaw viability compared with standard cryoprotectant media?",
                    "rationale": "Emphasizes measurable outcome.",
                },
                {
                    "label": "Protocol-focused hypothesis",
                    "question": "Can a trehalose-based freezing protocol improve HeLa recovery after thawing compared with DMSO?",
                    "rationale": "Makes the protocol context explicit.",
                },
            ],
            "_llm_provider": "OpenAI",
            "_llm_model": "test-model",
        }

    monkeypatch.setattr("ai_scientist.services.complete_json_with_prompt", fake_complete_json)

    response = test_client.post("/api/questions/refinements", json={"question": CELL_QUESTION})

    assert response.status_code == 200
    body = response.json()
    assert len(body["options"]) == 4
    assert body["options"][0]["option_id"] == "academic_1"
    assert body["options"][3]["option_id"] == "manual"
    assert body["options"][3]["editable"] is True
    assert body["llm_provider"] == "OpenAI"


def test_feedback_draft_does_not_persist_until_confirmed(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()
    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")
    test_client.post(f"/api/jobs/{job['job_id']}/protocols")
    test_client.post(f"/api/jobs/{job['job_id']}/tailored-protocol")
    original = test_client.post(f"/api/jobs/{job['job_id']}/tool-inventory").json()
    original_count = len(original["sections"][0]["rows"])

    draft_response = test_client.post(
        f"/api/jobs/{job['job_id']}/feedback-drafts",
        json={
            "stage": "tool_inventory",
            "mode": "manual",
            "operations": [
                {
                    "action": "add",
                    "row": {
                        "item": "backup controlled-rate freezer",
                        "status": "limited",
                        "note": "User requested backup capacity.",
                        "action": "Reserve backup slot.",
                    },
                }
            ],
        },
    )

    assert draft_response.status_code == 200
    draft = draft_response.json()
    assert draft["requires_confirmation"] is True
    assert len(draft["proposed_artifact"]["sections"][0]["rows"]) == original_count + 1

    unchanged = test_client.get(f"/api/jobs/{job['job_id']}").json()["tool_inventory"]
    assert len(unchanged["sections"][0]["rows"]) == original_count

    confirm_response = test_client.patch(
        f"/api/jobs/{job['job_id']}/artifacts/tool_inventory",
        json={"artifact": draft["proposed_artifact"]},
    )

    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert len(confirmed["sections"][0]["rows"]) == original_count + 1
    assert any(row["item"] == "backup controlled-rate freezer" for row in confirmed["sections"][0]["rows"])


def test_feedback_draft_materials_manual_delete_and_confirm(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()
    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")
    test_client.post(f"/api/jobs/{job['job_id']}/protocols")
    test_client.post(f"/api/jobs/{job['job_id']}/tailored-protocol")
    test_client.post(f"/api/jobs/{job['job_id']}/tool-inventory")
    materials = test_client.post(f"/api/jobs/{job['job_id']}/materials-consumables").json()

    draft_response = test_client.post(
        f"/api/jobs/{job['job_id']}/feedback-drafts",
        json={
            "stage": "materials_consumables",
            "mode": "manual",
            "operations": [{"action": "delete", "item_index": 0}],
        },
    )

    assert draft_response.status_code == 200
    draft = draft_response.json()
    assert len(draft["proposed_artifact"]["items"]) == max(0, len(materials["items"]) - 1)

    unchanged = test_client.get(f"/api/jobs/{job['job_id']}").json()["materials_consumables"]
    assert len(unchanged["items"]) == len(materials["items"])

    confirm_response = test_client.patch(
        f"/api/jobs/{job['job_id']}/artifacts/materials_consumables",
        json={"artifact": draft["proposed_artifact"]},
    )

    assert confirm_response.status_code == 200
    assert len(confirm_response.json()["items"]) == max(0, len(materials["items"]) - 1)


def test_protocols_require_literature_qc(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()

    response = test_client.post(f"/api/jobs/{job['job_id']}/protocols")

    assert response.status_code == 409
    assert "Run literature QC" in response.json()["detail"]


def test_materials_budget_requires_qc_and_protocols(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()

    before_qc = test_client.post(f"/api/jobs/{job['job_id']}/materials-budget")
    assert before_qc.status_code == 409
    assert "Run literature QC" in before_qc.json()["detail"]

    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")
    before_protocols = test_client.post(f"/api/jobs/{job['job_id']}/materials-budget")
    assert before_protocols.status_code == 409
    assert "Generate relevant protocols" in before_protocols.json()["detail"]


def test_eric_protocol_workflow_requires_ordered_artifacts(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()

    before_qc = test_client.post(f"/api/jobs/{job['job_id']}/tailored-protocol")
    assert before_qc.status_code == 409
    assert "Run literature QC" in before_qc.json()["detail"]

    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")
    before_protocols = test_client.post(f"/api/jobs/{job['job_id']}/tailored-protocol")
    assert before_protocols.status_code == 409
    assert "Generate relevant protocols" in before_protocols.json()["detail"]

    before_tailored = test_client.post(f"/api/jobs/{job['job_id']}/tool-inventory")
    assert before_tailored.status_code == 409
    assert "tailored protocol" in before_tailored.json()["detail"]

    before_tools = test_client.post(f"/api/jobs/{job['job_id']}/materials-consumables")
    assert before_tools.status_code == 409
    assert "tailored protocol" in before_tools.json()["detail"]


def test_protocols_endpoint_returns_candidate_protocols(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()
    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")

    def fake_generate_protocols(job_id, question, parsed, structured_parse, qc):
        assert qc["references"]
        assert qc["top_candidates"]
        return {
            "protocol_set_id": "protocols-1",
            "job_id": job_id,
            "summary": "Candidate protocol extracted from QC evidence.",
            "protocol_candidates": [
                {
                    "title": "QC-derived cryopreservation workflow",
                    "source_title": "Source method",
                    "source_url": "https://example.com/source-method",
                    "source_type": "paper",
                    "evidence_quality": "adapted",
                    "relevance_reason": "Matches the cell freezing question.",
                    "adapted_steps": ["Prepare cells.", "Run freeze/thaw comparison."],
                    "tools": [],
                    "consumables": [
                        {
                            "name": "HeLa cells",
                            "category": "biological sample",
                            "source_protocol_title": "QC-derived cryopreservation workflow",
                            "source_url": "https://example.com/source-method",
                            "rationale": "Sample input.",
                            "needs_user_check": True,
                            "procurement_required": True,
                        },
                        {
                            "name": "trehalose",
                            "category": "material",
                            "source_protocol_title": "QC-derived cryopreservation workflow",
                            "source_url": "https://example.com/source-method",
                            "rationale": "Reagent input.",
                            "needs_user_check": True,
                            "procurement_required": True,
                        },
                    ],
                    "validation_checks": ["Measure viability."],
                    "limitations": ["Requires manual protocol review."],
                    "citations": ["https://example.com/source-method"],
                }
            ],
            "tools": [],
            "consumables": [],
            "warnings": [],
            "evidence_count": 2,
        }

    monkeypatch.setattr("ai_scientist.app.generate_relevant_protocols", fake_generate_protocols)

    response = test_client.post(f"/api/jobs/{job['job_id']}/protocols")

    assert response.status_code == 200
    protocols = response.json()
    assert protocols["protocol_set_id"] == "protocols-1"
    assert protocols["protocol_candidates"][0]["adapted_steps"]
    assert protocols["protocol_candidates"][0]["consumables"]
    assert protocols["protocol_candidates"][0]["validation_checks"]


def test_eric_protocol_workflow_returns_persisted_shapes(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()
    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")
    test_client.post(f"/api/jobs/{job['job_id']}/protocols")

    def fake_tailored(job_id, question, parsed, structured_parse, qc, relevant_protocols):
        return {
            "tailored_protocol_id": "tailored-1",
            "job_id": job_id,
            "title": "Tailored cryopreservation protocol",
            "summary": "A protocol tailored to the original Rachael prompt and QC-derived protocols.",
            "steps": [
                {
                    "step_number": 1,
                    "title": "Prepare cells and media",
                    "description": "Prepare HeLa cells, freezing medium, trehalose, DMSO control, plates, pipettes, and a controlled-rate freezer.",
                    "inputs": ["HeLa cells", "trehalose", "DMSO control", "controlled-rate freezer", "pipette set"],
                    "outputs": ["Prepared experimental and control conditions"],
                    "duration": "1 day",
                    "validation_checks": ["Cell density documented."],
                    "safety_notes": ["Use approved cell culture handling procedures."],
                    "citations": ["https://example.com/protocol"],
                }
            ],
            "inputs": ["HeLa cells", "trehalose", "DMSO control", "controlled-rate freezer", "pipette set"],
            "outputs": ["Post-thaw viability measurement"],
            "validation_checks": ["Measure viability against DMSO control."],
            "safety_notes": ["Manual safety review required."],
            "source_protocol_refs": ["https://example.com/protocol"],
            "citations": ["https://example.com/protocol"],
            "warnings": ["Review before execution."],
        }

    monkeypatch.setattr("ai_scientist.app.generate_tailored_protocol", fake_tailored)

    tailored_response = test_client.post(f"/api/jobs/{job['job_id']}/tailored-protocol")
    assert tailored_response.status_code == 200
    tailored = tailored_response.json()
    assert tailored["tailored_protocol_id"] == "tailored-1"
    assert tailored["steps"][0]["inputs"]

    before_tools = test_client.post(f"/api/jobs/{job['job_id']}/materials-consumables")
    assert before_tools.status_code == 409
    assert "tool inventory" in before_tools.json()["detail"]

    tool_response = test_client.post(f"/api/jobs/{job['job_id']}/tool-inventory")
    assert tool_response.status_code == 200
    tools = tool_response.json()
    assert tools["sections"][0]["rows"]
    assert tools["sections"][0]["rows"][0]["status"] in {"available", "limited", "missing", "ordered"}

    materials_response = test_client.post(f"/api/jobs/{job['job_id']}/materials-consumables")
    assert materials_response.status_code == 200
    materials = materials_response.json()
    assert materials["items"]
    assert materials["items"][0]["pricing_status"] == "not_priced"
    assert materials["items"][0]["inventory_check_status"] == "not_checked"

    hydrated = test_client.get(f"/api/jobs/{job['job_id']}").json()
    assert hydrated["tailored_protocol"]["tailored_protocol_id"] == "tailored-1"
    assert hydrated["tool_inventory"]["sections"]
    assert hydrated["materials_consumables"]["items"]


def test_tool_inventory_dummy_statuses_are_stable() -> None:
    protocol = {
        "steps": [
            {
                "title": "Run plate reader measurement",
                "description": "Use a plate reader, pipette set, and data capture workstation.",
                "inputs": ["plate reader", "pipette set"],
                "outputs": [],
            }
        ]
    }

    first = generate_tool_inventory("job-123", protocol)
    second = generate_tool_inventory("job-123", protocol)

    assert first["sections"][0]["rows"] == second["sections"][0]["rows"]


def test_experiment_plan_owns_timeline_and_validation_from_late_stage_artifacts() -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    tailored_protocol = {
        "title": "Tailored cryopreservation protocol",
        "steps": [
            {
                "step_number": 1,
                "title": "Prepare freezing media",
                "description": "Prepare trehalose and DMSO control media.",
                "inputs": ["trehalose", "DMSO control"],
                "outputs": ["Prepared media"],
                "duration": "1 day",
                "validation_checks": ["Media formulation documented."],
                "citations": ["https://example.com/protocol"],
            },
            {
                "step_number": 2,
                "title": "Measure post-thaw viability",
                "description": "Thaw cells and measure viability.",
                "inputs": ["HeLa cells", "Trypan blue"],
                "outputs": ["Post-thaw viability data"],
                "duration": "2 days",
                "validation_checks": ["Post-thaw viability measured against DMSO control."],
                "citations": ["https://example.com/protocol"],
            },
        ],
        "validation_checks": ["Measure viability against DMSO control."],
        "citations": ["https://example.com/protocol"],
        "warnings": ["Cell passage and thaw timing need confirmation."],
    }
    materials_budget = {
        "materials": [
            {
                "name": "Trypan blue viability dye",
                "needs_manual_verification": True,
                "quote_confidence": "manual_quote_required",
            }
        ],
        "budget_lines": [
            {
                "category": "materials",
                "item": "Trypan blue viability dye",
                "quantity": "100 mL",
                "unit_cost_estimate": 65,
                "total_cost_estimate": 65,
                "notes": "Quote required.",
            }
        ],
        "warnings": ["Manual supplier quote required."],
        "overall_confidence": "low",
        "total_budget_estimate": {"amount": 65, "currency": "GBP"},
    }
    plan = generate_experiment_plan(
        CELL_QUESTION,
        parsed,
        {"novelty_signal": "similar_work_exists", "confidence": 0.84, "references": []},
        [],
        materials_budget,
        {"protocol_candidates": [{"source_url": "https://example.com/protocol", "validation_checks": ["Confirm viability assay controls."]}]},
        tailored_protocol,
        {"sections": [{"rows": [{"item": "controlled-rate freezer", "status": "limited"}]}]},
        {"items": [{"name": "Trypan blue viability dye", "pricing_status": "not_priced", "inventory_check_status": "not_checked"}]},
    )

    assert plan["timeline_phases"][0]["phase"] == "Readiness and sourcing gate"
    assert "Trypan blue viability dye" in plan["timeline_phases"][0]["blocking_items"]
    assert "controlled-rate freezer" in plan["timeline_phases"][0]["blocking_items"]
    assert any(phase["go_no_go_criteria"] for phase in plan["timeline_phases"])
    assert plan["validation"][0]["sample_size_or_replicates"]
    assert plan["validation"][0]["statistical_test"]
    assert plan["validation"][0]["linked_protocol_step"] == "Measure post-thaw viability"


def test_materials_budget_endpoint_returns_frontend_safe_shape(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()
    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")
    protocols = test_client.post(f"/api/jobs/{job['job_id']}/protocols").json()

    def fake_generate_materials(job_id, question, parsed, structured_parse, qc, relevant_protocols):
        assert relevant_protocols["protocol_set_id"] == protocols["protocol_set_id"]
        return {
            "proposal_id": "proposal-123",
            "job_id": job_id,
            "summary": "Trustworthy proposal with explicit verification flags.",
            "materials": [
                {
                    "name": "Trypan blue viability dye",
                    "category": "reagent",
                    "supplier": "Thermo Fisher",
                    "catalog_number": "15250061",
                    "quantity": "100 mL",
                    "unit_cost_estimate": 65,
                    "total_cost_estimate": 65,
                    "currency": "GBP",
                    "cost_confidence": "low",
                    "availability_status": "estimated",
                    "source_url": "https://www.thermofisher.com/",
                    "evidence_type": "estimated",
                    "rationale": "Viability readout.",
                    "substitution_notes": "Equivalent viability dye acceptable.",
                    "needs_manual_verification": True,
                }
            ],
            "budget_lines": [
                {
                    "category": "materials",
                    "item": "Trypan blue viability dye",
                    "quantity": "100 mL",
                    "unit_cost_estimate": 65,
                    "total_cost_estimate": 65,
                    "currency": "GBP",
                    "cost_confidence": "low",
                    "source_url": "https://www.thermofisher.com/",
                    "notes": "Estimate only.",
                    "needs_manual_verification": True,
                }
            ],
            "timeline_phases": [
                {
                    "phase": "Sourcing",
                    "duration": "1 week",
                    "dependencies": [],
                    "deliverable": "Supplier quote checked.",
                    "critical_path": True,
                    "risk_notes": "Lead time may vary.",
                }
            ],
            "validation": [
                {
                    "metric": "Viability",
                    "method": "Trypan blue count",
                    "success_threshold": ">=15 point increase",
                    "failure_criteria": "<5 point increase",
                    "controls": ["DMSO control"],
                    "evidence_url": "https://www.thermofisher.com/",
                    "confidence": "medium",
                }
            ],
            "supplier_evidence": [
                {
                    "supplier": "Thermo Fisher",
                    "evidence_type": "application_note",
                    "title": "Thermo Fisher supplier evidence",
                    "url": "https://www.thermofisher.com/",
                    "catalog_number": "",
                    "status": "reachable",
                    "message": "Application note page reachable; pricing not verified.",
                    "confidence": "low",
                }
            ],
            "assumptions": ["Pricing varies by region."],
            "warnings": ["Manual supplier quote required."],
            "total_budget_estimate": {"amount": 65, "currency": "GBP"},
            "evidence_count": 1,
            "overall_confidence": "low",
        }

    monkeypatch.setattr("ai_scientist.app.generate_materials_budget_proposal", fake_generate_materials)

    response = test_client.post(f"/api/jobs/{job['job_id']}/materials-budget")

    assert response.status_code == 200
    proposal = response.json()
    assert proposal["proposal_id"] == "proposal-123"
    assert proposal["materials"][0]["catalog_number"] == "15250061"
    assert proposal["materials"][0]["needs_manual_verification"] is True
    assert proposal["budget_lines"][0]["total_cost_estimate"] == 65
    assert proposal["timeline_phases"][0]["critical_path"] is True
    assert proposal["validation"][0]["controls"] == ["DMSO control"]
    assert proposal["supplier_evidence"][0]["evidence_type"] == "application_note"


def test_sse_events_include_expected_status_transitions(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()
    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")
    test_client.post(f"/api/jobs/{job['job_id']}/protocols")
    test_client.post(f"/api/jobs/{job['job_id']}/materials-budget")
    test_client.post(f"/api/jobs/{job['job_id']}/plans")

    with test_client.stream("GET", f"/api/jobs/{job['job_id']}/events") as response:
        body = response.read().decode("utf-8")

    assert "event: question_received" in body
    assert "event: parsing" in body
    assert "event: qc_running" in body
    assert "event: qc_ready" in body
    assert "event: plan_generating" in body
    assert "event: plan_ready" in body


def test_prior_feedback_is_reused_for_similar_plan(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)

    first_job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()
    test_client.post(f"/api/jobs/{first_job['job_id']}/literature-qc")
    test_client.post(f"/api/jobs/{first_job['job_id']}/protocols")
    test_client.post(f"/api/jobs/{first_job['job_id']}/materials-budget")
    first_plan = test_client.post(f"/api/jobs/{first_job['job_id']}/plans").json()
    correction = "Add a mycoplasma test immediately before freezing."
    test_client.post(
        f"/api/plans/{first_plan['plan_id']}/reviews",
        json={
            "section": "protocol",
            "rating": 5,
            "correction": correction,
            "annotation": "Contaminated cultures make cryopreservation results meaningless.",
        },
    )

    second_question = (
        "Testing trehalose and glycerol in HeLa cells will improve post-thaw recovery "
        "by at least 10 percentage points compared to the standard DMSO protocol."
    )
    second_job = test_client.post("/api/questions", json={"question": second_question}).json()
    test_client.post(f"/api/jobs/{second_job['job_id']}/literature-qc")
    test_client.post(f"/api/jobs/{second_job['job_id']}/protocols")
    test_client.post(f"/api/jobs/{second_job['job_id']}/materials-budget")
    second_plan = test_client.post(f"/api/jobs/{second_job['job_id']}/plans").json()

    assert second_plan["feedback_applied"]
    assert any(item["correction"] == correction for item in second_plan["feedback_applied"])
    assert any(correction in step["description"] for step in second_plan["protocol_steps"])


def test_examples_endpoint_returns_prompt_samples(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)

    response = test_client.get("/api/examples")

    assert response.status_code == 200
    examples = response.json()
    assert len(examples) == 4
    assert {example["id"] for example in examples} == {
        "diagnostics",
        "gut-health",
        "cell-biology",
        "climate",
    }


def test_query_profile_contains_scientific_rewrite_and_three_variants() -> None:
    parsed = parse_hypothesis(CELL_QUESTION)

    profile = build_query_profile(CELL_QUESTION, parsed)

    assert profile["original_query"] == CELL_QUESTION
    assert "Scientific hypothesis:" in profile["scientific_query"]
    assert "trehalose" in profile["keywords"]
    assert len(profile["query_variants"]) == 3
    assert profile["query_variants"][0]["kind"] == "strict_exact"


def test_llm_query_expansion_merges_with_deterministic_profile(monkeypatch) -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    profile = build_query_profile(CELL_QUESTION, parsed)
    expansion = {
        "used": True,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "prompt_path": "prompts/qc_paraphrase.md",
        "paraphrased_question": "Test whether trehalose improves HeLa cell cryopreservation.",
        "query_variants": [
            {
                "kind": "broad_synonyms",
                "query": "trehalose HeLa cryopreservation post thaw viability cell freezing",
            },
            {
                "kind": "protocol_method",
                "query": "HeLa cell freezing protocol trehalose DMSO viability assay",
            },
        ],
        "keywords": ["cell freezing", "post thaw recovery"],
        "warnings": [],
        "error": "",
    }

    monkeypatch.setenv("AI_SCIENTIST_QC_SEARCH_QUERY_LIMIT", "4")
    merged = merge_llm_query_expansion(profile, expansion)
    search_queries = search_queries_for_profile(merged)

    assert len(merged["query_variants"]) == 5
    assert merged["query_variants"][3]["kind"] == "llm_broad_synonyms"
    assert "cell freezing" in merged["keywords"]
    assert any("trehalose" in query and "HeLa" in query for query in search_queries)


def test_protocol_extraction_payload_uses_top_qc_evidence(monkeypatch) -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    captured = {}

    def fake_complete_json(prompt_paths, payload, *, max_tokens=1600):
        captured["prompt_paths"] = prompt_paths
        captured["payload"] = payload
        captured["max_tokens"] = max_tokens
        return {
            "summary": "Use the highest scoring QC evidence to adapt a cryopreservation protocol.",
            "protocol_candidates": [
                {
                    "title": "Trehalose cryopreservation protocol",
                    "source_title": "Trehalose cryopreservation of HeLa cells",
                    "source_url": "https://example.com/trehalose-protocol",
                    "source_type": "paper",
                    "evidence_quality": "adapted",
                    "relevance_reason": "Closest source to the submitted HeLa cryopreservation question.",
                    "adapted_steps": [
                        "Prepare HeLa cultures with a calibrated pipette set.",
                        "Use a fluorescence detection system to measure signal after thawing.",
                    ],
                    "tools": ["centrifuge", "3D printer"],
                    "consumables": ["HeLa cells", "blood samples", "trehalose reagent", "DMSO", "96-well plates"],
                    "validation_checks": ["Measure post-thaw viability."],
                    "limitations": ["Adapted from QC evidence rather than a direct protocol record."],
                    "citations": ["https://example.com/trehalose-protocol"],
                },
                {
                    "title": "Secondary protocol candidate",
                    "source_title": "Secondary source",
                    "source_url": "https://example.com/secondary",
                    "source_type": "paper",
                    "evidence_quality": "weak",
                    "relevance_reason": "Background protocol-like evidence.",
                    "adapted_steps": ["Review secondary method."],
                    "tools": [],
                    "consumables": ["review reagent"],
                    "validation_checks": ["Manual review."],
                    "limitations": ["Weak evidence."],
                    "citations": ["https://example.com/secondary"],
                },
                {
                    "title": "Third protocol candidate",
                    "source_title": "Third source",
                    "source_url": "https://example.com/third",
                    "source_type": "protocol",
                    "evidence_quality": "direct",
                    "relevance_reason": "Direct protocol source.",
                    "adapted_steps": ["Review third method."],
                    "tools": [],
                    "consumables": ["third reagent"],
                    "validation_checks": ["Manual review."],
                    "limitations": [],
                    "citations": ["https://example.com/third"],
                },
                {
                    "title": "Fourth protocol candidate should be trimmed",
                    "source_title": "Fourth source",
                    "source_url": "https://example.com/fourth",
                    "source_type": "paper",
                    "evidence_quality": "weak",
                    "relevance_reason": "Extra candidate.",
                    "adapted_steps": ["Review fourth method."],
                    "tools": [],
                    "consumables": ["fourth reagent"],
                    "validation_checks": ["Manual review."],
                    "limitations": [],
                    "citations": ["https://example.com/fourth"],
                },
            ],
            "warnings": [],
        }

    monkeypatch.setattr("ai_scientist.services.complete_json_with_prompt", fake_complete_json)
    qc = {
        "summary": "QC summary",
        "references": [
            {
                "title": "Trehalose cryopreservation of HeLa cells",
                "authors": [],
                "year": 2024,
                "source": "Crossref",
                "url": "https://example.com/trehalose-protocol",
                "relevance_reason": "Directly relevant method evidence.",
            }
        ],
        "top_candidates": [
            {
                "candidate_id": "candidate-1",
                "source": "Tavily",
                "source_type": "web",
                "title": "Detailed HeLa freezing workflow",
                "url": "https://example.com/hela-workflow",
                "abstract_or_snippet": "Protocol-like freezing and thawing workflow.",
                "final_score": 0.91,
                "llm_relevance_reason": "Contains workflow details.",
            }
        ],
        "ranking_explanation": "Ranking explanation",
        "novelty_signal": "similar_work_exists",
        "confidence": 0.84,
    }

    protocols = generate_relevant_protocols(
        "job-123",
        CELL_QUESTION,
        parsed,
        {"primary_field": "cell_biology", "confirmed": True},
        qc,
    )

    assert captured["payload"]["evidence"][0]["title"] == "Trehalose cryopreservation of HeLa cells"
    assert any(item["title"] == "Detailed HeLa freezing workflow" for item in captured["payload"]["evidence"])
    assert captured["payload"]["structured_parse"]["primary_field"] == "cell_biology"
    assert captured["max_tokens"] == 5000
    assert protocols["job_id"] == "job-123"
    assert len(protocols["protocol_candidates"]) == 3
    assert protocols["protocol_candidates"][0]["title"] == "Trehalose cryopreservation protocol"
    assert "materials_or_inputs" not in protocols["protocol_candidates"][0]
    assert protocols["protocol_candidates"][0]["tools"]
    assert protocols["protocol_candidates"][0]["consumables"]
    assert any(item["name"] == "centrifuge" for item in protocols["tools"])
    assert any(item["name"] == "3D printer" for item in protocols["tools"])
    assert any(item["name"] == "Detection system" for item in protocols["tools"])
    assert any(item["name"] == "Pipette set" for item in protocols["tools"])
    assert all(item["procurement_required"] is False for item in protocols["tools"])
    assert any(item["name"] == "blood samples" for item in protocols["consumables"])
    assert any(item["name"] == "trehalose reagent" for item in protocols["consumables"])
    assert any(item["name"] == "96-well plates" for item in protocols["consumables"])
    assert all(item["procurement_required"] is True for item in protocols["consumables"])


def test_protocol_consumables_preserve_specific_compositions() -> None:
    candidates = sanitize_protocol_candidates(
        [
            {
                "title": "Solar cell fabrication protocol",
                "source_title": "Perovskite solar cell fabrication",
                "source_url": "https://example.com/solar-protocol",
                "source_type": "paper",
                "evidence_quality": "adapted",
                "relevance_reason": "Contains substrate and precursor preparation details.",
                "adapted_steps": [
                    "Clean FTO glass substrates coated with compact TiO2 before depositing MAPbI3 perovskite precursor solution.",
                    "Measure device performance after annealing.",
                ],
                "tools": ["spin coater"],
                "consumables": [
                    "solar cell substrates",
                    {
                        "name": "perovskite precursor solution",
                        "composition": "MAPbI3 in DMF/DMSO",
                    },
                ],
                "validation_checks": ["Measure current-voltage curve."],
                "limitations": [],
                "citations": ["https://example.com/solar-protocol"],
            }
        ],
        [{"url": "https://example.com/solar-protocol"}],
    )

    consumables = candidates[0]["consumables"]
    assert any("FTO glass substrates" in item["name"] and "TiO2" in item["name"] for item in consumables)
    assert any(
        item["name"] == "perovskite precursor solution (MAPbI3 in DMF/DMSO)"
        and item["specification"] == "MAPbI3 in DMF/DMSO"
        for item in consumables
    )


def test_protocol_tools_and_consumables_are_not_entry_limited() -> None:
    tool_names = [f"specialized tool {idx} centrifuge" for idx in range(25)]
    consumable_names = [f"specific consumable {idx} reagent" for idx in range(35)]
    candidates = sanitize_protocol_candidates(
        [
            {
                "title": "Large protocol candidate",
                "source_title": "Large source",
                "source_url": "https://example.com/large",
                "source_type": "protocol",
                "evidence_quality": "adapted",
                "relevance_reason": "Contains a long bill of materials.",
                "adapted_steps": ["Use all listed tools and consumables."],
                "tools": tool_names,
                "consumables": consumable_names,
                "validation_checks": [],
                "limitations": [],
                "citations": ["https://example.com/large"],
            }
        ],
        [{"url": "https://example.com/large"}],
    )

    protocols = {"protocol_candidates": candidates, "tools": candidates[0]["tools"], "consumables": candidates[0]["consumables"]}
    procurement_items = build_procurement_items(parse_hypothesis(CELL_QUESTION), protocols, {})
    tailored_protocol = {
        "inputs": [f"tailored consumable {idx} reagent" for idx in range(35)],
        "source_protocol_refs": ["https://example.com/large"],
        "steps": [],
    }
    materials_dataset = generate_materials_consumables_dataset("job-large", tailored_protocol)

    assert len(candidates[0]["tools"]) == 25
    assert len(candidates[0]["consumables"]) == 35
    assert len(procurement_items) == 35
    assert len(materials_dataset["items"]) == 35


def test_materials_budget_uses_supplier_evidence_and_marks_web_items_for_verification(monkeypatch) -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    captured = {}
    supplier_evidence = [
        {
            "supplier": "Thermo Fisher",
            "evidence_type": "application_note",
            "title": "Thermo Fisher supplier evidence",
            "url": "https://www.thermofisher.com/application-notes",
            "catalog_number": "",
            "status": "reachable",
            "message": "Application note page reachable; product availability and pricing not verified.",
            "confidence": "low",
        }
    ]

    def fake_query_supplier_evidence(query, parsed, *, material_hints=None, procurement_items=None):
        captured["query"] = query
        captured["material_hints"] = material_hints
        captured["procurement_items"] = procurement_items
        return supplier_evidence

    def fake_complete_json(prompt_paths, payload, *, max_tokens=1600):
        captured["payload"] = payload
        captured["max_tokens"] = max_tokens
        return {
            "summary": "Proposal from supplier evidence.",
            "materials": [
                {
                    "name": "Trypan blue viability dye",
                    "category": "reagent",
                    "supplier": "Thermo Fisher",
                    "catalog_number": "15250061",
                    "quantity": "100 mL",
                    "unit_cost_estimate": 65,
                    "total_cost_estimate": 65,
                    "currency": "GBP",
                    "cost_confidence": "high",
                    "availability_status": "catalog_page",
                    "source_url": "https://www.thermofisher.com/application-notes",
                    "evidence_type": "application_note",
                    "rationale": "Viability readout.",
                    "substitution_notes": "",
                    "needs_manual_verification": False,
                }
            ],
            "budget_lines": [
                {
                    "category": "materials",
                    "item": "Trypan blue viability dye",
                    "quantity": "100 mL",
                    "unit_cost_estimate": 65,
                    "total_cost_estimate": 65,
                    "currency": "GBP",
                    "cost_confidence": "high",
                    "source_url": "https://www.thermofisher.com/application-notes",
                    "notes": "Estimated from supplier context.",
                    "needs_manual_verification": False,
                }
            ],
            "timeline_phases": [
                {
                    "phase": "Sourcing",
                    "duration": "1 week",
                    "dependencies": [],
                    "deliverable": "Supplier quote verified.",
                    "critical_path": True,
                    "risk_notes": "Lead time varies.",
                }
            ],
            "validation": [
                {
                    "metric": "Viability",
                    "method": "Trypan blue",
                    "success_threshold": ">=15 point increase",
                    "failure_criteria": "<5 point increase",
                    "controls": ["DMSO control"],
                    "evidence_url": "https://www.thermofisher.com/application-notes",
                    "confidence": "medium",
                }
            ],
            "assumptions": ["Supplier quote needed."],
            "warnings": [],
            "overall_confidence": "medium",
        }

    monkeypatch.setattr("ai_scientist.services.query_supplier_evidence", fake_query_supplier_evidence)
    monkeypatch.setattr("ai_scientist.services.complete_json_with_prompt", fake_complete_json)

    proposal = generate_materials_budget_proposal(
        "job-materials",
        CELL_QUESTION,
        parsed,
        {"primary_field": "cell_biology", "confirmed": True},
        {"novelty_signal": "similar_work_exists", "confidence": 0.8, "top_candidates": []},
        {
            "consumables": [
                {
                    "name": "Trypan blue viability dye",
                    "category": "reagent",
                    "source_protocol_title": "Viability protocol",
                    "source_url": "https://example.com/protocol",
                    "rationale": "Derived from protocol.",
                    "needs_user_check": True,
                    "procurement_required": True,
                }
            ],
            "tools": [
                {
                    "name": "Plate reader",
                    "category": "tool",
                    "source_protocol_title": "Viability protocol",
                    "source_url": "https://example.com/protocol",
                    "rationale": "User should confirm availability.",
                    "needs_user_check": True,
                    "procurement_required": False,
                }
            ],
            "protocol_candidates": [
                {
                    "tools": [],
                    "consumables": [
                        {
                            "name": "HeLa cells",
                            "category": "biological sample",
                            "source_protocol_title": "Viability protocol",
                            "source_url": "https://example.com/protocol",
                            "rationale": "Derived from protocol.",
                            "needs_user_check": True,
                            "procurement_required": True,
                        }
                    ],
                    "validation_checks": ["Measure post-thaw viability"],
                }
            ]
        },
    )

    assert "Trypan blue viability dye" in captured["material_hints"]
    assert "Plate reader" not in captured["material_hints"]
    assert captured["procurement_items"][0]["name"] == "Trypan blue viability dye"
    assert captured["procurement_items"][0]["unit_size"] == "100 mL or supplier-standard vial"
    assert captured["procurement_items"][0]["supplier_hint"] == "Thermo Fisher"
    assert all(item["name"] != "Plate reader" for item in captured["procurement_items"])
    assert captured["payload"]["procurement_items"] == captured["procurement_items"]
    assert captured["payload"]["supplier_evidence"] == supplier_evidence
    assert captured["max_tokens"] == 4000
    assert proposal["proposal_id"]
    assert proposal["materials"][0]["needs_manual_verification"] is True
    assert proposal["materials"][0]["cost_confidence"] == "high"
    assert proposal["materials"][0]["quote_confidence"] == "manual_quote_required"
    assert proposal["budget_lines"][0]["needs_manual_verification"] is True
    assert proposal["budget_lines"][0]["quote_confidence"] == "manual_quote_required"
    assert proposal["total_budget_estimate"]["amount"] > 65
    assert any(line["category"] == "labour" for line in proposal["budget_lines"])


def test_materials_budget_asks_llm_for_rough_estimate_when_price_missing(monkeypatch) -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    calls = {"materials": 0, "estimate": 0}

    supplier_evidence = [
        {
            "supplier": "Thermo Fisher",
            "evidence_type": "application_note",
            "title": "Thermo Fisher supplier evidence",
            "url": "https://www.thermofisher.com/us/en/home/technical-resources/application-notes.html",
            "catalog_number": "",
            "status": "reachable",
            "message": "Application note page reachable; pricing not verified.",
            "confidence": "low",
            "price_estimate": 0,
            "price_currency": "",
            "price_excerpt": "",
        }
    ]

    def fake_query_supplier_evidence(query, parsed, *, material_hints=None, procurement_items=None):
        return supplier_evidence

    def fake_complete_json(prompt_paths, payload, *, max_tokens=1600):
        prompt_name = prompt_paths[0].name
        if prompt_name == "qc_materials_budget.md":
            calls["materials"] += 1
            return {
                "summary": "Proposal from supplier evidence.",
                "materials": [
                    {
                        "name": "Trypan blue viability dye",
                        "category": "reagent",
                        "supplier": "Thermo Fisher",
                        "catalog_number": "",
                        "quantity": "100 mL",
                        "unit_cost_estimate": 0,
                        "total_cost_estimate": 0,
                        "currency": "",
                        "cost_confidence": "low",
                        "availability_status": "catalog_page",
                        "source_url": "",
                        "evidence_type": "application_note",
                        "rationale": "Viability readout.",
                        "substitution_notes": "",
                        "needs_manual_verification": True,
                    }
                ],
                "budget_lines": [
                    {
                        "category": "materials",
                        "item": "Trypan blue viability dye",
                        "quantity": "100 mL",
                        "unit_cost_estimate": 0,
                        "total_cost_estimate": 0,
                        "currency": "",
                        "cost_confidence": "low",
                        "source_url": "",
                        "notes": "",
                        "needs_manual_verification": True,
                    }
                ],
                "timeline_phases": [],
                "validation": [],
                "assumptions": [],
                "warnings": [],
                "overall_confidence": "low",
            }
        if prompt_name == "qc_price_estimation.md":
            calls["estimate"] += 1
            return {
                "materials": [
                    {
                        "name": "Trypan blue viability dye",
                        "unit_cost_estimate": 58,
                        "total_cost_estimate": 58,
                        "currency": "GBP",
                        "cost_confidence": "low",
                        "quote_confidence": "manual_quote_required",
                        "estimate_rationale": "Comparable reagent prices from supplier catalogs.",
                    }
                ],
                "budget_lines": [
                    {
                        "item": "Trypan blue viability dye",
                        "unit_cost_estimate": 58,
                        "total_cost_estimate": 58,
                        "currency": "GBP",
                        "cost_confidence": "low",
                        "quote_confidence": "manual_quote_required",
                        "estimate_rationale": "Single bottle estimate.",
                    }
                ],
                "assumptions": ["Rough estimate only."],
                "warnings": ["Manual quote still required."],
            }
        raise AssertionError(f"Unexpected prompt: {prompt_name}")

    monkeypatch.setattr("ai_scientist.services.query_supplier_evidence", fake_query_supplier_evidence)
    monkeypatch.setattr("ai_scientist.services.complete_json_with_prompt", fake_complete_json)

    proposal = generate_materials_budget_proposal(
        "job-materials",
        CELL_QUESTION,
        parsed,
        {"primary_field": "cell_biology", "confirmed": True},
        {"novelty_signal": "similar_work_exists", "confidence": 0.8, "top_candidates": []},
        {
            "consumables": [
                {
                    "name": "Trypan blue viability dye",
                    "category": "reagent",
                    "source_protocol_title": "Viability protocol",
                    "source_url": "https://example.com/protocol",
                    "rationale": "Derived from protocol.",
                    "needs_user_check": True,
                    "procurement_required": True,
                }
            ],
            "tools": [],
            "protocol_candidates": [],
        },
    )

    assert calls["materials"] == 1
    assert calls["estimate"] == 1
    assert proposal["materials"][0]["unit_cost_estimate"] == 58
    assert proposal["budget_lines"][0]["unit_cost_estimate"] == 58
    assert proposal["materials"][0]["quote_confidence"] == "manual_quote_required"
    assert "Manual quote still required." in proposal["warnings"]


def test_materials_budget_replaces_tbd_supplier_and_adds_labour(monkeypatch) -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    supplier_evidence = [
        {
            "supplier": "Thermo Fisher",
            "evidence_type": "tavily_product_candidate",
            "title": "Thermo Fisher Trypan Blue Solution",
            "url": "https://www.thermofisher.com/search/results?keyword=trypan+blue",
            "catalog_number": "",
            "status": "candidate",
            "message": "Tavily discovered a likely supplier/product candidate.",
            "confidence": "medium",
            "price_estimate": 62,
            "price_currency": "GBP",
            "price_excerpt": "Comparable Trypan Blue solution listing around GBP 62.",
        }
    ]

    def fake_query_supplier_evidence(query, parsed, *, material_hints=None, procurement_items=None):
        return supplier_evidence

    def fake_complete_json(prompt_paths, payload, *, max_tokens=1600):
        assert prompt_paths[0].name == "qc_materials_budget.md"
        return {
            "summary": "Demo procurement proposal.",
            "materials": [
                {
                    "name": "Trypan blue viability dye",
                    "category": "reagent",
                    "supplier": "TBD",
                    "catalog_number": "TBD",
                    "quantity": "TBD",
                    "unit_cost_estimate": 0,
                    "total_cost_estimate": 0,
                    "currency": "",
                    "cost_confidence": "low",
                    "quote_confidence": "none",
                    "availability_status": "unknown",
                    "source_url": "",
                    "evidence_type": "tavily_product_candidate",
                    "rationale": "Needed for viability staining.",
                    "substitution_notes": "",
                    "needs_manual_verification": True,
                }
            ],
            "budget_lines": [],
            "timeline_phases": [],
            "validation": [],
            "assumptions": [],
            "warnings": [],
            "overall_confidence": "low",
        }

    monkeypatch.setattr("ai_scientist.services.query_supplier_evidence", fake_query_supplier_evidence)
    monkeypatch.setattr("ai_scientist.services.complete_json_with_prompt", fake_complete_json)

    proposal = generate_materials_budget_proposal(
        "job-materials",
        CELL_QUESTION,
        parsed,
        {"primary_field": "cell_biology", "confirmed": True},
        {"novelty_signal": "similar_work_exists", "confidence": 0.8, "top_candidates": []},
        {"consumables": [{"name": "Trypan blue viability dye", "category": "reagent"}], "tools": [], "protocol_candidates": []},
    )

    assert proposal["materials"][0]["supplier"] == "Thermo Fisher"
    assert proposal["materials"][0]["catalog_number"] == "see supplier source"
    assert proposal["materials"][0]["quantity"] != "TBD"
    assert proposal["materials"][0]["unit_cost_estimate"] == 62
    assert any(line["category"] == "labour" for line in proposal["budget_lines"])
    assert proposal["total_budget_estimate"]["amount"] > 62


def test_procurement_items_infer_specs_and_exclude_tools() -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    items = build_procurement_items(
        parsed,
        {
            "consumables": [
                {
                    "name": "blood samples",
                    "category": "biological sample",
                    "source_protocol_title": "Diagnostics protocol",
                    "source_url": "https://example.com/protocol",
                    "rationale": "Needed for assay validation.",
                    "needs_user_check": True,
                    "procurement_required": True,
                },
                {
                    "name": "Trehalose reagent",
                    "category": "reagent",
                    "source_protocol_title": "Cryopreservation protocol",
                    "source_url": "https://example.com/trehalose",
                    "rationale": "Cryoprotectant under test.",
                    "needs_user_check": True,
                    "procurement_required": True,
                },
            ],
            "tools": [
                {
                    "name": "Detection system",
                    "category": "reusable lab tool/equipment",
                    "needs_user_check": True,
                    "procurement_required": False,
                }
            ],
            "protocol_candidates": [],
        },
        {"top_candidates": []},
    )

    names = [item["name"] for item in items]
    assert "blood samples" in names
    assert "Trehalose reagent" in names
    assert "Detection system" not in names
    blood = next(item for item in items if item["name"] == "blood samples")
    assert blood["unit_size"] == "sample aliquot"
    assert "anticoagulant" in blood["specification"]
    trehalose = next(item for item in items if item["name"] == "Trehalose reagent")
    assert trehalose["unit_size"] == "100 g bottle"
    assert trehalose["supplier_hint"] == "Sigma-Aldrich"


def test_supplier_api_adapters_report_missing_credentials(monkeypatch) -> None:
    monkeypatch.delenv("ADDGENE_API_TOKEN", raising=False)
    monkeypatch.delenv("IDT_API_KEY", raising=False)
    monkeypatch.delenv("ATCC_API_TOKEN", raising=False)
    parsed = parse_hypothesis(CELL_QUESTION)

    addgene = source_adapters._supplier_addgene_api(None, "HeLa plasmid", parsed, [])
    idt = source_adapters._supplier_idt_scitools(None, "qPCR primers", parsed, [])
    atcc = source_adapters._supplier_atcc_api(None, "HeLa cells", parsed, [])

    assert addgene[0].status == "needs_key"
    assert idt[0].status == "needs_key"
    assert atcc[0].status == "needs_key"


def test_supplier_tavily_evidence_discovers_product_candidates(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    parsed = parse_hypothesis(CELL_QUESTION)

    def fake_tavily_search(query, *, field="general_web", max_results=None):
        assert field == "supplier_material_discovery"
        assert "Trypan blue" in query
        return WebSearchResult(
            source_statuses=[
                {
                    "source": "Tavily",
                    "status": "queried",
                    "queried_url": "https://api.tavily.com/search",
                    "message": "Tavily supplier search queried.",
                    "result_count": 1,
                }
            ],
            candidates=[
                {
                    "title": "Trypan Blue Solution, Thermo Fisher Scientific",
                    "url": "https://www.thermofisher.com/order/catalog/product/15250061",
                    "abstract_or_snippet": "Trypan blue product page.",
                    "web_score": 0.9,
                }
            ],
        )

    monkeypatch.setattr(source_adapters, "tavily_search", fake_tavily_search)

    evidence = source_adapters._supplier_tavily_evidence(
        None,
        "HeLa viability assay",
        parsed,
        ["Trypan blue viability dye"],
    )

    assert evidence[0].supplier == "Thermo Fisher"
    assert evidence[0].evidence_type == "tavily_product_candidate"
    assert evidence[0].status == "candidate"
    assert evidence[0].confidence == "medium"
    assert "not verified" in evidence[0].message
    assert evidence[0].price_estimate == 0.0


def test_supplier_tavily_evidence_uses_structured_procurement_item(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    parsed = parse_hypothesis(CELL_QUESTION)
    captured = {}

    def fake_tavily_search(query, *, field="general_web", max_results=None):
        captured["query"] = query
        assert field == "supplier_material_discovery"
        return WebSearchResult(
            source_statuses=[
                {
                    "source": "Tavily",
                    "status": "queried",
                    "queried_url": "https://api.tavily.com/search",
                    "message": "Tavily supplier search queried.",
                    "result_count": 1,
                }
            ],
            candidates=[
                {
                    "title": "Trehalose, Sigma-Aldrich",
                    "url": "https://www.sigmaaldrich.com/catalog/product/trehalose",
                    "abstract_or_snippet": "Trehalose product page.",
                    "web_score": 0.8,
                }
            ],
        )

    monkeypatch.setattr(source_adapters, "tavily_search", fake_tavily_search)

    evidence = source_adapters._supplier_tavily_evidence(
        None,
        "cryopreservation",
        parsed,
        ["generic broad hint"],
        [
            {
                "name": "Trehalose reagent",
                "category": "reagent",
                "unit_size": "100 g bottle",
                "likely_quantity": "1 bottle",
                "specification": "Match grade and storage requirements.",
                "intended_use": "Cryoprotectant under test.",
                "supplier_hint": "Sigma-Aldrich",
            }
        ],
    )

    assert '"Trehalose reagent"' in captured["query"]
    assert "100 g bottle" in captured["query"]
    assert "Cryoprotectant under test" in captured["query"]
    assert "Sigma-Aldrich" in captured["query"]
    assert evidence[0].supplier == "Sigma-Aldrich"
    assert "Query context" in evidence[0].message


def test_supplier_tavily_evidence_extracts_price_from_candidate_text(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    parsed = parse_hypothesis(CELL_QUESTION)

    def fake_tavily_search(query, *, field="general_web", max_results=None):
        return WebSearchResult(
            source_statuses=[
                {
                    "source": "Tavily",
                    "status": "queried",
                    "queried_url": "https://api.tavily.com/search",
                    "message": "Tavily supplier search queried.",
                    "result_count": 1,
                }
            ],
            candidates=[
                {
                    "title": "Trypan Blue Solution, Thermo Fisher - $65.00",
                    "url": "https://www.thermofisher.com/order/catalog/product/15250061",
                    "abstract_or_snippet": "List price USD 65.00 per 100 mL bottle.",
                    "web_score": 0.9,
                }
            ],
        )

    monkeypatch.setattr(source_adapters, "tavily_search", fake_tavily_search)

    evidence = source_adapters._supplier_tavily_evidence(
        None,
        "HeLa viability assay",
        parsed,
        ["Trypan blue viability dye"],
    )

    assert evidence[0].price_estimate == 65.0
    assert evidence[0].price_currency == "USD"
    assert evidence[0].price_excerpt


def test_supplier_tavily_evidence_reports_missing_key(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    parsed = parse_hypothesis(CELL_QUESTION)

    evidence = source_adapters._supplier_tavily_evidence(
        None,
        "HeLa viability assay",
        parsed,
        ["Trypan blue viability dye"],
    )

    assert evidence[0].supplier == "Tavily"
    assert evidence[0].status == "needs_key"
    assert evidence[0].evidence_type == "tavily_product_candidate"


def test_supplier_evidence_focuses_known_suppliers_before_tavily(monkeypatch) -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    calls = []

    class FakeResponse:
        status_code = 200

        def __init__(self, url):
            self.url = url

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, **kwargs):
            calls.append(url)
            return FakeResponse(url)

    def fail_tavily(*args, **kwargs):
        raise AssertionError("Tavily should not be used for focused supplier items")

    monkeypatch.delenv("ADDGENE_API_TOKEN", raising=False)
    monkeypatch.delenv("IDT_API_KEY", raising=False)
    monkeypatch.setattr(source_adapters.httpx, "Client", FakeClient)
    monkeypatch.setattr(source_adapters, "tavily_search", fail_tavily)

    evidence = source_adapters.query_supplier_evidence(
        "focused",
        parsed,
        procurement_items=[
            {
                "name": "qPCR primer pair",
                "supplier_hint": "IDT",
                "unit_size": "custom oligo",
                "likely_quantity": "1 custom order",
                "specification": "custom sequence",
                "intended_use": "qPCR",
            },
            {
                "name": "pUC19 plasmid",
                "supplier_hint": "Addgene",
                "unit_size": "plasmid",
                "likely_quantity": "1 vial",
                "specification": "plasmid DNA",
                "intended_use": "control",
            },
            {
                "name": "Trypan blue viability dye",
                "supplier_hint": "Thermo Fisher",
                "unit_size": "100 mL or supplier-standard vial",
                "likely_quantity": "1 bottle",
                "specification": "cell viability dye",
                "intended_use": "viability readout",
            },
            {
                "name": "Trehalose reagent",
                "supplier_hint": "Sigma-Aldrich",
                "unit_size": "100 g bottle",
                "likely_quantity": "1 bottle",
                "specification": "reagent grade",
                "intended_use": "cryoprotectant",
            },
        ],
    )

    assert any(item["supplier"] == "IDT" for item in evidence)
    assert any(item["supplier"] == "Addgene" for item in evidence)
    assert any(item["supplier"] == "Thermo Fisher" and item["evidence_type"] == "application_note" for item in evidence)
    assert any(item["supplier"] == "Sigma-Aldrich" and item["evidence_type"] == "technical_bulletin" for item in evidence)
    assert any("idtdna.com" in url for url in calls)
    assert any("addgene.org" in url for url in calls)
    assert any("thermofisher.com" in url for url in calls)
    assert any("sigmaaldrich.com" in url for url in calls)


def test_supplier_evidence_uses_tavily_for_unmapped_items(monkeypatch) -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    captured_queries = []

    def fake_tavily_search(query, *, field="general_web", max_results=None):
        captured_queries.append(query)
        assert field == "supplier_material_discovery"
        return WebSearchResult(
            source_statuses=[
                {
                    "source": "Tavily",
                    "status": "queried",
                    "queried_url": "https://api.tavily.com/search",
                    "message": "ok",
                    "result_count": 1,
                }
            ],
            candidates=[
                {
                    "title": "Unknown supplier product page",
                    "url": "https://example-supplier.com/product",
                    "abstract_or_snippet": "Candidate product page.",
                    "web_score": 0.7,
                }
            ],
        )

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(source_adapters, "tavily_search", fake_tavily_search)

    evidence = source_adapters.query_supplier_evidence(
        "unmapped material",
        parsed,
        procurement_items=[
            {
                "name": "specialized solar substrate",
                "supplier_hint": "",
                "unit_size": "pack",
                "likely_quantity": "1 pack",
                "specification": "custom substrate",
                "intended_use": "fabrication",
            }
        ],
    )

    assert captured_queries
    assert any(item["evidence_type"] == "tavily_product_candidate" for item in evidence)


def test_supplier_evidence_uses_tavily_when_trusted_reference_fails(monkeypatch) -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    captured_queries = []

    class FakeResponse:
        status_code = 500

        def __init__(self, url):
            self.url = url

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, **kwargs):
            return FakeResponse(url)

    def fake_tavily_search(query, *, field="general_web", max_results=None):
        captured_queries.append(query)
        assert field == "supplier_material_discovery"
        return WebSearchResult(
            source_statuses=[
                {
                    "source": "Tavily",
                    "status": "queried",
                    "queried_url": "https://api.tavily.com/search",
                    "message": "ok",
                    "result_count": 1,
                }
            ],
            candidates=[
                {
                    "title": "Trypan Blue Solution, Thermo Fisher Scientific",
                    "url": "https://www.thermofisher.com/order/catalog/product/15250061",
                    "abstract_or_snippet": "Candidate product page.",
                    "web_score": 0.7,
                }
            ],
        )

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(source_adapters.httpx, "Client", FakeClient)
    monkeypatch.setattr(source_adapters, "tavily_search", fake_tavily_search)

    evidence = source_adapters.query_supplier_evidence(
        "failed trusted supplier",
        parsed,
        procurement_items=[
            {
                "name": "Trypan blue viability dye",
                "supplier_hint": "Thermo Fisher",
                "unit_size": "100 mL or supplier-standard vial",
                "likely_quantity": "1 bottle",
                "specification": "cell viability dye",
                "intended_use": "viability readout",
            }
        ],
    )

    assert captured_queries
    assert "site:thermofisher.com" in captured_queries[0]
    assert any(item["evidence_type"] == "tavily_product_candidate" for item in evidence)


def test_supplier_tavily_broadens_when_trusted_site_search_has_no_candidates(monkeypatch) -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    captured_queries = []

    def fake_tavily_search(query, *, field="general_web", max_results=None):
        captured_queries.append(query)
        candidates = []
        if len(captured_queries) == 2:
            candidates = [
                {
                    "title": "Specialty supplier substrate",
                    "url": "https://example-supplier.com/substrate",
                    "abstract_or_snippet": "Candidate product page.",
                    "web_score": 0.7,
                }
            ]
        return WebSearchResult(
            source_statuses=[
                {
                    "source": "Tavily",
                    "status": "queried",
                    "queried_url": "https://api.tavily.com/search",
                    "message": "ok",
                    "result_count": len(candidates),
                }
            ],
            candidates=candidates,
        )

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(source_adapters, "tavily_search", fake_tavily_search)

    evidence = source_adapters._supplier_tavily_evidence(
        None,
        "custom fabrication",
        parsed,
        [],
        [
            {
                "name": "specialized solar substrate",
                "supplier_hint": "",
                "unit_size": "pack",
                "likely_quantity": "1 pack",
                "specification": "custom substrate",
                "intended_use": "fabrication",
            }
        ],
    )

    assert len(captured_queries) == 2
    assert "site:thermofisher.com" in captured_queries[0]
    assert "site:thermofisher.com" not in captured_queries[1]
    assert evidence[0].supplier == "Unknown supplier"


def test_reference_only_evidence_cannot_claim_api_verified_quote() -> None:
    supplier_evidence = [
        {
            "supplier": "Thermo Fisher",
            "evidence_type": "application_note",
            "title": "Thermo Fisher trusted reference",
            "url": "https://www.thermofisher.com/us/en/home/technical-resources/application-notes.html",
            "catalog_number": "",
            "status": "reachable",
            "message": "Reference only.",
            "confidence": "low",
        }
    ]
    proposal = sanitize_materials_budget_response(
        {
            "summary": "Reference-only evidence.",
            "materials": [
                {
                    "name": "Trypan blue viability dye",
                    "supplier": "Thermo Fisher",
                    "source_url": "https://www.thermofisher.com/us/en/home/technical-resources/application-notes.html",
                    "evidence_type": "application_note",
                    "quote_confidence": "api_verified",
                    "needs_manual_verification": False,
                }
            ],
            "budget_lines": [
                {
                    "item": "Trypan blue viability dye",
                    "source_url": "https://www.thermofisher.com/us/en/home/technical-resources/application-notes.html",
                    "quote_confidence": "api_verified",
                    "needs_manual_verification": False,
                }
            ],
        },
        parse_hypothesis(CELL_QUESTION),
        {},
        supplier_evidence,
    )

    assert proposal["materials"][0]["quote_confidence"] == "manual_quote_required"
    assert proposal["materials"][0]["needs_manual_verification"] is True
    assert proposal["budget_lines"][0]["quote_confidence"] == "manual_quote_required"
    assert proposal["budget_lines"][0]["needs_manual_verification"] is True


def test_tavily_product_candidates_still_require_manual_verification(monkeypatch) -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    supplier_evidence = [
        {
            "supplier": "Thermo Fisher",
            "evidence_type": "tavily_product_candidate",
            "title": "Trypan Blue Solution, Thermo Fisher Scientific",
            "url": "https://www.thermofisher.com/order/catalog/product/15250061",
            "catalog_number": "",
            "status": "candidate",
            "message": "Tavily discovered possible product page; availability not verified.",
            "confidence": "medium",
        }
    ]

    generated = {
        "summary": "Proposal from Tavily discovery.",
        "materials": [
            {
                "name": "Trypan blue viability dye",
                "category": "reagent",
                "supplier": "Thermo Fisher",
                "catalog_number": "15250061",
                "quantity": "100 mL",
                "unit_cost_estimate": 65,
                "total_cost_estimate": 65,
                "currency": "GBP",
                "cost_confidence": "medium",
                "availability_status": "catalog_page",
                "source_url": "https://www.thermofisher.com/order/catalog/product/15250061",
                "evidence_type": "tavily_product_candidate",
                "rationale": "Viability readout.",
                "substitution_notes": "",
                "needs_manual_verification": False,
            }
        ],
        "budget_lines": [
            {
                "category": "materials",
                "item": "Trypan blue viability dye",
                "quantity": "100 mL",
                "unit_cost_estimate": 65,
                "total_cost_estimate": 65,
                "currency": "GBP",
                "cost_confidence": "medium",
                "source_url": "https://www.thermofisher.com/order/catalog/product/15250061",
                "notes": "Candidate only.",
                "needs_manual_verification": False,
            }
        ],
        "timeline_phases": [],
        "validation": [],
        "assumptions": [],
        "warnings": [],
        "overall_confidence": "medium",
    }

    proposal = sanitize_materials_budget_response(
        generated,
        parsed,
        {"novelty_signal": "similar_work_exists", "confidence": 0.8},
        supplier_evidence,
    )

    assert proposal["materials"][0]["needs_manual_verification"] is True
    assert proposal["materials"][0]["quote_confidence"] == "candidate"
    assert proposal["budget_lines"][0]["needs_manual_verification"] is True
    assert proposal["budget_lines"][0]["quote_confidence"] == "candidate"


def test_materials_budget_backfills_price_from_supplier_evidence_when_missing() -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    supplier_evidence = [
        {
            "supplier": "Thermo Fisher",
            "evidence_type": "tavily_product_candidate",
            "title": "Trypan Blue Solution",
            "url": "https://www.thermofisher.com/order/catalog/product/15250061",
            "catalog_number": "",
            "status": "candidate",
            "message": "Candidate product page.",
            "confidence": "medium",
            "price_estimate": 65.0,
            "price_currency": "USD",
            "price_excerpt": "List price USD 65.00 per 100 mL bottle.",
        }
    ]
    generated = {
        "summary": "Proposal from Tavily discovery.",
        "materials": [
            {
                "name": "Trypan blue viability dye",
                "category": "reagent",
                "supplier": "Thermo Fisher",
                "catalog_number": "15250061",
                "quantity": "100 mL",
                "unit_cost_estimate": 0,
                "total_cost_estimate": 0,
                "currency": "",
                "cost_confidence": "low",
                "availability_status": "catalog_page",
                "source_url": "https://www.thermofisher.com/order/catalog/product/15250061",
                "evidence_type": "tavily_product_candidate",
                "rationale": "Viability readout.",
                "substitution_notes": "",
                "needs_manual_verification": True,
            }
        ],
        "budget_lines": [
            {
                "category": "materials",
                "item": "Trypan blue viability dye",
                "quantity": "100 mL",
                "unit_cost_estimate": 0,
                "total_cost_estimate": 0,
                "currency": "",
                "cost_confidence": "low",
                "source_url": "https://www.thermofisher.com/order/catalog/product/15250061",
                "notes": "",
                "needs_manual_verification": True,
            }
        ],
        "timeline_phases": [],
        "validation": [],
        "assumptions": [],
        "warnings": [],
        "overall_confidence": "medium",
    }

    proposal = sanitize_materials_budget_response(
        generated,
        parsed,
        {"novelty_signal": "similar_work_exists", "confidence": 0.8},
        supplier_evidence,
    )

    assert proposal["materials"][0]["unit_cost_estimate"] == 65.0
    assert proposal["materials"][0]["total_cost_estimate"] == 65.0
    assert proposal["budget_lines"][0]["unit_cost_estimate"] == 65.0
    assert proposal["budget_lines"][0]["total_cost_estimate"] == 65.0


def test_advanced_parse_uses_openai_field_classification(monkeypatch) -> None:
    monkeypatch.setenv("AI_SCIENTIST_ADVANCED_QC", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")

    monkeypatch.setattr(
        "ai_scientist.services.structured_parse_question",
        lambda question, parsed: {
            "primary_field": "computer_science_ai",
            "secondary_fields": ["engineering_physics"],
            "specific_domain": "vector database indexing",
            "entities": ["vector index", "nearest-neighbor search"],
            "technologies": ["database indexing"],
            "application_context": "database query acceleration",
            "system": "vector database nearest-neighbor search",
            "outcome": "reduce database query latency",
            "constraints": [],
            "mechanism_or_rationale": "Indexing may reduce retrieval time.",
            "search_intent": "Find related vector index latency work.",
            "missing_information": [],
            "confirmation_question": "Is this a vector database indexing question?",
            "confidence": 0.9,
            "needs_confirmation": True,
            "confirmed": False,
        },
    )

    parsed = parse_question_for_job(
        "Can a new vector index reduce database query latency for nearest-neighbor search?"
    )

    assert parsed.domain == "computer_science_ai"
    assert parsed.experiment_type == "vector_database_indexing"
    assert "database" in parsed.system


def test_structured_parse_preserves_literature_target_framework() -> None:
    payload = advanced_qc.sanitize_structured_parse(
        {
            "primary_field": "life_sciences",
            "specific_domain": "cell cryopreservation",
            "system": "HeLa cell freezing medium",
            "outcome": "post-thaw viability",
            "optimized_query": "trehalose HeLa cryopreservation viability",
            "target_subject": "HeLa cells",
            "target_goal": "increase post-thaw viability",
            "target_methodology": "replace sucrose with trehalose in freezing medium",
            "target_readout": "post-thaw viability percentage",
            "target_parameters": "trehalose versus sucrose or DMSO control",
            "confidence": 0.92,
        }
    )

    framework = advanced_qc.target_framework_from_structured_parse(payload)

    assert framework["target_subject"] == "HeLa cells"
    assert framework["target_methodology"] == "replace sucrose with trehalose in freezing medium"
    assert framework["target_readout"] == "post-thaw viability percentage"
    assert framework["target_parameters"] == "trehalose versus sucrose or DMSO control"
    assert payload["optimized_query"] == "trehalose HeLa cryopreservation viability"


def robotics_solar_structured_parse() -> dict:
    return {
        "primary_field": "engineering_physics",
        "secondary_fields": ["climate_energy"],
        "specific_domain": "robotics battery design with solar cells",
        "entities": ["robotics", "battery design", "solar cells"],
        "technologies": ["robot power systems", "solar charging", "battery management"],
        "application_context": "solar-powered robots",
        "system": "robotics power system integrating batteries and solar cells",
        "outcome": "improve robot energy autonomy",
        "constraints": ["battery capacity", "solar charging efficiency"],
        "mechanism_or_rationale": "Solar cells may recharge robot batteries during operation.",
        "search_intent": "Find close prior work combining robotics, batteries, and solar cells.",
        "missing_information": ["robot type", "battery chemistry"],
        "confirmation_question": "Are you asking about solar-assisted battery systems for robotics?",
        "confidence": 0.88,
        "needs_confirmation": True,
        "confirmed": False,
    }


def factory_robot_solar_structured_parse() -> dict:
    return {
        "primary_field": "manufacturing_robotics",
        "secondary_fields": ["climate_energy", "engineering_physics"],
        "specific_domain": "robotic solar panel manufacturing",
        "entities": ["robot", "solar panels", "factory"],
        "technologies": ["factory automation", "robotic assembly", "solar panel manufacturing"],
        "application_context": "automated solar panel production line",
        "system": "factory robot building solar panels",
        "outcome": "improve solar panel manufacturing automation",
        "constraints": [],
        "mechanism_or_rationale": "Robotic assembly may automate factory production.",
        "search_intent": "Find prior work on robots building solar panels in factories.",
        "missing_information": ["robot task", "solar panel component"],
        "confirmation_question": "Are you asking about robotic factory automation for solar panel manufacturing?",
        "confidence": 0.86,
        "needs_confirmation": True,
        "confirmed": False,
    }


def test_factory_robot_solar_parse_does_not_fall_back_to_biology(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(
        "ai_scientist.services.structured_parse_question",
        lambda question, parsed: factory_robot_solar_structured_parse(),
    )

    parsed = parse_question_for_job("robot building solar panels in a factory")

    assert parsed.domain == "manufacturing_robotics"
    assert parsed.experiment_type == "robotic_solar_panel_manufacturing"
    assert "robot" in parsed.system.lower()
    assert "solar" in parsed.system.lower()
    assert "factory" in parsed.system.lower()


def test_advanced_parse_failure_is_visible(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_SCIENTIST_ADVANCED_QC", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setattr(
        "ai_scientist.services.structured_parse_question",
        lambda question, parsed: (_ for _ in ()).throw(RuntimeError("provider down")),
    )
    test_client = TestClient(create_app(str(tmp_path / "parse-failure.sqlite3")))

    response = test_client.post(
        "/api/questions",
        json={"question": "robot building solar panels in a factory"},
    )

    assert response.status_code == 502
    assert "Advanced OpenAI parse failed" in response.json()["detail"]


def test_advanced_qc_routes_non_bio_query_to_tavily_without_bio_sources(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_SCIENTIST_ADVANCED_QC", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setenv("AI_SCIENTIST_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AI_SCIENTIST_ADVANCED_QC_MAX_RESULTS", "2")
    monkeypatch.setattr(
        "ai_scientist.services.structured_parse_question",
        lambda question, parsed: {
            "primary_field": "computer_science_ai",
            "secondary_fields": [],
            "specific_domain": "distributed database indexing",
            "entities": ["vector index", "nearest-neighbor search"],
            "technologies": ["database indexing"],
            "application_context": "database query performance",
            "system": "vector database",
            "outcome": "reduce query latency",
            "constraints": [],
            "mechanism_or_rationale": "",
            "search_intent": "Find vector database latency work.",
            "missing_information": [],
            "confirmation_question": "Is this a database indexing question?",
            "confidence": 0.91,
            "needs_confirmation": True,
            "confirmed": False,
        },
    )
    monkeypatch.setattr(
        "ai_scientist.services.expand_literature_queries",
        lambda question, parsed, profile, force=False, structured_parse=None: {
            "used": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "prompt_path": "prompts/qc_paraphrase.md",
            "paraphrased_question": "Can vector indexing reduce database search latency?",
            "query_variants": [{"kind": "llm_broad", "query": "vector database indexing search latency"}],
            "keywords": ["vector database", "indexing", "latency"],
            "warnings": [],
            "error": "",
        },
    )

    def fake_complete_json(prompt_paths, payload, *, max_tokens=1600):
        if "candidates" not in payload:
            return {
                "field": "computer_science_ai",
                "specific_domain": "distributed database indexing",
                "confidence": 0.91,
                "rationale": "The question is about database query performance.",
                "use_bio_protocol_sources": False,
                "recommended_sources": ["Tavily web", "arXiv", "Semantic Scholar"],
                "search_queries": [
                    {
                        "kind": "domain_specific",
                        "query": "vector database indexing latency approximate nearest neighbor search",
                    }
                ],
                "warnings": [],
                "_llm_provider": "openai",
                "_llm_model": "gpt-4o-mini",
            }
        return {
            "ranked_candidates": [
                {
                    "candidate_id": "cs-1",
                    "llm_relevance_score": 0.82,
                    "llm_relevance_reason": "Discusses vector database indexing and search latency.",
                    "match_classification": "close_similar_work",
                },
                {
                    "candidate_id": "cs-2",
                    "llm_relevance_score": 0.22,
                    "llm_relevance_reason": "Only background material on databases.",
                    "match_classification": "weak_background_reference",
                },
            ],
            "literature_review_summary": (
                "Search results point to related work on approximate nearest-neighbor indexing "
                "and vector database latency. The closest result concerns indexing tradeoffs, "
                "while the weaker result provides only broad database background."
            ),
            "ranking_explanation": "Ranked by embedding similarity and LLM relevance to the database question.",
            "warnings": [],
            "_llm_provider": "openai",
            "_llm_model": "gpt-4o-mini",
        }

    def fake_tavily_search(query, *, field="general_web", max_results=None):
        return WebSearchResult(
            source_statuses=[
                {
                    "source": "Tavily",
                    "status": "queried",
                    "queried_url": "https://api.tavily.com/search",
                    "message": f"searched {field}",
                    "result_count": 2,
                }
            ],
            candidates=[
                {
                    "candidate_id": "cs-1",
                    "source": "Tavily",
                    "source_type": "web",
                    "title": "Vector database indexing latency tradeoffs",
                    "url": "https://example.com/vector-indexing",
                    "doi": None,
                    "authors": [],
                    "year": None,
                    "abstract_or_snippet": "Approximate nearest neighbor indexing for vector search.",
                    "raw_content": "Vector database indexing can reduce query latency.",
                    "web_score": 0.7,
                    "field": field,
                    "matched_fields": [],
                    "lexical_score": 0,
                    "embedding_similarity": None,
                    "llm_score": None,
                    "llm_relevance_score": None,
                    "llm_relevance_reason": "",
                    "visited_content_used": True,
                    "final_score": 0,
                    "match_classification": "unranked",
                },
                {
                    "candidate_id": "cs-2",
                    "source": "Tavily",
                    "source_type": "web",
                    "title": "General database background",
                    "url": "https://example.com/db-background",
                    "doi": None,
                    "authors": [],
                    "year": None,
                    "abstract_or_snippet": "Broad overview of databases.",
                    "raw_content": "",
                    "web_score": 0.2,
                    "field": field,
                    "matched_fields": [],
                    "lexical_score": 0,
                    "embedding_similarity": None,
                    "llm_score": None,
                    "llm_relevance_score": None,
                    "llm_relevance_reason": "",
                    "visited_content_used": False,
                    "final_score": 0,
                    "match_classification": "unranked",
                },
            ],
        )

    def fail_bio_sources(*args, **kwargs):
        if kwargs.get("adapter_group") == "scholarly":
            return SourceResult(
                source_statuses=[],
                candidates=[],
                references=[],
            )
        raise AssertionError("Bio/protocol source adapters should not run for computer_science_ai")

    monkeypatch.setattr(advanced_qc, "complete_json_with_prompt", fake_complete_json)
    monkeypatch.setattr(advanced_qc, "tavily_search", fake_tavily_search)
    monkeypatch.setattr(
        advanced_qc,
        "embed_texts",
        lambda texts: {
            "model": "text-embedding-3-small",
            "embeddings": [[1.0, 0.0]] + [[0.9, 0.1] for _ in texts[1:]],
        },
    )
    monkeypatch.setattr(advanced_qc, "query_live_sources", fail_bio_sources)

    app = create_app(str(tmp_path / "advanced.sqlite3"))
    test_client = TestClient(app)
    question = "Can a new vector index reduce database query latency for nearest-neighbor search?"
    job = test_client.post("/api/questions", json={"question": question}).json()
    test_client.patch(
        f"/api/jobs/{job['job_id']}/parse",
        json={"structured_parse": {**job["structured_parse"], "needs_confirmation": False, "confirmed": True}},
    )

    response = test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")

    assert response.status_code == 200
    qc = response.json()
    assert qc["advanced_qc_used"] is True
    assert qc["field_classification"]["field"] == "computer_science_ai"
    assert qc["field_classification"]["use_bio_protocol_sources"] is False
    assert qc["embedding_model"] == "text-embedding-3-small"
    assert qc["literature_review_summary"]
    assert qc["top_candidates"][0]["candidate_id"] == "cs-1"
    assert qc["top_candidates"][0]["llm_relevance_reason"]
    sources = [status["source"] for status in qc["source_statuses"]]
    assert sources.count("Tavily") == 1
    assert qc["source_statuses"][0]["result_count"] == 8
    assert "protocols.io" not in set(sources)


def test_structured_parse_queries_preserve_robotics_battery_and_solar() -> None:
    structured = robotics_solar_structured_parse()
    field_classification = {
        "search_queries": [
            {
                "kind": "domain_specific",
                "query": "robotics battery design solar cells autonomous robot power",
            }
        ]
    }

    queries = advanced_qc.structured_query_variants(structured, field_classification)
    joined = " ".join(queries).lower()

    assert "robot" in joined
    assert "battery" in joined
    assert "solar" in joined


def test_advanced_query_profile_omits_legacy_placeholder_phrases() -> None:
    structured = factory_robot_solar_structured_parse()
    parsed = parse_hypothesis("robot building solar panels in a factory")

    profile = build_advanced_query_profile(
        "robot building solar panels in a factory",
        parsed,
        structured,
    )
    joined = " ".join(variant["query"] for variant in profile["query_variants"]).lower()

    assert "robot" in joined
    assert "solar" in joined
    assert "factory" in joined or "manufacturing" in joined
    assert "experimental system inferred" not in joined
    assert "outcome must" not in joined
    assert "threshold not explicit" not in joined


def test_advanced_qc_passes_structured_parse_to_paraphrase(monkeypatch) -> None:
    captured = {}
    structured = factory_robot_solar_structured_parse()
    parsed = parse_hypothesis("robot building solar panels in a factory")

    def fake_expand(question, parsed, profile, force=False, structured_parse=None):
        captured["structured_parse"] = structured_parse
        return {
            "used": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "prompt_path": "prompts/qc_paraphrase.md",
            "paraphrased_question": "robotic factory automation for solar panel assembly",
            "query_variants": [
                {
                    "kind": "combined_facets",
                    "query": "robot solar panels factory automation robotic assembly",
                }
            ],
            "keywords": ["robot", "solar panels", "factory automation"],
            "warnings": [],
            "error": "",
        }

    monkeypatch.setenv("AI_SCIENTIST_ADVANCED_QC", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    monkeypatch.setattr("ai_scientist.services.advanced_qc_ready", lambda: True)
    monkeypatch.setattr("ai_scientist.services.expand_literature_queries", fake_expand)
    monkeypatch.setattr(
        "ai_scientist.services.run_advanced_literature_qc",
        lambda *args, **kwargs: {"advanced_qc_used": True},
    )

    from ai_scientist.services import run_literature_qc

    run_literature_qc("robot building solar panels in a factory", parsed, structured)

    assert captured["structured_parse"]["entities"] == ["robot", "solar panels", "factory"]


def test_advanced_candidates_still_query_scholarly_sources_when_tavily_times_out(monkeypatch) -> None:
    parsed = parse_hypothesis("robot building solar panels in a factory")
    profile = build_advanced_query_profile(
        "robot building solar panels in a factory",
        parsed,
        factory_robot_solar_structured_parse(),
    )
    field_classification = {
        "field": "manufacturing_robotics",
        "search_queries": [{"kind": "domain_specific", "query": "robot solar panel factory automation"}],
        "use_bio_protocol_sources": False,
    }
    calls = []
    tavily_calls = []

    monkeypatch.setattr(
        advanced_qc,
        "collect_tavily_candidates",
        lambda query, field, max_results: (
            tavily_calls.append(query)
            or {
                "source_statuses": [
                    {
                        "source": "Tavily",
                        "status": "error",
                        "queried_url": "https://api.tavily.com/search",
                        "message": "Tavily search failed: The read operation timed out",
                        "result_count": 0,
                    }
                ],
                "candidates": [],
            }
        ),
    )

    def fake_query_live_sources(question, parsed, search_query=None, adapter_group="all"):
        calls.append(adapter_group)
        return SourceResult(
            source_statuses=[],
            references=[
                {
                    "title": "Robotic assembly for solar panel manufacturing",
                    "authors": [],
                    "year": 2024,
                    "source": "Crossref",
                    "url": "https://example.com/solar-robotics",
                    "relevance_reason": "Scholarly fallback result.",
                }
            ],
            candidates=[],
        )

    monkeypatch.setattr(advanced_qc, "query_live_sources", fake_query_live_sources)

    result = advanced_qc.collect_advanced_candidates(
        "robot building solar panels in a factory",
        parsed,
        profile,
        field_classification,
    )

    assert "scholarly" in calls
    assert tavily_calls
    assert any(candidate["source"] == "Crossref" for candidate in result["candidates"])
    assert any(status["source"] == "Tavily" and status["status"] == "error" for status in result["source_statuses"])


def test_nature_protocols_uses_crossref_metadata_not_search_page() -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    captured = {}

    class FakeResponse:
        status_code = 200
        url = "https://api.crossref.org/v1/works?query.container-title=Nature+Protocols"

        def json(self):
            return {
                "message": {
                    "items": [
                        {
                            "title": ["A protocol for trehalose cryopreservation"],
                            "container-title": ["Nature Protocols"],
                            "ISSN": ["1754-2189"],
                            "author": [{"given": "Ada", "family": "Lovelace"}],
                            "issued": {"date-parts": [[2024]]},
                            "URL": "https://www.nature.com/articles/example",
                            "abstract": "Protocol-like cryopreservation workflow.",
                        },
                        {
                            "title": ["Unrelated result"],
                            "container-title": ["Nature"],
                            "URL": "https://www.nature.com/articles/unrelated",
                        },
                    ]
                }
            }

    class FakeClient:
        def get(self, url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs["params"]
            return FakeResponse()

    result = source_adapters._query_nature_protocols(FakeClient(), "trehalose HeLa cryopreservation", parsed)

    assert captured["url"] == "https://api.crossref.org/v1/works"
    assert captured["params"]["query.container-title"] == "Nature Protocols"
    assert result.source_statuses[0].source == "Nature Protocols"
    assert result.source_statuses[0].message == "Crossref metadata API queried for Nature Protocols journal records."
    assert result.source_statuses[0].result_count == 1
    assert result.references[0]["source"] == "Nature Protocols"
    assert result.references[0]["title"] == "A protocol for trehalose cryopreservation"


def test_conservative_novelty_rejects_generic_solar_without_robotics() -> None:
    structured = robotics_solar_structured_parse()
    candidates = [
        {
            "title": "High efficiency solar cells for charging",
            "abstract_or_snippet": "Solar cells can charge batteries in portable electronics.",
            "llm_relevance_reason": "Relevant to solar charging and batteries but not robotics.",
            "match_classification": "close_similar_work",
            "final_score": 0.91,
        }
    ]

    signal = advanced_qc.novelty_from_ranked_candidates(candidates, structured)

    assert signal == "not_found"


def test_advanced_facet_gates_downgrade_generic_exact_claim() -> None:
    candidates = [
        {
            "candidate_id": "generic-solar",
            "source": "Tavily",
            "source_type": "web",
            "title": "High efficiency solar cells for factories",
            "url": "https://example.com/solar",
            "abstract_or_snippet": "Solar cells and panels can improve industrial energy efficiency.",
            "web_score": 0.95,
            "embedding_similarity": 0.94,
            "final_score": 0.94,
            "match_classification": "unranked",
        }
    ]
    ranked_payload = {
        "ranked_candidates": [
            {
                "candidate_id": "generic-solar",
                "llm_relevance_score": 0.95,
                "facet_scores": {
                    "topic_relevance": 0.9,
                    "system_match": 0.25,
                    "intervention_match": 0.2,
                    "outcome_match": 0.15,
                    "comparison_match": 0.0,
                    "claim_or_threshold_match": 0.0,
                    "protocol_or_method_match": 0.1,
                    "evidence_quality": 0.7,
                },
                "llm_relevance_reason": "Topically related to solar panels but not the robotic factory assembly experiment.",
                "match_classification": "exact_match",
            }
        ]
    }

    ranked = advanced_qc.apply_llm_ranking(candidates, ranked_payload)

    assert ranked[0]["match_classification"] == "weak_background_reference"
    assert ranked[0]["final_score"] <= 0.42


def test_advanced_facet_gates_require_claim_and_comparison_for_exact() -> None:
    candidates = [
        {
            "candidate_id": "close-cell",
            "source": "Semantic Scholar",
            "source_type": "paper",
            "title": "Trehalose cryopreservation of HeLa cells",
            "url": "https://example.com/trehalose",
            "abstract_or_snippet": "Trehalose cryopreservation was evaluated in HeLa cells with viability readouts.",
            "web_score": 0.8,
            "embedding_similarity": 0.9,
            "final_score": 0.9,
            "match_classification": "unranked",
        }
    ]
    ranked_payload = {
        "ranked_candidates": [
            {
                "candidate_id": "close-cell",
                "llm_relevance_score": 0.92,
                "facet_scores": {
                    "topic_relevance": 0.95,
                    "system_match": 0.9,
                    "intervention_match": 0.9,
                    "outcome_match": 0.85,
                    "comparison_match": 0.2,
                    "claim_or_threshold_match": 0.1,
                    "protocol_or_method_match": 0.7,
                    "evidence_quality": 0.85,
                },
                "llm_relevance_reason": "Same system and intervention, but it does not establish the DMSO comparison or 15 percentage point claim.",
                "match_classification": "exact_match",
            }
        ]
    }

    ranked = advanced_qc.apply_llm_ranking(candidates, ranked_payload)

    assert ranked[0]["match_classification"] == "close_similar_work"
    assert ranked[0]["final_score"] <= 0.85


def test_advanced_ranking_prefers_trusted_sources_over_tavily_web() -> None:
    candidates = [
        {
            "candidate_id": "trusted-paper",
            "source": "NCBI PubMed",
            "source_type": "paper",
            "title": "Trehalose cryopreservation of HeLa cells",
            "url": "https://pubmed.ncbi.nlm.nih.gov/123456/",
            "abstract_or_snippet": "Trehalose cryopreservation was evaluated in HeLa cells with viability readouts.",
            "web_score": 0.4,
            "embedding_similarity": 0.82,
            "final_score": 0.82,
            "match_classification": "unranked",
        },
        {
            "candidate_id": "tavily-web",
            "source": "Tavily",
            "source_type": "web",
            "title": "Trehalose cryopreservation overview",
            "url": "https://example-blog.test/trehalose-cryopreservation",
            "abstract_or_snippet": "A general web overview of trehalose and HeLa cell freezing.",
            "web_score": 0.98,
            "embedding_similarity": 0.9,
            "final_score": 0.9,
            "match_classification": "unranked",
        },
    ]
    ranked_payload = {
        "ranked_candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "llm_relevance_score": 0.9,
                "facet_scores": {
                    "topic_relevance": 0.9,
                    "system_match": 0.8,
                    "intervention_match": 0.8,
                    "outcome_match": 0.7,
                    "comparison_match": 0.5,
                    "claim_or_threshold_match": 0.4,
                    "protocol_or_method_match": 0.7,
                    "evidence_quality": 0.8,
                },
                "llm_relevance_reason": "Relevant to the same cryopreservation question.",
                "match_classification": "close_similar_work",
            }
            for candidate in candidates
        ]
    }

    ranked = sorted(
        advanced_qc.apply_llm_ranking(candidates, ranked_payload),
        key=lambda item: (
            item.get("final_score") or 0.0,
            item.get("source_quality_score") or 0.0,
            item.get("embedding_similarity") or 0.0,
            item.get("web_score") or 0.0,
        ),
        reverse=True,
    )

    assert ranked[0]["candidate_id"] == "trusted-paper"
    assert ranked[0]["source_quality_score"] > ranked[1]["source_quality_score"]
    assert ranked[0]["final_score"] > ranked[1]["final_score"]


def test_candidate_ranking_classifies_exact_and_similar_matches() -> None:
    parsed = parse_hypothesis(CELL_QUESTION)
    profile = build_query_profile(CELL_QUESTION, parsed)
    candidates = [
        {
            "candidate_id": "exact-1",
            "source": "Crossref",
            "source_type": "paper",
            "title": "Trehalose cryopreservation of HeLa cells improves post-thaw viability over DMSO",
            "url": "https://doi.org/10.0000/example",
            "doi": "10.0000/example",
            "authors": ["Example Author"],
            "year": 2025,
            "abstract_or_snippet": (
                "HeLa cells were frozen with trehalose cryoprotectant and compared "
                "to DMSO control, improving post-thaw viability by 15 percentage points."
            ),
            "matched_fields": [],
            "lexical_score": 0,
            "llm_score": None,
            "final_score": 0,
            "match_classification": "unranked",
        },
        {
            "candidate_id": "weak-1",
            "source": "ATCC",
            "source_type": "supplier_note",
            "title": "General animal cell culture guide",
            "url": "https://www.atcc.org/",
            "doi": None,
            "authors": [],
            "year": None,
            "abstract_or_snippet": "General cell handling and culture notes.",
            "matched_fields": [],
            "lexical_score": 0,
            "llm_score": None,
            "final_score": 0,
            "match_classification": "unranked",
        },
    ]

    ranked = rank_qc_candidates(candidates, profile, parsed)

    assert ranked[0]["candidate_id"] == "exact-1"
    assert ranked[0]["match_classification"] == "exact_match"
    assert "intervention" in ranked[0]["matched_fields"]
    assert "system" in ranked[0]["matched_fields"]
    assert "outcome" in ranked[0]["matched_fields"]


def test_source_coverage_accounts_for_failures_and_credentials() -> None:
    statuses = [
        {"source": "Crossref", "status": "queried", "queried_url": "", "message": "", "result_count": 2},
        {"source": "Semantic Scholar", "status": "error", "queried_url": "", "message": "HTTP 429", "result_count": 0},
        {"source": "protocols.io", "status": "needs_key", "queried_url": "", "message": "token missing", "result_count": 0},
    ]

    coverage = compute_source_coverage(statuses, candidate_count=2)

    assert coverage["successful_source_count"] == 1
    assert coverage["failed_source_count"] == 1
    assert coverage["needs_key_source_count"] == 1
    assert coverage["coverage_score"] == 0.333
    assert coverage["notes"]


def test_novelty_decision_can_return_not_found_with_good_coverage() -> None:
    parsed = parse_hypothesis("Testing a completely novel reagent will improve an unspecified assay.")
    coverage = {
        "searched_source_count": 3,
        "successful_source_count": 3,
        "failed_source_count": 0,
        "needs_key_source_count": 0,
        "candidate_count": 0,
        "coverage_score": 1.0,
        "notes": [],
    }

    decision = decide_novelty([], coverage, parsed)

    assert decision["novelty_signal"] == "not_found"
    assert decision["confidence"] > 0.5


def test_structured_parse_qc_falls_back_without_advanced_credentials(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()

    confirmed = test_client.patch(
        f"/api/jobs/{job['job_id']}/parse",
        json={
            "structured_parse": {
                "primary_field": "cell_biology",
                "specific_domain": "cell culture optimization",
                "system": "HeLa cells",
                "outcome": "post-thaw viability",
                "target_subject": "HeLa cells",
                "target_goal": "post-thaw viability",
                "needs_confirmation": False,
                "confirmed": True,
            }
        },
    )
    assert confirmed.status_code == 200

    response = test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")

    assert response.status_code == 200
    qc = response.json()
    assert qc["advanced_qc_used"] is False
    assert qc["references"]


def test_literature_qc_rejected_parse_does_not_set_qc_running(tmp_path, monkeypatch) -> None:
    def fake_parse_with_confirmation(question: str):
        return parse_hypothesis(question), {
            "primary_field": "cell_biology",
            "specific_domain": "cell culture optimization",
            "system": "HeLa cells",
            "outcome": "post-thaw viability",
            "needs_confirmation": True,
            "confirmed": False,
        }

    monkeypatch.setattr("ai_scientist.app.parse_question_with_structure", fake_parse_with_confirmation)
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()

    response = test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")
    hydrated = test_client.get(f"/api/jobs/{job['job_id']}").json()

    assert response.status_code == 409
    assert hydrated["status"] == "question_received"


def test_protocol_tools_and_consumables_are_persisted_in_hydrated_job(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()
    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")

    def fake_generate_protocols(job_id, question, parsed, structured_parse, qc):
        return {
            "protocol_set_id": "protocols-persisted",
            "job_id": job_id,
            "summary": "Protocol with top-level procurement lists.",
            "protocol_candidates": [],
            "tools": [{"name": "Controlled-rate freezer"}],
            "consumables": [{"name": "Trehalose reagent"}],
            "warnings": [],
            "evidence_count": 1,
        }

    monkeypatch.setattr("ai_scientist.app.generate_relevant_protocols", fake_generate_protocols)

    response = test_client.post(f"/api/jobs/{job['job_id']}/protocols")
    hydrated = test_client.get(f"/api/jobs/{job['job_id']}").json()

    assert response.status_code == 200
    assert response.json()["tools"][0]["name"] == "Controlled-rate freezer"
    assert hydrated["relevant_protocols"]["tools"][0]["name"] == "Controlled-rate freezer"
    assert hydrated["relevant_protocols"]["consumables"][0]["name"] == "Trehalose reagent"


def test_frontend_rachael_adapter_contract(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)

    def fake_parse(question):
        parsed = parse_hypothesis(question)
        structured = {
            "primary_field": "cell_biology",
            "entities": ["HeLa", "trehalose", "DMSO"],
            "confidence": 0.84,
            "needs_confirmation": False,
            "confirmed": True,
        }
        return parsed, structured

    def fake_qc(question, parsed, structured_parse):
        return {
            "original_query": question,
            "novelty_signal": "similar_work_exists",
            "confidence": 0.71,
            "summary": "Related work exists with partial overlap.",
            "references": [],
            "top_candidates": [
                {
                    "candidate_id": "c1",
                    "title": "Trehalose improves post-thaw viability in HeLa cells",
                    "authors": ["A. Author", "B. Author"],
                    "source": "Semantic Scholar",
                    "year": 2024,
                    "final_score": 0.82,
                    "doi": "10.1000/demo",
                    "url": "https://example.org/paper",
                }
            ],
            "source_statuses": [
                {
                    "source": "Semantic Scholar",
                    "status": "queried",
                    "queried_url": "https://api.semanticscholar.org/",
                    "message": "ok",
                    "result_count": 5,
                }
            ],
        }

    monkeypatch.setattr("ai_scientist.app.parse_question_with_structure", fake_parse)
    monkeypatch.setattr("ai_scientist.app.run_literature_qc", fake_qc)

    response = test_client.post(
        "/api/frontend/chat/rachael",
        json={
            "messages": [{"role": "user", "text": CELL_QUESTION}],
            "messageCount": 1,
            "jobId": None,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["jobId"]
    assert payload["papers"]
    assert payload["similarityFlag"] == "similar_work_exists"
    assert payload["trailSteps"]
    assert payload["planUpdate"]["hypothesis"] == CELL_QUESTION
    assert payload["chips"]
    assert payload["parseSummary"]["primary_field"] == "cell_biology"
    assert "suggested_text" in payload
    assert "suggested_chips" in payload


def test_frontend_rachael_accepts_character_role_history(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)

    def fake_parse(question):
        parsed = parse_hypothesis(question)
        structured = {
            "primary_field": "cell_biology",
            "entities": ["HeLa", "trehalose", "DMSO"],
            "confidence": 0.84,
            "needs_confirmation": False,
            "confirmed": True,
        }
        return parsed, structured

    def fake_qc(question, parsed, structured_parse):
        return {
            "original_query": question,
            "novelty_signal": "similar_work_exists",
            "confidence": 0.71,
            "summary": "Related work exists with partial overlap.",
            "references": [],
            "top_candidates": [],
            "source_statuses": [],
        }

    monkeypatch.setattr("ai_scientist.app.parse_question_with_structure", fake_parse)
    monkeypatch.setattr("ai_scientist.app.run_literature_qc", fake_qc)

    first = test_client.post(
        "/api/frontend/chat/rachael",
        json={
            "messages": [{"role": "user", "text": CELL_QUESTION}],
            "messageCount": 1,
            "jobId": None,
        },
    )
    assert first.status_code == 200
    job_id = first.json()["jobId"]

    follow_up = test_client.post(
        "/api/frontend/chat/rachael",
        json={
            "messages": [
                {"role": "character", "text": "Initial character guidance."},
                {"role": "user", "text": CELL_QUESTION},
                {"role": "assistant", "text": "Backend replied."},
                {"role": "user", "text": "Refine this direction."},
            ],
            "messageCount": 2,
            "jobId": job_id,
        },
    )
    assert follow_up.status_code == 200
    payload = follow_up.json()
    assert payload["jobId"] == job_id
    assert "text" in payload


def test_frontend_eric_stage_progression_preserves_inventory_patch(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()
    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")

    def fake_protocols(job_id, question, parsed, structured_parse, qc):
        return {
            "protocol_set_id": "p1",
            "job_id": job_id,
            "summary": "Protocol candidates.",
            "protocol_candidates": [{"title": "Candidate 1"}],
            "warnings": [],
            "evidence_count": 1,
            "tools": ["Confocal microscope", "Calibrated pipette set"],
            "consumables": ["Trypan blue", "96-well plates"],
        }

    def fake_tailored(job_id, question, parsed, structured_parse, qc, protocols):
        return {
            "tailored_protocol_id": "tp1",
            "job_id": job_id,
            "title": "Tailored protocol",
            "summary": "Tailored summary",
            "steps": [{"step_number": 1, "title": "Thaw", "description": "Thaw cells"}],
            "inputs": [],
            "outputs": [],
            "validation_checks": [],
            "safety_notes": [],
            "source_protocol_refs": [],
            "controls": [],
            "citations": [],
            "warnings": [],
        }

    def fake_inventory(job_id, tailored):
        return {
            "tool_inventory_id": "ti1",
            "job_id": job_id,
            "summary": "Inventory",
            "sections": [
                {
                    "title": "Equipment",
                    "rows": [{"item": "Microscope", "status": "missing", "note": "", "action": "Buy"}],
                    "missingNote": "",
                }
            ],
            "warnings": [],
        }

    def fake_materials(job_id, tailored):
        return {
            "materials_consumables_id": "mc1",
            "job_id": job_id,
            "summary": "Materials",
            "items": [
                {
                    "name": "Trypan blue",
                    "category": "consumable",
                    "quantity": "1 bottle",
                    "supplier_hint": "Thermo Fisher",
                    "specification": "",
                    "rationale": "",
                    "pricing_status": "estimate_required",
                    "needs_manual_verification": True,
                }
            ],
            "warnings": [],
        }

    def fake_budget(job_id, question, parsed, structured_parse, qc, protocols):
        return {
            "proposal_id": "mb1",
            "job_id": job_id,
            "summary": "Priced materials budget.",
            "materials": [
                {
                    "name": "Trypan blue",
                    "category": "consumable",
                    "supplier": "Thermo Fisher",
                    "catalog_number": "T10282",
                    "quantity": "1 bottle",
                    "unit_cost_estimate": 58,
                    "total_cost_estimate": 58,
                    "currency": "GBP",
                    "cost_confidence": "medium",
                    "quote_confidence": "candidate",
                    "availability_status": "candidate",
                    "source_url": "https://example.com/trypan-blue",
                    "evidence_type": "tavily_product_candidate",
                    "rationale": "Cell viability stain.",
                    "substitution_notes": "",
                    "needs_manual_verification": True,
                }
            ],
            "budget_lines": [
                {
                    "category": "consumables",
                    "item": "Trypan blue",
                    "quantity": "1 bottle",
                    "unit_cost_estimate": 58,
                    "total_cost_estimate": 58,
                    "currency": "GBP",
                    "cost_confidence": "medium",
                    "quote_confidence": "candidate",
                    "source_url": "https://example.com/trypan-blue",
                    "notes": "Candidate quote.",
                    "needs_manual_verification": True,
                }
            ],
            "timeline_phases": [],
            "validation": [],
            "supplier_evidence": [],
            "assumptions": [],
            "warnings": [],
            "total_budget_estimate": {"amount": 58, "currency": "GBP"},
            "evidence_count": 1,
            "overall_confidence": "medium",
        }

    monkeypatch.setattr("ai_scientist.app.generate_relevant_protocols", fake_protocols)
    monkeypatch.setattr("ai_scientist.app.generate_tailored_protocol", fake_tailored)
    monkeypatch.setattr("ai_scientist.app.generate_tool_inventory", fake_inventory)
    monkeypatch.setattr("ai_scientist.app.generate_materials_consumables_dataset", fake_materials)
    monkeypatch.setattr("ai_scientist.app.generate_materials_budget_proposal", fake_budget)

    stage1 = test_client.post(
        "/api/frontend/chat/eric",
        json={"jobId": job["job_id"], "ericStage": "relevant_protocols", "messages": [], "currentInventory": []},
    ).json()
    assert stage1["ericStage"] == "tailored_protocol"
    assert stage1["protocols"]["protocol_set_id"] == "p1"
    assert "working on outputting the protocol" in stage1["text"]
    assert "existing papers" in stage1["text"]
    assert "2 equipment/tool hint(s)" in stage1["text"]
    assert stage1["protocols"]["tools"] == ["Confocal microscope", "Calibrated pipette set"]
    assert stage1["protocols"]["consumables"] == ["Trypan blue", "96-well plates"]

    stage2 = test_client.post(
        "/api/frontend/chat/eric",
        json={
            "jobId": job["job_id"],
            "ericStage": "tailored_protocol",
            "messages": [{"role": "user", "text": "ok continue"}],
            "currentInventory": [],
        },
    ).json()
    assert stage2["ericStage"] == "tools"
    assert stage2["tailoredProtocol"]["tailored_protocol_id"] == "tp1"
    assert "Please check this protocol outline" in stage2["text"]

    stage3 = test_client.post(
        "/api/frontend/chat/eric",
        json={
            "jobId": job["job_id"],
            "ericStage": "tools",
            "messages": [{"role": "user", "text": "approved"}],
            "currentInventory": [
                {
                    "title": "Equipment",
                    "rows": [{"item": "Microscope", "qty": "", "status": "available", "note": "Already present", "action": ""}],
                    "missingNote": "",
                }
            ],
        },
    ).json()
    assert stage3["ericStage"] == "materials_consumables"
    assert stage3["inventorySections"][0]["rows"][0]["status"] == "available"
    assert stage3["toolInventory"]["tool_inventory_id"] == "ti1"

    stage4 = test_client.post(
        "/api/frontend/chat/eric",
        json={
            "jobId": job["job_id"],
            "ericStage": "materials_consumables",
            "messages": [{"role": "user", "text": "proceed"}],
            "currentInventory": stage3["inventorySections"],
        },
    ).json()
    assert stage4["materialsConsumables"]["materials_consumables_id"] == "mc1"
    assert stage4["materialsBudget"]["proposal_id"] == "mb1"
    assert stage4["materialsBudget"]["total_budget_estimate"]["amount"] == 58
    assert "Estimated total: GBP 58" in stage4["text"]
    assert stage4["inventorySections"][0]["rows"][0]["status"] == "available"


def test_frontend_eric_routes_back_to_rachael_for_change_requests(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()

    response = test_client.post(
        "/api/frontend/chat/eric",
        json={
            "jobId": job["job_id"],
            "ericStage": "tailored_protocol",
            "messages": [{"role": "user", "text": "I am unhappy, please change this protocol"}],
            "currentInventory": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["routeBackTo"] == "rachael"
    assert payload["ericStage"] == "tailored_protocol"


def test_frontend_eric_accepts_real_payload_shape_with_null_job_id(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)

    response = test_client.post(
        "/api/frontend/chat/eric",
        json={
            "messages": [
                {"role": "assistant", "text": "Rachael context"},
                {"role": "user", "text": "continue"},
            ],
            "messageCount": 1,
            "jobId": None,
            "hypothesisContext": "Trehalose hypothesis context",
            "ericStage": "relevant_protocols",
            "currentInventory": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ericStage"] == "relevant_protocols"
    assert "Rachael" in payload["text"]


def test_frontend_faith_handles_unknown_job_with_frontend_safe_payload(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)

    response = test_client.post(
        "/api/frontend/chat/faith",
        json={
            "jobId": "missing-job-id",
            "hypothesisContext": CELL_QUESTION,
            "ericContext": "inventory + budget notes",
            "messages": [{"role": "assistant", "text": "Eric context"}],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"] is None
    assert payload["readinessScore"] == 0.0
    assert "Rachael" in payload["text"]


def test_frontend_faith_contract_returns_plan_data(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    test_client = client(tmp_path, monkeypatch)
    job = test_client.post("/api/questions", json={"question": CELL_QUESTION}).json()
    test_client.post(f"/api/jobs/{job['job_id']}/literature-qc")

    def fake_protocols(job_id, question, parsed, structured_parse, qc):
        return {"protocol_set_id": "p1", "job_id": job_id, "summary": "", "protocol_candidates": [], "warnings": [], "evidence_count": 1}

    def fake_tailored(job_id, question, parsed, structured_parse, qc, protocols):
        return {
            "tailored_protocol_id": "tp1",
            "job_id": job_id,
            "title": "Tailored",
            "summary": "Tailored summary",
            "steps": [],
            "inputs": [],
            "outputs": [],
            "validation_checks": [],
            "safety_notes": [],
            "source_protocol_refs": [],
            "controls": [],
            "citations": [],
            "warnings": [],
        }

    def fake_inventory(job_id, tailored):
        return {"tool_inventory_id": "ti1", "job_id": job_id, "summary": "", "sections": [], "warnings": []}

    def fake_materials(job_id, tailored):
        return {"materials_consumables_id": "mc1", "job_id": job_id, "summary": "", "items": [], "warnings": []}

    def fake_budget(job_id, question, parsed, structured_parse, qc, protocols):
        return {
            "proposal_id": "mb1",
            "job_id": job_id,
            "summary": "",
            "materials": [],
            "budget_lines": [],
            "timeline_phases": [],
            "validation": [],
            "supplier_evidence": [],
            "assumptions": [],
            "warnings": [],
            "total_budget_estimate": {"amount": 1000, "currency": "GBP"},
            "evidence_count": 0,
            "overall_confidence": "low",
        }

    def fake_plan(question, parsed, qc, reviews, materials_budget, relevant_protocols, tailored_protocol, tool_inventory, materials_consumables):
        return {
            "plan_id": "plan-1",
            "title": "Trehalose validation plan",
            "experiment_type": parsed.experiment_type,
            "domain": parsed.domain,
            "readiness_score": 0.78,
            "estimated_total_budget": {"amount": 1000, "currency": "GBP"},
            "estimated_duration": "4 weeks",
            "protocol_steps": [
                {
                    "step_number": 1,
                    "phase": "setup",
                    "title": "Prepare cells",
                    "description": "Prepare HeLa baseline cultures.",
                    "inputs": [],
                    "outputs": [],
                    "duration": "2 days",
                    "dependencies": [],
                    "quality_checks": [],
                    "citations": [],
                }
            ],
            "materials": [],
            "budget_lines": [],
            "timeline_phases": [{"phase": "Setup", "duration": "1 week", "dependencies": [], "deliverable": "Cells ready"}],
            "validation": [
                {
                    "metric": "Viability",
                    "method": "Trypan blue",
                    "success_threshold": ">=15 points",
                    "failure_criteria": "<5 points",
                    "controls": ["DMSO control"],
                    "evidence_url": "",
                    "confidence": "medium",
                }
            ],
            "assumptions": [],
            "risks": ["Batch effects"],
            "citations": [],
            "feedback_applied": [],
        }

    monkeypatch.setattr("ai_scientist.app.generate_relevant_protocols", fake_protocols)
    monkeypatch.setattr("ai_scientist.app.generate_tailored_protocol", fake_tailored)
    monkeypatch.setattr("ai_scientist.app.generate_tool_inventory", fake_inventory)
    monkeypatch.setattr("ai_scientist.app.generate_materials_consumables_dataset", fake_materials)
    monkeypatch.setattr("ai_scientist.app.generate_materials_budget_proposal", fake_budget)
    monkeypatch.setattr("ai_scientist.app.generate_experiment_plan", fake_plan)

    response = test_client.post(
        "/api/frontend/chat/faith",
        json={
            "jobId": job["job_id"],
            "hypothesisContext": CELL_QUESTION,
            "messages": [{"role": "user", "text": "compile final plan"}],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["readinessScore"] == 0.78
    assert payload["planData"]["hypothesis"] == CELL_QUESTION
    assert payload["planData"]["controls"]
    assert payload["planData"]["falsifiability"]
    assert payload["planData"]["timeline"]
    assert payload["text"] == "Any feedback for improvement?"
    assert "Approve protocol" in payload["chips"]
    assert "suggested_text" in payload

    feedback_response = test_client.post(
        "/api/frontend/chat/faith",
        json={
            "jobId": job["job_id"],
            "hypothesisContext": CELL_QUESTION,
            "messages": [{"role": "user", "text": "Search deeper for lower-cost suppliers and tighten controls."}],
        },
    )
    assert feedback_response.status_code == 200
    cache_path = tmp_path / "data" / "faith_feedback_cache.jsonl"
    assert cache_path.exists()
    cache_record = cache_path.read_text().strip().splitlines()[-1]
    assert "lower-cost suppliers" in cache_record
    assert "search_context" in cache_record


def test_frontend_rachael_response_keys_snapshot(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)

    def fake_parse(question):
        parsed = parse_hypothesis(question)
        structured = {
            "primary_field": "cell_biology",
            "entities": ["HeLa", "trehalose", "DMSO"],
            "confidence": 0.84,
            "needs_confirmation": False,
            "confirmed": True,
        }
        return parsed, structured

    def fake_qc(question, parsed, structured_parse):
        return {
            "original_query": question,
            "novelty_signal": "similar_work_exists",
            "confidence": 0.71,
            "summary": "Related work exists with partial overlap.",
            "references": [],
            "top_candidates": [],
            "source_statuses": [],
        }

    monkeypatch.setattr("ai_scientist.app.parse_question_with_structure", fake_parse)
    monkeypatch.setattr("ai_scientist.app.run_literature_qc", fake_qc)

    response = test_client.post(
        "/api/frontend/chat/rachael",
        json={
            "messages": [{"role": "user", "text": CELL_QUESTION}],
            "messageCount": 1,
            "jobId": None,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {
        "text",
        "papers",
        "similarityFlag",
        "trailSteps",
        "planUpdate",
        "chips",
        "jobId",
        "parseSummary",
        "suggested_text",
        "suggested_chips",
    }


def test_frontend_eric_response_keys_snapshot(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    response = test_client.post(
        "/api/frontend/chat/eric",
        json={
            "messages": [{"role": "assistant", "text": "Rachael context"}],
            "messageCount": 1,
            "jobId": None,
            "hypothesisContext": CELL_QUESTION,
            "ericStage": "relevant_protocols",
            "currentInventory": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {
        "text",
        "inventorySections",
        "planUpdate",
        "chips",
        "ericStage",
        "protocols",
        "tailoredProtocol",
        "toolInventory",
        "materialsConsumables",
        "materialsBudget",
        "routeBackTo",
        "suggested_text",
        "suggested_chips",
    }


def test_frontend_faith_response_keys_snapshot(tmp_path, monkeypatch) -> None:
    test_client = client(tmp_path, monkeypatch)
    response = test_client.post(
        "/api/frontend/chat/faith",
        json={
            "jobId": None,
            "hypothesisContext": CELL_QUESTION,
            "ericContext": "tool + budget context",
            "messages": [{"role": "assistant", "text": "Eric context"}],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {
        "text",
        "planData",
        "chips",
        "readinessScore",
        "plan",
        "suggested_text",
        "suggested_chips",
    }
