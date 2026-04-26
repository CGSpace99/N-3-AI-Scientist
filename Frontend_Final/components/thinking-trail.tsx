'use client'

import { useState, useEffect } from 'react'

export interface TrailStep {
  label: string
  detail: string
}

interface ThinkingTrailProps {
  steps: TrailStep[]
  animate?: boolean
  accentColor?: string
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <circle cx="6" cy="6" r="5.5" stroke="currentColor" strokeWidth="1" fill="none" />
      <path d="M3.5 6l1.8 1.8 3.2-3.6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function SpinnerIcon({ color }: { color: string }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" style={{ animation: 'spin 1s linear infinite' }}>
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
      <circle cx="6" cy="6" r="4.5" stroke={color} strokeWidth="1" fill="none" strokeDasharray="14 8" />
    </svg>
  )
}

export function ThinkingTrail({ steps, animate = true, accentColor = '#993C1D' }: ThinkingTrailProps) {
  const [visibleCount, setVisibleCount] = useState(animate ? 0 : steps.length)
  const [expanded, setExpanded] = useState<number | null>(null)

  useEffect(() => {
    if (!animate) return
    let i = 0
    const intervals: ReturnType<typeof setTimeout>[] = []

    const tick = () => {
      i++
      setVisibleCount(i)
      if (i < steps.length) {
        const delay = 850 + Math.random() * 300
        intervals.push(setTimeout(tick, delay))
      }
    }

    intervals.push(setTimeout(tick, 300))
    return () => intervals.forEach(clearTimeout)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const shown = steps.slice(0, visibleCount)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {shown.map((step, i) => {
        const isLast = animate && i === visibleCount - 1
        const isOpen = expanded === i
        return (
          <div key={i}>
            <button
              onClick={() => setExpanded(isOpen ? null : i)}
              className="flex items-center gap-1.5 py-0.5 text-left group"
            >
              <span style={{ color: isLast ? accentColor : '#1D9E75', flexShrink: 0 }}>
                {isLast ? <SpinnerIcon color={accentColor} /> : <CheckIcon />}
              </span>
              <span style={{
                fontFamily: 'var(--font-ibm-plex-mono)',
                fontSize: 10,
                color: isLast ? accentColor : '#555',
                letterSpacing: '0.02em',
              }}>
                {step.label}
              </span>
              {!isLast && (
                <svg width="8" height="8" viewBox="0 0 8 8" style={{ color: '#bbb', transition: 'transform 0.15s', transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)', flexShrink: 0 }}>
                  <path d="M1.5 3L4 5.5 6.5 3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" fill="none" />
                </svg>
              )}
            </button>

            {isOpen && !isLast && (
              <div style={{
                marginLeft: 18,
                padding: '4px 8px',
                background: '#faf9f7',
                border: '1px solid #e8e5e0',
                borderRadius: 6,
                fontFamily: 'var(--font-dm-sans)',
                fontSize: 11,
                color: '#555',
                lineHeight: 1.5,
                marginBottom: 2,
              }}>
                {step.detail}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export type TrailSequence = TrailStep[]

export const RACHAEL_TRAILS: TrailSequence[] = [
  [
    { label: 'Ran keyword scan', detail: 'Extracted core concept terms from your input. Identified primary domain and secondary associations.' },
    { label: 'Queried literature database → 4 searches', detail: 'Search 1: exact phrase match. Search 2: semantic neighbours. Search 3: cited-by expansion. Search 4: negative controls in similar work.' },
    { label: 'Sources considered: hypothesis framing', detail: 'Quick scan on how others have stated similar hypotheses and whether your framing is operationally testable.' },
    { label: 'Checked novelty against 4 criteria', detail: 'Prior replication attempts, recency of closest match, methodological overlap, and theoretical gap size.' },
  ],
  [
    { label: 'Scanned for control design precedents', detail: 'Looked for papers reporting positive and negative control strategies for this class of experiment.' },
    { label: 'Assessed confound exposure', detail: 'Flagged likely confounds based on experimental type. Checked which have been controlled for in the literature.' },
    { label: 'Sources considered: control methodology', detail: 'Re-reading prior source set for control-specific guidance.' },
  ],
  [
    { label: 'Extracted measurable outcome claims', detail: 'Identified quantifiable predictions from your hypothesis statement.' },
    { label: 'Cross-referenced with null hypothesis convention', detail: 'Checked whether the hypothesis is stated in a form that permits rejection.' },
  ],
  [
    { label: 'Read context', detail: 'Referenced prior exchanges for consistency.' },
    { label: 'Sources considered: domain depth', detail: 'Pulling adjacent methodological literature to test your framing.' },
  ],
  [
    { label: 'Synthesised full exchange', detail: 'Compiled all stated assumptions, controls, and hypothesis claims into a coherent picture.' },
    { label: 'Ran final plausibility check', detail: 'Compared against known failure modes for this class of experiment.' },
  ],
]
