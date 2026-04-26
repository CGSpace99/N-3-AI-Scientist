# Overall Workflow

The system is a staged artifact pipeline. The chat UI feels conversational, but each agent produces structured backend artifacts that are persisted and reused downstream.

```mermaid
flowchart TD
    userInput["User hypothesis"] --> frontendChat["Next.js chat UI"]
    frontendChat --> rachaelEndpoint["/api/frontend/chat/rachael"]
    rachaelEndpoint --> jobStore["SQLite job store"]
    rachaelEndpoint --> rachaelAgent["Rachael: scientific QC"]

    rachaelAgent --> parsedHypothesis["Parsed hypothesis"]
    rachaelAgent --> literatureQc["Literature QC artifact"]
    parsedHypothesis --> ericEndpoint["/api/frontend/chat/eric"]
    literatureQc --> ericEndpoint

    ericEndpoint --> ericAgent["Eric: protocol and logistics"]
    ericAgent --> protocolCandidates["Protocol candidates"]
    ericAgent --> tailoredProtocol["Tailored protocol"]
    ericAgent --> liveInventory["Live inventory table"]
    ericAgent --> materialsBudget["Materials and full procurement budget"]

    protocolCandidates --> faithEndpoint["/api/frontend/chat/faith"]
    tailoredProtocol --> faithEndpoint
    liveInventory --> faithEndpoint
    materialsBudget --> faithEndpoint
    literatureQc --> faithEndpoint

    faithEndpoint --> faithAgent["Faith: final plan synthesis"]
    faithAgent --> finalPlan["Experiment plan artifact"]
    finalPlan --> chatPlan["Plan rendered in chat"]
    finalPlan --> protocolPanel["Plan rendered in protocol side panel"]
    chatPlan --> feedbackPrompt["Any feedback for improvement?"]
    feedbackPrompt --> feedbackCache["Local feedback cache"]
    feedbackCache --> futureSearches["Future search and plan improvement"]
```

## Key Technical Bits

- The frontend lives in `Frontend_Final` and proxies persona calls through Next.js API routes.
- The backend lives in `ai_scientist` and exposes FastAPI endpoints for Rachael, Eric, and Faith.
- SQLite stores the job state, intermediate artifacts, final plans, and review metadata.
- Artifacts move forward as typed JSON contracts, not loose chat text.
- Optional live integrations improve the demo but are not mandatory: OpenAI/Anthropic for LLM tasks, Tavily for web/supplier search, and public literature APIs for QC.

## Artifact Chain

```mermaid
flowchart LR
    question["Question"] --> parse["ParsedHypothesis"]
    parse --> qc["LiteratureQC"]
    qc --> protocols["RelevantProtocols"]
    protocols --> tailored["TailoredProtocol"]
    tailored --> inventory["ToolInventory"]
    tailored --> consumables["MaterialsConsumables"]
    consumables --> budget["MaterialsBudget"]
    qc --> plan["ExperimentPlan"]
    tailored --> plan
    inventory --> plan
    budget --> plan
```
