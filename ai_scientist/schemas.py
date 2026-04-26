from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


JobStatus = Literal[
    "question_received",
    "parsing",
    "qc_running",
    "qc_ready",
    "protocols_generating",
    "protocols_ready",
    "tailored_protocol_generating",
    "tailored_protocol_ready",
    "tool_inventory_generating",
    "tool_inventory_ready",
    "materials_consumables_generating",
    "materials_consumables_ready",
    "materials_budget_generating",
    "materials_budget_ready",
    "plan_generating",
    "plan_ready",
    "review_saved",
    "error",
]

NoveltySignal = Literal["not_found", "similar_work_exists", "exact_match_found"]
ReviewSection = Literal["protocol", "materials", "budget", "timeline", "validation"]
ArtifactStage = Literal[
    "structured_parse",
    "relevant_protocols",
    "tailored_protocol",
    "tool_inventory",
    "materials_consumables",
    "materials_budget",
    "experiment_plan",
]
FeedbackMode = Literal["manual", "openai"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateQuestionRequest(StrictModel):
    question: str = Field(min_length=12)


class QuestionRefinementOption(StrictModel):
    option_id: str
    label: str
    question: str
    rationale: str = ""
    editable: bool = False


class QuestionRefinementResponse(StrictModel):
    original_question: str
    options: list[QuestionRefinementOption]
    llm_provider: str = ""
    llm_model: str = ""
    warnings: list[str] = Field(default_factory=list)


class ParsedHypothesis(StrictModel):
    domain: str
    experiment_type: str
    intervention: str
    system: str
    outcome: str
    threshold: str
    control: str
    mechanism: str


class StructuredQuestionParse(StrictModel):
    primary_field: str = ""
    secondary_fields: list[str] = Field(default_factory=list)
    specific_domain: str = ""
    entities: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    application_context: str = ""
    system: str = ""
    outcome: str = ""
    optimized_query: str = ""
    target_subject: str = ""
    target_goal: str = ""
    target_methodology: str = ""
    target_readout: str = ""
    target_parameters: str = ""
    constraints: list[str] = Field(default_factory=list)
    mechanism_or_rationale: str = ""
    search_intent: str = ""
    missing_information: list[str] = Field(default_factory=list)
    confirmation_question: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_confirmation: bool = True
    confirmed: bool = False


class ScientificQuestionResponse(StrictModel):
    job_id: str
    question: str
    status: JobStatus
    parsed_hypothesis: ParsedHypothesis
    structured_parse: StructuredQuestionParse | None = None


class ConfirmParseRequest(StrictModel):
    structured_parse: StructuredQuestionParse


class FeedbackDraftRequest(StrictModel):
    stage: ArtifactStage
    mode: FeedbackMode = "manual"
    feedback: str = ""
    edited_artifact: dict[str, Any] | None = None
    operations: list[dict[str, Any]] = Field(default_factory=list)


class FeedbackDraftResponse(StrictModel):
    job_id: str
    stage: ArtifactStage
    mode: FeedbackMode
    proposed_artifact: dict[str, Any]
    change_summary: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    warnings: list[str] = Field(default_factory=list)


class ArtifactConfirmRequest(StrictModel):
    artifact: dict[str, Any]


class Reference(StrictModel):
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    source: str
    url: str
    relevance_reason: str


class SourceQueryStatus(StrictModel):
    source: str
    status: str
    queried_url: str
    message: str
    result_count: int = Field(ge=0)


class QueryVariant(StrictModel):
    kind: str
    query: str


class SourceCoverage(StrictModel):
    searched_source_count: int = Field(ge=0)
    successful_source_count: int = Field(ge=0)
    failed_source_count: int = Field(ge=0)
    needs_key_source_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    coverage_score: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


class RankedCandidate(StrictModel):
    candidate_id: str
    source: str
    source_type: str
    title: str
    url: str
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract_or_snippet: str = ""
    field: str = ""
    web_score: float | None = Field(default=None, ge=0.0, le=1.0)
    matched_fields: list[str] = Field(default_factory=list)
    lexical_score: float = Field(ge=0.0, le=1.0)
    embedding_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
    llm_score: float | None = Field(default=None, ge=0.0, le=1.0)
    llm_relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    llm_relevance_reason: str = ""
    facet_scores: dict[str, float] = Field(default_factory=dict)
    source_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    visited_content_used: bool = False
    final_score: float = Field(ge=0.0, le=1.0)
    match_classification: str


class LiteratureQCResponse(StrictModel):
    original_query: str = ""
    advanced_qc_used: bool = False
    advanced_qc_error: str = ""
    field_classification: dict[str, Any] = Field(default_factory=dict)
    embedding_model: str = ""
    literature_review_summary: str = ""
    scientific_query: str = ""
    keywords: list[str] = Field(default_factory=list)
    query_variants: list[QueryVariant] = Field(default_factory=list)
    llm_query_expansion_used: bool = False
    llm_provider: str = ""
    llm_model: str = ""
    llm_prompt_path: str = ""
    llm_paraphrased_question: str = ""
    llm_warnings: list[str] = Field(default_factory=list)
    llm_error: str = ""
    novelty_signal: NoveltySignal
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    references: list[Reference] = Field(default_factory=list, max_length=10)
    source_statuses: list[SourceQueryStatus] = Field(default_factory=list)
    candidate_count: int = Field(default=0, ge=0)
    source_coverage: SourceCoverage | None = None
    top_candidates: list[RankedCandidate] = Field(default_factory=list)
    ranking_explanation: str = ""


class MoneyEstimate(StrictModel):
    amount: float = Field(ge=0)
    currency: str = "GBP"


class ProtocolStep(StrictModel):
    step_number: int = Field(ge=1)
    phase: str
    title: str
    description: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    duration: str
    dependencies: list[str] = Field(default_factory=list)
    quality_checks: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class MaterialItem(StrictModel):
    name: str
    category: str
    supplier: str
    catalog_number: str
    quantity: str
    unit_cost: float = Field(ge=0)
    total_cost: float = Field(ge=0)
    currency: str = "GBP"
    rationale: str


class BudgetLine(StrictModel):
    category: str
    item: str
    quantity: str
    unit_cost: float = Field(ge=0)
    total_cost: float = Field(ge=0)
    currency: str = "GBP"
    notes: str


class TimelinePhase(StrictModel):
    phase: str
    duration: str
    dependencies: list[str] = Field(default_factory=list)
    deliverable: str
    critical_path: bool = False
    risk_notes: str = ""
    owner: str = ""
    start_condition: str = ""
    go_no_go_criteria: str = ""
    blocking_items: list[str] = Field(default_factory=list)
    confidence: str = "medium"


class ValidationItem(StrictModel):
    metric: str
    method: str
    success_threshold: str
    failure_criteria: str
    controls: list[str] = Field(default_factory=list)
    evidence_url: str = ""
    confidence: str = "medium"
    sample_size_or_replicates: str = ""
    statistical_test: str = ""
    acceptance_window: str = ""
    measurement_timepoint: str = ""
    linked_protocol_step: str = ""


class FeedbackApplication(StrictModel):
    section: ReviewSection
    correction: str
    annotation: str | None = None
    applied_as: str


class ProtocolDerivedItem(StrictModel):
    name: str
    category: str = ""
    specification: str = ""
    source_protocol_title: str = ""
    source_url: str = ""
    rationale: str = ""
    needs_user_check: bool = True
    procurement_required: bool = False


class ProtocolCandidate(StrictModel):
    title: str
    source_title: str = ""
    source_url: str = ""
    source_type: str = ""
    evidence_quality: str = ""
    relevance_reason: str = ""
    adapted_steps: list[str] = Field(default_factory=list)
    tools: list[ProtocolDerivedItem] = Field(default_factory=list)
    consumables: list[ProtocolDerivedItem] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class RelevantProtocolsResponse(StrictModel):
    protocol_set_id: str
    job_id: str
    summary: str
    protocol_candidates: list[ProtocolCandidate] = Field(default_factory=list)
    tools: list[ProtocolDerivedItem] = Field(default_factory=list)
    consumables: list[ProtocolDerivedItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_count: int = Field(default=0, ge=0)


class TailoredProtocolStep(StrictModel):
    step_number: int = Field(ge=1)
    title: str
    description: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    duration: str = ""
    validation_checks: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class TailoredProtocolResponse(StrictModel):
    tailored_protocol_id: str
    job_id: str
    title: str
    summary: str
    steps: list[TailoredProtocolStep] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    source_protocol_refs: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


ToolInventoryStatus = Literal["available", "limited", "missing", "ordered"]


class ToolInventoryRow(StrictModel):
    item: str
    status: ToolInventoryStatus
    note: str = ""
    action: str = ""


class ToolInventorySection(StrictModel):
    title: str
    rows: list[ToolInventoryRow] = Field(default_factory=list)
    missingNote: str = ""


class ToolInventoryResponse(StrictModel):
    tool_inventory_id: str
    job_id: str
    summary: str
    sections: list[ToolInventorySection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MaterialConsumableItem(StrictModel):
    name: str
    category: str = ""
    quantity: str = ""
    supplier_hint: str = ""
    catalog_number: str = ""
    evidence_source: str = ""
    pricing_status: str = "not_priced"
    inventory_check_status: str = "not_checked"
    needs_manual_verification: bool = True
    notes: str = ""


class MaterialsConsumablesResponse(StrictModel):
    materials_consumables_id: str
    job_id: str
    summary: str
    items: list[MaterialConsumableItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SupplierEvidence(StrictModel):
    supplier: str
    evidence_type: str
    title: str = ""
    url: str = ""
    catalog_number: str = ""
    status: str = ""
    message: str = ""
    confidence: str = "low"
    price_estimate: float = Field(default=0, ge=0)
    price_currency: str = ""
    price_excerpt: str = ""


class TrustedMaterialItem(StrictModel):
    name: str
    category: str = ""
    supplier: str = ""
    catalog_number: str = ""
    quantity: str = ""
    unit_cost_estimate: float = Field(default=0, ge=0)
    total_cost_estimate: float = Field(default=0, ge=0)
    currency: str = "GBP"
    cost_confidence: str = "low"
    quote_confidence: str = "none"
    availability_status: str = "unknown"
    source_url: str = ""
    evidence_type: str = "estimated"
    rationale: str = ""
    substitution_notes: str = ""
    needs_manual_verification: bool = True


class TrustedBudgetLine(StrictModel):
    category: str
    item: str
    quantity: str = ""
    unit_cost_estimate: float = Field(default=0, ge=0)
    total_cost_estimate: float = Field(default=0, ge=0)
    currency: str = "GBP"
    cost_confidence: str = "low"
    quote_confidence: str = "none"
    source_url: str = ""
    notes: str = ""
    needs_manual_verification: bool = True


class TrustedTimelinePhase(StrictModel):
    phase: str
    duration: str
    dependencies: list[str] = Field(default_factory=list)
    deliverable: str = ""
    critical_path: bool = False
    risk_notes: str = ""


class TrustedValidationItem(StrictModel):
    metric: str
    method: str
    success_threshold: str
    failure_criteria: str
    controls: list[str] = Field(default_factory=list)
    evidence_url: str = ""
    confidence: str = "medium"


class MaterialsBudgetResponse(StrictModel):
    proposal_id: str
    job_id: str
    summary: str
    materials: list[TrustedMaterialItem] = Field(default_factory=list)
    budget_lines: list[TrustedBudgetLine] = Field(default_factory=list)
    timeline_phases: list[TrustedTimelinePhase] = Field(default_factory=list)
    validation: list[TrustedValidationItem] = Field(default_factory=list)
    supplier_evidence: list[SupplierEvidence] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    total_budget_estimate: MoneyEstimate
    evidence_count: int = Field(default=0, ge=0)
    overall_confidence: str = "low"


class ExperimentPlanResponse(StrictModel):
    plan_id: str
    title: str
    experiment_type: str
    domain: str
    readiness_score: float = Field(ge=0.0, le=1.0)
    estimated_total_budget: MoneyEstimate
    estimated_duration: str
    protocol_steps: list[ProtocolStep]
    materials: list[MaterialItem]
    budget_lines: list[BudgetLine]
    timeline_phases: list[TimelinePhase]
    validation: list[ValidationItem]
    assumptions: list[str]
    risks: list[str]
    citations: list[Reference]
    feedback_applied: list[FeedbackApplication] = Field(default_factory=list)


class ReviewFeedbackRequest(StrictModel):
    section: ReviewSection
    rating: int = Field(ge=1, le=5)
    correction: str = Field(min_length=2)
    annotation: str = ""


class ReviewFeedbackResponse(StrictModel):
    review_id: str
    plan_id: str
    section: ReviewSection
    rating: int
    correction: str
    annotation: str
    experiment_type: str
    domain: str


class JobEvent(StrictModel):
    event_id: int
    job_id: str
    status: JobStatus
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class JobResponse(StrictModel):
    job_id: str
    question: str
    status: JobStatus
    parsed_hypothesis: ParsedHypothesis
    structured_parse: StructuredQuestionParse | None = None
    literature_qc: LiteratureQCResponse | None = None
    relevant_protocols: RelevantProtocolsResponse | None = None
    tailored_protocol: TailoredProtocolResponse | None = None
    tool_inventory: ToolInventoryResponse | None = None
    materials_consumables: MaterialsConsumablesResponse | None = None
    materials_budget: MaterialsBudgetResponse | None = None
    experiment_plan: ExperimentPlanResponse | None = None
    error: str | None = None


FrontendChatRole = Literal["user", "assistant", "character"]
EricStage = Literal["relevant_protocols", "tailored_protocol", "tools", "materials_consumables"]


class FrontendChatMessage(StrictModel):
    role: FrontendChatRole
    text: str = ""


class FrontendRachaelRequest(StrictModel):
    messages: list[FrontendChatMessage] = Field(default_factory=list)
    messageCount: int = Field(default=1, ge=0)
    jobId: str | None = None


class FrontendPaper(StrictModel):
    title: str = ""
    authors: str = ""
    journal: str = ""
    year: int = 0
    similarity: int = Field(default=0, ge=0, le=100)
    doi: str = ""
    url: str = ""


class FrontendTrailStep(StrictModel):
    label: str
    detail: str


class FrontendPlanUpdate(StrictModel):
    hypothesis: str = ""
    controls: str = ""
    falsifiability: str = ""
    equipment: str = ""
    budget: str = ""
    timeline: str = ""


class FrontendRachaelResponse(StrictModel):
    text: str
    papers: list[FrontendPaper] = Field(default_factory=list)
    similarityFlag: str | None = None
    trailSteps: list[FrontendTrailStep] = Field(default_factory=list)
    planUpdate: FrontendPlanUpdate = Field(default_factory=FrontendPlanUpdate)
    chips: list[str] = Field(default_factory=list)
    jobId: str
    parseSummary: dict[str, Any] | None = None
    suggested_text: str = ""
    suggested_chips: list[str] = Field(default_factory=list)


class FrontendEricRequest(StrictModel):
    model_config = ConfigDict(extra="ignore")
    jobId: str | None = None
    ericStage: EricStage = "relevant_protocols"
    messages: list[FrontendChatMessage] = Field(default_factory=list)
    currentInventory: list[dict[str, Any]] = Field(default_factory=list)
    messageCount: int = Field(default=0, ge=0)
    hypothesisContext: str = ""


class FrontendEricResponse(StrictModel):
    text: str
    inventorySections: list[dict[str, Any]] = Field(default_factory=list)
    planUpdate: FrontendPlanUpdate = Field(default_factory=FrontendPlanUpdate)
    chips: list[str] = Field(default_factory=list)
    ericStage: EricStage
    protocols: dict[str, Any] | None = None
    tailoredProtocol: dict[str, Any] | None = None
    toolInventory: dict[str, Any] | None = None
    materialsConsumables: dict[str, Any] | None = None
    materialsBudget: dict[str, Any] | None = None
    routeBackTo: Literal["rachael"] | None = None
    suggested_text: str = ""
    suggested_chips: list[str] = Field(default_factory=list)


class FrontendFaithRequest(StrictModel):
    model_config = ConfigDict(extra="ignore")
    jobId: str | None = None
    hypothesisContext: str = ""
    messages: list[FrontendChatMessage] = Field(default_factory=list)
    ericContext: str = ""


class FrontendPlanData(StrictModel):
    hypothesis: str = ""
    controls: str = ""
    falsifiability: str = ""
    equipment: str = ""
    budget: str = ""
    timeline: str = ""
    impact: str = ""


class FrontendFaithResponse(StrictModel):
    text: str
    planData: FrontendPlanData = Field(default_factory=FrontendPlanData)
    chips: list[str] = Field(default_factory=list)
    readinessScore: float = Field(default=0.0, ge=0.0, le=1.0)
    plan: dict[str, Any] | None = None
    suggested_text: str = ""
    suggested_chips: list[str] = Field(default_factory=list)


class ExampleInput(StrictModel):
    id: str
    label: str
    hypothesis: str
    plain_english: str
    domain: str
