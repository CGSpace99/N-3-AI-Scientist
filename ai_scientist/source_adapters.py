from __future__ import annotations

import os
import re
import hashlib
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus

import httpx

from .schemas import ParsedHypothesis
from .web_search import tavily_search


MAX_WORKERS = int(os.environ.get("AI_SCIENTIST_SOURCE_MAX_WORKERS", "8"))


def source_timeout_seconds() -> float:
    return float(os.environ.get("AI_SCIENTIST_SOURCE_TIMEOUT_SECONDS", "6.0"))


@dataclass(frozen=True)
class SourceStatus:
    source: str
    status: str
    queried_url: str
    message: str
    result_count: int = 0


@dataclass
class SourceResult:
    source_statuses: list[SourceStatus] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SupplierEvidenceResult:
    supplier: str
    evidence_type: str
    title: str = ""
    url: str = ""
    catalog_number: str = ""
    status: str = "unknown"
    message: str = ""
    confidence: str = "low"
    price_estimate: float = 0.0
    price_currency: str = ""
    price_excerpt: str = ""


def live_qc_enabled() -> bool:
    return os.environ.get("AI_SCIENTIST_LIVE_QC", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def query_live_sources(
    question: str,
    parsed: ParsedHypothesis,
    search_query: str | None = None,
    adapter_group: str = "all",
) -> SourceResult:
    if not live_qc_enabled():
        return SourceResult(
            source_statuses=[
                SourceStatus(
                    source="live_source_layer",
                    status="disabled",
                    queried_url="",
                    message="Live source querying disabled by AI_SCIENTIST_LIVE_QC.",
                )
            ]
        )

    query = search_query or build_query(question, parsed)
    adapters = source_adapters_for_group(adapter_group)

    aggregate = SourceResult()
    with httpx.Client(timeout=source_timeout_seconds(), follow_redirects=True) as client:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(adapter, client, query, parsed) for adapter in adapters]
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - defensive isolation
                    aggregate.source_statuses.append(
                        SourceStatus(
                            source="unknown",
                            status="error",
                            queried_url="",
                            message=f"Source adapter failed: {exc}",
                        )
                    )
                    continue
                aggregate.source_statuses.extend(result.source_statuses)
                aggregate.references.extend(result.references)
                aggregate.candidates.extend(result.candidates)

    aggregate.references = rank_references(dedupe_references(aggregate.references), query)
    aggregate.candidates.extend(reference_to_candidate(ref) for ref in aggregate.references)
    aggregate.candidates = dedupe_candidates(aggregate.candidates)
    return aggregate


