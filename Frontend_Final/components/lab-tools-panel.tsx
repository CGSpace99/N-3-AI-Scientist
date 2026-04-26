'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import type { InventorySection, InventoryStatus } from '@/components/inventory-table'
import type { Paper } from '@/components/literature-card'

type ActiveTab = 'equipment' | 'consumables'
type Status = 'available' | 'limited' | 'missing' | 'ordered'

interface ToolItem {
  name: string
  status: Status
  note?: string
  action?: string
}

interface Consumable {
  name: string
  qty: string
  supplier?: string
  status: Status
  note?: string
  action?: string
}

const STATUS_CONFIG: Record<Status, { label: string; color: string; bg: string; border: string }> = {
  available: { label: 'Available', color: '#085041', bg: '#E9F7F2', border: '#9FE1CB' },
  limited: { label: 'Limited', color: '#7C4A00', bg: '#FEF3C7', border: '#F5C842' },
  missing: { label: 'Missing', color: '#7A1800', bg: '#FEE9E3', border: '#F5B9A8' },
  ordered: { label: 'On order', color: '#0D3766', bg: '#E6F1FB', border: '#B5D4F4' },
}

const STATUSES: Status[] = ['available', 'limited', 'missing', 'ordered']

const DEFAULT_TOOLS: ToolItem[] = [
  { name: 'Centrifuge (benchtop)', status: 'available' },
  { name: 'Plate reader', status: 'limited', note: 'Booked through Thursday - schedule needed', action: 'Book Thursday slot' },
  { name: 'Gel electrophoresis rig', status: 'available' },
  { name: '-80 C freezer space', status: 'limited', note: 'Capacity low - flag early', action: 'Rearrange stock' },
  { name: 'Micropipette set 1-10 uL', status: 'missing', note: 'Failed QC last week', action: 'PO raised - 2-day delivery' },
  { name: 'Biosafety cabinet (Class II)', status: 'limited', note: 'Thurs afternoon slot only', action: 'Book slot' },
  { name: 'Incubator shakers x2', status: 'available', note: 'Both units free' },
  { name: 'Analytical balance', status: 'available', note: 'Calibrated Jan 2026' },
  { name: 'Vacuum filtration setup', status: 'available' },
  { name: 'CO2 sensor', status: 'ordered', note: 'Needed for incubation monitoring', action: 'Sourcing from Building C' },
  { name: 'Sterile dissection tools', status: 'missing', note: 'In sterilisation - not back before next week', action: 'Chase sterile services' },
  { name: 'Thermal cycler', status: 'limited', note: 'Due for maintenance', action: 'Book maintenance window' },
  { name: 'Spectrophotometer (UV-Vis)', status: 'available', note: 'Calibrated, good' },
  { name: 'Flow cytometer', status: 'limited', note: 'Shared with Building B - booking required', action: 'Request access slot' },
]

const CONSUMABLES: Consumable[] = [
  { name: 'ELISA kit (96-well format)', qty: '2 kits', supplier: 'Abcam', status: 'ordered' },
  { name: 'PBS buffer (10x)', qty: '500 mL x 4', supplier: 'Sigma-Aldrich', status: 'available' },
  { name: 'HEPES buffer', qty: '250 mL x 2', supplier: 'Sigma-Aldrich', status: 'available' },
  { name: 'Primary antibody (anti-target)', qty: '100 ug', supplier: 'Cell Signaling', status: 'limited' },
  { name: 'Secondary antibody (HRP-conjugated)', qty: '50 ug', supplier: 'Abcam', status: 'limited' },
  { name: 'PVDF membrane', qty: '1 pack', supplier: 'Millipore', status: 'available' },
  { name: 'Mounting medium', qty: '10 mL', supplier: 'Vector Labs', status: 'missing' },
  { name: '96-well plates', qty: '12 plates', supplier: 'Nunc', status: 'available' },
  { name: '1.5 mL microtubes', qty: '500', supplier: 'Eppendorf', status: 'available' },
  { name: '200 uL filter tips', qty: '4 boxes', supplier: 'Sartorius', status: 'available' },
  { name: 'T-75 cell culture flasks', qty: '24', supplier: 'Corning', status: 'limited' },
  { name: 'Sterile cell scrapers', qty: '50', supplier: 'Greiner Bio-One', status: 'missing' },
  { name: 'Nitrile gloves (M + L)', qty: '2 boxes each', supplier: 'Kimberly-Clark', status: 'available' },
  { name: 'DAPI stain', qty: '1 mg', supplier: 'Thermo Fisher', status: 'ordered' },
  { name: 'Parafilm', qty: '1 roll', supplier: 'Bemis', status: 'available' },
]

