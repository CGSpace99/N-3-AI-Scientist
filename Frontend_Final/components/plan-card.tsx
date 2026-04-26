'use client'

import type { Paper } from '@/components/literature-card'

interface PlanCardProps {
  hypothesis: string
  controls: string
  falsifiability: string
  equipment: string
  budget: string
  timeline: string
  impact: string
  papers?: Paper[]
}

// ─── Inline citation superscripts ────────────────────────────────────────────

const CITATION_RE = /\(([A-Z][a-zA-Z]+(?:\s+et\s+al\.?)?),?\s+(\d{4})\)/g

interface ResolvedRef {
  authorYear: string
  index: number
  url: string
}

function buildRefs(allText: string, papers: Paper[]): Map<string, ResolvedRef> {
  const map = new Map<string, ResolvedRef>()
  let counter = 1
  CITATION_RE.lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = CITATION_RE.exec(allText)) !== null) {
    const author = match[1].trim()
    const year = match[2]
    const key = `${author} ${year}`
    if (!map.has(key)) {
      const paper = papers.find(p => {
        const yearMatch = String(p.year) === year
        const surname = author.split(/\s+/)[0].toLowerCase()
        return yearMatch && p.authors.toLowerCase().includes(surname)
      })
      map.set(key, { authorYear: key, index: counter++, url: paper?.url || '' })
    }
  }
  return map
}

function CitedLine({ text, refs }: { text: string; refs: Map<string, ResolvedRef> }) {
  if (refs.size === 0) return <>{text}</>
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  CITATION_RE.lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = CITATION_RE.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index))
    const key = `${match[1].trim()} ${match[2]}`
    const ref = refs.get(key)
    parts.push(
      <span key={match.index}>
        {match[0]}
        {ref && (
          ref.url
            ? <a href={ref.url} target="_blank" rel="noopener noreferrer" title={ref.authorYear} style={{ textDecoration: 'none', color: 'inherit' }}>
                <sup style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 8, color: '#185FA5', fontWeight: 600, marginLeft: 1, cursor: 'pointer', borderBottom: '1px dotted #185FA5' }}>[{ref.index}]</sup>
              </a>
            : <sup style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 8, color: '#aaa', marginLeft: 1 }}>[{ref.index}]</sup>
        )}
      </span>
    )
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex))
  return <>{parts}</>
}

// ─── Rich text renderer: paragraphs + bullet points ──────────────────────────

