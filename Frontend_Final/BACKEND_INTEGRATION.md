# N=3 Backend Integration Guide

This document describes the API contract between the N=3 frontend and your backend services. The frontend is a Next.js 16 app. All dummy data lives in `app/api/chat/backend.ts` and the three route files below — replace these with real implementations.

---

## UI Overview

The app has 6 views, each driven by a specific API route or shared state.

### 1. Rachael — Scientific Rigour (Chat)
![Rachael Chat](public/examples/rachael-chat.jpg)
Conversational hypothesis interrogation. Drives `readiness` score in the gauge, collects `papers` from literature QC, and stages the experiment through numbered exchanges.

### 2. Eric — Lab Logistics (Chat)
![Eric Chat](public/examples/eric-chat.jpg)
Lab logistics chat with a live editable inventory table at the bottom. The `inventory` object from Eric's API populates the in-chat table and syncs to the Lab Tools panel.

### 3. Faith — Experiment Planner (Chat)
![Faith Chat](public/examples/faith-chat.jpg)
Full experiment plan card rendered below Faith's final message. The `plan` object from Faith's API drives the structured document with numbered steps, bullet points, and paper references.

### 4. Literature Panel
![Literature Panel](public/examples/literature-panel.jpg)
Displays the `papers` array accumulated during Rachael's conversation. Unlocked after Rachael's first substantive reply.

### 5. Lab Tools Panel
![Lab Tools Panel](public/examples/lab-tools-panel.jpg)
Equipment and consumables tables, editable inline. Status changes propagate back to Eric's in-chat inventory. Consumable names link to relevant papers via superscript citations.

### 6. Protocol Panel
![Protocol Panel](public/examples/protocol-panel.jpg)
Eric's tailored protocol rendered as a structured document with numbered steps, timeline visualization, and inline citation superscripts that link to papers and appear in a References section.

---

## Setup

```bash
pnpm install
cp .env.local.example .env.local   # add your keys
pnpm dev                            # runs on http://localhost:3000
```

**Node version:** 18+  
**Package manager:** pnpm

---

## Architecture Overview

```
Browser
  └── n3-chat.tsx (React, client-side state)
        ├── POST /api/chat/rachael   ← hypothesis parsing + literature QC
        ├── POST /api/chat/eric      ← protocol derivation + inventory
        └── POST /api/chat/faith     ← full experiment plan generation
```

The three characters are sequential. The user starts with Rachael, gets a `jobId` back, then passes it to Eric and Faith. State is held entirely client-side — your backend is stateless per request.

---

## File Map

| File | Purpose |
|---|---|
| `app/api/chat/rachael/route.ts` | Replace with real hypothesis parser + literature QC |
| `app/api/chat/eric/route.ts` | Replace with real protocol + inventory engine |
| `app/api/chat/faith/route.ts` | Replace with real experiment plan generator |
| `app/api/chat/backend.ts` | Keep the utility functions; replace `dummy*` functions |
| `lib/characters.ts` | Frontend only — character configs, chips, system prompts |
| `components/` | Frontend only — do not modify |

---

## API Reference

### POST `/api/chat/rachael`

**Purpose:** Parse a scientific hypothesis, run a literature QC pass, and return structured metadata that drives all downstream steps.

#### Request body

```ts
{
  messages: { role: 'user' | 'assistant'; text: string }[]
  messageCount: number        // 1 on first message, increments each turn
  jobId?: string              // undefined on first message; echo back on follow-ups
}
```

#### Response body

```ts
{
  text: string                // Rachael's reply rendered in the chat bubble
  papers: Paper[]             // literature QC matches — shown in literature panel
  similarityFlag: string | null  // 'novel_gap' | 'similar_work_exists' | 'direct_replication'
  trailSteps: TrailStep[]     // shown in the thinking trail panel
  planUpdate: {               // partial update merged into Faith's plan state
    hypothesis?: string
    controls?: string
    falsifiability?: string
  }
  chips: string[]             // quick-reply suggestions shown above the input
  jobId: string               // create this on the first message and echo it back on every subsequent response
  parseSummary?: {
    primary_field: string
    entities: string[]
    confidence: number
  }
}
```

#### Type definitions

