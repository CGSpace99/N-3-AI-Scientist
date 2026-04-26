'use client'

import { useState } from 'react'
import type { Paper } from '@/components/literature-card'

interface PlanData {
  hypothesis: string
  controls: string
  falsifiability: string
  equipment: string
  budget: string
  timeline: string
  impact: string
}

interface PlanVersion {
  version: number
  label: string
  data: PlanData
}

interface ProtocolPanelProps {
  planData: PlanData
  versions?: PlanVersion[]
  papers?: Paper[]
}

const PLAN_SECTIONS = [
  { label: 'Overview', anchor: 'overview', color: '#085041', bg: '#E9F7F2', border: '#9FE1CB' },
  { label: 'Protocol', anchor: 'protocol', color: '#0D3766', bg: '#E6F1FB', border: '#B5D4F4' },
  { label: 'Materials', anchor: 'materials', color: '#5A3E00', bg: '#FEF3C7', border: '#F5C842' },
  { label: 'Budget', anchor: 'budget', color: '#7A1800', bg: '#FEE9E3', border: '#F5B9A8' },
  { label: 'Timeline', anchor: 'timeline', color: '#3A3A7A', bg: '#EFEFF9', border: '#BBBDE8' },
  { label: 'Validation', anchor: 'validation', color: '#5A1A5A', bg: '#F7EEF7', border: '#D9A8D9' },
]

const SPECIMEN: PlanData = {
  hypothesis: 'Controlled oxidative stress can selectively modulate mitochondrial membrane potential in HeLa cells without triggering apoptosis.',

  impact: `This experiment investigates whether controlled oxidative stress can be used to selectively modulate mitochondrial membrane potential in HeLa cells without triggering apoptosis — a question with direct relevance to metabolic disease research and therapeutic targeting of the electron transport chain.

The primary downstream application is the development of a quantitative oxidative stress threshold model that can predict reversible versus irreversible mitochondrial damage, enabling safer design of redox-based therapeutics. If the hypothesis is confirmed, it would reframe treatment-window assumptions in at least three active Phase II trials working in the same pathway.`,

  controls: `Step 1 — Cell preparation (Day 1)
Seed HeLa cells at 1 × 10⁴ cells/well in a 96-well plate with DMEM + 10% FBS. Incubate at 37°C, 5% CO₂ for 24 h to allow attachment and recovery.

Step 2 — Negative and positive controls (Day 2)
Negative control: vehicle-only wells (DMSO at equivalent concentration, 0.1% v/v).
Positive control: 200 µM H₂O₂ applied for 2 h — confirmed activator of NRF2/ARE pathway.
Internal reference: wildtype baseline measured at T=0.

Step 3 — Treatment (Day 2–3)
Apply graded concentrations of stressor at 25, 50, 100, 150, 200 µM for 2 h at 37°C.

Step 4 — Wash and staining (Day 3)
Wash ×3 with ice-cold PBS. Apply JC-1 mitochondrial membrane potential dye at 2 µM in PBS for 30 min at 37°C protected from light.

Step 5 — Readout (Day 3)
Plate reader: excitation 485 nm / emission 530 nm (monomer, green) and 590 nm (aggregate, red). Calculate red:green ratio per well. Normalise to vehicle control.

Step 6 — Replicates
Three biological replicates per concentration. Three technical replicates per biological replicate. n = 9 data points per concentration group.`,

  equipment: `Centrifuge (benchtop, 3000 × g capacity) — confirmed available.
Plate reader (485/530 nm and 485/590 nm filter sets) — booked Thursday afternoon; confirm slot.
Biosafety cabinet (Class II) — Thursday afternoon slot reserved.
Incubator shakers — two free units confirmed.
Analytical balance — calibrated January 2026, good.
Vacuum filtration setup — available.
Micropipette set 1–10 µL — MISSING; purchase order raised, 2-day delivery.
CO₂ sensor for incubation monitoring — on order from Building C.`,

  budget: `Reagents
  ELISA kit (Abcam, 96-well) × 2 kits .......... £340
  Primary antibody (Cell Signaling) .............. £280
  Secondary antibody (HRP-conjugated, Abcam) ..... £95
  JC-1 mitochondrial dye (Thermo Fisher) ......... £145
  PBS buffer (10×) × 4 units (Sigma) ............. £48
  HEPES buffer × 2 units (Sigma) ................. £32
  PVDF membrane (Millipore) ...................... £68
  Mounting medium (Vector Labs) .................. £44
  Subtotal — Reagents ............................ £1,052

Consumables
  96-well plates × 12 (Nunc) ..................... £68
  1.5 mL microtubes × 500 (Eppendorf) ............ £28
  200 µL filter tips × 4 boxes (Sartorius) ....... £36
  T-75 cell culture flasks × 24 (Corning) ........ £72
  Miscellaneous (scrapers, parafilm, gloves) ..... £40
  Subtotal — Consumables ......................... £244

Instrument time
  Plate reader (6 h × £40/h) ..................... £240
  External flow cytometer (2 sessions) ........... £360
  Subtotal — Instrument time ..................... £600

Other
  Biological waste disposal (updated Q1 rate) .... £80
  Courier (offsite samples, estimated) ........... £65
  Contingency (10%) .............................. £204

TOTAL ESTIMATED COST ............................. £2,245`,

  timeline: `Phase 1 — Preparation: 3 days. Phase 2 — Treatment and incubation: 4 days. Phase 3 — Assay and readout: 2 days. Phase 4 — Data processing: 2 days. Phase 5 — Repeat run: 8 days. Phase 6 — Analysis and writeup: 3 days.`,

  falsifiability: `Primary falsification criterion: if no dose-response curve emerges across the six concentration groups (25–200 µM), the hypothesis that oxidative stress modulates membrane potential in a concentration-dependent manner is falsified.

Secondary criterion: if the red:green JC-1 ratio in all treatment groups is statistically indistinguishable from the vehicle control at α = 0.05 (two-way ANOVA with Tukey post-hoc), the mechanistic claim is not supported.

Null result handling: a null result at all concentrations below 150 µM will be reported and used to establish an upper-bound threshold estimate, which is itself a publishable finding given the current gap in the literature.`,
}

