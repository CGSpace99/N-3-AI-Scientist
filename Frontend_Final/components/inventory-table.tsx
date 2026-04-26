'use client'

import { useState } from 'react'
import type { Paper } from '@/components/literature-card'

export type InventoryStatus = 'available' | 'limited' | 'missing' | 'ordered'

export interface InventoryRow {
  item: string
  qty?: string
  status: InventoryStatus
  note: string
  action?: string
}

export interface InventorySection {
  title: string
  rows: InventoryRow[]
  missingNote?: string
}

interface InventoryTableProps {
  sections: InventorySection[]
  papers?: Paper[]
  onUpdate?: (sections: InventorySection[]) => void
}

const STATUS_CONFIG: Record<InventoryStatus, { label: string; dot: string; bg: string; text: string; border: string }> = {
  available: { label: 'Available', dot: '#1D9E75', bg: '#E9F7F2', text: '#085041', border: '#9FE1CB' },
  limited:   { label: 'Limited',   dot: '#D97706', bg: '#FEF3C7', text: '#7C4A00', border: '#F5C842' },
  missing:   { label: 'Missing',   dot: '#CC3010', bg: '#FEE9E3', text: '#7A1800', border: '#F5B9A8' },
  ordered:   { label: 'On order',  dot: '#185FA5', bg: '#E6F1FB', text: '#0D3766', border: '#B5D4F4' },
}
const ALL_STATUSES: InventoryStatus[] = ['available', 'limited', 'missing', 'ordered']

// Match a row item name to a paper by keyword overlap
function matchPaper(itemName: string, papers: Paper[]): Paper | undefined {
  if (!papers.length) return undefined
  const words = itemName.toLowerCase().split(/\s+/).filter(w => w.length > 3)
  let best: Paper | undefined
  let bestScore = 0
  for (const paper of papers) {
    const haystack = (paper.title + ' ' + paper.authors).toLowerCase()
    const score = words.filter(w => haystack.includes(w)).length
    if (score > bestScore) { bestScore = score; best = paper }
  }
  return bestScore > 0 ? best : undefined
}

function PaperSup({ paper, index }: { paper: Paper; index: number }) {
  return (
    <a
      href={paper.url}
      target="_blank"
      rel="noopener noreferrer"
      title={`${paper.authors} · ${paper.journal} · ${paper.year}`}
      style={{ textDecoration: 'none', color: 'inherit' }}
    >
      <sup style={{
        fontFamily: 'var(--font-ibm-plex-mono)',
        fontSize: 8,
        color: '#185FA5',
        fontWeight: 600,
        marginLeft: 2,
        cursor: 'pointer',
        borderBottom: '1px dotted #185FA5',
        letterSpacing: 0,
      }}>
        [{index}]
      </sup>
    </a>
  )
}

