from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def default_db_path() -> str:
    return os.environ.get(
        "AI_SCIENTIST_DB",
        str(Path.cwd() / "data" / "ai_scientist.sqlite3"),
    )


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)


class Store:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or default_db_path()
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    parsed_hypothesis_json TEXT NOT NULL,
                    structured_parse_json TEXT,
                    parse_confirmed INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS literature_qc (
                    job_id TEXT PRIMARY KEY,
                    original_query TEXT NOT NULL DEFAULT '',
                    advanced_qc_used INTEGER NOT NULL DEFAULT 0,
                    advanced_qc_error TEXT NOT NULL DEFAULT '',
                    field_classification_json TEXT NOT NULL DEFAULT '{}',
                    embedding_model TEXT NOT NULL DEFAULT '',
                    literature_review_summary TEXT NOT NULL DEFAULT '',
                    scientific_query TEXT NOT NULL DEFAULT '',
                    keywords_json TEXT NOT NULL DEFAULT '[]',
                    query_variants_json TEXT NOT NULL DEFAULT '[]',
                    llm_query_expansion_used INTEGER NOT NULL DEFAULT 0,
                    llm_provider TEXT NOT NULL DEFAULT '',
                    llm_model TEXT NOT NULL DEFAULT '',
                    llm_prompt_path TEXT NOT NULL DEFAULT '',
                    llm_paraphrased_question TEXT NOT NULL DEFAULT '',
                    llm_warnings_json TEXT NOT NULL DEFAULT '[]',
                    llm_error TEXT NOT NULL DEFAULT '',
                    novelty_signal TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    summary TEXT NOT NULL,
                    references_json TEXT NOT NULL,
                    source_statuses_json TEXT NOT NULL DEFAULT '[]',
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    source_coverage_json TEXT NOT NULL DEFAULT '{}',
                    top_candidates_json TEXT NOT NULL DEFAULT '[]',
                    ranking_explanation TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    experiment_type TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    readiness_score REAL NOT NULL,
                    estimated_total_budget_json TEXT NOT NULL,
                    estimated_duration TEXT NOT NULL,
                    protocol_steps_json TEXT NOT NULL,
                    materials_json TEXT NOT NULL,
                    budget_lines_json TEXT NOT NULL,
                    timeline_phases_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    assumptions_json TEXT NOT NULL,
                    risks_json TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    feedback_applied_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS protocols (
                    protocol_set_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    protocol_candidates_json TEXT NOT NULL,
                    tools_json TEXT NOT NULL DEFAULT '[]',
                    consumables_json TEXT NOT NULL DEFAULT '[]',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS materials_budget (
                    proposal_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    materials_json TEXT NOT NULL,
                    budget_lines_json TEXT NOT NULL,
                    timeline_phases_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    supplier_evidence_json TEXT NOT NULL DEFAULT '[]',
                    assumptions_json TEXT NOT NULL DEFAULT '[]',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    total_budget_estimate_json TEXT NOT NULL,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    overall_confidence TEXT NOT NULL DEFAULT 'low',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tailored_protocols (
                    tailored_protocol_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    inputs_json TEXT NOT NULL DEFAULT '[]',
                    outputs_json TEXT NOT NULL DEFAULT '[]',
                    validation_checks_json TEXT NOT NULL DEFAULT '[]',
                    safety_notes_json TEXT NOT NULL DEFAULT '[]',
                    source_protocol_refs_json TEXT NOT NULL DEFAULT '[]',
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tool_inventory (
                    tool_inventory_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    sections_json TEXT NOT NULL DEFAULT '[]',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS materials_consumables (
                    materials_consumables_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    items_json TEXT NOT NULL DEFAULT '[]',
                    assumptions_json TEXT NOT NULL DEFAULT '[]',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    review_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    section TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    correction TEXT NOT NULL,
                    annotation TEXT NOT NULL,
                    experiment_type TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES plans(plan_id) ON DELETE CASCADE,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );
                """
            )
            self._ensure_column(
                conn,
                "literature_qc",
                "source_statuses_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            for column_name, definition in [
                ("structured_parse_json", "TEXT"),
                ("parse_confirmed", "INTEGER NOT NULL DEFAULT 0"),
            ]:
                self._ensure_column(conn, "jobs", column_name, definition)
            for column_name, definition in [
                ("original_query", "TEXT NOT NULL DEFAULT ''"),
                ("advanced_qc_used", "INTEGER NOT NULL DEFAULT 0"),
                ("advanced_qc_error", "TEXT NOT NULL DEFAULT ''"),
                ("field_classification_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("embedding_model", "TEXT NOT NULL DEFAULT ''"),
                ("literature_review_summary", "TEXT NOT NULL DEFAULT ''"),
                ("scientific_query", "TEXT NOT NULL DEFAULT ''"),
                ("keywords_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("query_variants_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("llm_query_expansion_used", "INTEGER NOT NULL DEFAULT 0"),
                ("llm_provider", "TEXT NOT NULL DEFAULT ''"),
                ("llm_model", "TEXT NOT NULL DEFAULT ''"),
                ("llm_prompt_path", "TEXT NOT NULL DEFAULT ''"),
                ("llm_paraphrased_question", "TEXT NOT NULL DEFAULT ''"),
                ("llm_warnings_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("llm_error", "TEXT NOT NULL DEFAULT ''"),
                ("candidate_count", "INTEGER NOT NULL DEFAULT 0"),
                ("source_coverage_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("top_candidates_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("ranking_explanation", "TEXT NOT NULL DEFAULT ''"),
            ]:
                self._ensure_column(conn, "literature_qc", column_name, definition)
            for column_name, definition in [
                ("tools_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("consumables_json", "TEXT NOT NULL DEFAULT '[]'"),
            ]:
                self._ensure_column(conn, "protocols", column_name, definition)

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            conn.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
            )

    def create_job(
        self,
        question: str,
        parsed_hypothesis: dict[str, Any],
        structured_parse: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, question, status, parsed_hypothesis_json, structured_parse_json,
                    parse_confirmed, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    question,
                    "question_received",
                    dumps(parsed_hypothesis),
                    dumps(structured_parse) if structured_parse else None,
                    1 if structured_parse and structured_parse.get("confirmed") else 0,
                    now,
                    now,
                ),
            )
            self._insert_event(
                conn,
                job_id,
                "question_received",
                "Scientific question received.",
                {"question": question},
            )
            self._insert_event(
                conn,
                job_id,
                "parsing",
                "Hypothesis fields extracted for frontend display.",
                {"parsed_hypothesis": parsed_hypothesis, "structured_parse": structured_parse},
            )
        return self.get_job(job_id)  # type: ignore[return-value]

    def update_job_parse(
        self,
        job_id: str,
        parsed_hypothesis: dict[str, Any],
        structured_parse: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET parsed_hypothesis_json = ?, structured_parse_json = ?,
                    parse_confirmed = 1, updated_at = ?
                WHERE job_id = ?
                """,
                (dumps(parsed_hypothesis), dumps(structured_parse), now, job_id),
            )
            self._insert_event(
                conn,
                job_id,
                "parsing",
                "Structured parse confirmed for literature QC.",
                {"parsed_hypothesis": parsed_hypothesis, "structured_parse": structured_parse},
            )
        return self.get_job(job_id)

    def update_job_status(
        self,
        job_id: str,
        status: str,
        message: str,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, error, now, job_id),
            )
            self._insert_event(conn, job_id, status, message, payload or {})

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        status: str,
        message: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO job_events (job_id, status, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, status, message, dumps(payload), utc_now()),
        )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None

        latest_protocols = self.get_latest_protocols_for_job(job_id)
        latest_tailored_protocol = self.get_latest_tailored_protocol_for_job(job_id)
        latest_tool_inventory = self.get_latest_tool_inventory_for_job(job_id)
        latest_materials_consumables = self.get_latest_materials_consumables_for_job(job_id)
        latest_materials_budget = self.get_latest_materials_budget_for_job(job_id)
        latest_plan = self.get_latest_plan_for_job(job_id)
        return {
            "job_id": row["job_id"],
            "question": row["question"],
            "status": row["status"],
            "parsed_hypothesis": loads(row["parsed_hypothesis_json"], {}),
            "structured_parse": loads(row["structured_parse_json"], None),
            "literature_qc": self.get_qc(job_id),
            "relevant_protocols": latest_protocols,
            "tailored_protocol": latest_tailored_protocol,
            "tool_inventory": latest_tool_inventory,
            "materials_consumables": latest_materials_consumables,
            "materials_budget": latest_materials_budget,
            "experiment_plan": latest_plan,
            "error": row["error"],
        }

    def save_qc(self, job_id: str, qc: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO literature_qc (
                    job_id, original_query, advanced_qc_used, advanced_qc_error,
                    field_classification_json, embedding_model, literature_review_summary,
                    scientific_query, query_variants_json,
                    keywords_json, llm_query_expansion_used, llm_provider, llm_model,
                    llm_prompt_path, llm_paraphrased_question, llm_warnings_json,
                    llm_error, novelty_signal, confidence, summary, references_json,
                    source_statuses_json, candidate_count, source_coverage_json,
                    top_candidates_json, ranking_explanation, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    original_query = excluded.original_query,
                    advanced_qc_used = excluded.advanced_qc_used,
                    advanced_qc_error = excluded.advanced_qc_error,
                    field_classification_json = excluded.field_classification_json,
                    embedding_model = excluded.embedding_model,
                    literature_review_summary = excluded.literature_review_summary,
                    scientific_query = excluded.scientific_query,
                    keywords_json = excluded.keywords_json,
                    query_variants_json = excluded.query_variants_json,
                    llm_query_expansion_used = excluded.llm_query_expansion_used,
                    llm_provider = excluded.llm_provider,
                    llm_model = excluded.llm_model,
                    llm_prompt_path = excluded.llm_prompt_path,
                    llm_paraphrased_question = excluded.llm_paraphrased_question,
                    llm_warnings_json = excluded.llm_warnings_json,
                    llm_error = excluded.llm_error,
                    novelty_signal = excluded.novelty_signal,
                    confidence = excluded.confidence,
                    summary = excluded.summary,
                    references_json = excluded.references_json,
                    source_statuses_json = excluded.source_statuses_json,
                    candidate_count = excluded.candidate_count,
                    source_coverage_json = excluded.source_coverage_json,
                    top_candidates_json = excluded.top_candidates_json,
                    ranking_explanation = excluded.ranking_explanation,
                    created_at = excluded.created_at
                """,
                (
                    job_id,
                    qc.get("original_query", ""),
                    1 if qc.get("advanced_qc_used") else 0,
                    qc.get("advanced_qc_error", ""),
                    dumps(qc.get("field_classification", {})),
                    qc.get("embedding_model", ""),
                    qc.get("literature_review_summary", ""),
                    qc.get("scientific_query", ""),
                    dumps(qc.get("query_variants", [])),
                    dumps(qc.get("keywords", [])),
                    1 if qc.get("llm_query_expansion_used") else 0,
                    qc.get("llm_provider", ""),
                    qc.get("llm_model", ""),
                    qc.get("llm_prompt_path", ""),
                    qc.get("llm_paraphrased_question", ""),
                    dumps(qc.get("llm_warnings", [])),
                    qc.get("llm_error", ""),
                    qc["novelty_signal"],
                    qc["confidence"],
                    qc["summary"],
                    dumps(qc["references"]),
                    dumps(qc.get("source_statuses", [])),
                    qc.get("candidate_count", 0),
                    dumps(qc.get("source_coverage", {})),
                    dumps(qc.get("top_candidates", [])),
                    qc.get("ranking_explanation", ""),
                    now,
                ),
            )
        self.update_job_status(job_id, "qc_ready", "Literature QC ready.", qc)
        return self.get_qc(job_id)  # type: ignore[return-value]

    def get_qc(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM literature_qc WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "original_query": row["original_query"],
            "advanced_qc_used": bool(row["advanced_qc_used"]),
            "advanced_qc_error": row["advanced_qc_error"],
            "field_classification": loads(row["field_classification_json"], {}),
            "embedding_model": row["embedding_model"],
            "literature_review_summary": row["literature_review_summary"],
            "scientific_query": row["scientific_query"],
            "keywords": loads(row["keywords_json"], []),
            "query_variants": loads(row["query_variants_json"], []),
            "llm_query_expansion_used": bool(row["llm_query_expansion_used"]),
            "llm_provider": row["llm_provider"],
            "llm_model": row["llm_model"],
            "llm_prompt_path": row["llm_prompt_path"],
            "llm_paraphrased_question": row["llm_paraphrased_question"],
            "llm_warnings": loads(row["llm_warnings_json"], []),
            "llm_error": row["llm_error"],
            "novelty_signal": row["novelty_signal"],
            "confidence": row["confidence"],
            "summary": row["summary"],
            "references": loads(row["references_json"], []),
            "source_statuses": loads(row["source_statuses_json"], []),
            "candidate_count": row["candidate_count"],
            "source_coverage": loads(row["source_coverage_json"], {}),
            "top_candidates": loads(row["top_candidates_json"], []),
            "ranking_explanation": row["ranking_explanation"],
        }

    def save_protocols(self, job_id: str, protocols: dict[str, Any]) -> dict[str, Any]:
        protocol_set_id = protocols["protocol_set_id"]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO protocols (
                    protocol_set_id, job_id, summary, protocol_candidates_json,
                    tools_json, consumables_json, warnings_json, evidence_count, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    protocol_set_id,
                    job_id,
                    protocols["summary"],
                    dumps(protocols.get("protocol_candidates", [])),
                    dumps(protocols.get("tools", [])),
                    dumps(protocols.get("consumables", [])),
                    dumps(protocols.get("warnings", [])),
                    protocols.get("evidence_count", 0),
                    utc_now(),
                ),
            )
        self.update_job_status(
            job_id,
            "protocols_ready",
            "Relevant protocols ready.",
            {"protocol_set_id": protocol_set_id},
        )
        return self.get_protocols(protocol_set_id)  # type: ignore[return-value]

    def get_protocols(self, protocol_set_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM protocols WHERE protocol_set_id = ?",
                (protocol_set_id,),
            ).fetchone()
        if row is None:
            return None
        return self._protocols_from_row(row)

    def get_latest_protocols_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM protocols
                WHERE job_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._protocols_from_row(row)

    def _protocols_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "protocol_set_id": row["protocol_set_id"],
            "job_id": row["job_id"],
            "summary": row["summary"],
            "protocol_candidates": loads(row["protocol_candidates_json"], []),
            "tools": loads(row["tools_json"], []),
            "consumables": loads(row["consumables_json"], []),
            "warnings": loads(row["warnings_json"], []),
            "evidence_count": row["evidence_count"],
        }

    def save_tailored_protocol(self, job_id: str, protocol: dict[str, Any]) -> dict[str, Any]:
        protocol_id = protocol["tailored_protocol_id"]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tailored_protocols (
                    tailored_protocol_id, job_id, title, summary, steps_json,
                    inputs_json, outputs_json, validation_checks_json, safety_notes_json,
                    source_protocol_refs_json, citations_json, warnings_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    protocol_id,
                    job_id,
                    protocol["title"],
                    protocol["summary"],
                    dumps(protocol.get("steps", [])),
                    dumps(protocol.get("inputs", [])),
                    dumps(protocol.get("outputs", [])),
                    dumps(protocol.get("validation_checks", [])),
                    dumps(protocol.get("safety_notes", [])),
                    dumps(protocol.get("source_protocol_refs", [])),
                    dumps(protocol.get("citations", [])),
                    dumps(protocol.get("warnings", [])),
                    utc_now(),
                ),
            )
        self.update_job_status(
            job_id,
            "tailored_protocol_ready",
            "Tailored protocol ready.",
            {"tailored_protocol_id": protocol_id},
        )
        return self.get_tailored_protocol(protocol_id)  # type: ignore[return-value]

    def get_tailored_protocol(self, tailored_protocol_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tailored_protocols WHERE tailored_protocol_id = ?",
                (tailored_protocol_id,),
            ).fetchone()
        if row is None:
            return None
        return self._tailored_protocol_from_row(row)

    def get_latest_tailored_protocol_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM tailored_protocols
                WHERE job_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._tailored_protocol_from_row(row)

    def _tailored_protocol_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "tailored_protocol_id": row["tailored_protocol_id"],
            "job_id": row["job_id"],
            "title": row["title"],
            "summary": row["summary"],
            "steps": loads(row["steps_json"], []),
            "inputs": loads(row["inputs_json"], []),
            "outputs": loads(row["outputs_json"], []),
            "validation_checks": loads(row["validation_checks_json"], []),
            "safety_notes": loads(row["safety_notes_json"], []),
            "source_protocol_refs": loads(row["source_protocol_refs_json"], []),
            "citations": loads(row["citations_json"], []),
            "warnings": loads(row["warnings_json"], []),
        }

    def save_tool_inventory(self, job_id: str, inventory: dict[str, Any]) -> dict[str, Any]:
        inventory_id = inventory["tool_inventory_id"]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_inventory (
                    tool_inventory_id, job_id, summary, sections_json, warnings_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    inventory_id,
                    job_id,
                    inventory["summary"],
                    dumps(inventory.get("sections", [])),
                    dumps(inventory.get("warnings", [])),
                    utc_now(),
                ),
            )
        self.update_job_status(
            job_id,
            "tool_inventory_ready",
            "Tool inventory ready.",
            {"tool_inventory_id": inventory_id},
        )
        return self.get_tool_inventory(inventory_id)  # type: ignore[return-value]

    def get_tool_inventory(self, tool_inventory_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tool_inventory WHERE tool_inventory_id = ?",
                (tool_inventory_id,),
            ).fetchone()
        if row is None:
            return None
        return self._tool_inventory_from_row(row)

    def get_latest_tool_inventory_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM tool_inventory
                WHERE job_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._tool_inventory_from_row(row)

    def _tool_inventory_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "tool_inventory_id": row["tool_inventory_id"],
            "job_id": row["job_id"],
            "summary": row["summary"],
            "sections": loads(row["sections_json"], []),
            "warnings": loads(row["warnings_json"], []),
        }

    def save_materials_consumables(self, job_id: str, dataset: dict[str, Any]) -> dict[str, Any]:
        dataset_id = dataset["materials_consumables_id"]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO materials_consumables (
                    materials_consumables_id, job_id, summary, items_json,
                    assumptions_json, warnings_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    job_id,
                    dataset["summary"],
                    dumps(dataset.get("items", [])),
                    dumps(dataset.get("assumptions", [])),
                    dumps(dataset.get("warnings", [])),
                    utc_now(),
                ),
            )
        self.update_job_status(
            job_id,
            "materials_consumables_ready",
            "Materials and consumables dataset ready.",
            {"materials_consumables_id": dataset_id},
        )
        return self.get_materials_consumables(dataset_id)  # type: ignore[return-value]

    def get_materials_consumables(self, materials_consumables_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM materials_consumables WHERE materials_consumables_id = ?",
                (materials_consumables_id,),
            ).fetchone()
        if row is None:
            return None
        return self._materials_consumables_from_row(row)

    def get_latest_materials_consumables_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM materials_consumables
                WHERE job_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._materials_consumables_from_row(row)

    def _materials_consumables_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "materials_consumables_id": row["materials_consumables_id"],
            "job_id": row["job_id"],
            "summary": row["summary"],
            "items": loads(row["items_json"], []),
            "assumptions": loads(row["assumptions_json"], []),
            "warnings": loads(row["warnings_json"], []),
        }

    def save_materials_budget(self, job_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
        proposal_id = proposal["proposal_id"]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO materials_budget (
                    proposal_id, job_id, summary, materials_json, budget_lines_json,
                    timeline_phases_json, validation_json, supplier_evidence_json,
                    assumptions_json, warnings_json, total_budget_estimate_json,
                    evidence_count, overall_confidence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    job_id,
                    proposal["summary"],
                    dumps(proposal.get("materials", [])),
                    dumps(proposal.get("budget_lines", [])),
                    dumps(proposal.get("timeline_phases", [])),
                    dumps(proposal.get("validation", [])),
                    dumps(proposal.get("supplier_evidence", [])),
                    dumps(proposal.get("assumptions", [])),
                    dumps(proposal.get("warnings", [])),
                    dumps(proposal.get("total_budget_estimate", {})),
                    proposal.get("evidence_count", 0),
                    proposal.get("overall_confidence", "low"),
                    utc_now(),
                ),
            )
        self.update_job_status(
            job_id,
            "materials_budget_ready",
            "Materials and budget proposal ready.",
            {"proposal_id": proposal_id},
        )
        return self.get_materials_budget(proposal_id)  # type: ignore[return-value]

    def get_materials_budget(self, proposal_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM materials_budget WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            return None
        return self._materials_budget_from_row(row)

    def get_latest_materials_budget_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM materials_budget
                WHERE job_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._materials_budget_from_row(row)

    def _materials_budget_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "proposal_id": row["proposal_id"],
            "job_id": row["job_id"],
            "summary": row["summary"],
            "materials": loads(row["materials_json"], []),
            "budget_lines": loads(row["budget_lines_json"], []),
            "timeline_phases": loads(row["timeline_phases_json"], []),
            "validation": loads(row["validation_json"], []),
            "supplier_evidence": loads(row["supplier_evidence_json"], []),
            "assumptions": loads(row["assumptions_json"], []),
            "warnings": loads(row["warnings_json"], []),
            "total_budget_estimate": loads(row["total_budget_estimate_json"], {}),
            "evidence_count": row["evidence_count"],
            "overall_confidence": row["overall_confidence"],
        }

    def save_plan(self, job_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        plan_id = plan["plan_id"]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO plans (
                    plan_id, job_id, title, experiment_type, domain, readiness_score,
                    estimated_total_budget_json, estimated_duration, protocol_steps_json,
                    materials_json, budget_lines_json, timeline_phases_json, validation_json,
                    assumptions_json, risks_json, citations_json, feedback_applied_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    job_id,
                    plan["title"],
                    plan["experiment_type"],
                    plan["domain"],
                    plan["readiness_score"],
                    dumps(plan["estimated_total_budget"]),
                    plan["estimated_duration"],
                    dumps(plan["protocol_steps"]),
                    dumps(plan["materials"]),
                    dumps(plan["budget_lines"]),
                    dumps(plan["timeline_phases"]),
                    dumps(plan["validation"]),
                    dumps(plan["assumptions"]),
                    dumps(plan["risks"]),
                    dumps(plan["citations"]),
                    dumps(plan.get("feedback_applied", [])),
                    utc_now(),
                ),
            )
        self.update_job_status(job_id, "plan_ready", "Experiment plan ready.", {"plan_id": plan_id})
        return self.get_plan(plan_id)  # type: ignore[return-value]

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM plans WHERE plan_id = ?", (plan_id,)).fetchone()
        if row is None:
            return None
        return self._plan_from_row(row)

    def get_latest_plan_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM plans
                WHERE job_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._plan_from_row(row)

    def _plan_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "plan_id": row["plan_id"],
            "title": row["title"],
            "experiment_type": row["experiment_type"],
            "domain": row["domain"],
            "readiness_score": row["readiness_score"],
            "estimated_total_budget": loads(row["estimated_total_budget_json"], {}),
            "estimated_duration": row["estimated_duration"],
            "protocol_steps": loads(row["protocol_steps_json"], []),
            "materials": loads(row["materials_json"], []),
            "budget_lines": loads(row["budget_lines_json"], []),
            "timeline_phases": loads(row["timeline_phases_json"], []),
            "validation": loads(row["validation_json"], []),
            "assumptions": loads(row["assumptions_json"], []),
            "risks": loads(row["risks_json"], []),
            "citations": loads(row["citations_json"], []),
            "feedback_applied": loads(row["feedback_applied_json"], []),
        }

    def save_review(
        self,
        plan_id: str,
        job_id: str,
        section: str,
        rating: int,
        correction: str,
        annotation: str,
        experiment_type: str,
        domain: str,
    ) -> dict[str, Any]:
        review_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reviews (
                    review_id, plan_id, job_id, section, rating, correction, annotation,
                    experiment_type, domain, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    plan_id,
                    job_id,
                    section,
                    rating,
                    correction,
                    annotation,
                    experiment_type,
                    domain,
                    utc_now(),
                ),
            )
        self.update_job_status(
            job_id,
            "review_saved",
            "Scientist review saved as future generation feedback.",
            {"review_id": review_id, "section": section},
        )
        return {
            "review_id": review_id,
            "plan_id": plan_id,
            "section": section,
            "rating": rating,
            "correction": correction,
            "annotation": annotation,
            "experiment_type": experiment_type,
            "domain": domain,
        }

    def list_relevant_reviews(
        self,
        domain: str,
        experiment_type: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reviews
                WHERE domain = ? OR experiment_type = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (domain, experiment_type, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM job_events
                WHERE job_id = ?
                ORDER BY event_id ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "job_id": row["job_id"],
                "status": row["status"],
                "message": row["message"],
                "payload": loads(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