def query_supplier_evidence(
    query: str,
    parsed: ParsedHypothesis,
    *,
    material_hints: list[str] | None = None,
    procurement_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    hints = material_hints or []
    items = procurement_items or []
    evidence: list[SupplierEvidenceResult] = []
    with httpx.Client(timeout=source_timeout_seconds(), follow_redirects=True) as client:
        focused_items = focused_supplier_items(items)
        adapter_calls = []
        if focused_items.get("Addgene"):
            adapter_calls.append((_supplier_addgene_api, focused_items["Addgene"]))
        if focused_items.get("IDT"):
            adapter_calls.append((_supplier_idt_scitools, focused_items["IDT"]))
        if any(focused_items.values()):
            adapter_calls.append((_supplier_focused_web_evidence, [item for values in focused_items.values() for item in values]))
        if adapter_calls:
            evidence.extend(run_supplier_adapter_calls(client, query, parsed, hints, adapter_calls))
        tavily_items = tavily_fallback_items(items, evidence)
        if tavily_items or not items:
            evidence.extend(run_supplier_adapter_calls(client, query, parsed, hints, [(_supplier_tavily_evidence, tavily_items)]))
    return supplier_evidence_dicts(evidence)


FOCUSED_PROCUREMENT_SUPPLIERS = {"Thermo Fisher", "Sigma-Aldrich", "Promega", "QIAGEN", "Addgene", "IDT"}


def run_supplier_adapter_calls(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
    hints: list[str],
    adapter_calls: list[tuple[Any, list[dict[str, Any]]]],
) -> list[SupplierEvidenceResult]:
    evidence: list[SupplierEvidenceResult] = []
    with ThreadPoolExecutor(max_workers=max(1, min(MAX_WORKERS, len(adapter_calls)))) as executor:
        futures = [executor.submit(adapter, client, query, parsed, hints, adapter_items) for adapter, adapter_items in adapter_calls]
        for future in as_completed(futures):
            try:
                evidence.extend(future.result())
            except Exception as exc:  # pragma: no cover - defensive isolation
                evidence.append(
                    SupplierEvidenceResult(
                        supplier="unknown",
                        evidence_type="error",
                        status="error",
                        message=f"Supplier evidence adapter failed: {exc}",
                    )
                )
    return evidence


def focused_supplier_items(procurement_items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    focused = {supplier: [] for supplier in FOCUSED_PROCUREMENT_SUPPLIERS}
    for item in procurement_items:
        supplier = normalized_supplier_hint(item.get("supplier_hint", ""))
        if supplier in focused:
            focused[supplier].append(item)
    return focused


def tavily_fallback_items(
    procurement_items: list[dict[str, Any]],
    supplier_evidence: list[SupplierEvidenceResult] | None = None,
) -> list[dict[str, Any]]:
    supplier_evidence = supplier_evidence or []
    return [
        item
        for item in procurement_items
        if normalized_supplier_hint(item.get("supplier_hint", "")) not in FOCUSED_PROCUREMENT_SUPPLIERS
        or not item_has_useful_supplier_evidence(item, supplier_evidence)
    ]


def normalized_supplier_hint(value: str) -> str:
    lower = str(value or "").strip().lower()
    if "thermo" in lower or "fisher" in lower:
        return "Thermo Fisher"
    if "sigma" in lower or "millipore" in lower or "merck" in lower:
        return "Sigma-Aldrich"
    if "promega" in lower:
        return "Promega"
    if "qiagen" in lower:
        return "QIAGEN"
    if "addgene" in lower:
        return "Addgene"
    if lower == "idt" or "integrated dna" in lower:
        return "IDT"
    return ""


def item_has_useful_supplier_evidence(item: dict[str, Any], evidence: list[SupplierEvidenceResult]) -> bool:
    supplier = normalized_supplier_hint(item.get("supplier_hint", ""))
    if not supplier:
        return False
    item_name = clean_supplier_query(item.get("name", "")).lower()
    useful_statuses = {"reachable", "queried", "configured", "candidate"}
    for evidence_item in evidence:
        if evidence_item.supplier != supplier or evidence_item.status not in useful_statuses:
            continue
        haystack = " ".join([evidence_item.title, evidence_item.message, evidence_item.url]).lower()
        if not item_name or item_name in haystack:
            return True
    return False


def supplier_evidence_dicts(evidence: list[SupplierEvidenceResult]) -> list[dict[str, Any]]:
    return [
        {
            "supplier": item.supplier,
            "evidence_type": item.evidence_type,
            "title": item.title,
            "url": item.url,
            "catalog_number": item.catalog_number,
            "status": item.status,
            "message": item.message,
            "confidence": item.confidence,
            "price_estimate": item.price_estimate,
            "price_currency": item.price_currency,
            "price_excerpt": item.price_excerpt,
        }
        for item in evidence
    ]


def source_adapters_for_group(adapter_group: str) -> list:
    scholarly_adapters = [
        _query_semantic_scholar,
        _query_crossref,
        _query_europe_pmc,
        _query_ncbi_pubmed,
        _query_arxiv,
    ]
    if adapter_group == "scholarly":
        return scholarly_adapters
    return scholarly_adapters + [
        _query_protocols_io,
        _query_nature_protocols,
        _query_protocol_repository_search_pages,
        _query_supplier_search_pages,
        _query_scientific_standards,
    ]


def build_query(question: str, parsed: ParsedHypothesis) -> str:
    domain_queries = {
        "diagnostics": [
            "C-reactive protein",
            "CRP",
            "electrochemical biosensor",
            "whole blood",
            "anti-CRP",
            "ELISA",
        ],
        "gut_health": [
            "Lactobacillus rhamnosus GG",
            "FITC-dextran",
            "intestinal permeability",
            "claudin-1",
            "occludin",
            "C57BL/6",
        ],
        "cell_biology": [
            "trehalose",
            "cryopreservation",
            "HeLa",
            "DMSO",
            "post-thaw viability",
            "cryoprotectant",
        ],
        "climate": [
            "Sporomusa ovata",
            "bioelectrochemical",
            "CO2",
            "acetate",
            "cathode",
            "carbon fixation",
        ],
        "molecular_biology": [
            "qPCR",
            "MIQE",
            "primer",
            "RNA",
            "assay validation",
        ],
    }
    if parsed.domain in domain_queries:
        return " ".join(domain_queries[parsed.domain])

    fields = [
        parsed.intervention,
        parsed.system,
        parsed.outcome,
        parsed.mechanism,
    ]
    joined = " ".join(field for field in fields if field)
    cleaned = re.sub(r"[^A-Za-z0-9%./+\-\s]", " ", joined)
    tokens = [
        token
        for token in cleaned.split()
        if len(token) > 2 and token.lower() not in STOPWORDS
    ]
    if not tokens:
        tokens = question.split()
    return " ".join(tokens[:18])


def dedupe_references(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for ref in references:
        if _excluded_reference(ref):
            continue
        key = (ref.get("url") or ref.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def reference_to_candidate(ref: dict[str, Any]) -> dict[str, Any]:
    url = ref.get("url") or ""
    title = ref.get("title") or "Untitled result"
    return {
        "candidate_id": _candidate_id(ref),
        "source": ref.get("source") or "unknown",
        "source_type": source_type_for_source(ref.get("source") or ""),
        "title": title,
        "url": url,
        "doi": _doi_from_url(url),
        "authors": ref.get("authors") or [],
        "year": ref.get("year"),
        "abstract_or_snippet": ref.get("abstract_or_snippet") or ref.get("relevance_reason") or "",
        "matched_fields": [],
        "lexical_score": 0.0,
        "llm_score": None,
        "final_score": 0.0,
        "match_classification": "unranked",
    }


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        if _excluded_reference(candidate):
            continue
        key = (candidate.get("url") or candidate.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def source_type_for_source(source: str) -> str:
    source_lower = source.lower()
    if source_lower in {"semantic scholar", "crossref", "europe pmc", "ncbi pubmed", "arxiv"}:
        return "paper"
    if "protocol" in source_lower or source_lower in {"jove", "openwetware"}:
        return "protocol"
    if source_lower in {
        "thermo fisher",
        "sigma-aldrich",
        "promega",
        "qiagen",
        "idt",
        "atcc",
        "addgene",
    }:
        return "supplier_note"
    if "miqe" in source_lower:
        return "standard"
    return "reference"


def rank_references(references: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    query_tokens = _search_tokens(query)
    source_priority = {
        "NCBI PubMed": 5,
        "Europe PMC": 4,
        "Crossref": 3,
        "Semantic Scholar": 3,
        "protocols.io": 3,
        "Nature Protocols": 3,
        "arXiv": 2,
        "NCBI PMC / MIQE Guidelines": 5,
    }

    def score(ref: dict[str, Any]) -> tuple[int, int, int]:
        title_tokens = _search_tokens(ref.get("title", ""))
        overlap = len(query_tokens & title_tokens)
        generic_penalty = 3 if _generic_title(ref.get("title", "")) else 0
        source_score = source_priority.get(ref.get("source", ""), 1)
        year = ref.get("year") or 0
        return (overlap - generic_penalty, source_score, year)

    return sorted(references, key=score, reverse=True)


STOPWORDS = {
    "with",
    "will",
    "the",
    "and",
    "for",
    "into",
    "from",
    "that",
    "this",
    "than",
    "compared",
    "least",
    "increase",
    "reduce",
    "detect",
    "measured",
    "standard",
    "protocol",
    "medium",
    "points",
    "percentage",
}


def _search_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9+-]{3,}", text)
        if token.lower() not in STOPWORDS
    }


def _generic_title(title: str) -> bool:
    lower = title.lower().strip()
    return any(
        marker in lower
        for marker in [
            "posters",
            "conference proceedings",
            "congress",
            "abstracts",
            "meeting abstracts",
        ]
    )


def _excluded_reference(ref: dict[str, Any]) -> bool:
    title = (ref.get("title") or "").lower()
    return "retracted" in title


def source_status_dicts(statuses: list[SourceStatus]) -> list[dict[str, Any]]:
    return [
        {
            "source": status.source,
            "status": status.status,
            "queried_url": status.queried_url,
            "message": status.message,
            "result_count": status.result_count,
        }
        for status in statuses
    ]


def _query_semantic_scholar(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
) -> SourceResult:
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": 10,
        "fields": "title,authors,year,url,venue,abstract",
    }
    headers = {}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    response, error = _get_or_status(client, "Semantic Scholar", url, params=params, headers=headers)
    if error:
        return error
    if response.status_code == 429:
        return _single_status(
            "Semantic Scholar",
            "error",
            str(response.url),
            "HTTP 429 rate-limited — set SEMANTIC_SCHOLAR_API_KEY to avoid this.",
        )
    if response.status_code != 200:
        return _single_status(
            "Semantic Scholar",
            "error",
            str(response.url),
            f"HTTP {response.status_code}",
        )
    data = response.json()
    references = []
    for item in data.get("data", [])[:10]:
        references.append(
            {
                "title": item.get("title") or "Untitled Semantic Scholar result",
                "authors": [author.get("name", "") for author in item.get("authors", [])[:6]],
                "year": item.get("year"),
                "source": "Semantic Scholar",
                "url": item.get("url") or "https://www.semanticscholar.org/",
                "relevance_reason": f"Semantic Scholar paper search match for {parsed.domain}.",
                "abstract_or_snippet": item.get("abstract") or "",
            }
        )
    return SourceResult(
        source_statuses=[
            SourceStatus(
                source="Semantic Scholar",
                status="queried",
                queried_url=str(response.url),
                message="Paper search endpoint queried.",
                result_count=len(references),
            )
        ],
        references=references,
    )


def _query_crossref(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
) -> SourceResult:
    url = "https://api.crossref.org/v1/works"
    params: dict[str, Any] = {"query": query, "rows": 10}
    if mailto := os.environ.get("CROSSREF_MAILTO"):
        params["mailto"] = mailto
    response, error = _get_or_status(
        client,
        "Crossref",
        url,
        params=params,
        headers={"User-Agent": _user_agent()},
    )
    if error:
        return error
    if response.status_code != 200:
        return _single_status("Crossref", "error", str(response.url), f"HTTP {response.status_code}")
    items = response.json().get("message", {}).get("items", [])
    references = []
    for item in items[:10]:
        title = _first(item.get("title")) or "Untitled Crossref result"
        authors = [
            " ".join(
                part
                for part in [author.get("given"), author.get("family")]
                if part
            )
            for author in item.get("author", [])[:6]
        ]
        references.append(
            {
                "title": title,
                "authors": authors,
                "year": _crossref_year(item),
                "source": "Crossref",
                "url": item.get("URL") or "https://search.crossref.org/",
                "relevance_reason": f"Crossref metadata match for {parsed.experiment_type}.",
                "abstract_or_snippet": item.get("abstract") or "",
            }
        )
    return SourceResult(
        source_statuses=[
            SourceStatus(
                source="Crossref",
                status="queried",
                queried_url=str(response.url),
                message="Public Crossref REST API queried.",
                result_count=len(references),
            )
        ],
        references=references,
    )


def _query_nature_protocols(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
) -> SourceResult:
    url = "https://api.crossref.org/v1/works"
    params: dict[str, Any] = {
        "query.bibliographic": query,
        "query.container-title": "Nature Protocols",
        "rows": 10,
    }
    if mailto := os.environ.get("CROSSREF_MAILTO"):
        params["mailto"] = mailto
    response, error = _get_or_status(
        client,
        "Nature Protocols",
        url,
        params=params,
        headers={"User-Agent": _user_agent()},
    )
    if error:
        return error
    if response.status_code != 200:
        return _single_status("Nature Protocols", "error", str(response.url), f"HTTP {response.status_code}")
    items = response.json().get("message", {}).get("items", [])
    references = []
    for item in items:
        if not _is_nature_protocols_item(item):
            continue
        title = _first(item.get("title")) or "Untitled Nature Protocols result"
        authors = [
            " ".join(
                part
                for part in [author.get("given"), author.get("family")]
                if part
            )
            for author in item.get("author", [])[:6]
        ]
        references.append(
            {
                "title": title,
                "authors": authors,
                "year": _crossref_year(item),
                "source": "Nature Protocols",
                "url": item.get("URL") or "https://www.nature.com/nprot",
                "relevance_reason": f"Nature Protocols journal metadata match for {parsed.domain}.",
                "abstract_or_snippet": item.get("abstract") or "",
            }
        )
        if len(references) >= 10:
            break
    return SourceResult(
        source_statuses=[
            SourceStatus(
                source="Nature Protocols",
                status="queried",
                queried_url=str(response.url),
                message="Crossref metadata API queried for Nature Protocols journal records.",
                result_count=len(references),
            )
        ],
        references=references,
    )


def _query_europe_pmc(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
) -> SourceResult:
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    params = {"query": query, "format": "json", "pageSize": 10, "resultType": "core"}
    response, error = _get_or_status(client, "Europe PMC", url, params=params)
    if error:
        return error
    if response.status_code != 200:
        return _single_status("Europe PMC", "error", str(response.url), f"HTTP {response.status_code}")
    results = response.json().get("resultList", {}).get("result", [])
    references = []
    for item in results[:10]:
        identifier = item.get("pmid") or item.get("pmcid") or item.get("doi") or ""
        url_value = (item.get("fullTextUrlList") or {}).get("fullTextUrl", [])
        link = _first([entry.get("url") for entry in url_value if entry.get("url")]) if url_value else None
        references.append(
            {
                "title": item.get("title") or "Untitled Europe PMC result",
                "authors": [item.get("authorString", "")] if item.get("authorString") else [],
                "year": _safe_int(item.get("pubYear")),
                "source": "Europe PMC",
                "url": link or f"https://europepmc.org/article/{item.get('source', 'MED')}/{identifier}",
                "relevance_reason": f"Europe PMC life-sciences search match for {parsed.domain}.",
                "abstract_or_snippet": item.get("abstractText") or "",
            }
        )
    return SourceResult(
        source_statuses=[
            SourceStatus(
                source="Europe PMC",
                status="queried",
                queried_url=str(response.url),
                message="Europe PMC REST search queried.",
                result_count=len(references),
            )
        ],
        references=references,
    )


def _query_ncbi_pubmed(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
) -> SourceResult:
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": 10,
        "tool": os.environ.get("NCBI_TOOL", "ai_scientist_hackathon"),
    }
    if email := os.environ.get("NCBI_EMAIL"):
        params["email"] = email
    if api_key := os.environ.get("NCBI_API_KEY"):
        params["api_key"] = api_key
    search_response, error = _get_or_status(
        client,
        "NCBI PubMed",
        search_url,
        params=params,
    )
    if error:
        return error
    if search_response.status_code != 200:
        return _single_status("NCBI PubMed", "error", str(search_response.url), f"HTTP {search_response.status_code}")
    ids = search_response.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return SourceResult(
            source_statuses=[
                SourceStatus(
                    source="NCBI PubMed",
                    status="queried",
                    queried_url=str(search_response.url),
                    message="E-utilities ESearch queried; no PubMed IDs returned.",
                    result_count=0,
                )
            ]
        )

    summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    summary_params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "json",
        "tool": params["tool"],
    }
    if "email" in params:
        summary_params["email"] = params["email"]
    if "api_key" in params:
        summary_params["api_key"] = params["api_key"]
    summary_response, error = _get_or_status(
        client,
        "NCBI PubMed",
        summary_url,
        params=summary_params,
    )
    if error:
        return error
    if summary_response.status_code != 200:
        return _single_status("NCBI PubMed", "error", str(summary_response.url), f"HTTP {summary_response.status_code}")
    payload = summary_response.json().get("result", {})
    references = []
    for pmid in ids[:10]:
        item = payload.get(pmid, {})
        references.append(
            {
                "title": item.get("title") or "Untitled PubMed result",
                "authors": [author.get("name", "") for author in item.get("authors", [])[:6]],
                "year": _safe_int(str(item.get("pubdate", ""))[:4]),
                "source": "NCBI PubMed",
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "relevance_reason": f"PubMed metadata match for {parsed.domain}.",
            }
        )
    return SourceResult(
        source_statuses=[
            SourceStatus(
                source="NCBI PubMed",
                status="queried",
                queried_url=str(search_response.url),
                message="E-utilities ESearch and ESummary queried.",
                result_count=len(references),
            )
        ],
        references=references,
    )


def _query_arxiv(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
) -> SourceResult:
    url = "https://export.arxiv.org/api/query"
    params = {"search_query": f"all:{query}", "start": 0, "max_results": 10}
    response, error = _get_or_status(client, "arXiv", url, params=params)
    if error:
        return error
    if response.status_code != 200:
        return _single_status("arXiv", "error", str(response.url), f"HTTP {response.status_code}")
    root = ET.fromstring(response.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    references = []
    for entry in root.findall("atom:entry", ns)[:10]:
        title = _xml_text(entry, "atom:title", ns) or "Untitled arXiv result"
        authors = [
            _xml_text(author, "atom:name", ns)
            for author in entry.findall("atom:author", ns)[:6]
        ]
        published = _xml_text(entry, "atom:published", ns)
        summary = _xml_text(entry, "atom:summary", ns) or ""
        references.append(
            {
                "title": " ".join(title.split()),
                "authors": [author for author in authors if author],
                "year": _safe_int((published or "")[:4]),
                "source": "arXiv",
                "url": _xml_text(entry, "atom:id", ns) or "https://arxiv.org/",
                "relevance_reason": f"Preprint search match for {parsed.experiment_type}.",
                "abstract_or_snippet": " ".join(summary.split()),
            }
        )
    return SourceResult(
        source_statuses=[
            SourceStatus(
                source="arXiv",
                status="queried",
                queried_url=str(response.url),
                message="arXiv Atom API queried.",
                result_count=len(references),
            )
        ],
        references=references,
    )


def _query_protocols_io(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
) -> SourceResult:
    token = os.environ.get("PROTOCOLS_IO_TOKEN")
    url = "https://www.protocols.io/api/v3/protocols"
    if not token:
        return _single_status(
            "protocols.io",
            "needs_key",
            url,
            "API requires PROTOCOLS_IO_TOKEN bearer token for public protocol access.",
        )
    params = {"filter": "public", "page_size": 10, "key": query, "order_field": "relevance"}
    response, error = _get_or_status(
        client,
        "protocols.io",
        url,
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    if error:
        return error
    if response.status_code != 200:
        return _single_status("protocols.io", "error", str(response.url), f"HTTP {response.status_code}")
    payload = response.json()
    items = payload.get("items") or payload.get("protocols") or []
    references = []
    for item in items[:10]:
        uri = item.get("uri") or ""
        references.append(
            {
                "title": item.get("title") or "Untitled protocols.io result",
                "authors": [item.get("creator", {}).get("name", "protocols.io")],
                "year": None,
                "source": "protocols.io",
                "url": f"https://www.protocols.io/view/{uri}" if uri else "https://www.protocols.io/",
                "relevance_reason": f"Runnable protocol repository match for {parsed.domain}.",
            }
        )
    return SourceResult(
        source_statuses=[
            SourceStatus(
                source="protocols.io",
                status="queried",
                queried_url=str(response.url),
                message="Authenticated public protocol list endpoint queried.",
                result_count=len(references),
            )
        ],
        references=references,
    )


def _query_protocol_repository_search_pages(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
) -> SourceResult:
    specs = [
        ("Bio-protocol", f"https://bio-protocol.org/en/search?kw={quote_plus(query)}"),
        ("JoVE", f"https://www.jove.com/search?q={quote_plus(query)}"),
        ("OpenWetWare", f"https://openwetware.org/wiki/Special:Search?search={quote_plus(query)}"),
    ]
    return _query_search_pages(client, specs, "protocol_repository")


def _query_supplier_search_pages(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
) -> SourceResult:
    specs = [
        ("Thermo Fisher", f"https://www.thermofisher.com/search/results?keyword={quote_plus(query)}"),
        ("Sigma-Aldrich", f"https://www.sigmaaldrich.com/US/en/search/{quote_plus(query)}"),
        ("Promega", f"https://www.promega.com/search/?q={quote_plus(query)}"),
        ("Qiagen", f"https://www.qiagen.com/us/search?query={quote_plus(query)}"),
        ("IDT", f"https://www.idtdna.com/site/search?keyword={quote_plus(query)}"),
        ("ATCC", f"https://www.atcc.org/search#q={quote_plus(query)}"),
        ("Addgene", f"https://www.addgene.org/search/advanced/?q={quote_plus(query)}"),
    ]
    return _query_search_pages(client, specs, "supplier_reference")


def _supplier_addgene_api(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
    material_hints: list[str],
    procurement_items: list[dict[str, Any]] | None = None,
) -> list[SupplierEvidenceResult]:
    del procurement_items
    token = os.environ.get("ADDGENE_API_TOKEN", "").strip()
    base_url = os.environ.get("ADDGENE_API_BASE_URL", "https://api.addgene.org").rstrip("/")
    if not token:
        return [
            SupplierEvidenceResult(
                supplier="Addgene",
                evidence_type="api_result",
                url=f"{base_url}/catalog",
                status="needs_key",
                message="Addgene Developers Portal access requires ADDGENE_API_TOKEN.",
                confidence="low",
            )
        ]
    response, error = _get_or_status(
        client,
        "Addgene",
        f"{base_url}/catalog/plasmids/",
        params={"q": query, "page_size": 5},
        headers={"Authorization": f"Bearer {token}", "User-Agent": _user_agent()},
    )
    if error:
        return [
            SupplierEvidenceResult(
                supplier="Addgene",
                evidence_type="api_result",
                url=f"{base_url}/catalog/plasmids/",
                status="error",
                message=error.source_statuses[0].message,
                confidence="low",
            )
        ]
    if response.status_code != 200:
        return [
            SupplierEvidenceResult(
                supplier="Addgene",
                evidence_type="api_result",
                url=str(response.url),
                status="error",
                message=f"HTTP {response.status_code}",
                confidence="low",
            )
        ]
    payload = response.json()
    items = payload.get("results") or payload.get("items") or []
    evidence = []
    for item in items[:5]:
        catalog_number = str(item.get("id") or item.get("plasmid_id") or item.get("catalog_number") or "")
        source_url = item.get("url") or (f"https://www.addgene.org/{catalog_number}/" if catalog_number else "https://www.addgene.org/")
        evidence.append(
            SupplierEvidenceResult(
                supplier="Addgene",
                evidence_type="api_result",
                title=item.get("name") or item.get("title") or "Addgene catalog result",
                url=source_url,
                catalog_number=catalog_number,
                status="queried",
                message="Addgene catalog API returned a structured result.",
                confidence="high",
            )
        )
    if not evidence:
        evidence.append(
            SupplierEvidenceResult(
                supplier="Addgene",
                evidence_type="api_result",
                url=str(response.url),
                status="queried",
                message="Addgene catalog API queried, no matching items returned.",
                confidence="medium",
            )
        )
    return evidence


def _supplier_idt_scitools(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
    material_hints: list[str],
    procurement_items: list[dict[str, Any]] | None = None,
) -> list[SupplierEvidenceResult]:
    del procurement_items
    if not os.environ.get("IDT_API_KEY", "").strip():
        return [
            SupplierEvidenceResult(
                supplier="IDT",
                evidence_type="api_result",
                url="https://www.idtdna.com/pages/support/faqs/what-features-are-available-through-scitools-plus-api",
                status="needs_key",
                message="IDT SciTools Plus API integration requires IDT_API_KEY and account setup.",
                confidence="low",
            )
        ]
    return [
        SupplierEvidenceResult(
            supplier="IDT",
            evidence_type="api_result",
            url="https://www.idtdna.com/pages/tools",
            status="configured",
            message="IDT API key detected; use for oligo/primer design evidence, not anonymous catalog pricing.",
            confidence="medium",
        )
    ]


def _supplier_atcc_api(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
    material_hints: list[str],
    procurement_items: list[dict[str, Any]] | None = None,
) -> list[SupplierEvidenceResult]:
    del procurement_items
    if not os.environ.get("ATCC_API_TOKEN", "").strip():
        return [
            SupplierEvidenceResult(
                supplier="ATCC",
                evidence_type="api_result",
                url="https://docs.onecodex.com/en/articles/5812163-atcc-genome-portal-api-guide",
                status="needs_key",
                message="ATCC Genome Portal API requires credentials and is metadata-focused, not live catalog pricing.",
                confidence="low",
            )
        ]
    return [
        SupplierEvidenceResult(
            supplier="ATCC",
            evidence_type="api_result",
            url="https://www.atcc.org/",
            status="configured",
            message="ATCC API token detected; use for relevant cell-line metadata where applicable.",
            confidence="medium",
        )
    ]


def _supplier_focused_web_evidence(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
    material_hints: list[str],
    procurement_items: list[dict[str, Any]] | None = None,
) -> list[SupplierEvidenceResult]:
    del query, parsed, material_hints
    evidence: list[SupplierEvidenceResult] = []
    for item in procurement_items or []:
        supplier = normalized_supplier_hint(item.get("supplier_hint", ""))
        if supplier not in FOCUSED_PROCUREMENT_SUPPLIERS:
            continue
        search_text = procurement_item_search_text(item)
        evidence_type, url = focused_supplier_reference(supplier, search_text)
        try:
            response = client.get(url, headers={"User-Agent": _user_agent()})
            status = "reachable" if response.status_code < 400 else "error"
            message = (
                f"{supplier} trusted reference page reached for '{item.get('name', '')}'. "
                "Use this for material identity/protocol grounding; pricing and stock still require quote verification."
                if status == "reachable"
                else f"HTTP {response.status_code}"
            )
            evidence.append(
                SupplierEvidenceResult(
                    supplier=supplier,
                    evidence_type=evidence_type if status == "reachable" else "search_page_reachable",
                    title=f"{supplier} trusted reference for {item.get('name', '')}",
                    url=str(response.url),
                    status=status,
                    message=message,
                    confidence="medium" if status == "reachable" and evidence_type == "catalog_page" else "low",
                )
            )
        except Exception as exc:
            evidence.append(
                SupplierEvidenceResult(
                    supplier=supplier,
                    evidence_type=evidence_type,
                    title=f"{supplier} trusted reference for {item.get('name', '')}",
                    url=url,
                    status="error",
                    message=str(exc),
                    confidence="low",
                )
            )
    return evidence


def focused_supplier_reference(supplier: str, search_text: str) -> tuple[str, str]:
    encoded = quote_plus(search_text)
    if supplier == "Thermo Fisher":
        return "application_note", "https://www.thermofisher.com/us/en/home/technical-resources/application-notes.html"
    if supplier == "Sigma-Aldrich":
        return "technical_bulletin", f"https://www.sigmaaldrich.com/US/en/technical-documents?term={encoded}"
    if supplier == "Promega":
        return "protocol_page", f"https://www.promega.com/resources/protocols/?q={encoded}"
    if supplier == "QIAGEN":
        return "protocol_page", "https://www.qiagen.com/us/resources/resourcedetail?id=protocols"
    if supplier == "IDT":
        return "tool_page", f"https://www.idtdna.com/pages/tools?keyword={encoded}"
    if supplier == "Addgene":
        return "catalog_page", f"https://www.addgene.org/search/advanced/?q={encoded}"
    return "search_page_reachable", ""


def _supplier_web_evidence(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
    material_hints: list[str],
    procurement_items: list[dict[str, Any]] | None = None,
) -> list[SupplierEvidenceResult]:
    del parsed
    structured_terms = [procurement_item_search_text(item) for item in (procurement_items or [])[:3]]
    encoded_query = quote_plus(" ".join([*structured_terms, query, *material_hints[:5]]).strip() or query)
    specs = [
        ("Thermo Fisher", "application_note", f"https://www.thermofisher.com/us/en/home/technical-resources/application-notes.html"),
        ("Sigma-Aldrich", "application_note", f"https://www.sigmaaldrich.com/US/en/technical-documents?term={encoded_query}"),
        ("Promega", "protocol_page", f"https://www.promega.com/resources/protocols/?q={encoded_query}"),
        ("Qiagen", "protocol_page", f"https://www.qiagen.com/us/resources/resourcedetail?id=protocols"),
        ("IDT", "catalog_page", f"https://www.idtdna.com/site/search?keyword={encoded_query}"),
        ("ATCC", "catalog_page", f"https://www.atcc.org/search#q={encoded_query}"),
        ("Addgene", "catalog_page", f"https://www.addgene.org/search/advanced/?q={encoded_query}"),
    ]
    evidence = []
    for supplier, evidence_type, url in specs:
        try:
            response = client.get(url, headers={"User-Agent": _user_agent()})
            status = "reachable" if response.status_code < 400 else "error"
            message = (
                f"{evidence_type} page reachable; product availability and pricing not verified."
                if status == "reachable"
                else f"HTTP {response.status_code}"
            )
            evidence.append(
                SupplierEvidenceResult(
                    supplier=supplier,
                    evidence_type=evidence_type if status == "reachable" else "search_page_reachable",
                    title=f"{supplier} supplier evidence",
                    url=str(response.url),
                    status=status,
                    message=message,
                    confidence="low",
                )
            )
        except Exception as exc:
            evidence.append(
                SupplierEvidenceResult(
                    supplier=supplier,
                    evidence_type="search_page_reachable",
                    url=url,
                    status="error",
                    message=str(exc),
                    confidence="low",
                )
            )
    return evidence


def _supplier_tavily_evidence(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
    material_hints: list[str],
    procurement_items: list[dict[str, Any]] | None = None,
) -> list[SupplierEvidenceResult]:
    del client, parsed
    if not os.environ.get("TAVILY_API_KEY", "").strip():
        return [
            SupplierEvidenceResult(
                supplier="Tavily",
                evidence_type="tavily_product_candidate",
                url="https://api.tavily.com/search",
                status="needs_key",
                message="TAVILY_API_KEY is required for supplier/material discovery.",
                confidence="low",
            )
        ]

    evidence: list[SupplierEvidenceResult] = []
    for search_item in supplier_tavily_search_items(query, material_hints, procurement_items or []):
        result, status = supplier_tavily_search_with_fallback(search_item)
        if status.get("status") != "queried":
            evidence.append(
                SupplierEvidenceResult(
                    supplier="Tavily",
                    evidence_type="tavily_product_candidate",
                    url=status.get("queried_url", "https://api.tavily.com/search"),
                    status=status.get("status", "error"),
                    message=status.get("message", "Tavily supplier/material search did not return results."),
                    confidence="low",
                )
            )
            continue
        for candidate in result.candidates[: supplier_tavily_max_results()]:
            supplier = supplier_from_url(candidate.get("url", "")) or supplier_from_title(candidate.get("title", ""))
            price_estimate, price_currency, price_excerpt = supplier_price_from_candidate(candidate)
            evidence.append(
                SupplierEvidenceResult(
                    supplier=supplier or "Unknown supplier",
                    evidence_type="tavily_product_candidate",
                    title=candidate.get("title", "")[:240],
                    url=candidate.get("url", ""),
                    status="candidate",
                    message=(
                        f"Tavily discovered a possible supplier/product page for '{search_item['name']}'. "
                        f"Query context: {search_item.get('context', '')}. "
                        "Availability, catalog number, and pricing are not verified."
                    ),
                    confidence="medium" if supplier else "low",
                    price_estimate=price_estimate,
                    price_currency=price_currency,
                    price_excerpt=price_excerpt,
                )
            )
    return dedupe_supplier_evidence(evidence)[:20]


def supplier_tavily_search_with_fallback(search_item: dict[str, str]):
    result = tavily_search(
        supplier_tavily_query(search_item, fallback_mode="trusted_sites"),
        field="supplier_material_discovery",
        max_results=supplier_tavily_max_results(),
    )
    status = result.source_statuses[0] if result.source_statuses else {}
    if status.get("status") == "queried" and result.candidates:
        return result, status
    broad_result = tavily_search(
        supplier_tavily_query(search_item, fallback_mode="broad"),
        field="supplier_material_discovery",
        max_results=supplier_tavily_max_results(),
    )
    broad_status = broad_result.source_statuses[0] if broad_result.source_statuses else {}
    if broad_status.get("status") == "queried" or not result.candidates:
        return broad_result, broad_status
    return result, status


def supplier_tavily_search_items(
    query: str,
    material_hints: list[str],
    procurement_items: list[dict[str, Any]],
) -> list[dict[str, str]]:
    structured = [
        {
            "name": clean_supplier_query(item.get("name", "")),
            "context": procurement_item_search_text(item),
            "supplier_hint": clean_supplier_query(item.get("supplier_hint", "")),
        }
        for item in procurement_items
        if clean_supplier_query(item.get("name", ""))
    ]
    if structured:
        return structured[:5]
    return [
        {"name": material, "context": material, "supplier_hint": ""}
        for material in supplier_tavily_material_queries(query, material_hints)
    ]


def supplier_tavily_material_queries(query: str, material_hints: list[str]) -> list[str]:
    hints = [
        hint
        for hint in material_hints
        if hint and len(hint.split()) <= 12 and not hint.lower().startswith("http")
    ]
    if not hints:
        hints = [query]
    return list(dict.fromkeys(clean_supplier_query(hint) for hint in hints if clean_supplier_query(hint)))[:5]


def supplier_tavily_query(item: dict[str, str] | str, *, fallback_mode: str = "trusted_sites") -> str:
    if isinstance(item, str):
        name = item
        context = item
        supplier_hint = ""
    else:
        name = item.get("name", "")
        context = item.get("context", name)
        supplier_hint = item.get("supplier_hint", "")
    if fallback_mode == "broad":
        return f'"{name}" {context} catalog product price package size supplier'
    supplier_context = f'"{supplier_hint}" ' if supplier_hint else ""
    return f'({trusted_supplier_site_filter()}) {supplier_context}"{name}" {context} catalog product price package size'


def trusted_supplier_site_filter() -> str:
    return " OR ".join(
        [
            "site:thermofisher.com",
            "site:sigmaaldrich.com",
            "site:promega.com",
            "site:qiagen.com",
            "site:idtdna.com",
            "site:addgene.org",
        ]
    )


def supplier_price_from_candidate(candidate: dict[str, Any]) -> tuple[float, str, str]:
    text = " ".join(
        [
            str(candidate.get("title", "")),
            str(candidate.get("abstract_or_snippet", "")),
        ]
    )
    return extract_price_from_text(text)


def extract_price_from_text(text: str) -> tuple[float, str, str]:
    if not text:
        return 0.0, "", ""
    patterns = [
        (r"(?:US\$|USD\s?)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)", "USD"),
        (r"(?:GBP\s?|£)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)", "GBP"),
        (r"(?:EUR\s?|€)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)", "EUR"),
        (r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)", "USD"),
    ]
    for pattern, currency in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1).replace(",", "")
        try:
            value = round(float(raw), 2)
        except ValueError:
            continue
        if value <= 0:
            continue
        excerpt_start = max(0, match.start() - 24)
        excerpt_end = min(len(text), match.end() + 24)
        excerpt = text[excerpt_start:excerpt_end].strip()
        return value, currency, excerpt[:160]
    return 0.0, "", ""


def procurement_item_search_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("name", ""),
        item.get("category", ""),
        item.get("unit_size", ""),
        item.get("likely_quantity", ""),
        item.get("specification", ""),
        item.get("intended_use", ""),
    ]
    return clean_supplier_query(" ".join(str(part) for part in parts if part))


def clean_supplier_query(value: str) -> str:
    return " ".join(str(value or "").split())[:160]


def supplier_tavily_max_results() -> int:
    try:
        return max(1, min(5, int(os.environ.get("AI_SCIENTIST_TAVILY_SUPPLIER_MAX_RESULTS", "3"))))
    except ValueError:
        return 3


def supplier_from_url(url: str) -> str:
    supplier_domains = {
        "thermofisher.com": "Thermo Fisher",
        "sigmaaldrich.com": "Sigma-Aldrich",
        "promega.com": "Promega",
        "qiagen.com": "QIAGEN",
        "idtdna.com": "IDT",
        "atcc.org": "ATCC",
        "addgene.org": "Addgene",
    }
    lower = url.lower()
    for domain, supplier in supplier_domains.items():
        if domain in lower:
            return supplier
    return ""


def supplier_from_title(title: str) -> str:
    lower = title.lower()
    for marker, supplier in [
        ("thermo fisher", "Thermo Fisher"),
        ("sigma-aldrich", "Sigma-Aldrich"),
        ("merck", "Sigma-Aldrich"),
        ("promega", "Promega"),
        ("qiagen", "QIAGEN"),
        ("idt", "IDT"),
        ("atcc", "ATCC"),
        ("addgene", "Addgene"),
    ]:
        if marker in lower:
            return supplier
    return ""


def dedupe_supplier_evidence(evidence: list[SupplierEvidenceResult]) -> list[SupplierEvidenceResult]:
    deduped = []
    seen = set()
    for item in evidence:
        key = (item.supplier.lower(), item.url.lower(), item.title.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _query_search_pages(
    client: httpx.Client,
    specs: list[tuple[str, str]],
    source_type: str,
) -> SourceResult:
    statuses = []
    for source, url in specs:
        try:
            response = client.get(url, headers={"User-Agent": _user_agent()})
            if response.status_code < 400:
                statuses.append(
                    SourceStatus(
                        source=source,
                        status="queried",
                        queried_url=str(response.url),
                        message=f"{source_type} search page reachable.",
                        result_count=0,
                    )
                )
            else:
                statuses.append(
                    SourceStatus(
                        source=source,
                        status="error",
                        queried_url=str(response.url),
                        message=f"HTTP {response.status_code}",
                        result_count=0,
                    )
                )
        except Exception as exc:
            statuses.append(
                SourceStatus(
                    source=source,
                    status="error",
                    queried_url=url,
                    message=str(exc),
                    result_count=0,
                )
            )
    return SourceResult(source_statuses=statuses)


def _query_scientific_standards(
    client: httpx.Client,
    query: str,
    parsed: ParsedHypothesis,
) -> SourceResult:
    url = "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2737408/"
    response, error = _get_or_status(client, "MIQE Guidelines", url)
    if error:
        return error
    status = "queried" if response.status_code < 400 else "error"
    references = []
    if "qpcr" in query.lower() or "qPCR" in query or parsed.domain == "molecular_biology":
        references.append(
            {
                "title": "The MIQE guidelines: minimum information for publication of quantitative real-time PCR experiments",
                "authors": ["Bustin et al."],
                "year": 2009,
                "source": "NCBI PMC / MIQE Guidelines",
                "url": url,
                "relevance_reason": "Required reporting and validation standard for qPCR experiments.",
            }
        )
    return SourceResult(
        source_statuses=[
            SourceStatus(
                source="MIQE Guidelines",
                status=status,
                queried_url=url,
                message="qPCR scientific standard page checked.",
                result_count=len(references),
            )
        ],
        references=references,
    )


def _single_status(source: str, status: str, queried_url: str, message: str) -> SourceResult:
    return SourceResult(
        source_statuses=[
            SourceStatus(
                source=source,
                status=status,
                queried_url=queried_url,
                message=message,
                result_count=0,
            )
        ]
    )


def _get_or_status(
    client: httpx.Client,
    source: str,
    url: str,
    **kwargs: Any,
) -> tuple[httpx.Response, None] | tuple[None, SourceResult]:
    try:
        return client.get(url, **kwargs), None
    except httpx.HTTPError as exc:
        return None, _single_status(source, "error", url, str(exc))


def _user_agent() -> str:
    return os.environ.get(
        "AI_SCIENTIST_USER_AGENT",
        "ai-scientist-hackathon/0.1 (mailto:demo@example.com)",
    )


def _first(value: list[Any] | None) -> Any:
    if not value:
        return None
    return value[0]


def _candidate_id(ref: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(ref.get("source") or ""),
            str(ref.get("url") or ""),
            str(ref.get("title") or ""),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _doi_from_url(url: str) -> str | None:
    match = re.search(r"10\.\d{4,9}/[^\s?#]+", url)
    if not match:
        return None
    return match.group(0)


def _crossref_year(item: dict[str, Any]) -> int | None:
    parts = (item.get("issued") or {}).get("date-parts", [])
    if parts and parts[0]:
        return _safe_int(parts[0][0])
    return None


def _is_nature_protocols_item(item: dict[str, Any]) -> bool:
    journal_titles = [
        *item.get("container-title", []),
        *item.get("short-container-title", []),
    ]
    if any(title.lower() == "nature protocols" for title in journal_titles if isinstance(title, str)):
        return True
    issns = {str(issn).strip() for issn in item.get("ISSN", [])}
    return bool(issns & {"1754-2189", "1750-2799"})


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _xml_text(node: ET.Element, path: str, ns: dict[str, str]) -> str | None:
    found = node.find(path, ns)
    if found is None or found.text is None:
        return None
    return found.text.strip()