```ts
interface Paper {
  title: string
  authors: string            // comma-separated
  journal: string
  year: number
  similarity: number         // 0–100 integer
  doi: string                // e.g. "doi:10.1038/..."
  url: string                // direct link opened by superscript citations
}

interface TrailStep {
  label: string              // short heading
  detail: string             // one-line explanation
}
```

#### Behaviour notes

- `messageCount === 1` is the first user turn — this is where you run the full hypothesis parse and literature QC. Return a `jobId`.
- On subsequent turns, `jobId` will be present. Return the same `jobId` echoed back. `papers` can be `[]` on follow-ups.
- `planUpdate` is merged into Faith's plan card — only send the fields you want to update.
- `chips` are the suggested quick-reply buttons shown above the text input. Send 2–4 short strings.

---

### POST `/api/chat/eric`

**Purpose:** Derive a protocol from the approved hypothesis, build a tool/inventory list, and return materials and consumables.

#### Request body

```ts
{
  jobId: string                         // required — created by Rachael
  ericStage: EricStage                  // controls which response stage to serve
  messages: { role: 'user' | 'assistant'; text: string }[]
  currentInventory: InventorySection[]  // the current in-chat inventory table state
}

type EricStage =
  | 'relevant_protocols'       // first call — show candidate protocols
  | 'tailored_protocol'        // after user approves candidates
  | 'tools'                    // after user approves tailored protocol
  | 'materials_consumables'    // after user approves tool list
```

#### Response body

```ts
{
  text: string
  inventorySections: InventorySection[]   // replaces the in-chat inventory table
  planUpdate: {                           // partial update merged into Faith's plan
    controls?: string                     // formatted protocol steps text
    equipment?: string                    // formatted equipment list text
    budget?: string                       // formatted budget text
  }
  chips: string[]
  ericStage: EricStage                    // the NEXT stage the frontend should send on the next call
  protocols?: ProtocolCandidates          // only on ericStage === 'relevant_protocols'
  tailoredProtocol?: TailoredProtocol     // only on ericStage === 'tailored_protocol'
  toolInventory?: ToolInventory           // only on ericStage === 'tools'
  materialsConsumables?: Materials        // only on ericStage === 'materials_consumables'
  routeBackTo?: 'rachael'                 // optional — if set, the UI nudges user back to Rachael
}
```

#### Type definitions

```ts
interface InventorySection {
  title: string
  rows: InventoryRow[]
  missingNote?: string
}

interface InventoryRow {
  item: string
  qty?: string
  status: 'available' | 'limited' | 'missing' | 'ordered'
  note?: string
  action?: string           // short instruction shown in the action column
}

interface ProtocolCandidates {
  protocol_candidates: {
    title: string
    evidence_quality: 'high' | 'moderate' | 'low'
    source_title: string    // e.g. "Holland et al. 2021"
    adapted_steps: string[]
  }[]
}

interface TailoredProtocol {
  title: string
  steps: {
    step_number: number
    title: string
    description: string
    duration: string
  }[]
  validation_checks: string[]
  warnings: string[]
}

interface ToolInventory {
  sections: {
    title: string
    rows: {
      item: string
      qty: string
      status: 'available' | 'limited' | 'missing' | 'ordered'
      note: string
      action?: string
    }[]
  }[]
}

interface Materials {
  items: {
    name: string
    category: string
    quantity: string
    supplier_hint: string
    pricing_status: string
    needs_manual_verification: boolean
  }[]
}
```

#### Stage flow

```
relevant_protocols → (user approves) → tailored_protocol
                   → (user approves) → tools
                   → (user approves) → materials_consumables
```

The frontend sends `ericStage` in the request. Your response should set `ericStage` to the **next** stage so the frontend knows what to request next.

If the user sends a change/revision request mid-flow, return `routeBackTo: 'rachael'` to redirect them.

---

### POST `/api/chat/faith`

**Purpose:** Produce the final experiment plan card shown in Faith's tab.

#### Request body

```ts
{
  jobId: string
  hypothesisContext: string               // the user's original hypothesis text
  messages: { role: 'user' | 'assistant'; text: string }[]
}
```

#### Response body