interface LabToolsPanelProps {
  hasInventory: boolean
  inventorySections?: InventorySection[]
  papers?: Paper[]
  onInventoryUpdate?: (sections: InventorySection[]) => void
}

export function LabToolsPanel({ hasInventory, inventorySections = [], papers = [], onInventoryUpdate }: LabToolsPanelProps) {
  const [tools, setTools] = useState<ToolItem[]>(DEFAULT_TOOLS)
  const [consumables, setConsumables] = useState<Consumable[]>(CONSUMABLES)
  const [generatedTools, setGeneratedTools] = useState<ToolItem[]>([])
  const [generatedConsumables, setGeneratedConsumables] = useState<Consumable[]>([])
  const [activeTab, setActiveTab] = useState<ActiveTab>('equipment')
  const inventorySignature = useMemo(() => JSON.stringify(inventorySections), [inventorySections])
  const hasUserEditedInventory = useRef(false)

  useEffect(() => {
    hasUserEditedInventory.current = false
    const { equipment, consumableItems } = splitInventorySections(inventorySections)
    setGeneratedTools(equipment)
    setGeneratedConsumables(consumableItems)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inventorySignature])

  const displayTools = generatedTools.length ? generatedTools : tools
  const displayConsumables = generatedConsumables.length ? generatedConsumables : consumables
  const usingGeneratedTools = generatedTools.length > 0
  const usingGeneratedConsumables = generatedConsumables.length > 0

  // Sync outward after any tool/consumable change — runs after render, not during
  useEffect(() => {
    if (!onInventoryUpdate) return
    if (!hasUserEditedInventory.current) return
    const equipSection: InventorySection = {
      title: 'Core instruments',
      rows: displayTools.map(t => ({ item: t.name, status: t.status as InventoryStatus, note: t.note || '', action: t.action })),
    }
    const consumableSection: InventorySection = {
      title: 'Reagents & consumables',
      rows: displayConsumables.map(c => ({ item: c.name, qty: c.qty, status: c.status as InventoryStatus, note: c.note || '', action: c.action })),
    }
    onInventoryUpdate([equipSection, consumableSection])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayTools, displayConsumables])

  const setStatus = (index: number, status: Status) => {
    hasUserEditedInventory.current = true
    const setter = usingGeneratedTools ? setGeneratedTools : setTools
    setter(prev => prev.map((t, i) => i === index ? { ...t, status } : t))
  }

  const setConsumableStatus = (index: number, status: Status) => {
    hasUserEditedInventory.current = true
    const setter = usingGeneratedConsumables ? setGeneratedConsumables : setConsumables
    setter(prev => prev.map((t, i) => i === index ? { ...t, status } : t))
  }

  const setToolName = (index: number, name: string) => {
    hasUserEditedInventory.current = true
    const setter = usingGeneratedTools ? setGeneratedTools : setTools
    setter(prev => prev.map((t, i) => i === index ? { ...t, name } : t))
  }

  const setConsumableName = (index: number, name: string) => {
    hasUserEditedInventory.current = true
    const setter = usingGeneratedConsumables ? setGeneratedConsumables : setConsumables
    setter(prev => prev.map((t, i) => i === index ? { ...t, name } : t))
  }

  const counts = statusCounts(displayTools)
  const consumableCounts = statusCounts(displayConsumables)

  if (!hasInventory) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: '#bbb', padding: 40 }}>
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
          <path d="M10 4v10l-4 6v4h20v-4l-4-6V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
          <path d="M10 14h12" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        <span style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 13, color: '#bbb', textAlign: 'center' }}>
          Lab inventory will appear after Eric runs his assessment.
        </span>
      </div>
    )
  }

  const TABS: { id: ActiveTab; label: string; count: number }[] = [
    { id: 'equipment', label: 'Equipment', count: displayTools.length },
    { id: 'consumables', label: 'Consumables', count: displayConsumables.length },
  ]

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #e0ddd8', background: '#faf9f7' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M5 1v5l-2 3v2h8v-2l-2-3V1" stroke="#185FA5" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
          </svg>
          <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, fontWeight: 600, color: '#1a1a1a', letterSpacing: '0.04em' }}>
            Eric - Lab Inventory
          </span>
        </div>
        <p style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#888', margin: 0 }}>
          {inventorySections.length > 0 ? 'Protocol-derived equipment & consumables' : 'Equipment & Consumables'}
        </p>
      </div>

      <div style={{ display: 'flex', borderBottom: '1px solid #e0ddd8' }}>
        {TABS.map(tab => {
          const active = activeTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6, padding: '10px 16px',
                fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 11, fontWeight: 500,
                color: active ? '#185FA5' : '#888',
                background: 'transparent', border: 'none', borderBottom: active ? '2px solid #185FA5' : '2px solid transparent',
                cursor: 'pointer',
              }}
            >
              {tab.label}
              <span style={{ background: active ? '#E6F1FB' : '#f0ede8', color: active ? '#185FA5' : '#999', padding: '1px 5px', borderRadius: 4, fontSize: 9 }}>
                {tab.count}
              </span>
            </button>
          )
        })}
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {activeTab === 'equipment' && (
          <EquipmentTable tools={displayTools} counts={counts} onStatusChange={setStatus} onNameChange={setToolName} />
        )}
        {activeTab === 'consumables' && (
          <ConsumablesTable consumables={displayConsumables} counts={consumableCounts} onStatusChange={setConsumableStatus} onNameChange={setConsumableName} papers={papers} />
        )}
      </div>
    </div>
  )
}