export function InventoryTable({ sections, papers = [], onUpdate }: InventoryTableProps) {
  const [localSections, setLocalSections] = useState<InventorySection[]>(sections)
  const [editingCell, setEditingCell] = useState<{ si: number; ri: number } | null>(null)
  const [editValue, setEditValue] = useState('')

  // Keep in sync when sections prop changes from outside
  const effectiveSections = onUpdate ? localSections : sections

  const update = (next: InventorySection[]) => {
    setLocalSections(next)
    onUpdate?.(next)
  }

  const handleStatusChange = (si: number, ri: number, status: InventoryStatus) => {
    const next = effectiveSections.map((sec, sIdx) =>
      sIdx !== si ? sec : {
        ...sec,
        rows: sec.rows.map((row, rIdx) => rIdx !== ri ? row : { ...row, status }),
      }
    )
    update(next)
  }

  const startEdit = (si: number, ri: number, currentName: string) => {
    setEditingCell({ si, ri })
    setEditValue(currentName)
  }

  const commitEdit = () => {
    if (!editingCell) return
    const { si, ri } = editingCell
    const next = effectiveSections.map((sec, sIdx) =>
      sIdx !== si ? sec : {
        ...sec,
        rows: sec.rows.map((row, rIdx) => rIdx !== ri ? row : { ...row, item: editValue }),
      }
    )
    update(next)
    setEditingCell(null)
  }

  // Build a deduplicated paper index for superscripts
  const paperIndex = new Map<string, { paper: Paper; num: number }>()
  let supCounter = 1
  effectiveSections.forEach(sec => {
    sec.rows.forEach(row => {
      const matched = matchPaper(row.item, papers)
      if (matched && !paperIndex.has(matched.doi)) {
        paperIndex.set(matched.doi, { paper: matched, num: supCounter++ })
      }
    })
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 2px' }}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <rect x="1" y="1" width="12" height="12" rx="2" stroke="#185FA5" strokeWidth="1.2" fill="none" />
          <path d="M3.5 4.5h7M3.5 7h7M3.5 9.5h4" stroke="#185FA5" strokeWidth="1" strokeLinecap="round" />
        </svg>
        <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#555', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
          Inventory check
        </span>
      </div>

      {effectiveSections.map((section, si) => (
        <div key={si} style={{ border: '1px solid #e0ddd8', borderRadius: 10, overflow: 'hidden' }}>
          <div style={{ padding: '8px 14px', background: '#faf9f7', borderBottom: '1px solid #e0ddd8' }}>
            <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#555', letterSpacing: '0.04em' }}>
              {section.title}
            </span>
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#f7f5f2' }}>
                {['Item', 'Status', 'Note'].map(h => (
                  <th key={h} style={{ padding: '6px 12px', textAlign: 'left', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#999', letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 500 }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {section.rows.map((row, ri) => {
                const cfg = STATUS_CONFIG[row.status]
                const isLast = ri === section.rows.length - 1
                const matched = matchPaper(row.item, papers)
                const supInfo = matched ? paperIndex.get(matched.doi) : undefined
                const isEditing = editingCell?.si === si && editingCell?.ri === ri

                return (
                  <tr key={ri} style={{ borderBottom: isLast ? 'none' : '1px solid #f0ede8' }}>
                    {/* Editable item name */}
                    <td style={{ padding: '9px 12px', fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#1a1a1a' }}>
                      {isEditing ? (
                        <input
                          autoFocus
                          value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          onBlur={commitEdit}
                          onKeyDown={e => { if (e.key === 'Enter') commitEdit(); if (e.key === 'Escape') setEditingCell(null) }}
                          style={{
                            fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#1a1a1a',
                            border: '1px solid #B5D4F4', borderRadius: 4, padding: '1px 6px',
                            background: '#f0f7ff', outline: 'none', width: '100%',
                          }}
                        />
                      ) : (
                        <span
                          onClick={() => startEdit(si, ri, row.item)}
                          title="Click to edit"
                          style={{ cursor: 'text', borderBottom: '1px dashed transparent', transition: 'border-color 0.15s' }}
                          onMouseEnter={e => (e.currentTarget.style.borderBottomColor = '#ccc')}
                          onMouseLeave={e => (e.currentTarget.style.borderBottomColor = 'transparent')}
                        >
                          {row.item}
                          {supInfo && <PaperSup paper={supInfo.paper} index={supInfo.num} />}
                        </span>
                      )}
                      {row.qty && !isEditing && (
                        <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#bbb', marginLeft: 4 }}>· {row.qty}</span>
                      )}
                    </td>

                    {/* Editable status */}
                    <td style={{ padding: '9px 12px' }}>
                      <div style={{ position: 'relative', display: 'inline-block' }}>
                        <span style={{ position: 'absolute', left: 6, top: '50%', transform: 'translateY(-50%)', width: 5, height: 5, borderRadius: '50%', background: cfg.dot, pointerEvents: 'none' }} />
                        <select
                          value={row.status}
                          onChange={e => handleStatusChange(si, ri, e.target.value as InventoryStatus)}
                          style={{
                            appearance: 'none', paddingLeft: 16, paddingRight: 20, paddingTop: 2, paddingBottom: 2,
                            borderRadius: 4, fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9,
                            textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 500,
                            border: `1px solid ${cfg.border}`, color: cfg.text, background: cfg.bg, cursor: 'pointer',
                          }}
                        >
                          {ALL_STATUSES.map(s => (
                            <option key={s} value={s}>{STATUS_CONFIG[s].label}</option>
                          ))}
                        </select>
                        <svg width="8" height="8" viewBox="0 0 8 8" fill="none" style={{ position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: cfg.text }}>
                          <path d="M1.5 3L4 5.5 6.5 3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" fill="none" />
                        </svg>
                      </div>
                    </td>

                    <td style={{ padding: '9px 12px', fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#666' }}>
                      {row.note}
                      {row.action && (
                        <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#993C1D', marginTop: 2 }}>
                          {row.action}
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {section.missingNote && (
            <div style={{ padding: '8px 14px', background: '#FEE9E3', borderTop: '1px solid #F5B9A8' }}>
              <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#7A1800', fontWeight: 600 }}>Action required: </span>
              <span style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#7A1800' }}>{section.missingNote}</span>
            </div>
          )}
        </div>
      ))}

      {/* Paper reference footnotes */}
      {paperIndex.size > 0 && (
        <div style={{ paddingTop: 10, borderTop: '1px solid #f0ede8', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {[...paperIndex.values()].sort((a, b) => a.num - b.num).map(({ paper, num }) => (
            <div key={num} style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
              <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#185FA5', fontWeight: 600, flexShrink: 0, minWidth: 18 }}>[{num}]</span>
              <a
                href={paper.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 10, color: '#185FA5', textDecoration: 'none', lineHeight: 1.5 }}
                onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
                onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}
              >
                {paper.authors} · {paper.journal} · {paper.year} ↗
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export const ERIC_INVENTORY_DATA: InventorySection[][] = [
  [
    {
      title: 'Core instruments',
      rows: [
        { item: 'Centrifuge', qty: '1 unit', status: 'available', note: 'Confirmed in store' },
        { item: 'Plate reader', qty: '1 unit', status: 'limited', note: 'Booked through Thursday', action: 'Schedule window now' },
        { item: 'Gel electrophoresis', qty: '1 rig', status: 'available', note: 'Ready to use' },
        { item: '-80°C freezer space', qty: '~12 positions', status: 'limited', note: 'Capacity is tight', action: 'Flag to lab manager' },
      ],
    },
    {
      title: 'Missing items',
      rows: [
        { item: 'Calibrated micropipette set', qty: '1–10 µL', status: 'missing', note: 'Failed QC last week — zero usable units', action: 'Raise PO today — 2-day lead time' },
      ],
      missingNote: 'Micropipette set failed QC. Experiment cannot start without replacement. Raising purchase order immediately.',
    },
  ],
  [
    {
      title: 'Reagents & consumables',
      rows: [
        { item: 'ELISA kit + buffers + standards', status: 'available', qty: 'per run', note: '~£320 per run' },
        { item: 'Tips, tubes, plates', status: 'available', qty: 'per run', note: '~£85 per run' },
        { item: 'Instrument time — plate reader', status: 'limited', qty: '6 hrs', note: '£40/hr → ~£240' },
      ],
    },
    {
      title: 'Budget gaps',
      rows: [
        { item: 'Waste disposal', status: 'missing', note: 'Not costed — always non-zero', action: 'Get figure from facilities' },
        { item: 'PPE restocking', status: 'missing', note: 'Not in current template', action: 'Add £80 contingency line' },
        { item: 'Courier costs', status: 'missing', note: 'If samples go offsite — unquoted', action: 'Confirm offsite requirement' },
      ],
      missingNote: 'Estimated per-run total: ~£620 before contingency. Three line items are uncosted — fix before grant submission.',
    },
  ],
]