function RichText({ text, refs }: { text: string; refs: Map<string, ResolvedRef> }) {
  const elements: React.ReactNode[] = []

  // Split on double newlines to get logical blocks
  const blocks = text.trim().split(/\n\n+/)

  blocks.forEach((block, blockIdx) => {
    const lines = block.split('\n').map(l => l.trimEnd())
    const firstLine = lines[0].trim()

    // Numbered step block: "1. Title\nDescription text"
    const numberedMatch = firstLine.match(/^(\d+)\.\s+(.+)/)
    if (numberedMatch) {
      const stepNum = numberedMatch[1]
      const stepTitle = numberedMatch[2]
      const rest = lines.slice(1).join(' ').trim()
      elements.push(
        <div key={`step-${blockIdx}`} style={{ display: 'flex', gap: 10, padding: '6px 0', borderBottom: blockIdx < blocks.length - 1 ? '1px solid #f5f3f0' : 'none' }}>
          <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, fontWeight: 600, color: '#fff', background: '#2a2a2a', borderRadius: 4, padding: '1px 6px', flexShrink: 0, alignSelf: 'flex-start', marginTop: 2 }}>
            {stepNum}
          </span>
          <div>
            <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, fontWeight: 600, color: '#1a1a1a', lineHeight: 1.5 }}>
              <CitedLine text={stepTitle} refs={refs} />
            </div>
            {rest && (
              <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#555', lineHeight: 1.65, marginTop: 2 }}>
                <CitedLine text={rest} refs={refs} />
              </div>
            )}
          </div>
        </div>
      )
      return
    }

    // Dash bullet block: "- Item\n  Sub: detail"
    if (firstLine.startsWith('- ')) {
      const bulletText = firstLine.slice(2).trim()
      const subLines = lines.slice(1).filter(l => l.trim())
      elements.push(
        <div key={`bullet-${blockIdx}`} style={{ display: 'flex', gap: 8, padding: '4px 0' }}>
          <span style={{ color: '#aaa', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, flexShrink: 0, marginTop: 3 }}>—</span>
          <div>
            <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#1a1a1a', lineHeight: 1.6 }}>
              <CitedLine text={bulletText} refs={refs} />
            </div>
            {subLines.length > 0 && (
              <div style={{ marginTop: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
                {subLines.map((sub, si) => {
                  const colonIdx = sub.indexOf(':')
                  if (colonIdx > -1) {
                    const label = sub.slice(0, colonIdx).trim()
                    const value = sub.slice(colonIdx + 1).trim()
                    return (
                      <div key={si} style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#666', lineHeight: 1.55 }}>
                        <span style={{ fontWeight: 600, color: '#888' }}>{label}: </span>
                        <CitedLine text={value} refs={refs} />
                      </div>
                    )
                  }
                  return (
                    <div key={si} style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#666', lineHeight: 1.55 }}>
                      <CitedLine text={sub.trim()} refs={refs} />
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )
      return
    }

    // Plain heading (single short line with no punctuation, e.g. "Risks")
    if (lines.length === 1 && firstLine.length < 40 && !firstLine.includes('.') && !firstLine.includes(':')) {
      elements.push(
        <div key={`heading-${blockIdx}`} style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, fontWeight: 600, color: '#999', letterSpacing: '0.08em', textTransform: 'uppercase', paddingTop: blockIdx > 0 ? 10 : 0, paddingBottom: 4 }}>
          {firstLine}
        </div>
      )
      return
    }

    // Default paragraph
    const fullText = lines.join(' ').trim()
    elements.push(
      <p key={`p-${blockIdx}`} style={{ margin: blockIdx === 0 ? 0 : '6px 0 0', fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#2a2a2a', lineHeight: 1.65 }}>
        <CitedLine text={fullText} refs={refs} />
      </p>
    )
  })

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>{elements}</div>
}

// ─── Section config ───────────────────────────────────────────────────────────

const SECTIONS = [
  { code: 'OVW', label: 'Overview & Impact',   key: 'impact',         color: '#085041', bg: '#E9F7F2', border: '#9FE1CB',  reviewer: 'Faith, Experiment Planner' },
  { code: 'HYP', label: 'Hypothesis',          key: 'hypothesis',     color: '#993C1D', bg: '#fff4ef', border: '#f5c4b3',  reviewer: 'Rachael, Scientific Rigour' },
  { code: 'CTR', label: 'Controls & Variables',key: 'controls',       color: '#0D3766', bg: '#E6F1FB', border: '#B5D4F4',  reviewer: 'Rachael, Scientific Rigour' },
  { code: 'FAL', label: 'Falsifiability',      key: 'falsifiability', color: '#5A1A5A', bg: '#F7EEF7', border: '#D9A8D9',  reviewer: 'Rachael, Scientific Rigour' },
  { code: 'EQP', label: 'Equipment',           key: 'equipment',      color: '#5A3E00', bg: '#FEF3C7', border: '#F5C842',  reviewer: 'Eric, Lab Logistics' },
  { code: 'BGT', label: 'Budget & Timeline',   key: 'budgetTimeline', color: '#3A3A7A', bg: '#EFEFF9', border: '#BBBDE8',  reviewer: 'Eric, Lab Logistics' },
] as const

type SectionKey = typeof SECTIONS[number]['key']

export function PlanCard({
  hypothesis, controls, falsifiability, equipment, budget, timeline, impact, papers = [],
}: PlanCardProps) {
  const data: Record<SectionKey, string> = {
    impact,
    hypothesis,
    controls,
    falsifiability,
    equipment,
    budgetTimeline: budget && timeline ? `${budget}\n\n${timeline}` : budget || timeline,
  }

  const allText = Object.values(data).join('\n')
  const refs = buildRefs(allText, papers)
  const sortedRefs = [...refs.values()].sort((a, b) => a.index - b.index)

  return (
    <div style={{
      background: '#ffffff',
      border: '1px solid #e0ddd8',
      borderRadius: 12,
      overflow: 'hidden',
      width: '100%',
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 18px',
        borderBottom: '1px solid #e0ddd8',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        background: '#faf9f7',
      }}>
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
          <path d="M2 3h10M2 7h10M2 11h6" stroke="#993C1D" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
        <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, fontWeight: 600, color: '#1a1a1a', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          N=3 Experiment Plan
        </span>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#999', padding: '2px 6px', border: '1px solid #e0ddd8', borderRadius: 4, background: '#fff' }}>
          Verified by 3 experts
        </span>
      </div>

      {/* Sections */}
      <div style={{ padding: '0 18px' }}>
        {SECTIONS.map((s, idx) => {
          const value = data[s.key]
          if (!value) return null
          return (
            <div
              key={s.code}
              style={{
                paddingTop: 16,
                paddingBottom: 16,
                borderBottom: idx < SECTIONS.length - 1 ? '1px solid #f0ede8' : 'none',
              }}
            >
              {/* Section label */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <span style={{
                  fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 8, fontWeight: 600,
                  color: s.color, background: s.bg, border: `1px solid ${s.border}`,
                  padding: '2px 6px', borderRadius: 4, letterSpacing: '0.06em', textTransform: 'uppercase',
                }}>
                  {s.code}
                </span>
                <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#888', letterSpacing: '0.04em' }}>
                  {s.label}
                </span>
              </div>

              {/* Rich content */}
              <RichText text={value} refs={refs} />

              {/* Reviewer attribution */}
              <div style={{ marginTop: 8, fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#ccc' }}>
                {s.reviewer}
              </div>
            </div>
          )
        })}
      </div>

      {/* References */}
      {sortedRefs.length > 0 && (
        <div style={{ padding: '12px 18px', borderTop: '1px solid #f0ede8', display: 'flex', flexDirection: 'column', gap: 5 }}>
          <span style={{
            fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 8, fontWeight: 600, color: '#3A3A7A',
            background: '#EFEFF9', border: '1px solid #BBBDE8', padding: '2px 7px', borderRadius: 4,
            letterSpacing: '0.04em', alignSelf: 'flex-start', marginBottom: 4,
          }}>References</span>
          {sortedRefs.map(ref => (
            <div key={ref.index} style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
              <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#185FA5', fontWeight: 600, flexShrink: 0, minWidth: 18 }}>
                [{ref.index}]
              </span>
              {ref.url
                ? <a href={ref.url} target="_blank" rel="noopener noreferrer"
                    style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#185FA5', textDecoration: 'none', lineHeight: 1.5, borderBottom: '1px solid transparent' }}
                    onMouseEnter={e => (e.currentTarget.style.borderBottomColor = '#185FA5')}
                    onMouseLeave={e => (e.currentTarget.style.borderBottomColor = 'transparent')}>
                    {ref.authorYear} ↗
                  </a>
                : <span style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#888' }}>{ref.authorYear}</span>
              }
            </div>
          ))}
        </div>
      )}

      {/* Footer */}
      <div style={{ padding: '8px 18px', borderTop: '1px solid #e0ddd8', background: '#faf9f7', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#aaa' }}>
          Reviewed by Rachael · Resourced by Eric · Championed by Faith
        </span>
        <div style={{ display: 'flex', gap: 4 }}>
          {['#993C1D', '#185FA5', '#085041'].map(c => (
            <div key={c} style={{ width: 6, height: 6, borderRadius: '50%', background: c }} />
          ))}
        </div>
      </div>
    </div>
  )
}
