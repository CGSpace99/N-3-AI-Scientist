# Eric Agent Workflow

Eric is the lab logistics agent. He converts Rachael's scientific context into protocol steps, inventory requirements, materials, and a full procurement budget.

```mermaid
flowchart TD
    rachaelArtifacts["Parsed hypothesis and literature QC"] --> ericRoute["FastAPI /api/frontend/chat/eric"]
    ericRoute --> stageRouter{"Eric stage"}

    stageRouter -->|"relevant_protocols"| protocolSearch["Generate relevant protocols"]
    protocolSearch --> paperContext["Use QC papers and source context"]
    paperContext --> protocolCandidates["Protocol candidates"]
    protocolCandidates --> adaptedSteps["Adapted protocol steps"]

    stageRouter -->|"tailored_protocol"| tailorProtocol["Generate tailored protocol"]
    protocolCandidates --> tailorProtocol
    tailorProtocol --> tailoredSteps["Runnable step-by-step protocol"]

    stageRouter -->|"tools"| deriveTools["Derive tool and equipment inventory"]
    tailoredSteps --> deriveTools
    deriveTools --> liveInventory["Live inventory sections"]
    liveInventory --> frontendTable["Eric live inventory table"]

    stageRouter -->|"materials_consumables"| materialsDataset["Generate materials and consumables"]
    tailoredSteps --> materialsDataset
    protocolCandidates --> materialsDataset
    materialsDataset --> procurementItems["Structured procurement items"]

    procurementItems --> supplierEvidence["Supplier evidence search"]
    supplierEvidence --> focusedAdapters["Focused supplier pages"]
    supplierEvidence --> tavilyFallback["Tavily supplier discovery fallback"]
    focusedAdapters --> candidateSources["Candidate source URLs"]
    tavilyFallback --> candidateSources

    candidateSources --> budgetPrompt["LLM materials budget prompt"]
    procurementItems --> budgetPrompt
    budgetPrompt --> priceEstimation["GPT cost estimation for missing prices"]
    priceEstimation --> budgetFinalizer["Budget finalizer"]
    budgetFinalizer --> totalBudget["Total budget with materials and labour"]
    totalBudget --> frontendBudget["Budget card and plan update"]
```

## Key Technical Bits

- Protocol candidates are generated from literature QC and relevant source context.
- Each candidate carries adapted steps so the demo shows how papers become practical workflow steps.
- The tailored protocol becomes the source of truth for equipment and tool extraction.
- Tool inventory is rendered once as the live inventory table and can be edited by the user.
- Consumables become structured procurement items with expected quantity, unit size, specification, supplier hint, and intended use.
- Supplier discovery uses focused adapters for known suppliers and Tavily fallback queries for broader product/source search.
- The supplier query includes trusted supplier site filters such as Thermo Fisher, Sigma-Aldrich, Promega, QIAGEN, IDT, Addgene, and ATCC.
- The budget path uses GPT to estimate missing costs, then a backend finalizer prevents `TBD` suppliers and adds labour, facility time, analysis, waste/safety, and contingency.

## Procurement And Budgeting Detail

```mermaid
flowchart TD
    consumables["Protocol consumables"] --> procurementItems["Build procurement items"]
    procurementItems --> materialHints["Extract material hints"]
    procurementItems --> focusedSupplier["Focused supplier adapters"]
    procurementItems --> tavilyQuery["Tavily product search query"]
    materialHints --> tavilyQuery

    focusedSupplier --> evidencePool["Supplier evidence pool"]
    tavilyQuery --> evidencePool

    evidencePool --> sourceMatch["Match evidence to materials"]
    sourceMatch --> llmBudget["LLM budget proposal"]
    llmBudget --> missingPrices{"Any missing prices?"}
    missingPrices -->|"Yes"| pricePrompt["GPT rough price estimation"]
    missingPrices -->|"No"| sanitizeBudget["Sanitize trusted budget"]
    pricePrompt --> sanitizeBudget
    sanitizeBudget --> noTbd["Replace empty or TBD supplier fields"]
    noTbd --> nonMaterialCosts["Add labour, facility, analysis, waste, contingency"]
    nonMaterialCosts --> recomputeTotal["Recompute total budget"]
```
