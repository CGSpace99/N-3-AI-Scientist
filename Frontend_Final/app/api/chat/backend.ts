// backend.ts — all dummy data, no external services required

export type ChatMessage = { role: string; text: string }

export function latestUserMessage(messages: ChatMessage[]) {
  return [...messages].reverse().find(m => m.role === 'user' && m.text?.trim())?.text?.trim() || ''
}

// ---------------------------------------------------------------------------
// Dummy data generators
// ---------------------------------------------------------------------------

export function dummyJob(question: string) {
  return {
    job_id: 'dummy-job-001',
    parsed_hypothesis: {
      intervention: 'CRISPR-Cas9 knockout of PTEN',
      system: 'murine glioblastoma organoids',
      outcome: 'increased PI3K/AKT pathway activity and proliferation',
      domain: 'molecular oncology',
    },
    structured_parse: {
      primary_field: 'Neuro-oncology',
      entities: ['PTEN', 'CRISPR-Cas9', 'PI3K', 'AKT', 'glioblastoma'],
      confidence: 0.91,
      needs_confirmation: false,
      confirmed: true,
    },
  }
}

export function dummyLiteratureQc() {
  return {
    novelty_signal: 'similar_work_exists',
    confidence: 0.87,
    summary: 'Multiple studies confirm PTEN loss drives AKT hyper-activation in GBM. Your proposed organoid model adds translational novelty.',
    top_candidates: [
      {
        title: 'PTEN loss drives PI3K/AKT-dependent resistance in glioblastoma',
        authors: ['Holland, E.C.', 'Celestino, J.', 'Dai, C.'],
        year: 2021,
        journal: 'Nature Medicine',
        doi: '10.1038/nm.2021.4401',
        embedding_similarity: 0.94,
        source: 'PubMed',
        match_classification: 'direct mechanistic match',
        url: 'https://pubmed.ncbi.nlm.nih.gov/example1',
      },
      {
        title: 'Organoid models recapitulate GBM heterogeneity for drug screening',
        authors: ['Linkous, A.', 'Balamatsias, D.', 'Snuderl, M.'],
        year: 2022,
        journal: 'Cell Reports',
        doi: '10.1016/j.celrep.2022.110211',
        embedding_similarity: 0.88,
        source: 'bioRxiv',
        match_classification: 'model system overlap',
        url: 'https://pubmed.ncbi.nlm.nih.gov/example2',
      },
      {
        title: 'CRISPR screens identify synthetic lethal partners of PTEN in brain tumours',
        authors: ['Chen, S.', 'Sanjana, N.E.', 'Zheng, K.'],
        year: 2023,
        journal: 'Molecular Cell',
        doi: '10.1016/j.molcel.2023.01.005',
        embedding_similarity: 0.82,
        source: 'PubMed',
        match_classification: 'partial mechanistic overlap',
        url: 'https://pubmed.ncbi.nlm.nih.gov/example3',
      },
      {
        title: 'AKT pathway inhibitors potentiate temozolomide in PTEN-null GBM',
        authors: ['Raizer, J.J.', 'Abrey, L.E.', 'Lassman, A.B.'],
        year: 2020,
        journal: 'Neuro-Oncology',
        doi: '10.1093/neuonc/noaa120',
        embedding_similarity: 0.78,
        source: 'PubMed',
        match_classification: 'therapeutic relevance',
        url: 'https://pubmed.ncbi.nlm.nih.gov/example4',
      },
    ],
    source_statuses: [
      { source: 'PubMed', result_count: 142, status: 'ok', message: '142 abstracts retrieved and ranked.' },
      { source: 'bioRxiv', result_count: 31, status: 'ok', message: '31 preprints scanned.' },
      { source: 'Semantic Scholar', result_count: 87, status: 'ok', message: '87 records cross-referenced.' },
    ],
  }
}

