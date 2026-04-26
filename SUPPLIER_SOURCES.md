# Supplier Evidence Sources

The Materials & Budget stage uses supplier evidence conservatively. It does not treat a
reachable supplier search page as verified product availability or live pricing.

## Evidence Modes

- `api_result`: Structured result from a supplier or catalog API.
- `catalog_page`: Supplier catalog or product page evidence.
- `protocol_page`: Supplier protocol page evidence.
- `application_note`: Supplier technical note or application note evidence.
- `search_page_reachable`: Search page was reachable, but no product availability or price was verified.

## Supplier Support

| Supplier | Current mode | Notes |
| --- | --- | --- |
| Addgene | `api_result` when `ADDGENE_API_TOKEN` is configured; otherwise web evidence | Read-only Developers Portal API requires approved access and a data license. |
| IDT | credential-gated placeholder plus web evidence | SciTools Plus is useful for oligo/primer workflows, but not a general anonymous catalog API. |
| ATCC | credential-gated placeholder plus web evidence | Genome Portal API is metadata-focused, not a general product/pricing catalog API. |
| QIAGEN | web evidence | Biomedical Knowledge Base API is not a reagent catalog/pricing API. |
| Thermo Fisher | web evidence | No public anonymous product/pricing API is assumed. |
| Sigma-Aldrich | web evidence | No public anonymous product/pricing API is assumed. |
| Promega | web evidence | No public anonymous product/pricing API is assumed. |

## Environment Variables

- `ADDGENE_API_TOKEN`: Enables Addgene catalog API requests when approved access is available.
- `ADDGENE_API_BASE_URL`: Optional override for the Addgene API base URL.
- `IDT_API_KEY`: Reserved for a future IDT SciTools Plus integration.
- `ATCC_API_TOKEN`: Reserved for a future ATCC Genome Portal integration.
- `AI_SCIENTIST_SOURCE_TIMEOUT_SECONDS`: Shared HTTP timeout for supplier/source lookups.
- `AI_SCIENTIST_SOURCE_MAX_WORKERS`: Shared concurrency limit for source adapters.

## Trust Rules

- Supplier page reachability is only evidence that a search URL loaded.
- Prices are estimates unless an API or product page explicitly provides a current price.
- Catalog numbers must come from supplier evidence, curated templates, or be flagged as requiring manual verification.
- Custom products such as IDT primers should be represented by design/specification evidence instead of fake catalog numbers.