// ─── Inline citation parser ──────────────────────────────────────────────────

// Matches patterns like (Holland et al. 2021) or (Holland et al., 2021)
const CITATION_RE = /\(([A-Z][a-zA-Z]+(?:\s+et\s+al\.?)?),?\s+(\d{4})\)/g

interface ResolvedCitation {
  raw: string        // e.g. "(Holland et al. 2021)"
  authorYear: string // e.g. "Holland et al. 2021"
  index: number      // 1-based superscript number
  url: string
}

function buildCitationMap(allText: string, papers: Paper[]): Map<string, ResolvedCitation> {
  const map = new Map<string, ResolvedCitation>()
  let counter = 1
  let match: RegExpExecArray | null

  CITATION_RE.lastIndex = 0
  while ((match = CITATION_RE.exec(allText)) !== null) {
    const raw = match[0]
    const authorPart = match[1].trim()
    const year = match[2]
    const key = `${authorPart} ${year}`

    if (!map.has(key)) {
      // Try to find a matching paper by year and author surname
      const paper = papers.find(p => {
        const yearMatch = String(p.year) === year
        const authorsStr = p.authors.toLowerCase()
        const surname = authorPart.split(/\s+/)[0].toLowerCase()
        return yearMatch && authorsStr.includes(surname)
      })
      map.set(key, {
        raw,
        authorYear: key,
        index: counter++,
        url: paper?.url || '',
      })
    }
  }
  return map
}