export function dummyProtocols() {
  return {
    protocol_candidates: [
      {
        title: 'CRISPR-Cas9 PTEN knockout in GBM organoids — standard electroporation',
        evidence_quality: 'high',
        source_title: 'Holland et al. 2021',
        adapted_steps: [
          'Dissociate GBM organoids to single-cell suspension using Accutase.',
          'Electroporate sgRNA:Cas9 RNP complex (1:1 molar ratio) at 1,400 V, 20 ms, 2 pulses.',
          'Recover cells for 48 h in low-attachment conditions.',
          'Confirm editing by Sanger sequencing and TIDE analysis.',
          'Expand edited organoids for 7 days before downstream assays.',
        ],
      },
      {
        title: 'Lentiviral shRNA PTEN knockdown — backup approach',
        evidence_quality: 'moderate',
        source_title: 'Linkous et al. 2022',
        adapted_steps: [
          'Clone PTEN shRNA into pLKO.1 backbone.',
          'Package lentivirus in HEK293T with psPAX2 and pMD2.G.',
          'Transduce GBM cells at MOI 5, select with puromycin 2 µg/mL.',
          'Confirm knockdown by qRT-PCR and Western blot.',
        ],
      },
    ],
  }
}

export function dummyTailoredProtocol() {
  return {
    title: 'Tailored CRISPR-Cas9 PTEN knockout in murine GBM organoids',
    steps: [
      { step_number: 1, title: 'Organoid dissociation', description: 'Accutase digest at 37°C for 12 min, triturate gently to single-cell suspension. Count with haemocytometer.', duration: '30 min' },
      { step_number: 2, title: 'RNP preparation', description: 'Pre-complex PTEN sgRNA (50 pmol) with Cas9 protein (30 pmol) at RT for 15 min in SE buffer.', duration: '15 min' },
      { step_number: 3, title: 'Electroporation', description: 'Nucleofect 5×10⁵ cells with RNP using SE kit, program CM-138.', duration: '10 min' },
      { step_number: 4, title: 'Recovery culture', description: 'Plate in ultra-low attachment 6-well with neural basal medium + B27. 37°C, 5% CO₂.', duration: '48 h' },
      { step_number: 5, title: 'Editing confirmation', description: 'Extract gDNA, PCR amplify PTEN locus, Sanger sequence, run TIDE analysis. Target ≥70% indel efficiency.', duration: '3 days' },
      { step_number: 6, title: 'Functional readout', description: 'Measure pAKT (S473), pS6K by ELISA and Western. Quantify proliferation by EdU incorporation (24 h pulse).', duration: '2 days' },
    ],
    validation_checks: ['TIDE indel efficiency ≥70%', 'pAKT fold-change ≥2× vs. control', 'EdU+ fraction ≥1.5× control'],
    warnings: ['Batch-to-batch variability in organoid size; normalise by volume.', 'Cas9 off-target activity: run Cas-OFFinder before proceeding to in vivo.'],
  }
}

export function dummyToolInventory() {
  return {
    sections: [
      {
        title: 'Core equipment',
        rows: [
          { item: 'Nucleofector 4D', qty: '1 unit', status: 'available', note: 'Lonza — booked Tue/Thu slots' },
          { item: 'Ultra-low attachment 6-well plates', qty: '24 plates', status: 'available', note: 'Corning #3471 — in stock' },
          { item: 'Confocal microscope (Zeiss LSM 980)', qty: '1 unit', status: 'limited', note: 'Core facility — 2-week booking lead time' },
          { item: 'Flow cytometer (BD FACSCanto II)', qty: '1 unit', status: 'available', note: 'Core facility — 48 h lead time' },
          { item: 'PCR thermocycler', qty: '1 unit', status: 'available', note: 'Lab-owned BioRad T100' },
        ],
      },
      {
        title: 'Reagents — CRISPR',
        rows: [
          { item: 'PTEN sgRNA (pre-designed)', qty: '2 nmol lyophilised', status: 'missing', note: 'Synthego — order time 5–7 business days', action: 'Place order immediately' },
          { item: 'SpCas9 protein (nuclease grade)', qty: '50 µg', status: 'available', note: 'Addgene #62988 — −80°C stock' },
          { item: 'SE Nucleofector Kit', qty: '1 kit (24 rxn)', status: 'limited', note: 'Lonza — 4 reactions remaining; reorder needed', action: 'Reorder SE kit' },
        ],
      },
    ],
  }
}

