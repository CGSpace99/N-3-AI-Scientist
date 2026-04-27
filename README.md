# HackNation AI Scientist

This is a **24-hour** hackathon project, competed in the **5th HackNation AI** (25–26 April 2026).

## Product video

<video width="100%" controls playsinline>
  <source src="Video/hacknation1.mp4" type="video/mp4" />
  Your browser does not support inline video. <a href="Video/hacknation1.mp4">Open or download the MP4</a>.
</video>

[Open the product video on GitHub](Video/hacknation1.mp4) if the player above does not load.

---

HackNation AI Scientist is a hypothesis-to-protocol planning demo. It takes a raw scientific idea and moves it through three specialist agents: Rachael validates the science, Eric turns the science into lab logistics and procurement, and Faith synthesizes the final execution-ready protocol.

The project is built as a Next.js frontend backed by a FastAPI service with SQLite persistence. The backend can run with deterministic fallbacks for demos, or use optional OpenAI, Anthropic, Tavily, and literature-source credentials for richer search, ranking, and cost estimation.

## Demo Workflow

```text
User hypothesis
  -> Rachael: parse hypothesis, run literature QC, assess novelty
  -> Eric: extract protocols, adapt steps, derive tools and consumables, build budget
  -> Faith: produce final plan, ask for feedback, cache improvement signals
```

Workflow diagrams are available in `docs/diagrams`:

- `docs/diagrams/overall-workflow.md`
- `docs/diagrams/rachael-agent.md`
- `docs/diagrams/eric-agent.md`
- `docs/diagrams/faith-agent.md`

### Rachael: Scientific QC

Rachael is the scientific rigour layer. The frontend sends the user's hypothesis to the backend, which creates a persisted job, parses the hypothesis into structured scientific fields, builds query variants, and runs literature/source quality control.

Outputs include:

- Parsed hypothesis and structured field classification
- Literature candidates and novelty signal
- Source coverage and source-status diagnostics
- Readiness/context used by downstream agents

### Eric: Protocols, Inventory, And Procurement

Eric converts validated science into lab operations. The backend searches for relevant protocol candidates, extracts adapted steps, tailors the protocol to the user's hypothesis, and derives the tool/equipment inventory and material list.

Eric also creates a procurement budget. Supplier evidence is gathered from focused source adapters and Tavily-style supplier discovery when configured. GPT-based estimation fills missing costs, while deterministic fallbacks keep the demo usable offline. The final budget includes:

- Reagents, consumables, samples, kits, and services
- Candidate supplier/source URLs and catalog guidance
- Labour, shared facility time, data analysis, waste/safety, and contingency
- Total estimated budget with confidence and manual-verification flags

### Faith: Final Experiment Plan

Faith combines Rachael's scientific context and Eric's logistics into the final protocol document. The frontend renders the same plan in the chat and protocol side panel.

Outputs include:

- Protocol steps and controls
- Materials and equipment
- Budget lines and total estimate
- Timeline, validation criteria, assumptions, risks, and impact framing
- A final prompt: `Any feedback for improvement?`

Faith feedback is stored locally with search, protocol, supplier, and plan context so future searches and plan generation can reuse improvement signals.

## Architecture

```text
Frontend_Final/                 Next.js + React chat UI
  app/api/chat/*                Next.js API routes proxying to FastAPI
  components/n3-chat.tsx        Main Rachael/Eric/Faith chat workflow
  components/*panel.tsx         Literature, inventory, and protocol side panels

ai_scientist/                  FastAPI backend package
  app.py                       API routes and frontend persona endpoints
  services.py                  Hypothesis parsing, QC, protocol, budget, plan logic
  source_adapters.py           Literature, protocol, supplier, and Tavily adapters
  database.py                  SQLite persistence
  schemas.py                   Pydantic request/response contracts
  frontend_contract.py         Backend-to-frontend artifact shaping

prompts/                       Editable LLM prompt instructions
tests/                         Backend API and contract tests
data/                          Runtime SQLite/cache files
```

## Tech Stack

- Frontend: Next.js, React, TypeScript, Tailwind/Radix UI components
- Backend: FastAPI, Pydantic, SQLite, Uvicorn
- Search/source layer: Semantic Scholar, Crossref, Europe PMC, NCBI PubMed, arXiv, supplier pages, optional Tavily
- LLM layer: optional OpenAI or Anthropic for query expansion, ranking, protocol extraction, price estimation, and plan synthesis
- Testing: Pytest for backend contracts, TypeScript compiler for frontend checks

## Local Setup

### 1. Backend

Create a Python environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy the example environment file if you want live source checks or LLM features:

```bash
cp .env.example .env
```

Run the backend:

```bash
uvicorn ai_scientist.app:app --reload
```

The backend runs at `http://localhost:8000`. Health check:

```bash
curl http://localhost:8000/api/health
```

The default SQLite database is created at `data/ai_scientist.sqlite3`. Local Faith feedback is written to `data/faith_feedback_cache.jsonl`.

### 2. Frontend

Install dependencies and run the Next.js app:

```bash
cd Frontend_Final
npm install
npm run dev
```

The frontend defaults to `http://localhost:3000` and proxies chat calls to `http://localhost:8000`. To point it at another backend:

```bash
API_URL=http://localhost:8001 npm run dev
```

## Environment Variables

The app works without API keys by using deterministic fallbacks. Optional integrations improve search and generation quality.

Common settings:

```bash
AI_SCIENTIST_LOAD_DOTENV=1
AI_SCIENTIST_LIVE_QC=1
AI_SCIENTIST_ADVANCED_QC=0
AI_SCIENTIST_LLM_QUERY_EXPANSION=0
AI_SCIENTIST_LLM_PROVIDER=openai
AI_SCIENTIST_LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
TAVILY_API_KEY=
```

Optional source credentials:

- `SEMANTIC_SCHOLAR_API_KEY`
- `PROTOCOLS_IO_TOKEN`
- `NCBI_API_KEY`
- `NCBI_EMAIL`
- `CROSSREF_MAILTO`

See `.env.example` for the full list.

## API Overview

Core backend endpoints:

- `GET /api/health`
- `GET /api/examples`
- `POST /api/questions`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/events`
- `POST /api/jobs/{job_id}/literature-qc`
- `POST /api/jobs/{job_id}/protocols`
- `POST /api/jobs/{job_id}/tailored-protocol`
- `POST /api/jobs/{job_id}/tool-inventory`
- `POST /api/jobs/{job_id}/materials-consumables`
- `POST /api/jobs/{job_id}/materials-budget`
- `POST /api/jobs/{job_id}/plans`
- `POST /api/plans/{plan_id}/reviews`

Frontend persona endpoints:

- `POST /api/frontend/chat/rachael`
- `POST /api/frontend/chat/eric`
- `POST /api/frontend/chat/faith`

The Next.js app wraps these through:

- `POST /api/chat/rachael`
- `POST /api/chat/eric`
- `POST /api/chat/faith`

## Testing

Run backend tests:

```bash
python -m pytest tests/test_api.py
```

Run frontend type checks:

```bash
cd Frontend_Final
npx tsc --noEmit
```

## Demo Pitch

This is not a single chat completion. The app chains structured backend artifacts: hypothesis parsing, literature QC, protocol extraction, inventory derivation, supplier-backed budgeting, and final plan synthesis. Each stage persists state and passes a typed artifact to the next agent, which makes the workflow auditable and easier to improve.
