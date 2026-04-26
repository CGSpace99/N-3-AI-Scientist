from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .database import Store
from .env import load_local_env
from .schemas import (
    ArtifactConfirmRequest,
    ConfirmParseRequest,
    CreateQuestionRequest,
    ExampleInput,
    ExperimentPlanResponse,
    FeedbackDraftRequest,
    FeedbackDraftResponse,
    JobResponse,
    LiteratureQCResponse,
    MaterialsConsumablesResponse,
    MaterialsBudgetResponse,
    ParsedHypothesis,
    QuestionRefinementResponse,
    RelevantProtocolsResponse,
    ReviewFeedbackRequest,
    ReviewFeedbackResponse,
    ScientificQuestionResponse,
    TailoredProtocolResponse,
    ToolInventoryResponse,
    FrontendEricRequest,
    FrontendEricResponse,
    FrontendFaithRequest,
    FrontendFaithResponse,
    FrontendPlanUpdate,
    FrontendRachaelRequest,
    FrontendRachaelResponse,
)
from .advanced_qc import parsed_hypothesis_from_structured_parse
from .frontend_contract import (
    inventory_sections_from_tool_and_materials,
    inventory_sections_from_tool_and_budget,
    is_approval,
    is_change_request,
    latest_user_message,
    normalize_frontend_messages,
    novelty_flag,
    parse_trail_steps,
    plan_data_from_plan,
    source_trail_steps,
    to_frontend_papers,
)
from .services import (
    EXAMPLES,
    draft_artifact_revision,
    generate_experiment_plan,
    generate_materials_budget_proposal,
    generate_materials_consumables_dataset,
    generate_question_refinements,
    generate_relevant_protocols,
    generate_tailored_protocol,
    generate_tool_inventory,
    parse_question_with_structure,
    run_literature_qc,
)