export function dummyMaterialsConsumables() {
  return {
    items: [
      { name: 'Neural Basal Medium', category: 'cell culture', quantity: '500 mL', supplier_hint: 'Gibco #21103049', pricing_status: 'catalogue price ~£45', needs_manual_verification: false },
      { name: 'B27 Supplement (50×)', category: 'cell culture', quantity: '10 mL', supplier_hint: 'Gibco #17504044', pricing_status: 'catalogue price ~£65', needs_manual_verification: false },
      { name: 'Accutase', category: 'dissociation', quantity: '100 mL', supplier_hint: 'Sigma #A6964', pricing_status: 'catalogue price ~£55', needs_manual_verification: false },
      { name: 'EdU (5-ethynyl-2′-deoxyuridine)', category: 'proliferation assay', quantity: '25 mg', supplier_hint: 'Invitrogen #A10044', pricing_status: 'catalogue price ~£180', needs_manual_verification: true },
      { name: 'Anti-pAKT (S473) antibody', category: 'antibody', quantity: '100 µL', supplier_hint: 'Cell Signaling #4060', pricing_status: 'catalogue price ~£350', needs_manual_verification: false },
      { name: 'Puromycin (1 mg/mL)', category: 'selection reagent', quantity: '10 mL', supplier_hint: 'Sigma #P8833', pricing_status: 'catalogue price ~£30', needs_manual_verification: false },
    ],
  }
}

export function dummyPlan(question: string) {
  return {
    title: 'PTEN knockout in GBM organoids — experiment plan',
    readiness_score: 0.78,
    protocol_steps: dummyTailoredProtocol().steps,
    validation: [
      { metric: 'PTEN editing efficiency', success_threshold: '≥70% indels by TIDE', failure_criteria: '<50% indels', controls: ['scramble sgRNA', 'wild-type organoids'] },
      { metric: 'pAKT (S473) upregulation', success_threshold: '≥2× fold increase vs. control', failure_criteria: '<1.3× change', controls: ['non-targeting sgRNA control'] },
      { metric: 'Proliferation (EdU)', success_threshold: '≥1.5× EdU+ fraction', failure_criteria: 'No significant difference at 24 h', controls: ['DMSO vehicle control'] },
    ],
    risks: [
      'Cas9 off-target edits may confound phenotype — run WGS on 3 clones.',
      'Organoid size variance: standardise by embedding volume before dissociation.',
    ],
    materials: [
      { name: 'PTEN sgRNA', supplier: 'Synthego', catalog_number: 'custom', quantity: '2 nmol' },
      { name: 'SpCas9 protein', supplier: 'Addgene', catalog_number: '#62988', quantity: '50 µg' },
      { name: 'Neural Basal Medium', supplier: 'Gibco', catalog_number: '21103049', quantity: '500 mL' },
    ],
    budget_lines: [
      { item: 'CRISPR reagents (sgRNA + Cas9)', total_cost: 420 },
      { item: 'Cell culture consumables', total_cost: 310 },
      { item: 'Antibodies and assay kits', total_cost: 580 },
      { item: 'Sequencing (Sanger, ×24)', total_cost: 192 },
    ],
    estimated_total_budget: { currency: 'GBP', amount: 1502 },
    timeline_phases: [
      { phase: 'Reagent procurement & organoid expansion', duration: '1 week' },
      { phase: 'CRISPR editing & recovery', duration: '1 week' },
      { phase: 'Validation & functional assays', duration: '2 weeks' },
      { phase: 'Data analysis & write-up', duration: '1 week' },
    ],
  }
}

// ---------------------------------------------------------------------------
// Utility functions used by route handlers
// ---------------------------------------------------------------------------

