# Faith Agent Workflow

Faith is the synthesis agent. She combines Rachael's scientific QC and Eric's protocol/logistics artifacts into the final experiment plan, then asks the user for improvement feedback.

```mermaid
flowchart TD
    faithTab["User opens Faith tab"] --> frontendRoute["Next.js /api/chat/faith"]
    frontendRoute --> backendRoute["FastAPI /api/frontend/chat/faith"]
    backendRoute --> loadJob["Load persisted job"]

    loadJob --> hasPlan{"Existing plan?"}
    hasPlan -->|"Yes"| loadPlan["Load saved experiment plan"]
    hasPlan -->|"No"| gatherArtifacts["Gather upstream artifacts"]

    gatherArtifacts --> qcArtifact["Literature QC"]
    gatherArtifacts --> protocolArtifact["Relevant and tailored protocols"]
    gatherArtifacts --> inventoryArtifact["Tool inventory"]
    gatherArtifacts --> budgetArtifact["Materials budget"]
    gatherArtifacts --> materialsArtifact["Materials and consumables"]

    qcArtifact --> planGenerator["Generate experiment plan"]
    protocolArtifact --> planGenerator
    inventoryArtifact --> planGenerator
    budgetArtifact --> planGenerator
    materialsArtifact --> planGenerator

    planGenerator --> savePlan["Persist plan in SQLite"]
    savePlan --> planDataMapper["Map backend plan to frontend PlanData"]
    loadPlan --> planDataMapper

    planDataMapper --> chatPlanCard["Render full plan in chat"]
    planDataMapper --> sideProtocolPanel["Render same plan in protocol panel"]
    chatPlanCard --> feedbackPrompt["Any feedback for improvement?"]
    feedbackPrompt --> userFeedback["User feedback"]
    userFeedback --> feedbackCache["Append local feedback cache"]
    feedbackCache --> futurePlanning["Reuse feedback for future similar plans"]
```

## Key Technical Bits

- Faith does not regenerate everything from scratch; she loads persisted job artifacts from SQLite.
- The final plan is generated from the approved scientific context, protocol, inventory, materials, and budget.
- The frontend maps the backend plan into `PlanData` so the chat card and protocol side panel stay aligned.
- Faith's visible response after the plan is a direct feedback prompt: `Any feedback for improvement?`
- User feedback is appended to a local JSONL cache with search context, protocol context, supplier context, and plan context.
- Related historical feedback can be reused by future plan generation, which creates a lightweight improvement loop.

## Feedback Cache Detail

```mermaid
flowchart LR
    userFeedback["User feedback text"] --> cacheRecord["Build cache record"]
    cacheRecord --> searchContext["Search context"]
    cacheRecord --> protocolContext["Protocol context"]
    cacheRecord --> supplierContext["Supplier context"]
    cacheRecord --> planContext["Plan context"]
    searchContext --> jsonlCache["data/faith_feedback_cache.jsonl"]
    protocolContext --> jsonlCache
    supplierContext --> jsonlCache
    planContext --> jsonlCache
    jsonlCache --> futureSimilarity["Future similar experiment"]
    futureSimilarity --> feedbackApplied["Prior feedback applied to plan"]
```