def create_app(db_path: str | None = None) -> FastAPI:
    load_local_env()

    app = FastAPI(
        title="AI Scientist Backend",
        version="0.1.0",
        description="Hackathon backend for hypothesis-to-runnable-experiment planning.",
    )
    store = Store(db_path)
    store.init_db()
    app.state.store = store

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _static_dir = Path(__file__).parent.parent / "static"
    if _static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    @app.get("/")
    def root() -> FileResponse:
        index = Path(__file__).parent.parent / "static" / "index.html"
        return FileResponse(str(index))

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/examples", response_model=list[ExampleInput])
    def examples() -> list[ExampleInput]:
        return EXAMPLES

    @app.post("/api/questions/refinements", response_model=QuestionRefinementResponse)
    def question_refinements(payload: CreateQuestionRequest) -> dict:
        return generate_question_refinements(payload.question)

    @app.post("/api/questions", response_model=ScientificQuestionResponse)
    def create_question(payload: CreateQuestionRequest, request: Request) -> dict:
        try:
            parsed, structured_parse = parse_question_with_structure(payload.question)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        job = _store(request).create_job(
            payload.question,
            parsed.model_dump(),
            structured_parse,
        )
        return {
            "job_id": job["job_id"],
            "question": job["question"],
            "status": job["status"],
            "parsed_hypothesis": job["parsed_hypothesis"],
            "structured_parse": job["structured_parse"],
        }

    @app.patch("/api/jobs/{job_id}/parse", response_model=ScientificQuestionResponse)
    def confirm_parse(job_id: str, payload: ConfirmParseRequest, request: Request) -> dict:
        store = _store(request)
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        fallback = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
        structured_parse = payload.structured_parse.model_dump()
        structured_parse["needs_confirmation"] = False
        structured_parse["confirmed"] = True
        parsed = parsed_hypothesis_from_structured_parse(
            job["question"],
            fallback,
            structured_parse,
        )
        updated = store.update_job_parse(job_id, parsed.model_dump(), structured_parse)
        if updated is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "job_id": updated["job_id"],
            "question": updated["question"],
            "status": updated["status"],
            "parsed_hypothesis": updated["parsed_hypothesis"],
            "structured_parse": updated["structured_parse"],
        }

    @app.post("/api/jobs/{job_id}/feedback-drafts", response_model=FeedbackDraftResponse)
    def feedback_draft(job_id: str, payload: FeedbackDraftRequest, request: Request) -> dict:
        store = _store(request)
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        current = _artifact_for_stage(job, payload.stage)
        if current is None:
            raise HTTPException(status_code=409, detail=f"Artifact for stage {payload.stage} is not ready.")
        draft = draft_artifact_revision(
            payload.stage,
            current,
            mode=payload.mode,
            feedback=payload.feedback,
            edited_artifact=payload.edited_artifact,
            operations=payload.operations,
            job_context=_job_feedback_context(job),
        )
        return {
            "job_id": job_id,
            "stage": payload.stage,
            "mode": payload.mode,
            "proposed_artifact": draft["proposed_artifact"],
            "change_summary": draft["change_summary"],
            "requires_confirmation": True,
            "warnings": draft["warnings"],
        }

    @app.patch("/api/jobs/{job_id}/artifacts/{stage}")
    def confirm_artifact(stage: str, job_id: str, payload: ArtifactConfirmRequest, request: Request) -> dict:
        store = _store(request)
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return _persist_artifact_for_stage(store, job, stage, payload.artifact)

    @app.get("/api/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str, request: Request) -> dict:
        job = _store(request).get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str, request: Request) -> StreamingResponse:
        store = _store(request)
        if store.get_job(job_id) is None:
            raise HTTPException(status_code=404, detail="Job not found")

        def stream() -> Generator[str, None, None]:
            events = store.list_events(job_id)
            for event in events:
                yield _sse(event["status"], event)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/jobs/{job_id}/literature-qc", response_model=LiteratureQCResponse)
    def literature_qc(job_id: str, request: Request) -> dict:
        store = _store(request)
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        structured_parse = job.get("structured_parse")
        if structured_parse and structured_parse.get("needs_confirmation"):
            raise HTTPException(
                status_code=409,
                detail="Confirm or edit the parsed interpretation before running literature QC.",
            )
        store.update_job_status(
            job_id,
            "qc_running",
            "Running novelty and related-work check.",
            {"domain": job["parsed_hypothesis"]["domain"]},
        )
        try:
            parsed = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
            qc = run_literature_qc(job["question"], parsed, structured_parse)
            return store.save_qc(job_id, qc)
        except Exception as exc:  # pragma: no cover - final guardrail for demo server
            store.update_job_status(job_id, "error", "Literature QC failed.", error=str(exc))
            raise HTTPException(status_code=500, detail="Literature QC failed") from exc

    @app.post("/api/jobs/{job_id}/plans", response_model=ExperimentPlanResponse)
    def generate_plan(job_id: str, request: Request) -> dict:
        store = _store(request)
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["literature_qc"] is None:
            raise HTTPException(
                status_code=409,
                detail="Run literature QC before generating an experiment plan.",
            )
        if job["materials_budget"] is None:
            raise HTTPException(
                status_code=409,
                detail="Generate materials and budget before generating an experiment plan.",
            )
        store.update_job_status(
            job_id,
            "plan_generating",
            "Generating operational experiment plan.",
            {"domain": job["parsed_hypothesis"]["domain"]},
        )
        try:
            parsed = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
            reviews = store.list_relevant_reviews(parsed.domain, parsed.experiment_type)
            plan = generate_experiment_plan(
                job["question"],
                parsed,
                job["literature_qc"],
                reviews,
                job.get("materials_budget"),
                job.get("relevant_protocols"),
                job.get("tailored_protocol"),
                job.get("tool_inventory"),
                job.get("materials_consumables"),
            )
            return store.save_plan(job_id, plan)
        except Exception as exc:  # pragma: no cover - final guardrail for demo server
            store.update_job_status(job_id, "error", "Plan generation failed.", error=str(exc))
            raise HTTPException(status_code=500, detail="Plan generation failed") from exc

    @app.post("/api/jobs/{job_id}/protocols", response_model=RelevantProtocolsResponse)
    def relevant_protocols(job_id: str, request: Request) -> dict:
        store = _store(request)
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["literature_qc"] is None:
            raise HTTPException(
                status_code=409,
                detail="Run literature QC before extracting relevant protocols.",
            )
        store.update_job_status(
            job_id,
            "protocols_generating",
            "Extracting relevant protocols from QC evidence.",
            {"domain": job["parsed_hypothesis"]["domain"]},
        )
        try:
            parsed = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
            protocols = generate_relevant_protocols(
                job_id,
                job["question"],
                parsed,
                job.get("structured_parse"),
                job["literature_qc"],
            )
            return store.save_protocols(job_id, protocols)
        except Exception as exc:  # pragma: no cover - final guardrail for demo server
            store.update_job_status(job_id, "error", "Relevant protocol extraction failed.", error=str(exc))
            raise HTTPException(status_code=500, detail="Relevant protocol extraction failed") from exc

    @app.post("/api/jobs/{job_id}/materials-budget", response_model=MaterialsBudgetResponse)
    def materials_budget(job_id: str, request: Request) -> dict:
        store = _store(request)
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["literature_qc"] is None:
            raise HTTPException(
                status_code=409,
                detail="Run literature QC before generating materials and budget.",
            )
        if job["relevant_protocols"] is None:
            raise HTTPException(
                status_code=409,
                detail="Generate relevant protocols before generating materials and budget.",
            )
        store.update_job_status(
            job_id,
            "materials_budget_generating",
            "Generating trustworthy materials, budget, and supplier confidence proposal.",
            {"domain": job["parsed_hypothesis"]["domain"]},
        )
        try:
            parsed = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
            proposal = generate_materials_budget_proposal(
                job_id,
                job["question"],
                parsed,
                job.get("structured_parse"),
                job["literature_qc"],
                job["relevant_protocols"],
            )
            return store.save_materials_budget(job_id, proposal)
        except Exception as exc:  # pragma: no cover - final guardrail for demo server
            store.update_job_status(job_id, "error", "Materials and budget proposal failed.", error=str(exc))
            raise HTTPException(status_code=500, detail="Materials and budget proposal failed") from exc

    @app.post("/api/jobs/{job_id}/tailored-protocol", response_model=TailoredProtocolResponse)
    def tailored_protocol(job_id: str, request: Request) -> dict:
        store = _store(request)
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["literature_qc"] is None:
            raise HTTPException(
                status_code=409,
                detail="Run literature QC before generating a tailored protocol.",
            )
        if job["relevant_protocols"] is None:
            raise HTTPException(
                status_code=409,
                detail="Generate relevant protocols before generating a tailored protocol.",
            )
        store.update_job_status(
            job_id,
            "tailored_protocol_generating",
            "Generating tailored protocol from QC evidence.",
            {"domain": job["parsed_hypothesis"]["domain"]},
        )
        try:
            parsed = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
            protocol = generate_tailored_protocol(
                job_id,
                job["question"],
                parsed,
                job.get("structured_parse"),
                job["literature_qc"],
                job["relevant_protocols"],
            )
            return store.save_tailored_protocol(job_id, protocol)
        except Exception as exc:  # pragma: no cover - final guardrail for demo server
            store.update_job_status(job_id, "error", "Tailored protocol generation failed.", error=str(exc))
            raise HTTPException(status_code=500, detail="Tailored protocol generation failed") from exc

    @app.post("/api/jobs/{job_id}/tool-inventory", response_model=ToolInventoryResponse)
    def tool_inventory(job_id: str, request: Request) -> dict:
        store = _store(request)
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["tailored_protocol"] is None:
            raise HTTPException(
                status_code=409,
                detail="Generate a tailored protocol before generating tool inventory.",
            )
        store.update_job_status(
            job_id,
            "tool_inventory_generating",
            "Generating dummy tool inventory from tailored protocol.",
            {"domain": job["parsed_hypothesis"]["domain"]},
        )
        try:
            inventory = generate_tool_inventory(job_id, job["tailored_protocol"])
            return store.save_tool_inventory(job_id, inventory)
        except Exception as exc:  # pragma: no cover - final guardrail for demo server
            store.update_job_status(job_id, "error", "Tool inventory generation failed.", error=str(exc))
            raise HTTPException(status_code=500, detail="Tool inventory generation failed") from exc

    @app.post("/api/jobs/{job_id}/materials-consumables", response_model=MaterialsConsumablesResponse)
    def materials_consumables(job_id: str, request: Request) -> dict:
        store = _store(request)
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["tailored_protocol"] is None:
            raise HTTPException(
                status_code=409,
                detail="Generate a tailored protocol before generating materials and consumables.",
            )
        if job["tool_inventory"] is None:
            raise HTTPException(
                status_code=409,
                detail="Generate tool inventory before generating materials and consumables.",
            )
        store.update_job_status(
            job_id,
            "materials_consumables_generating",
            "Generating materials and consumables dataset from tailored protocol.",
            {"domain": job["parsed_hypothesis"]["domain"]},
        )
        try:
            dataset = generate_materials_consumables_dataset(job_id, job["tailored_protocol"])
            return store.save_materials_consumables(job_id, dataset)
        except Exception as exc:  # pragma: no cover - final guardrail for demo server
            store.update_job_status(job_id, "error", "Materials and consumables generation failed.", error=str(exc))
            raise HTTPException(status_code=500, detail="Materials and consumables generation failed") from exc

    @app.post("/api/frontend/chat/rachael", response_model=FrontendRachaelResponse)
    def frontend_rachael(payload: FrontendRachaelRequest, request: Request) -> dict:
        store = _store(request)
        normalized_messages = normalize_frontend_messages([message.model_dump() for message in payload.messages])
        latest_text = latest_user_message(normalized_messages)
        if payload.messageCount <= 1 or not payload.jobId:
            if not latest_text:
                latest_text = "Please provide your scientific hypothesis."
            parsed, structured_parse = parse_question_with_structure(latest_text)
            job = store.create_job(latest_text, parsed.model_dump(), structured_parse)
            qc = run_literature_qc(latest_text, parsed, structured_parse)
            store.save_qc(job["job_id"], qc)
            papers = to_frontend_papers(qc)
            trail_steps = parse_trail_steps(job.get("structured_parse")) + source_trail_steps(qc)
            summary = (
                f"I parsed this as {job['structured_parse'].get('primary_field', 'scientific question')}. "
                f"These are {len(papers)} Literature QC matches. "
                f"The novelty signal is \"{qc.get('novelty_signal', 'similar_work_exists').replace('_', ' ')}\"."
            )
            chips = [
                "The control should be explicit",
                "Define a falsification threshold",
                "Continue to protocol planning",
            ]
            return {
                "text": summary,
                "papers": papers,
                "similarityFlag": novelty_flag(qc.get("novelty_signal", "")),
                "trailSteps": trail_steps,
                "planUpdate": FrontendPlanUpdate(
                    hypothesis=latest_text,
                    controls="",
                    falsifiability=qc.get("summary", ""),
                ).model_dump(),
                "chips": chips,
                "jobId": job["job_id"],
                "parseSummary": {
                    "primary_field": job["structured_parse"].get("primary_field", ""),
                    "entities": job["structured_parse"].get("entities", []),
                    "confidence": job["structured_parse"].get("confidence", 0.0),
                },
                "suggested_text": summary,
                "suggested_chips": chips,
            }
        job = store.get_job(payload.jobId)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        follow_up = (
            "Good refinement. If you want to change scientific direction, revise with Rachael; "
            "otherwise continue to Eric for protocol/logistics."
        )
        chips = ["Continue to Eric", "Refine hypothesis", "Ask for protocol options"]
        return {
            "text": follow_up,
            "papers": [],
            "similarityFlag": None,
            "trailSteps": [],
            "planUpdate": FrontendPlanUpdate().model_dump(),
            "chips": chips,
            "jobId": job["job_id"],
            "parseSummary": None,
            "suggested_text": follow_up,
            "suggested_chips": chips,
        }

    @app.post("/api/frontend/chat/eric", response_model=FrontendEricResponse)
    def frontend_eric(payload: FrontendEricRequest, request: Request) -> dict:
        store = _store(request)
        if not payload.jobId:
            return {
                "text": "I need Rachael to create the job before I can process logistics.",
                "inventorySections": payload.currentInventory,
                "planUpdate": FrontendPlanUpdate().model_dump(),
                "chips": ["Go back to Rachael", "Submit hypothesis first", "Retry with job id"],
                "ericStage": payload.ericStage,
                "suggested_text": "Missing job id.",
                "suggested_chips": ["Go back to Rachael"],
            }
        job = store.get_job(payload.jobId)
        if job is None:
            return {
                "text": "I need Rachael to create the job before I can process logistics.",
                "inventorySections": payload.currentInventory,
                "planUpdate": FrontendPlanUpdate().model_dump(),
                "chips": ["Go back to Rachael", "Submit hypothesis first", "Retry with job id"],
                "ericStage": payload.ericStage,
                "suggested_text": "Missing job id.",
                "suggested_chips": ["Go back to Rachael"],
            }
        normalized_messages = normalize_frontend_messages([message.model_dump() for message in payload.messages])
        latest_text = latest_user_message(normalized_messages)
        if is_change_request(latest_text) and payload.ericStage in {"relevant_protocols", "tailored_protocol"}:
            text = (
                "That is a scientific/protocol change request. "
                "Please return to Rachael for hypothesis-level review first."
            )
            return {
                "text": text,
                "inventorySections": payload.currentInventory,
                "planUpdate": FrontendPlanUpdate().model_dump(),
                "chips": ["Go back to Rachael", "Revise hypothesis", "Re-run literature QC"],
                "ericStage": payload.ericStage,
                "routeBackTo": "rachael",
                "suggested_text": text,
                "suggested_chips": ["Go back to Rachael"],
            }

        if payload.ericStage == "relevant_protocols":
            if job["literature_qc"] is None:
                parsed = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
                qc = run_literature_qc(job["question"], parsed, job.get("structured_parse"))
                store.save_qc(job["job_id"], qc)
                job = store.get_job(job["job_id"]) or job
            protocols = job.get("relevant_protocols")
            if protocols is None:
                parsed = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
                protocols = generate_relevant_protocols(
                    job["job_id"],
                    job["question"],
                    parsed,
                    job.get("structured_parse"),
                    job["literature_qc"],
                )
                store.save_protocols(job["job_id"], protocols)
            candidate_titles = [
                str(candidate.get("title", "")).strip()
                for candidate in (protocols.get("protocol_candidates", []) or [])[:3]
                if str(candidate.get("title", "")).strip()
            ]
            candidate_summary = "\n".join(f"- {title}" for title in candidate_titles)
            candidate_block = f"\n\nProtocol sources to review:\n{candidate_summary}" if candidate_summary else ""
            tool_count = len(protocols.get("tools", []) or [])
            consumable_count = len(protocols.get("consumables", []) or [])
            procurement_block = (
                f"\n\nFrom those candidates I also extracted {tool_count} equipment/tool hint(s) "
                f"and {consumable_count} consumable/material hint(s). They are shown below for review."
                if tool_count or consumable_count
                else ""
            )
            text = (
                "I am working on outputting the protocol by examining the protocols and methods in the existing papers. "
                f"I found {len(protocols.get('protocol_candidates', []))} relevant protocol candidate(s) from Literature QC."
                f"{candidate_block}"
                f"{procurement_block}"
                "\n\nIf these are the right sources, tell me to continue and I will tailor the protocol."
            )
            return {
                "text": text,
                "inventorySections": payload.currentInventory,
                "planUpdate": FrontendPlanUpdate().model_dump(),
                "chips": ["Ok, tailor the protocol", "Continue", "Go back to Rachael"],
                "ericStage": "tailored_protocol",
                "protocols": protocols,
                "suggested_text": text,
                "suggested_chips": ["Ok, tailor the protocol", "Continue"],
            }

        if not is_approval(latest_text):
            text = "I need explicit approval before moving to the next Eric stage."
            return {
                "text": text,
                "inventorySections": payload.currentInventory,
                "planUpdate": FrontendPlanUpdate().model_dump(),
                "chips": ["Ok, continue", "Go back to Rachael", "Hold here"],
                "ericStage": payload.ericStage,
                "suggested_text": text,
                "suggested_chips": ["Ok, continue"],
            }

        if payload.ericStage == "tailored_protocol":
            protocol = job.get("tailored_protocol")
            if protocol is None:
                parsed = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
                protocol = generate_tailored_protocol(
                    job["job_id"],
                    job["question"],
                    parsed,
                    job.get("structured_parse"),
                    job["literature_qc"] or {},
                    job["relevant_protocols"] or {},
                )
                store.save_tailored_protocol(job["job_id"], protocol)
            controls_text = "\n\n".join(
                [
                    f"Step {step.get('step_number', idx + 1)} — {step.get('title', '')}: {step.get('description', '')}"
                    for idx, step in enumerate(protocol.get("steps", []) or [])
                ]
            )
            step_summary = "\n".join(
                [
                    f"{step.get('step_number', idx + 1)}. {step.get('title', '')}"
                    for idx, step in enumerate((protocol.get("steps", []) or [])[:6])
                ]
            )
            step_block = f"\n\nProtocol outline:\n{step_summary}" if step_summary else ""
            text = (
                f"I drafted a tailored protocol with {len(protocol.get('steps', []))} step(s). "
                "Please check this protocol outline before we continue."
                f"{step_block}"
                "\n\nIf it looks right, approve and I will derive the equipment/tool inventory next."
            )
            return {
                "text": text,
                "inventorySections": payload.currentInventory,
                "planUpdate": FrontendPlanUpdate(controls=controls_text).model_dump(),
                "chips": ["Ok, generate tool list", "Continue", "Rachael should revise this"],
                "ericStage": "tools",
                "tailoredProtocol": protocol,
                "suggested_text": text,
                "suggested_chips": ["Ok, generate tool list", "Continue"],
            }

        if payload.ericStage == "tools":
            inventory = job.get("tool_inventory")
            if inventory is None:
                inventory = generate_tool_inventory(job["job_id"], job.get("tailored_protocol") or {})
                store.save_tool_inventory(job["job_id"], inventory)
            sections = inventory_sections_from_tool_and_materials(
                inventory,
                None,
                payload.currentInventory,
            )
            equipment = "\n".join(
                [
                    f"- {row.get('item', '')}: {row.get('status', '')}{f' ({row.get('note', '')})' if row.get('note') else ''}"
                    for section in sections
                    for row in section.get("rows", [])
                ]
            )
            text = (
                "Equipment and tools are now derived from the approved protocol. "
                "Approve to generate the materials and consumables before we move to Faith."
            )
            return {
                "text": text,
                "inventorySections": sections,
                "planUpdate": FrontendPlanUpdate(equipment=equipment).model_dump(),
                "chips": ["Ok, list materials", "Continue", "Hold at tools"],
                "ericStage": "materials_consumables",
                "toolInventory": inventory,
                "suggested_text": text,
                "suggested_chips": ["Ok, list materials", "Continue"],
            }

        materials = job.get("materials_consumables")
        if materials is None:
            materials = generate_materials_consumables_dataset(job["job_id"], job.get("tailored_protocol") or {})
            store.save_materials_consumables(job["job_id"], materials)
            job = store.get_job(job["job_id"]) or job
        materials_budget = job.get("materials_budget")
        if materials_budget is None:
            parsed = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
            materials_budget = generate_materials_budget_proposal(
                job["job_id"],
                job["question"],
                parsed,
                job.get("structured_parse"),
                job["literature_qc"] or {},
                job["relevant_protocols"] or {},
            )
            store.save_materials_budget(job["job_id"], materials_budget)
        sections = inventory_sections_from_tool_and_materials(
            job.get("tool_inventory") or {},
            materials,
            payload.currentInventory,
        )
        if materials_budget:
            sections = inventory_sections_from_tool_and_budget(
                job.get("tool_inventory") or {},
                materials_budget,
                payload.currentInventory,
            )
        budget = "\n".join(
            [
                (
                    f"- {line.get('item', '')} ({line.get('quantity', '')}) — "
                    f"{line.get('currency', 'GBP')} {line.get('total_cost_estimate', 0)} "
                    f"via {line.get('source_url', '') or 'supplier search'}"
                )
                for line in ((materials_budget or {}).get("budget_lines", []) or [])
            ]
        )
        equipment = "\n".join(
            [
                f"- {row.get('item', '')}: {row.get('status', '')}"
                for section in sections
                for row in section.get("rows", [])
            ]
        )
        text = (
            f"I created a priced materials/consumables and budget list with {len((materials_budget or {}).get('materials', []))} item(s). "
            f"Estimated total: {((materials_budget or {}).get('total_budget_estimate') or {}).get('currency', 'GBP')} "
            f"{((materials_budget or {}).get('total_budget_estimate') or {}).get('amount', 0)}. "
            "I am showing quantities, supplier/catalog evidence, pricing, equipment, tools, materials, and consumables below."
        )
        return {
            "text": text,
            "inventorySections": sections,
            "planUpdate": FrontendPlanUpdate(equipment=equipment, budget=budget).model_dump(),
            "chips": ["Proceed to Faith", "Review tool list", "Review materials"],
            "ericStage": "materials_consumables",
            "materialsConsumables": materials,
            "materialsBudget": materials_budget,
            "suggested_text": text,
            "suggested_chips": ["Proceed to Faith", "Review materials"],
        }

    @app.post("/api/frontend/chat/faith", response_model=FrontendFaithResponse)
    def frontend_faith(payload: FrontendFaithRequest, request: Request) -> dict:
        store = _store(request)
        normalized_messages = normalize_frontend_messages([message.model_dump() for message in payload.messages])
        latest_text = latest_user_message(normalized_messages)
        if not payload.jobId:
            return {
                "text": "I need the backend job before I can prepare the final plan.",
                "planData": {},
                "chips": ["Return to Rachael", "Retry final plan", "Check backend job"],
                "readinessScore": 0.0,
                "suggested_text": "Missing backend job id.",
                "suggested_chips": ["Return to Rachael"],
            }
        job = store.get_job(payload.jobId)
        if job is None:
            text = "I could not find that backend job yet. Please return to Rachael and run the first step again."
            chips = ["Return to Rachael", "Retry final plan", "Check backend job"]
            return {
                "text": text,
                "planData": {},
                "chips": chips,
                "readinessScore": 0.0,
                "plan": None,
                "suggested_text": text,
                "suggested_chips": chips,
            }
        parsed = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
        if job.get("literature_qc") is None:
            qc = run_literature_qc(job["question"], parsed, job.get("structured_parse"))
            store.save_qc(job["job_id"], qc)
            job = store.get_job(job["job_id"]) or job
        if job.get("relevant_protocols") is None:
            protocols = generate_relevant_protocols(
                job["job_id"],
                job["question"],
                parsed,
                job.get("structured_parse"),
                job["literature_qc"] or {},
            )
            store.save_protocols(job["job_id"], protocols)
            job = store.get_job(job["job_id"]) or job
        if job.get("tailored_protocol") is None:
            tailored = generate_tailored_protocol(
                job["job_id"],
                job["question"],
                parsed,
                job.get("structured_parse"),
                job["literature_qc"] or {},
                job["relevant_protocols"] or {},
            )
            store.save_tailored_protocol(job["job_id"], tailored)
            job = store.get_job(job["job_id"]) or job
        if job.get("tool_inventory") is None:
            inventory = generate_tool_inventory(job["job_id"], job["tailored_protocol"] or {})
            store.save_tool_inventory(job["job_id"], inventory)
            job = store.get_job(job["job_id"]) or job
        if job.get("materials_consumables") is None:
            materials_consumables = generate_materials_consumables_dataset(job["job_id"], job["tailored_protocol"] or {})
            store.save_materials_consumables(job["job_id"], materials_consumables)
            job = store.get_job(job["job_id"]) or job
        if job.get("materials_budget") is None:
            materials_budget = generate_materials_budget_proposal(
                job["job_id"],
                job["question"],
                parsed,
                job.get("structured_parse"),
                job["literature_qc"] or {},
                job["relevant_protocols"] or {},
            )
            store.save_materials_budget(job["job_id"], materials_budget)
            job = store.get_job(job["job_id"]) or job
        plan = job.get("experiment_plan")
        if plan is None:
            reviews = store.list_relevant_reviews(parsed.domain, parsed.experiment_type)
            plan = generate_experiment_plan(
                job["question"],
                parsed,
                job["literature_qc"] or {},
                reviews,
                job.get("materials_budget"),
                job.get("relevant_protocols"),
                job.get("tailored_protocol"),
                job.get("tool_inventory"),
                job.get("materials_consumables"),
            )
            plan = store.save_plan(job["job_id"], plan)
        if latest_text:
            append_faith_feedback_cache(job, plan, latest_text)
        question = payload.hypothesisContext.strip() or job["question"]
        plan_data = plan_data_from_plan(plan, question)
        text = "Any feedback for improvement?"
        chips = ["Approve protocol", "Strengthen impact framing", "Search deeper for suppliers", "Tighten validation criteria"]
        return {
            "text": text,
            "planData": plan_data,
            "chips": chips,
            "readinessScore": float(plan.get("readiness_score", 0)),
            "plan": plan,
            "suggested_text": text,
            "suggested_chips": chips,
        }

    @app.post("/api/plans/{plan_id}/reviews", response_model=ReviewFeedbackResponse)
    def save_review(plan_id: str, payload: ReviewFeedbackRequest, request: Request) -> dict:
        store = _store(request)
        plan = store.get_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        job = _job_for_plan(store, plan_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Plan job not found")
        return store.save_review(
            plan_id=plan_id,
            job_id=job["job_id"],
            section=payload.section,
            rating=payload.rating,
            correction=payload.correction,
            annotation=payload.annotation,
            experiment_type=plan["experiment_type"],
            domain=plan["domain"],
        )

    return app


def _store(request: Request) -> Store:
    return request.app.state.store


def append_faith_feedback_cache(job: dict, plan: dict, feedback: str) -> None:
    feedback = feedback.strip()
    if not feedback:
        return
    cache_path = Path.cwd() / "data" / "faith_feedback_cache.jsonl"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    literature_qc = job.get("literature_qc") or {}
    materials_budget = job.get("materials_budget") or {}
    record = {
        "cache_id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "job_id": job.get("job_id", ""),
        "question": job.get("question", ""),
        "feedback": feedback,
        "parse": job.get("structured_parse") or {},
        "search_context": {
            "query_variants": literature_qc.get("query_variants", []),
            "keywords": literature_qc.get("keywords", []),
            "source_statuses": literature_qc.get("source_statuses", []),
            "top_candidates": literature_qc.get("top_candidates", [])[:5],
            "ranking_explanation": literature_qc.get("ranking_explanation", ""),
        },
        "protocol_context": {
            "relevant_protocols": job.get("relevant_protocols") or {},
            "tailored_protocol": job.get("tailored_protocol") or {},
        },
        "supplier_context": {
            "supplier_evidence": materials_budget.get("supplier_evidence", [])[:10],
            "budget_lines": materials_budget.get("budget_lines", [])[:10],
            "total_budget_estimate": materials_budget.get("total_budget_estimate", {}),
        },
        "plan_context": {
            "plan_id": plan.get("plan_id", ""),
            "readiness_score": plan.get("readiness_score", 0),
            "estimated_total_budget": plan.get("estimated_total_budget", {}),
            "risks": plan.get("risks", []),
        },
    }
    with cache_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")


def _sse(event_name: str, data: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def _job_for_plan(store: Store, plan_id: str) -> dict | None:
    # Keep Store focused on stable contract methods; this lookup is small and isolated.
    with store._connect() as conn:  # noqa: SLF001 - internal app helper for demo backend
        row = conn.execute(
            """
            SELECT jobs.*
            FROM jobs
            JOIN plans ON plans.job_id = jobs.job_id
            WHERE plans.plan_id = ?
            """,
            (plan_id,),
        ).fetchone()
    if row is None:
        return None
    return store.get_job(row["job_id"])


def _artifact_for_stage(job: dict, stage: str) -> dict | None:
    if stage == "structured_parse":
        return job.get("structured_parse")
    if stage == "relevant_protocols":
        return job.get("relevant_protocols")
    if stage == "tailored_protocol":
        return job.get("tailored_protocol")
    if stage == "tool_inventory":
        return job.get("tool_inventory")
    if stage == "materials_consumables":
        return job.get("materials_consumables")
    if stage == "materials_budget":
        return job.get("materials_budget")
    if stage == "experiment_plan":
        return job.get("experiment_plan")
    return None


def _job_feedback_context(job: dict) -> dict:
    return {
        "question": job.get("question", ""),
        "parsed_hypothesis": job.get("parsed_hypothesis", {}),
        "structured_parse": job.get("structured_parse", {}),
        "literature_qc_summary": (job.get("literature_qc") or {}).get("summary", ""),
        "relevant_protocols_summary": (job.get("relevant_protocols") or {}).get("summary", ""),
    }


def _persist_artifact_for_stage(store: Store, job: dict, stage: str, artifact: dict) -> dict:
    job_id = job["job_id"]
    if stage == "structured_parse":
        fallback = ParsedHypothesis.model_validate(job["parsed_hypothesis"])
        structured_parse = dict(artifact)
        structured_parse["needs_confirmation"] = False
        structured_parse["confirmed"] = True
        parsed = parsed_hypothesis_from_structured_parse(job["question"], fallback, structured_parse)
        updated = store.update_job_parse(job_id, parsed.model_dump(), structured_parse)
        if updated is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return updated
    if stage == "relevant_protocols":
        proposed = dict(artifact)
        proposed["protocol_set_id"] = str(uuid.uuid4())
        proposed["job_id"] = job_id
        return store.save_protocols(job_id, proposed)
    if stage == "tailored_protocol":
        proposed = dict(artifact)
        proposed["tailored_protocol_id"] = str(uuid.uuid4())
        proposed["job_id"] = job_id
        return store.save_tailored_protocol(job_id, proposed)
    if stage == "tool_inventory":
        proposed = dict(artifact)
        proposed["tool_inventory_id"] = str(uuid.uuid4())
        proposed["job_id"] = job_id
        return store.save_tool_inventory(job_id, proposed)
    if stage == "materials_consumables":
        proposed = dict(artifact)
        proposed["materials_consumables_id"] = str(uuid.uuid4())
        proposed["job_id"] = job_id
        return store.save_materials_consumables(job_id, proposed)
    if stage == "materials_budget":
        proposed = dict(artifact)
        proposed["proposal_id"] = str(uuid.uuid4())
        proposed["job_id"] = job_id
        return store.save_materials_budget(job_id, proposed)
    if stage == "experiment_plan":
        proposed = dict(artifact)
        proposed["plan_id"] = str(uuid.uuid4())
        return store.save_plan(job_id, proposed)
    raise HTTPException(status_code=404, detail=f"Unsupported artifact stage: {stage}")


app = create_app()