export function mapPapers(qc: ReturnType<typeof dummyLiteratureQc>) {
  return qc.top_candidates.map(item => ({
    title: item.title,
    authors: Array.isArray(item.authors) ? item.authors.join(', ') : '',
    journal: item.journal,
    year: item.year,
    similarity: Math.round(item.embedding_similarity * 100),
    doi: item.doi ? `doi:${item.doi}` : '',
    url: item.url || '',
  }))
}

export function noveltyFlag(signal: string) {
  const map: Record<string, string> = {
    not_found: 'novel_gap',
    similar_work_exists: 'similar_work_exists',
    exact_match_found: 'direct_replication',
  }
  return map[signal] || 'similar_work_exists'
}

export function parseTrail(job: ReturnType<typeof dummyJob>) {
  const parse = job.structured_parse
  return [
    { label: 'Parsed hypothesis domain', detail: `Identified as: ${parse.primary_field}` },
    { label: 'Extracted key entities', detail: parse.entities.join(', ') },
    { label: 'Assessed confidence', detail: `Parse confidence: ${Math.round(parse.confidence * 100)}%` },
  ]
}

export function sourceTrail(qc: ReturnType<typeof dummyLiteratureQc>) {
  return qc.source_statuses.map(s => ({
    label: `${s.source} — ${s.result_count} results`,
    detail: s.message,
  }))
}

type InventorySection = ReturnType<typeof dummyToolInventory>['sections'][number] & { missingNote?: string }

export function inventoryFromToolAndMaterials(toolInventory: ReturnType<typeof dummyToolInventory>, materialsConsumables?: ReturnType<typeof dummyMaterialsConsumables>) {
  const sections: InventorySection[] = [...(toolInventory?.sections || [])]
  const materialRows = (materialsConsumables?.items || []).map(item => ({
    item: item.name,
    qty: item.quantity,
    status: item.needs_manual_verification ? 'missing' : 'available',
    note: `${item.category} · ${item.supplier_hint} · ${item.pricing_status}`,
    action: item.needs_manual_verification ? 'Verify supplier, quantity, and stock' : undefined,
  }))
  if (materialRows.length) {
    sections.push({
      title: 'Materials and consumables',
      rows: materialRows,
      missingNote: 'Pricing and inventory checks are intentionally deferred.',
    })
  }
  return sections
}

export function planDataFromPlan(plan: ReturnType<typeof dummyPlan>, question: string) {
  const currency = plan.estimated_total_budget.currency

  const controlsSteps = plan.protocol_steps
    .map(s => `${s.step_number}. ${s.title} (${s.duration})\n${s.description}`)
    .join('\n\n')

  const validationBlock = plan.validation
    .map(v =>
      `- ${v.metric}\n  Pass: ${v.success_threshold}\n  Fail: ${v.failure_criteria}\n  Controls: ${v.controls.join(', ')}`
    )
    .join('\n\n')

  const risksBlock = plan.risks.map(r => `- ${r}`).join('\n')

  const equipmentBlock = plan.materials
    .map(m => `- ${m.name} — ${m.supplier} (${m.catalog_number}), ${m.quantity}`)
    .join('\n')

  const budgetBlock = [
    ...plan.budget_lines.map(b => `- ${b.item}: ${currency} ${b.total_cost.toLocaleString()}`),
    `\nTotal estimated cost: ${currency} ${plan.estimated_total_budget.amount.toLocaleString()}`,
  ].join('\n')

  const timelineBlock = plan.timeline_phases
    .map((p, i) => `${i + 1}. ${p.phase} — ${p.duration}`)
    .join('\n')

  return {
    hypothesis: question || plan.title,
    controls: controlsSteps,
    falsifiability: `${validationBlock}\n\nRisks\n\n${risksBlock}`,
    equipment: equipmentBlock,
    budget: budgetBlock,
    timeline: timelineBlock,
    impact: `${plan.title}\n\nReadiness score: ${Math.round(plan.readiness_score * 100)}%. This plan has been reviewed for scientific rigour, lab logistics, and experiment design.`,
  }
}