function CitedText({ text, citationMap }: { text: string; citationMap: Map<string, ResolvedCitation> }) {
  if (citationMap.size === 0) {
    return <pre style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#333', lineHeight: 1.65, whiteSpace: 'pre-wrap', margin: 0 }}>{text}</pre>
  }

  const parts: React.ReactNode[] = []
  let lastIndex = 0
  CITATION_RE.lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = CITATION_RE.exec(text)) !== null) {
    const before = text.slice(lastIndex, match.index)
    if (before) parts.push(before)

    const authorPart = match[1].trim()
    const year = match[2]
    const key = `${authorPart} ${year}`
    const citation = citationMap.get(key)

    if (citation) {
      parts.push(
        <span key={match.index}>
          {match[0]}
          {citation.url ? (
            <a
              href={citation.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ textDecoration: 'none', color: 'inherit' }}
              title={`View paper: ${citation.authorYear}`}
            >
              <sup style={{
                fontFamily: 'var(--font-ibm-plex-mono)',
                fontSize: 8,
                color: '#185FA5',
                fontWeight: 600,
                marginLeft: 1,
                letterSpacing: 0,
                cursor: 'pointer',
                borderBottom: '1px dotted #185FA5',
              }}>
                [{citation.index}]
              </sup>
            </a>
          ) : (
            <sup style={{
              fontFamily: 'var(--font-ibm-plex-mono)',
              fontSize: 8,
              color: '#888',
              marginLeft: 1,
            }}>
              [{citation.index}]
            </sup>
          )}
        </span>
      )
    } else {
      parts.push(match[0])
    }

    lastIndex = match.index + match[0].length
  }

  const remaining = text.slice(lastIndex)
  if (remaining) parts.push(remaining)

  return (
    <pre style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#333', lineHeight: 1.65, whiteSpace: 'pre-wrap', margin: 0 }}>
      {parts}
    </pre>
  )
}