function EquipmentTable({ tools, counts, onStatusChange, onNameChange }: {
  tools: ToolItem[]
  counts: Record<Status, number>
  onStatusChange: (i: number, s: Status) => void
  onNameChange: (i: number, name: string) => void
}) {
  const [editingIdx, setEditingIdx] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')

  const startEdit = (i: number) => { setEditingIdx(i); setEditValue(tools[i].name) }
  const commitEdit = (i: number) => { onNameChange(i, editValue); setEditingIdx(null) }

  return (
    <div>
      <StatusChips counts={counts} />
      <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 12 }}>
        <thead>
          <tr style={{ background: '#f7f5f2' }}>
            {['Equipment', 'Status', 'Note', 'Action'].map(h => (
              <th key={h} style={{ padding: '6px 10px', textAlign: 'left', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#999', letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 500 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tools.map((tool, i) => (
            <tr key={i} style={{ borderBottom: '1px solid #f0ede8' }}>
              <td style={{ padding: '8px 10px', fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#1a1a1a' }}>
                {editingIdx === i ? (
                  <input
                    autoFocus
                    value={editValue}
                    onChange={e => setEditValue(e.target.value)}
                    onBlur={() => commitEdit(i)}
                    onKeyDown={e => { if (e.key === 'Enter') commitEdit(i); if (e.key === 'Escape') setEditingIdx(null) }}
                    style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#1a1a1a', border: '1px solid #B5D4F4', borderRadius: 4, padding: '1px 6px', background: '#f0f7ff', outline: 'none', width: '100%' }}
                  />
                ) : (
                  <span
                    onClick={() => startEdit(i)}
                    title="Click to edit"
                    style={{ cursor: 'text', borderBottom: '1px dashed transparent', transition: 'border-color 0.15s' }}
                    onMouseEnter={e => (e.currentTarget.style.borderBottomColor = '#ccc')}
                    onMouseLeave={e => (e.currentTarget.style.borderBottomColor = 'transparent')}
                  >{tool.name}</span>
                )}
              </td>
              <td style={{ padding: '8px 10px' }}><StatusSelect value={tool.status} onChange={s => onStatusChange(i, s)} /></td>
              <td style={{ padding: '8px 10px', fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#666' }}>{tool.note ? <span>{tool.note}</span> : <span style={{ color: '#ccc' }}>-</span>}</td>
              <td style={{ padding: '8px 10px', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#993C1D' }}>{tool.action ? <span>{tool.action}</span> : <span style={{ color: '#ccc' }}>-</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Match item name to closest paper by keyword overlap
function matchPaper(name: string, papers: Paper[]): Paper | undefined {
  if (!papers.length) return undefined
  const words = name.toLowerCase().split(/\s+/).filter(w => w.length > 3)
  let best: Paper | undefined; let bestScore = 0
  for (const p of papers) {
    const hay = (p.title + ' ' + p.authors).toLowerCase()
    const score = words.filter(w => hay.includes(w)).length
    if (score > bestScore) { bestScore = score; best = p }
  }
  return bestScore > 0 ? best : undefined
}

function ConsumablesTable({ consumables, counts, onStatusChange, onNameChange, papers = [] }: {
  consumables: Consumable[]
  counts: Record<Status, number>
  onStatusChange: (i: number, s: Status) => void
  onNameChange: (i: number, name: string) => void
  papers?: Paper[]
}) {
  const [editingIdx, setEditingIdx] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')

  const startEdit = (i: number) => { setEditingIdx(i); setEditValue(consumables[i].name) }
  const commitEdit = (i: number) => { onNameChange(i, editValue); setEditingIdx(null) }

  // Build paper index for superscripts
  const paperIndex = new Map<string, { paper: Paper; num: number }>()
  let counter = 1
  consumables.forEach(c => {
    const matched = matchPaper(c.name, papers)
    if (matched && !paperIndex.has(matched.doi)) paperIndex.set(matched.doi, { paper: matched, num: counter++ })
  })

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 11, fontWeight: 600, color: '#1D9E75' }}>{counts.available + counts.ordered}</span>
          <span style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#888' }}>/ {consumables.length} available or ordered</span>
        </div>
        <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#185FA5', background: '#E6F1FB', padding: '2px 7px', borderRadius: 4 }}>Procurement list</span>
      </div>
      <StatusChips counts={counts} />
      <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 12 }}>
        <thead>
          <tr style={{ background: '#f7f5f2' }}>
            {['Item', 'Status', 'Qty', 'Supplier', 'Action'].map(h => (
              <th key={h} style={{ padding: '6px 10px', textAlign: 'left', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#999', letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 500 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {consumables.map((c, i) => {
            const matched = matchPaper(c.name, papers)
            const supInfo = matched ? paperIndex.get(matched.doi) : undefined
            return (
              <tr key={i} style={{ borderBottom: '1px solid #f0ede8' }}>
                <td style={{ padding: '8px 10px' }}>
                  {editingIdx === i ? (
                    <input
                      autoFocus
                      value={editValue}
                      onChange={e => setEditValue(e.target.value)}
                      onBlur={() => commitEdit(i)}
                      onKeyDown={e => { if (e.key === 'Enter') commitEdit(i); if (e.key === 'Escape') setEditingIdx(null) }}
                      style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#1a1a1a', border: '1px solid #B5D4F4', borderRadius: 4, padding: '1px 6px', background: '#f0f7ff', outline: 'none', width: '100%' }}
                    />
                  ) : (
                    <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#1a1a1a' }}>
                      <span
                        onClick={() => startEdit(i)}
                        title="Click to edit"
                        style={{ cursor: 'text', borderBottom: '1px dashed transparent', transition: 'border-color 0.15s' }}
                        onMouseEnter={e => (e.currentTarget.style.borderBottomColor = '#ccc')}
                        onMouseLeave={e => (e.currentTarget.style.borderBottomColor = 'transparent')}
                      >{c.name}</span>
                      {supInfo && (
                        <a href={supInfo.paper.url} target="_blank" rel="noopener noreferrer" title={`${supInfo.paper.authors} · ${supInfo.paper.journal} · ${supInfo.paper.year}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                          <sup style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 8, color: '#185FA5', fontWeight: 600, marginLeft: 2, cursor: 'pointer', borderBottom: '1px dotted #185FA5' }}>[{supInfo.num}]</sup>
                        </a>
                      )}
                    </div>
                  )}
                  {c.note && <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 10, color: '#aaa', marginTop: 1 }}>{c.note}</div>}
                </td>
                <td style={{ padding: '8px 10px' }}><StatusSelect value={c.status} onChange={s => onStatusChange(i, s)} /></td>
                <td style={{ padding: '8px 10px', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#555' }}>{c.qty}</td>
                <td style={{ padding: '8px 10px', fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#666' }}>{c.supplier ?? '-'}</td>
                <td style={{ padding: '8px 10px', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#993C1D' }}>{c.action ? <span>{c.action}</span> : <span style={{ color: '#ccc' }}>-</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {/* Paper footnotes */}
      {paperIndex.size > 0 && (
        <div style={{ paddingTop: 10, marginTop: 8, borderTop: '1px solid #f0ede8', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {[...paperIndex.values()].sort((a, b) => a.num - b.num).map(({ paper, num }) => (
            <div key={num} style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
              <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#185FA5', fontWeight: 600, flexShrink: 0, minWidth: 18 }}>[{num}]</span>
              <a href={paper.url} target="_blank" rel="noopener noreferrer"
                style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 10, color: '#185FA5', textDecoration: 'none', lineHeight: 1.5, borderBottom: '1px solid transparent' }}
                onMouseEnter={e => (e.currentTarget.style.borderBottomColor = '#185FA5')}
                onMouseLeave={e => (e.currentTarget.style.borderBottomColor = 'transparent')}
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

function StatusChips({ counts }: { counts: Record<Status, number> }) {
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {(Object.entries(counts) as [Status, number][]).map(([status, count]) => {
        const cfg = STATUS_CONFIG[status]
        return (
          <span key={status} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: cfg.color, background: cfg.bg, border: `1px solid ${cfg.border}`, padding: '2px 7px', borderRadius: 4 }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: cfg.color }} />
            {count} {cfg.label}
          </span>
        )
      })}
    </div>
  )
}

function StatusSelect({ value, onChange }: { value: Status; onChange: (s: Status) => void }) {
  const cfg = STATUS_CONFIG[value]
  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <span style={{ position: 'absolute', left: 6, top: '50%', transform: 'translateY(-50%)', width: 5, height: 5, borderRadius: '50%', background: cfg.color, pointerEvents: 'none' }} />
      <select
        value={value}
        onChange={e => onChange(e.target.value as Status)}
        style={{
          appearance: 'none', paddingLeft: 16, paddingRight: 20, paddingTop: 2, paddingBottom: 2,
          borderRadius: 4, fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, textTransform: 'uppercase',
          letterSpacing: '0.05em', fontWeight: 500, border: `1px solid ${cfg.border}`,
          color: cfg.color, background: cfg.bg, cursor: 'pointer',
        }}
      >
        {STATUSES.map(s => (
          <option key={s} value={s}>{STATUS_CONFIG[s].label}</option>
        ))}
      </select>
      <svg width="8" height="8" viewBox="0 0 8 8" fill="none" style={{ position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: cfg.color }}>
        <path d="M1.5 3L4 5.5 6.5 3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" fill="none" />
      </svg>
    </div>
  )
}

function statusCounts<T extends { status: Status }>(items: T[]): Record<Status, number> {
  return {
    available: items.filter(t => t.status === 'available').length,
    limited: items.filter(t => t.status === 'limited').length,
    missing: items.filter(t => t.status === 'missing').length,
    ordered: items.filter(t => t.status === 'ordered').length,
  }
}

function splitInventorySections(sections: InventorySection[]) {
  const equipment: ToolItem[] = []
  const consumableItems: Consumable[] = []

  sections.forEach(section => {
    const isConsumables = /material|consumable|reagent|supply/i.test(section.title)
    section.rows.forEach(row => {
      if (isConsumables) {
        const { qty, supplier, note } = parseConsumableDetails(row.qty, row.note)
        consumableItems.push({ name: row.item, qty, supplier, status: statusValue(row.status), note, action: row.action })
      } else {
        equipment.push({ name: row.item, status: statusValue(row.status), note: row.note, action: row.action })
      }
    })
  })

  return { equipment, consumableItems }
}

function statusValue(value: string): Status {
  return STATUSES.includes(value as Status) ? value as Status : 'limited'
}

function parseConsumableDetails(qty: string | undefined, note: string | undefined) {
  const parts = (qty || note || '').split('·').map(p => p.trim()).filter(Boolean)
  return { qty: parts[0] || 'TBD', supplier: parts.length > 2 ? parts[2] : undefined, note: note || '' }
}
