# Rachael Agent Workflow

Rachael is the scientific validation agent. Her job is to turn a raw hypothesis into structured scientific context and a literature QC signal.

```mermaid
flowchart TD
    userHypothesis["Raw hypothesis"] --> frontendRoute["Next.js /api/chat/rachael"]
    frontendRoute --> backendRoute["FastAPI /api/frontend/chat/rachael"]
    backendRoute --> createJob["Create or update backend job"]
    createJob --> parseQuestion["Parse hypothesis"]

    parseQuestion --> structuredParse["Structured parse"]
    parseQuestion --> parsedModel["ParsedHypothesis model"]

    parsedModel --> queryProfile["Build query profile"]
    structuredParse --> queryProfile
    queryProfile --> keywords["Extract keywords"]
    queryProfile --> queryVariants["Build query variants"]

    queryVariants --> qcMode{"Advanced QC enabled?"}
    keywords --> qcMode

    qcMode -->|"No"| deterministicQc["Deterministic QC fallback"]
    qcMode -->|"Yes"| fieldClassifier["LLM field classification"]

    fieldClassifier --> advancedQueries["Merge structured and field-specific queries"]
    advancedQueries --> tavilySearch["Tavily web search"]
    advancedQueries --> scholarlySources["Scholarly and protocol source adapters"]
    advancedQueries --> bioSources["Bio-specific sources when relevant"]

    tavilySearch --> candidates["Candidate result pool"]
    scholarlySources --> candidates
    bioSources --> candidates
    deterministicQc --> candidates

    candidates --> embeddings["OpenAI text embeddings"]
    embeddings --> cosineSim["Cosine similarity scoring"]
    cosineSim --> llmRanker["LLM relevance ranking"]
    llmRanker --> finalScores["Facet-gated final scores"]
    finalScores --> novelty["Novelty signal and confidence"]
    novelty --> rachaelResponse["Frontend-safe Rachael response"]
```

## Key Technical Bits

- `build_query_profile` creates strict, broad, and protocol-focused query variants.
- `extract_keywords` seeds domain-specific and hypothesis-specific search terms.
- Advanced QC can classify the field, expand the search plan, and query Tavily plus scholarly/protocol adapters.
- Candidate titles and snippets are embedded with the configured embedding model, defaulting to `text-embedding-3-small`.
- Cosine similarity gives a semantic relevance score between the user hypothesis and each candidate.
- An LLM ranking step adds facet-aware relevance judgments such as system match, intervention match, outcome match, and novelty relevance.
- The final literature QC artifact includes source coverage, query variants, candidate count, top candidates, novelty signal, and confidence.

## Search And Ranking Detail

```mermaid
flowchart LR
    structuredTerms["Structured terms"] --> queryVariants["Query variants"]
    domainKeywords["Domain keywords"] --> queryVariants
    llmExpansion["Optional LLM query expansion"] --> queryVariants

    queryVariants --> sourceAdapters["Source adapters"]
    sourceAdapters --> rawCandidates["Raw candidates"]
    rawCandidates --> dedupe["Dedupe candidates"]
    dedupe --> embedText["Embed hypothesis and candidate snippets"]
    embedText --> similarity["Cosine similarity"]
    similarity --> rankPayload["LLM ranking payload"]
    rankPayload --> facetScores["Facet scores"]
    facetScores --> sourceQuality["Source-quality adjustment"]
    sourceQuality --> topCandidates["Ranked top candidates"]
```