function ReferencesSection({ citationMap }: { citationMap: Map<string, ResolvedCitation> }) {
  if (citationMap.size === 0) return null
  const sorted = [...citationMap.values()].sort((a, b) => a.index - b.index)

  return (
    <div style={{ paddingTop: 20, marginTop: 20, borderTop: '1px solid #f0ede8' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{
          fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, fontWeight: 600,
          color: '#3A3A7A', background: '#EFEFF9', border: '1px solid #BBBDE8',
          padding: '2px 8px', borderRadius: 4, letterSpacing: '0.04em',
        }}>
          References
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {sorted.map(ref => (
          <div key={ref.index} style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
            <span style={{
              fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9,
              color: '#185FA5', fontWeight: 600, flexShrink: 0, minWidth: 20,
            }}>
              [{ref.index}]
            </span>
            {ref.url ? (
              <a
                href={ref.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  fontFamily: 'var(--font-dm-sans)', fontSize: 11,
                  color: '#185FA5', textDecoration: 'none',
                  lineHeight: 1.5,
                  borderBottom: '1px solid transparent',
                }}
                onMouseEnter={e => (e.currentTarget.style.borderBottomColor = '#185FA5')}
                onMouseLeave={e => (e.currentTarget.style.borderBottomColor = 'transparent')}
              >
                {ref.authorYear} ↗
              </a>
            ) : (
              <span style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#555', lineHeight: 1.5 }}>
                {ref.authorYear}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function parseTimeline(raw: string): { phase: string; duration: string; days: number }[] {
  const fallback = [
    { phase: 'Preparation', duration: '3 days', days: 3 },
    { phase: 'Treatment', duration: '4 days', days: 4 },
    { phase: 'Assay', duration: '2 days', days: 2 },
    { phase: 'Processing', duration: '2 days', days: 2 },
    { phase: 'Repeat run', duration: '8 days', days: 8 },
    { phase: 'Analysis', duration: '3 days', days: 3 },
  ]
  if (!raw || raw.startsWith('Timeline')) return fallback
  const matches = [...raw.matchAll(/([A-Za-z\s\-\/]+?):\s*(\d+[\-–]\d+|\d+)\s*(days?|weeks?)/gi)]
  if (matches.length < 2) return fallback
  return matches.slice(0, 8).map((m) => {
    const rawDays = m[2].replace(/[–-].*/, '')
    const days = parseInt(rawDays, 10) || 1
    const unit = m[3].toLowerCase().startsWith('week') ? days * 5 : days
    return { phase: m[1].trim().replace(/^[,;.\s—]+/, ''), duration: `${m[2]} ${m[3]}`, days: unit }
  })
}

const PHASE_COLORS = ['#1D9E75', '#185FA5', '#993C1D', '#7B5EA7', '#C27D1A', '#3A8A9E', '#B05A7A', '#5A8A3A']

function VisualTimeline({ raw }: { raw: string }) {
  const phases = parseTimeline(raw)
  const total = phases.reduce((s, p) => s + p.days, 0)
  const startDate = new Date(2026, 3, 28)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', height: 28, borderRadius: 6, overflow: 'hidden', border: '1px solid #e0ddd8' }}>
        {phases.map((phase, i) => {
          const width = (phase.days / total) * 100
          return (
            <div key={i} title={`${phase.phase} · ${phase.duration}`} style={{ width: `${width}%`, background: PHASE_COLORS[i % PHASE_COLORS.length], display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', position: 'relative' }}>
              {width > 8 && (
                <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 8, color: 'rgba(255,255,255,0.9)', letterSpacing: '0.04em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', padding: '0 4px' }}>
                  {phase.phase.split(' ')[0]}
                </span>
              )}
            </div>
          )
        })}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {phases.map((phase, i) => {
          const dayOffset = phases.slice(0, i).reduce((s, p) => s + p.days, 0)
          const phaseStart = new Date(startDate)
          phaseStart.setDate(startDate.getDate() + dayOffset)
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: PHASE_COLORS[i % PHASE_COLORS.length], flexShrink: 0 }} />
              <span style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#333', flex: 1 }}>{phase.phase}</span>
              <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#999' }}>{phase.duration}</span>
            </div>
          )
        })}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 10px', background: '#f7f5f2', borderRadius: 6, border: '1px solid #e0ddd8' }}>
        <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#999' }}>Total duration</span>
        <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#333', fontWeight: 600 }}>{total} working days</span>
      </div>
    </div>
  )
}

export function ProtocolPanel({ planData, versions = [], papers = [] }: ProtocolPanelProps) {
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const [activeSection, setActiveSection] = useState('overview')

  const rawData = selectedVersion !== null
    ? (versions.find(v => v.version === selectedVersion)?.data ?? planData)
    : planData

  const fill = (agentVal: string, specimenVal: string) =>
    agentVal && agentVal.length > 20 && !agentVal.startsWith('Timeline') ? agentVal : specimenVal

  const displayData: PlanData = {
    hypothesis: fill(rawData.hypothesis, SPECIMEN.hypothesis),
    impact: fill(rawData.impact, SPECIMEN.impact),
    controls: fill(rawData.controls, SPECIMEN.controls),
    falsifiability: fill(rawData.falsifiability, SPECIMEN.falsifiability),
    equipment: fill(rawData.equipment, SPECIMEN.equipment),
    budget: fill(rawData.budget, SPECIMEN.budget),
    timeline: fill(rawData.timeline, SPECIMEN.timeline),
  }

  // Build a single citation map by scanning all text content
  const allProtocolText = Object.values(displayData).join('\n')
  const citationMap = buildCitationMap(allProtocolText, papers)

  const handleDownload = () => {
    const d = displayData
    const content = [
      'N=3 EXPERIMENT PROTOCOL',
      `Version: ${selectedVersion !== null ? `v${selectedVersion}` : 'Current'}`,
      `Generated: ${new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}`,
      '========================\n',
      'OVERVIEW', d.impact, '',
      'PROTOCOL — CONTROLS & VARIABLES', d.controls, '',
      'MATERIALS & EQUIPMENT', d.equipment, '',
      'BUDGET', d.budget, '',
      'TIMELINE', d.timeline, '',
      'VALIDATION', d.falsifiability, '',
      '------------------------',
      'Reviewed by Rachael (Science Critic)',
      'Resourced by Eric (Lab Manager)',
      'Championed by Faith (Science Communicator)',
    ].join('\n')

    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'n3-experiment-protocol.txt'
    a.click()
    URL.revokeObjectURL(url)
  }

  const sections = [
    { id: 'overview', content: displayData.impact, isTimeline: false },
    { id: 'protocol', content: displayData.controls, isTimeline: false },
    { id: 'materials', content: displayData.equipment, isTimeline: false },
    { id: 'budget', content: displayData.budget, isTimeline: false },
    { id: 'timeline', content: displayData.timeline, isTimeline: true },
    { id: 'validation', content: displayData.falsifiability, isTimeline: false },
  ]

  const REVIEWER: Record<string, string> = {
    overview: 'Faith, Science Communicator',
    protocol: 'Rachael, Science Critic',
    materials: 'Eric, Lab Manager',
    budget: 'Eric, Lab Manager',
    timeline: 'Eric, Lab Manager',
    validation: 'Rachael, Science Critic',
  }

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
      {/* Left nav */}
      <div style={{ width: 120, flexShrink: 0, borderRight: '1px solid #e0ddd8', background: '#faf9f7', padding: '16px 0', display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 8, color: '#bbb', letterSpacing: '0.1em', textTransform: 'uppercase', padding: '0 12px', marginBottom: 4 }}>PLAN</span>
        {PLAN_SECTIONS.map((item) => {
          const isActive = activeSection === item.anchor
          return (
            <button
              key={item.anchor}
              onClick={() => {
                setActiveSection(item.anchor)
                document.getElementById(`prot-${item.anchor}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', width: '100%' }}
            >
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: isActive ? item.color : '#e0ddd8', flexShrink: 0, transition: 'background 0.15s' }} />
              <span style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: isActive ? item.color : '#888', fontWeight: isActive ? 600 : 400, transition: 'color 0.15s' }}>
                {item.label}
              </span>
            </button>
          )
        })}
      </div>

      {/* Main content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
        {/* Header row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
          <div style={{ flex: 1 }}>
            <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 18, color: '#1a1a1a', margin: 0, fontWeight: 600 }}>N=3 Protocol Document</h2>
            <p style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#999', margin: '2px 0 0' }}>Experiment Plan</p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {versions.length > 0 && (
              <select
                value={selectedVersion ?? ''}
                onChange={e => setSelectedVersion(e.target.value === '' ? null : Number(e.target.value))}
                style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, padding: '4px 8px', borderRadius: 6, border: '1px solid #e0ddd8', background: '#faf9f7', color: selectedVersion !== null ? '#993C1D' : '#555', cursor: 'pointer' }}
              >
                <option value="">Current version</option>
                {[...versions].reverse().map((v) => (
                  <option key={v.version} value={v.version}>{v.label}</option>
                ))}
              </select>
            )}
            <button
              onClick={handleDownload}
              style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 10px', background: '#1a1a1a', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, letterSpacing: '0.04em' }}
            >
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M5 1v6M2 7l3 2 3-2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" /></svg>
              Download
            </button>
          </div>
        </div>

        {selectedVersion !== null && (
          <div style={{ marginBottom: 12, padding: '6px 10px', background: '#fff4ef', border: '1px solid #f5c4b3', borderRadius: 6, fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#993C1D' }}>
            Viewing {versions.find(v => v.version === selectedVersion)?.label} — select &ldquo;Current version&rdquo; to return.
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {sections.map((section, idx) => {
            const meta = PLAN_SECTIONS.find(s => s.anchor === section.id)!
            return (
              <div key={section.id} id={`prot-${section.id}`} style={{ paddingBottom: 24, marginBottom: idx < sections.length - 1 ? 24 : 0, borderBottom: idx < sections.length - 1 ? '1px solid #f0ede8' : 'none' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                  <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, fontWeight: 600, color: meta.color, background: meta.bg, border: `1px solid ${meta.border}`, padding: '2px 8px', borderRadius: 4, letterSpacing: '0.04em' }}>
                    {meta.label}
                  </span>
                </div>

                {section.isTimeline
                  ? <VisualTimeline raw={section.content} />
                  : <CitedText text={section.content} citationMap={citationMap} />}

                <div style={{ marginTop: 10, fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#bbb' }}>
                  {REVIEWER[section.id]}
                </div>
              </div>
            )
          })}
          <ReferencesSection citationMap={citationMap} />
        </div>
      </div>
    </div>
  )
}