```ts
{
  text: string
  planData: PlanData
  chips: string[]
  readinessScore: number                  // 0.0–1.0, shown in the readiness gauge
  plan?: FullPlan                         // optional — raw plan object for your own use
}
```

#### Type definitions

```ts
interface PlanData {
  hypothesis: string        // one sentence, the core question
  controls: string          // formatted as numbered steps: "1. Title (duration)\nDescription\n\n2. ..."
  falsifiability: string    // formatted as dash bullets with sub-labels, then a "Risks" section
  equipment: string         // formatted as dash bullets: "- Item — Supplier (catalog), qty"
  budget: string            // formatted as dash bullets + total line
  timeline: string          // formatted as numbered items: "1. Phase — duration"
  impact: string            // paragraph + readiness statement
}

interface FullPlan {
  title: string
  readiness_score: number
  protocol_steps: { step_number: number; title: string; description: string; duration: string }[]
  validation: {
    metric: string
    success_threshold: string
    failure_criteria: string
    controls: string[]
  }[]
  risks: string[]
  materials: { name: string; supplier: string; catalog_number: string; quantity: string }[]
  budget_lines: { item: string; total_cost: number }[]
  estimated_total_budget: { currency: string; amount: number }
  timeline_phases: { phase: string; duration: string }[]
}
```

#### Text formatting rules for `PlanData`

The plan card renders text with a custom `RichText` parser. Follow these conventions exactly so items display correctly:

| Field | Format |
|---|---|
| `controls` | Numbered blocks: `"1. Step title (duration)\nStep description"`, blocks separated by `\n\n` |
| `falsifiability` | Dash bullets: `"- Metric\n  Pass: ...\n  Fail: ...\n  Controls: ..."`, blocks separated by `\n\n`, then `\n\nRisks\n\n` then `"- Risk text"` per line |
| `equipment` | One dash bullet per line: `"- Item name — Supplier (catalog), quantity"` |
| `budget` | One dash bullet per line: `"- Line item: GBP amount"`, last line: `"\nTotal estimated cost: GBP amount"` |
| `timeline` | Numbered items: `"1. Phase name — duration"` per line |
| `impact` | Free paragraph text, with `\n\n` to separate the title from the body |

---

## Utility Functions to Keep

These functions in `backend.ts` are used by the route handlers and are format-correct. Keep them as-is and call them with your real data:

```ts
mapPapers(qc)               // converts raw QC candidates to Paper[] for the frontend
noveltyFlag(signal)         // converts novelty_signal string to UI flag
parseTrail(job)             // converts parse result to TrailStep[]
sourceTrail(qc)             // converts source statuses to TrailStep[]
inventoryFromToolAndMaterials(toolInventory, materialsConsumables?)  // builds InventorySection[]
planDataFromPlan(plan, question)   // formats raw plan object into PlanData with correct text formatting
```

---

## Environment Variables

Create `.env.local` in the project root:

```bash
# LLM / AI
OPENAI_API_KEY=sk-...
# or whichever provider you use

# Database (if using one for job persistence)
DATABASE_URL=postgresql://...

# Literature QC
PUBMED_API_KEY=...
SEMANTIC_SCHOLAR_API_KEY=...

# Optional: job queue / session store
REDIS_URL=redis://...
```

The frontend reads **no environment variables** — all env vars are server-side only in the route handlers.

---

## Integration Checklist

- [ ] Replace `dummyJob()` with a real hypothesis parser (LLM call + structured output)
- [ ] Replace `dummyLiteratureQc()` with real PubMed / bioRxiv / Semantic Scholar search
- [ ] Replace `dummyProtocols()` with a real protocol retrieval step
- [ ] Replace `dummyTailoredProtocol()` with a real protocol tailoring step (LLM)
- [ ] Replace `dummyToolInventory()` with a real inventory database query
- [ ] Replace `dummyMaterialsConsumables()` with a real procurement database
- [ ] Replace `dummyPlan()` with a real plan assembly step
- [ ] Persist `jobId` in a database or cache so sessions can resume
- [ ] Add authentication/session middleware if required
- [ ] Verify `planDataFromPlan()` output format matches the text formatting rules above
- [ ] Test `Paper.url` links are valid — they drive the superscript citation links in the protocol and plan panels
