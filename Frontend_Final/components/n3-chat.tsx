'use client'

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { CHARACTERS, getContextualChips, type CharacterId, type Character } from '@/lib/characters'
import { FireCanvas } from '@/components/fire-canvas'
import { PlanCard } from '@/components/plan-card'
import { LiteratureCard } from '@/components/literature-card'
import type { Paper } from '@/components/literature-card'
import { ThinkingTrail, type TrailSequence, RACHAEL_TRAILS } from '@/components/thinking-trail'
import { SideNav, type NavView } from '@/components/side-nav'
import { LiteraturePanel } from '@/components/literature-panel'
import { LabToolsPanel } from '@/components/lab-tools-panel'
import { ProtocolPanel } from '@/components/protocol-panel'
import { InventoryTable, type InventorySection } from '@/components/inventory-table'

interface Message {
  role: 'user' | 'character'
  text: string
  characterId?: CharacterId
  isPlanCard?: boolean
  isLiterature?: boolean
  isProtocolArtifact?: boolean
  isBudgetArtifact?: boolean
  isFaithProtocol?: boolean
  papers?: Paper[]
  similarityFlag?: string | null
  trail?: TrailSequence
  protocols?: ProtocolCandidate[]
  tailoredProtocol?: TailoredProtocol
  materialsBudget?: MaterialsBudget
  planData?: PlanData
}

function toBackendMessages(messages: Message[]) {
  return messages
    .filter(m => Boolean(m.text))
    .map(m => ({
      role: m.role === 'character' ? 'assistant' : 'user',
      text: m.text,
    }))
}

interface PlanData {
  hypothesis: string
  controls: string
  falsifiability: string
  equipment: string
  budget: string
  timeline: string
  impact: string
}

interface StageState {
  messages: Message[]
  messageCount: number
  done: boolean
}

type Stages = Record<CharacterId, StageState>
type EricStage = 'relevant_protocols' | 'tailored_protocol' | 'tools' | 'materials_consumables'

interface ProtocolCandidate {
  title?: string
  source_title?: string
  source_url?: string
  evidence_quality?: string
  relevance_reason?: string
  adapted_steps?: string[]
  tools?: string[]
  consumables?: string[]
  limitations?: string[]
}

interface ProtocolStep {
  step_number?: number
  title?: string
  description?: string
  inputs?: string[]
  outputs?: string[]
  duration?: string
  validation_checks?: string[]
}

interface TailoredProtocol {
  title?: string
  summary?: string
  steps?: ProtocolStep[]
  inputs?: string[]
  outputs?: string[]
  validation_checks?: string[]
  source_protocol_refs?: string[]
}

interface BudgetMaterial {
  name?: string
  category?: string
  supplier?: string
  catalog_number?: string
  quantity?: string
  unit_cost_estimate?: number
  total_cost_estimate?: number
  currency?: string
  cost_confidence?: string
  quote_confidence?: string
  source_url?: string
  rationale?: string
}

interface BudgetLine {
  item?: string
  quantity?: string
  unit_cost_estimate?: number
  total_cost_estimate?: number
  currency?: string
  cost_confidence?: string
  source_url?: string
}

interface MaterialsBudget {
  summary?: string
  materials?: BudgetMaterial[]
  budget_lines?: BudgetLine[]
  total_budget_estimate?: { amount?: number; currency?: string }
  overall_confidence?: string
}

// ─── Small presentational components ────────────────────────────────────────

const LONG_MESSAGE_THRESHOLD = 160
const RACHAEL_PROGRESS_STEPS = [
  'Analyzing question...',
  'Running literature QC...',
  'Ranking evidence and preparing response...',
]

function FormattedMessage({ text }: { text: string }) {
  if (text.length < LONG_MESSAGE_THRESHOLD) {
    return <>{text}</>
  }

  // Split on numbered list markers (e.g. "1. ", "2. ") or sentence endings followed by capital letters
  // First, split into raw segments by double newlines, then within each segment detect list items
  const rawBlocks = text.split(/\n\n+/)

  const blocks = rawBlocks.flatMap(block => {
    // Detect inline numbered list items: "1. text 2. text" etc.
    const inlineListMatch = block.match(/^\d+\.\s/)
    if (inlineListMatch) return [block]

    // Split a flat paragraph into numbered items if it contains " 1. " or " 2. " mid-string
    const splitByNumbers = block.split(/(?=\s\d+\.\s)/)
    if (splitByNumbers.length > 1) return splitByNumbers.map(s => s.trim()).filter(Boolean)
    return [block]
  })

  const elements: React.ReactNode[] = []
  const listItems: string[] = []

  const flushList = (key: string) => {
    if (listItems.length === 0) return
    elements.push(
      <ul key={key} style={{ margin: '6px 0 4px', paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 4 }}>
        {listItems.map((item, i) => (
          <li key={i} style={{ listStyleType: 'disc', paddingLeft: 2 }}>{item}</li>
        ))}
      </ul>
    )
    listItems.length = 0
  }

  blocks.forEach((block, idx) => {
    const trimmed = block.trim()
    if (!trimmed) return

    // Numbered list item: starts with digit and dot
    const numberedMatch = trimmed.match(/^\d+\.\s+(.+)/)
    if (numberedMatch) {
      listItems.push(numberedMatch[1])
      return
    }

    flushList(`list-${idx}`)

    elements.push(
      <p key={`p-${idx}`} style={{ margin: idx === 0 ? 0 : '6px 0 0' }}>
        {trimmed}
      </p>
    )
  })

  flushList('list-end')

  return <>{elements}</>
}

function Avatar({ char, size = 36 }: { char: Character; size?: number }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: char.avatarBg, color: char.avatarText,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'var(--font-playfair)', fontSize: size * 0.44, fontWeight: 700,
      flexShrink: 0,
    }}>
      {char.initial}
    </div>
  )
}

function MoodPill({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color,
      background: `${color}18`, border: `1px solid ${color}44`,
      padding: '1px 6px', borderRadius: 4, letterSpacing: '0.06em',
    }}>
      {label}
    </span>
  )
}

function SimilarityBadge({ flag }: { flag: string }) {
  const config: Record<string, { label: string; bg: string; text: string; border: string }> = {
    similar_work_exists: { label: '⚠ Similar work exists', bg: '#FEF3C7', text: '#7C4A00', border: '#F5C842' },
    direct_replication: { label: '✗ Direct replication', bg: '#FEE9E3', text: '#7A1800', border: '#F5B9A8' },
    adjacent_method: { label: '~ Adjacent method', bg: '#E6F1FB', text: '#0D3766', border: '#B5D4F4' },
    novel_gap: { label: '✓ Novel gap identified', bg: '#E9F7F2', text: '#085041', border: '#9FE1CB' },
    novel: { label: '✓ Novel gap identified', bg: '#E9F7F2', text: '#085041', border: '#9FE1CB' },
  }
  const c = config[flag] ?? config.similar_work_exists
  return (
    <span style={{
      fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9,
      background: c.bg, color: c.text, border: `1px solid ${c.border}`,
      padding: '2px 7px', borderRadius: 5,
    }}>
      {c.label}
    </span>
  )
}

function TypingDots({ char }: { char: Character }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0' }}>
      <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: char.nameColor }}>
        {char.name}
      </span>
      <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            width: 5, height: 5, borderRadius: '50%', background: char.nameColor,
            animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
          }} />
        ))}
      </div>
      <style>{`@keyframes bounce { 0%,80%,100%{transform:scale(0.6);opacity:0.4} 40%{transform:scale(1);opacity:1} }`}</style>
    </div>
  )
}

function ArtifactShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ border: '1px solid #B5D4F4', background: '#F8FBFF', borderRadius: 12, padding: 12, maxWidth: '95%' }}>
      <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#185FA5', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function formatArtifactItem(item: unknown): string {
  if (typeof item === 'string') return item
  if (typeof item === 'number' || typeof item === 'boolean') return String(item)
  if (item && typeof item === 'object') {
    const record = item as Record<string, unknown>
    const name = String(record.name || record.item || record.title || record.label || '').trim()
    const category = String(record.category || record.status || '').trim()
    const detail = String(record.specification || record.quantity || record.rationale || record.note || '').trim()
    return [name || 'Protocol-derived item', category, detail].filter(Boolean).join(' - ')
  }
  return ''
}

function CompactList({ items }: { items?: unknown[] }) {
  const visible = (items || []).map(formatArtifactItem).filter(Boolean).slice(0, 5)
  if (!visible.length) return null
  return (
    <ul style={{ margin: '6px 0 0', paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 3 }}>
      {visible.map((item, idx) => (
        <li key={`${item}-${idx}`} style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#333' }}>{item}</li>
      ))}
    </ul>
  )
}

function ProtocolArtifactCard({
  protocols,
  tailoredProtocol,
}: {
  protocols?: ProtocolCandidate[]
  tailoredProtocol?: TailoredProtocol
}) {
  if (tailoredProtocol) {
    return (
      <ArtifactShell title="Eric · Revised Protocol">
        <div style={{ fontFamily: 'var(--font-playfair)', fontSize: 16, fontWeight: 700, color: '#0D3766', marginBottom: 4 }}>
          {tailoredProtocol.title || 'Tailored protocol'}
        </div>
        {tailoredProtocol.summary && (
          <p style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#444', margin: '0 0 10px', lineHeight: 1.5 }}>
            {tailoredProtocol.summary}
          </p>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {(tailoredProtocol.steps || []).slice(0, 8).map((step, idx) => (
            <div key={`${step.step_number || idx}-${step.title || 'step'}`} style={{ borderTop: idx === 0 ? 'none' : '1px solid #D8E8F8', paddingTop: idx === 0 ? 0 : 8 }}>
              <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#185FA5', marginBottom: 2 }}>
                Step {step.step_number || idx + 1}{step.duration ? ` · ${step.duration}` : ''}
              </div>
              <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 13, color: '#1a1a1a', fontWeight: 600 }}>{step.title || 'Protocol step'}</div>
              {step.description && <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#555', lineHeight: 1.45 }}>{step.description}</div>}
              <CompactList items={step.validation_checks} />
            </div>
          ))}
        </div>
      </ArtifactShell>
    )
  }

  return (
    <ArtifactShell title="Eric · Protocols From Papers">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {(protocols || []).slice(0, 3).map((candidate, idx) => (
          <div key={`${candidate.title || 'candidate'}-${idx}`} style={{ borderTop: idx === 0 ? 'none' : '1px solid #D8E8F8', paddingTop: idx === 0 ? 0 : 10 }}>
            <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 13, color: '#1a1a1a', fontWeight: 700 }}>
              {candidate.title || `Protocol candidate ${idx + 1}`}
            </div>
            {(candidate.source_title || candidate.evidence_quality) && (
              <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#777', marginTop: 2 }}>
                {[candidate.source_title, candidate.evidence_quality].filter(Boolean).join(' · ')}
              </div>
            )}
            {candidate.relevance_reason && (
              <p style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#555', margin: '6px 0 0', lineHeight: 1.45 }}>
                {candidate.relevance_reason}
              </p>
            )}
            <div style={{ marginTop: 8, padding: 9, background: '#FFFFFF', border: '1px solid #E5F0FA', borderRadius: 8 }}>
              <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#185FA5', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                Adapted steps and relevant protocol
              </div>
              <CompactList items={candidate.adapted_steps} />
              {!candidate.adapted_steps?.length && (
                <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#777', marginTop: 5 }}>
                  No adapted steps were extracted for this candidate; Eric will tailor the protocol after approval.
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </ArtifactShell>
  )
}

function money(currency?: string, value?: number) {
  const amount = typeof value === 'number' ? value : 0
  return `${currency || 'GBP'} ${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

function BudgetArtifactCard({ materialsBudget }: { materialsBudget: MaterialsBudget }) {
  const total = materialsBudget.total_budget_estimate || {}
  const materials = materialsBudget.materials || []
  return (
    <ArtifactShell title="Eric · Materials Budget">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, marginBottom: 10 }}>
        <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 13, color: '#333' }}>
          {materialsBudget.summary || 'Supplier and price estimates generated from protocol-derived consumables.'}
        </div>
        <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 13, color: '#185FA5', fontWeight: 700, whiteSpace: 'nowrap' }}>
          Total {money(total.currency, total.amount)}
        </div>
      </div>
      <div style={{ border: '1px solid #D8E8F8', borderRadius: 8, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#EEF5FD' }}>
              {['Item', 'Supplier / catalog', 'Qty', 'Estimate'].map(header => (
                <th key={header} style={{ padding: '6px 8px', textAlign: 'left', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#185FA5', textTransform: 'uppercase' }}>
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {materials.slice(0, 10).map((item, idx) => {
              const supplier = item.supplier || 'Supplier search pending'
              const catalog = item.catalog_number || item.source_url || 'Catalog/source search pending'
              return (
                <tr key={`${item.name || 'material'}-${idx}`} style={{ borderTop: idx === 0 ? 'none' : '1px solid #E5F0FA' }}>
                  <td style={{ padding: '7px 8px', fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#1a1a1a' }}>
                    <div style={{ fontWeight: 600 }}>{item.name || 'Material requiring review'}</div>
                    <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#888' }}>{item.category || 'material'} · {item.cost_confidence || 'low'} confidence</div>
                  </td>
                  <td style={{ padding: '7px 8px', fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#555' }}>
                    <div>{supplier}</div>
                    {item.source_url ? (
                      <a href={item.source_url} target="_blank" rel="noopener noreferrer" style={{ color: '#185FA5', textDecoration: 'none' }}>{catalog} ↗</a>
                    ) : (
                      <div style={{ color: '#777' }}>{catalog}</div>
                    )}
                  </td>
                  <td style={{ padding: '7px 8px', fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#555' }}>{item.quantity || 'Quantity estimate pending'}</td>
                  <td style={{ padding: '7px 8px', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#333' }}>
                    <div>{money(item.currency, item.unit_cost_estimate)} unit</div>
                    <div>{money(item.currency, item.total_cost_estimate)} total</div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </ArtifactShell>
  )
}

function FaithProtocolCard({ planData, papers = [] }: { planData: PlanData; papers?: Paper[] }) {
  const sections = [
    { label: 'Overview & Impact', value: planData.impact },
    { label: 'Hypothesis', value: planData.hypothesis },
    { label: 'Protocol', value: planData.controls },
    { label: 'Materials & Equipment', value: planData.equipment },
    { label: 'Budget', value: planData.budget },
    { label: 'Timeline', value: planData.timeline },
    { label: 'Validation', value: planData.falsifiability },
  ]
  return (
    <ArtifactShell title="Faith · Full Protocol Document">
      <PlanCard {...planData} papers={papers} />
      <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {sections.map(section => (
          <div key={section.label} style={{ borderTop: '1px solid #DDEFE7', paddingTop: 10 }}>
            <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#085041', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 5 }}>
              {section.label}
            </div>
            <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#333', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
              {section.value || 'Pending'}
            </div>
          </div>
        ))}
      </div>
    </ArtifactShell>
  )
}

// ─── Multiple-choice options shown after first literature results ─────────────

const LITERATURE_MULTI_CHOICES = [
  "The top result is most relevant — my work diverges in mechanism",
  "There's partial overlap with 1–2 papers — my approach is methodologically distinct",
  "None of these directly address my hypothesis — this is genuinely novel",
  "These results make me want to refine my hypothesis first",
]

function MultiChoiceInput({
  options,
  onSelect,
  disabled,
}: {
  options: string[]
  onSelect: (choice: string) => void
  disabled?: boolean
}) {
  return (
    <div style={{ padding: '8px 16px 8px', borderTop: '1px solid #f5c4b3', background: '#fff8f6' }}>
      <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#aaa', letterSpacing: '0.08em', marginBottom: 6, textTransform: 'uppercase' }}>
        Select your response
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {options.map((option, i) => (
          <button
            key={i}
            onClick={() => !disabled && onSelect(option)}
            disabled={disabled}
            className="w-full text-left px-4 py-2.5 rounded-xl border text-sm transition-all hover:border-[#993C1D] hover:bg-[#fff4ef]"
            style={{
              fontFamily: 'var(--font-dm-sans)',
              background: '#ffffff',
              borderColor: '#e0ddd8',
              color: '#1a1a1a',
              opacity: disabled ? 0.5 : 1,
            }}
          >
            <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#993C1D', marginRight: 8 }}>
              {String.fromCharCode(65 + i)}.{' '}
            </span>
            {option}
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── Readiness gauge (Rachael) ───────────────────────────────────────────────

function ReadinessGauge({
  readiness, messageCount, onBypass, typing,
}: {
  readiness: number
  messageCount: number
  onBypass: () => void
  typing: boolean
}) {
  const showBypass = messageCount >= 3

  return (
    <div style={{ padding: '8px 16px 10px', borderTop: '1px solid #f5c4b3', background: '#fff8f6' }}>
      {/* Gauge bar */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#aaa', letterSpacing: '0.06em' }}>
            {showBypass ? 'Hypothesis readiness' : `${messageCount}/3 minimum exchanges`}
          </span>
          {showBypass && (
            <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: readiness >= 80 ? '#993C1D' : '#bbb', fontWeight: 600 }}>
              {readiness}%
            </span>
          )}
        </div>

        <div style={{ height: 3, background: '#f0ede8', borderRadius: 2, overflow: 'hidden' }}>
          {showBypass ? (
            <div style={{
              height: '100%', borderRadius: 2,
              width: `${readiness}%`,
              background: readiness >= 80 ? '#993C1D' : '#c97a5a',
              transition: 'width 0.6s ease',
            }} />
          ) : (
            <div style={{ display: 'flex', height: '100%', gap: 2 }}>
              {[0, 1, 2].map(i => (
                <div key={i} style={{
                  flex: 1, borderRadius: 2,
                  background: i < messageCount ? '#993C1D' : '#f0ede8',
                  transition: 'background 0.3s',
                }} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Bypass button — appears at 3+ messages */}
      {showBypass && (
        <button
          onClick={onBypass}
          disabled={typing}
          className="w-full mt-2 px-4 py-2 rounded-xl border text-xs transition-all hover:border-[#993C1D]"
          style={{
            fontFamily: 'var(--font-dm-sans)',
            background: readiness >= 70 ? '#fff4ef' : '#faf9f7',
            borderColor: '#f5c4b3',
            color: '#993C1D',
            opacity: typing ? 0.5 : 1,
          }}
        >
          I can&apos;t take it anymore — go straight to Eric →
        </button>
      )}
    </div>
  )
}

// ─── Eric "Talk to Faith" strip ───────────────────────────────────────────────

function EricProceedStrip({ onProceed }: { onProceed: () => void }) {
  return (
    <div style={{ padding: '8px 16px', borderTop: '1px solid #f0ede8' }}>
      <button
        onClick={onProceed}
        className="w-full px-4 py-2.5 rounded-xl text-sm font-medium transition-all hover:bg-[#e8f3ff]"
        style={{ background: '#EEF5FD', borderColor: '#B5D4F4', border: '1px solid #B5D4F4', color: '#185FA5', fontFamily: 'var(--font-dm-sans)' }}
      >
        Eric&apos;s workflow looks good — talk to Faith →
      </button>
    </div>
  )
}

// ─── Main component ──────────────────────────────────────────────────────────

const EMPTY_PLAN: PlanData = { hypothesis: '', controls: '', falsifiability: '', equipment: '', budget: '', timeline: '', impact: '' }

export function N3Chat() {
  const [activeTab, setActiveTab] = useState<CharacterId>('rachael')
  const [stages, setStages] = useState<Stages>({
    rachael: { messages: [], messageCount: 0, done: false },
    eric: { messages: [], messageCount: 0, done: false },
    faith: { messages: [], messageCount: 0, done: false },
  })
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const [fireActive, setFireActive] = useState(false)
  const [shaking, setShaking] = useState(false)
  const [activeView, setActiveView] = useState<NavView>('chat')
  const [collectedPapers, setCollectedPapers] = useState<Paper[]>([])
  const [planVersions, setPlanVersions] = useState<Array<{ version: number; label: string; data: PlanData }>>([])
  const planVersionCounter = useRef(0)
  const [jobId, setJobId] = useState<string | null>(null)
  const [showMultiChoice, setShowMultiChoice] = useState(false)
  const [relevantPaperIndices, setRelevantPaperIndices] = useState<Set<number>>(new Set())

  const [agentChips, setAgentChips] = useState<string[]>([])
  const [rachaelProgressText, setRachaelProgressText] = useState('')

  const [ericInventorySections, setEricInventorySections] = useState<InventorySection[]>([])
  const [ericReadyForFaith, setEricReadyForFaith] = useState(false)
  const [ericStage, setEricStage] = useState<EricStage>('relevant_protocols')

  const planData = useRef<PlanData>({ ...EMPTY_PLAN })
  const hypothesisContext = useRef('')
  const ericContext = useRef('')
  const [planDataVersion, setPlanDataVersion] = useState(0)
  const bumpPlan = () => setPlanDataVersion(v => v + 1)

  const chatEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const fireTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rachaelProgressTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const activeChar = CHARACTERS.find(c => c.id === activeTab)!
  const stage = stages[activeTab]

  const isLocked = (id: CharacterId) => {
    if (id === 'rachael') return false
    if (id === 'eric') return !stages.rachael.done
    if (id === 'faith') return !stages.eric.done
    return true
  }

  const isDone = (id: CharacterId) => stages[id].done

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [stages, typing])

  useEffect(() => {
    if (activeTab !== 'rachael') { setFireActive(false); if (fireTimerRef.current) clearTimeout(fireTimerRef.current) }
  }, [activeTab])

  useEffect(() => { setAgentChips([]) }, [activeTab])
  useEffect(() => {
    return () => {
      if (rachaelProgressTimerRef.current) clearInterval(rachaelProgressTimerRef.current)
    }
  }, [])

  // ─── Rachael readiness gauge ─────────────────────────────────────────────
  const rachaelReadiness = useMemo(() => {
    const pd = planData.current
    let score = 0
    if (pd.hypothesis && pd.hypothesis.length > 15) score += 35
    if (pd.controls && pd.controls.length > 15) score += 30
    if (pd.falsifiability && pd.falsifiability.length > 15) score += 25
    score += Math.min(10, stages.rachael.messageCount * 2)
    return Math.min(100, score)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planDataVersion, stages.rachael.messageCount])

  // ─── API callers ─────────────────────────────────────────────────────────

  const callEricAPI = useCallback(async (userMessages: Message[], newCount: number) => {
    try {
      const res = await fetch('/api/chat/eric', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: toBackendMessages(userMessages),
          messageCount: newCount,
          jobId,
          hypothesisContext: hypothesisContext.current,
          ericStage,
          currentInventory: ericInventorySections.length > 0 ? ericInventorySections : undefined,
        }),
      })
      const data = await res.json()
      setTyping(false)

      if (data.planUpdate) { Object.assign(planData.current, data.planUpdate); bumpPlan() }
      if (data.text) ericContext.current += `\nEric: ${data.text}`
      if (data.planUpdate?.budget) ericContext.current += `\nBudget: ${data.planUpdate.budget}`
      if (data.ericStage) setEricStage(data.ericStage)

      if (Array.isArray(data.inventorySections) && data.inventorySections.length > 0) {
        setEricInventorySections(data.inventorySections)
      }

      if (data.materialsConsumables || data.materialsBudget) setEricReadyForFaith(true)
      if (data.chips?.length) setAgentChips(data.chips)

      if (data.text) {
        const ericMessages: Message[] = [{ role: 'character', text: data.text, characterId: 'eric' }]
        const protocolCandidates = data.protocols?.protocol_candidates
        if (Array.isArray(protocolCandidates) && protocolCandidates.length > 0) {
          ericMessages.push({
            role: 'character',
            text: 'Protocol candidates extracted from the literature are below.',
            characterId: 'eric',
            isProtocolArtifact: true,
            protocols: protocolCandidates,
          })
        }
        if (data.tailoredProtocol) {
          ericMessages.push({
            role: 'character',
            text: 'Revised protocol draft.',
            characterId: 'eric',
            isProtocolArtifact: true,
            tailoredProtocol: data.tailoredProtocol,
          })
        }
        if (data.materialsBudget) {
          ericMessages.push({
            role: 'character',
            text: 'Priced materials budget generated from supplier evidence.',
            characterId: 'eric',
            isBudgetArtifact: true,
            materialsBudget: data.materialsBudget,
          })
        }

        setStages(prev => ({
          ...prev,
          eric: {
            ...prev.eric,
            messages: [...prev.eric.messages, ...ericMessages],
            messageCount: newCount,
          },
        }))
      }
    } catch (err) {
      console.error('Eric API error', err)
      setTyping(false)
    }
  }, [ericInventorySections, ericStage, jobId])

  const callFaithAPI = useCallback(async (userMessages: Message[], isRefinement: boolean) => {
    try {
      const res = await fetch('/api/chat/faith', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: toBackendMessages(userMessages),
          jobId,
          hypothesisContext: hypothesisContext.current,
          ericContext: ericContext.current,
        }),
      })
      const data = await res.json()
      setTyping(false)

      if (data.planData) {
        const pd = data.planData as Partial<PlanData>
        if (pd.hypothesis && pd.hypothesis.length > 10) planData.current.hypothesis = pd.hypothesis
        if (pd.controls && pd.controls.length > 20) planData.current.controls = pd.controls
        if (pd.falsifiability && pd.falsifiability.length > 20) planData.current.falsifiability = pd.falsifiability
        if (pd.equipment && pd.equipment.length > 20) planData.current.equipment = pd.equipment
        if (pd.budget && pd.budget.length > 20) planData.current.budget = pd.budget
        if (pd.timeline && pd.timeline.length > 10) planData.current.timeline = pd.timeline
        if (pd.impact && pd.impact.length > 20) planData.current.impact = pd.impact
        bumpPlan()
      }
      const faithPlanSnapshot = { ...planData.current }

      if (isRefinement) {
        planVersionCounter.current += 1
        const vNum = planVersionCounter.current
        setPlanVersions(prev => [
          ...prev,
          { version: vNum, label: `v${vNum} — ${new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`, data: { ...planData.current } },
        ])
      }

      if (data.chips?.length) setAgentChips(data.chips)

      setStages(prev => ({
        ...prev,
        faith: {
          ...prev.faith,
          messages: [
            ...prev.faith.messages,
            {
              role: 'character',
              text: data.text || "Here's your updated plan. Please review the full protocol below and tell me what you want changed, approved, or searched more deeply.",
              characterId: 'faith',
              isFaithProtocol: true,
              planData: faithPlanSnapshot,
            },
          ],
        },
      }))
    } catch (err) {
      console.error('Faith API error', err)
      setTyping(false)
    }
  }, [jobId])

  // ─── Greetings + auto-calls ─────────────────────────────────────────────

  useEffect(() => {
    const s = stages[activeTab]
    if (s.messages.length > 0) return

    const greetings: Record<CharacterId, string> = {
      rachael: "Right. You want to run an experiment. Let's see if it's worth anyone's time. Tell me — what is your hypothesis, and why should I believe it's worth interrogating?",
      eric: "Rachael's signed off the science. Give me a moment — I'm working on the protocol from the papers, then I'll check it with you before we continue.",
      faith: "You made it. Rachael vetted the science, Eric locked in the resources. Let me put the complete plan together.",
    }

    if (activeTab === 'eric') {
      setStages(prev => ({
        ...prev,
        eric: { ...prev.eric, messages: [{ role: 'character', text: greetings.eric, characterId: 'eric' }] },
      }))
      setTyping(true)
      callEricAPI([], 0)
      return
    }

    if (activeTab === 'faith') {
      setStages(prev => ({
        ...prev,
        faith: { ...prev.faith, messages: [{ role: 'character', text: greetings.faith, characterId: 'faith' }] },
      }))
      setTyping(true)
      callFaithAPI([], false)
      return
    }

    setStages(prev => ({
      ...prev,
      rachael: { ...prev.rachael, messages: [{ role: 'character', text: greetings.rachael, characterId: 'rachael' }] },
    }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  // ─── Send ───────────────────────────────────────────────────────────────

  const handleSend = useCallback(async (overrideText?: string) => {
    const text = (overrideText !== undefined ? overrideText : input).trim()
    if (!text || typing || stage.done) return

    const newCount = stage.messageCount + 1
    if (overrideText === undefined) setInput('')

    const userMsg: Message = { role: 'user', text }
    const updatedMessages: Message[] = [...stage.messages, userMsg]

    setStages(prev => ({
      ...prev,
      [activeTab]: { ...prev[activeTab], messages: [...prev[activeTab].messages, userMsg], messageCount: newCount },
    }))
    setTyping(true)
    setAgentChips([])

    if (activeTab === 'rachael') {
      let progressStep = 0
      try {
        setRachaelProgressText(RACHAEL_PROGRESS_STEPS[0])
        if (rachaelProgressTimerRef.current) clearInterval(rachaelProgressTimerRef.current)
        rachaelProgressTimerRef.current = setInterval(() => {
          progressStep = Math.min(progressStep + 1, RACHAEL_PROGRESS_STEPS.length - 1)
          setRachaelProgressText(RACHAEL_PROGRESS_STEPS[progressStep])
        }, 12000)

        const res = await fetch('/api/chat/rachael', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            messages: toBackendMessages(updatedMessages),
            messageCount: newCount,
            jobId,
          }),
        })
        const raw = await res.text()
        const data = raw ? JSON.parse(raw) : {}

        if (!res.ok) {
          const detail = typeof data.detail === 'string'
            ? data.detail
            : `Rachael request failed with status ${res.status}.`
          setTyping(false)
          setRachaelProgressText('')
          if (rachaelProgressTimerRef.current) clearInterval(rachaelProgressTimerRef.current)
          setStages(prev => ({
            ...prev,
            rachael: {
              ...prev.rachael,
              messages: [
                ...prev.rachael.messages,
                {
                  role: 'character',
                  text: `Backend detail: ${detail}`,
                  characterId: 'rachael',
                },
              ],
            },
          }))
          setAgentChips(['Retry question', 'Shorten hypothesis prompt', 'Check backend OpenAI config'])
          return
        }
        setTyping(false)
        setRachaelProgressText('')
        if (rachaelProgressTimerRef.current) clearInterval(rachaelProgressTimerRef.current)

        setShaking(true); setTimeout(() => setShaking(false), 500)
        setFireActive(true)
        if (fireTimerRef.current) clearTimeout(fireTimerRef.current)
        fireTimerRef.current = setTimeout(() => setFireActive(false), 3000)

        if (data.planUpdate) { Object.assign(planData.current, data.planUpdate); bumpPlan() }
        if (data.jobId) setJobId(data.jobId)
        const responseText = data.text || 'Rachael did not return text. Check backend detail logs.'
        hypothesisContext.current += `\nUser: ${text}\nRachael: ${responseText}`

        if (data.chips?.length) setAgentChips(data.chips)

        const trail: TrailSequence | undefined = data.trailSteps?.length ? data.trailSteps : undefined
        const newMsgs: Message[] = [
          { role: 'character', text: responseText, characterId: 'rachael', trail },
        ]

        if (newCount === 1 && data.papers?.length) {
          setCollectedPapers(data.papers)
          newMsgs.push({
            role: 'character', text: "I pulled the closest Literature QC matches.", characterId: 'rachael',
            isLiterature: true, papers: data.papers.slice(0, 5), similarityFlag: data.similarityFlag,
          })
          newMsgs.push({
            role: 'character',
            text: "Have you read any of these? Which is most relevant — or is this genuinely breaking new ground?",
            characterId: 'rachael',
          })
          setShowMultiChoice(true)
        }

        setStages(prev => ({
          ...prev,
          rachael: { ...prev.rachael, messages: [...prev.rachael.messages, ...newMsgs] },
        }))
      } catch (err) {
        console.error('Rachael error', err)
        setTyping(false)
        setRachaelProgressText('')
        if (rachaelProgressTimerRef.current) clearInterval(rachaelProgressTimerRef.current)
        const detail = err instanceof Error ? err.message : String(err)
        setStages(prev => ({
          ...prev,
          rachael: {
            ...prev.rachael,
            messages: [
              ...prev.rachael.messages,
              {
                role: 'character',
                text: `Backend detail: ${detail}`,
                characterId: 'rachael',
              },
            ],
          },
        }))
        setAgentChips(['Retry question', 'Check backend server', 'Check API keys'])
      }
    } else if (activeTab === 'eric') {
      callEricAPI(updatedMessages, newCount)
    } else if (activeTab === 'faith') {
      callFaithAPI(updatedMessages, true)
    }
  }, [input, typing, stage, activeTab, callEricAPI, callFaithAPI, jobId])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const handleBypassRachael = () => {
    setStages(prev => ({
      ...prev,
      rachael: {
        ...prev.rachael,
        messages: [
          ...prev.rachael.messages,
          { role: 'character', text: "Right. That'll have to do. You've given me enough to work with — barely. Eric's waiting. Don't embarrass me.", characterId: 'rachael' },
        ],
        done: true,
      },
    }))
  }

  const handleMultiChoiceSelect = useCallback((choice: string) => {
    setShowMultiChoice(false)
    handleSend(choice)
  }, [handleSend])

  const handleEricProceed = () => {
    setStages(prev => ({ ...prev, eric: { ...prev.eric, done: true } }))
    setActiveTab('faith')
  }

  const handleTabClick = (id: CharacterId) => { if (!isLocked(id)) setActiveTab(id) }

  const handleAdvance = () => {
    if (activeTab === 'rachael' && stages.rachael.done) setActiveTab('eric')
    else if (activeTab === 'eric' && stages.eric.done) setActiveTab('faith')
  }

  // ─── Chips ──────────────────────────────────────────────────────────────
  const suggestedChips = useMemo(() => {
    if (stage.done) return []
    if (agentChips.length > 0) return agentChips
    if (stage.messageCount === 0) return getContextualChips(activeTab, 0, '', false, [])
    return []
  }, [agentChips, stage.done, stage.messageCount, activeTab])

  const canAdvance = (activeTab === 'rachael' && stages.rachael.done) || (activeTab === 'eric' && stages.eric.done)

  void planDataVersion
  const displayPlanData: PlanData = {
    hypothesis: planData.current.hypothesis || 'Your hypothesis will appear here',
    controls: planData.current.controls || "Protocol will appear after Rachael's review",
    falsifiability: planData.current.falsifiability || 'Falsifiability criteria from discussion',
    equipment: planData.current.equipment || 'Materials list from Eric',
    budget: planData.current.budget || 'Budget estimate',
    timeline: planData.current.timeline || 'Timeline',
    impact: planData.current.impact || 'Impact statement from Faith',
  }

  const hasLiterature = collectedPapers.length > 0
  const hasTools = ericInventorySections.length > 0
  const hasProtocol = Boolean(planData.current.controls.trim()) || stages.faith.messages.length > 0

  const isRachael = activeTab === 'rachael'
  const panelBg = isRachael ? '#fff8f6' : activeTab === 'eric' ? '#f6f8ff' : '#f6fff9'
  const borderColor = isRachael ? '#f5c4b3' : activeTab === 'eric' ? '#B5D4F4' : '#9FE1CB'

  return (
    <div style={{ display: 'flex', height: '100dvh', width: '100%', background: panelBg, fontFamily: 'var(--font-dm-sans)', overflow: 'hidden' }}>
      <SideNav
        activeView={activeView}
        onViewChange={setActiveView}
        hasLiterature={hasLiterature}
        hasTools={hasTools}
        hasProtocol={hasProtocol}
      />

      {/* Fire canvas — positioned behind Rachael header */}
      {activeTab === 'rachael' && (
        <div style={{ position: 'fixed', top: 0, left: 52, right: 0, height: 80, pointerEvents: 'none', zIndex: 0 }}>
          <FireCanvas active={fireActive} width={800} height={80} />
        </div>
      )}

      {activeView === 'literature' && (
        <LiteraturePanel
          papers={collectedPapers}
          relevantIndices={relevantPaperIndices}
          onToggleRelevant={i => setRelevantPaperIndices(prev => {
            const next = new Set(prev)
            if (next.has(i)) next.delete(i); else next.add(i)
            return next
          })}
        />
      )}
      {activeView === 'tools' && <LabToolsPanel hasInventory={hasTools} inventorySections={ericInventorySections} papers={collectedPapers} onInventoryUpdate={setEricInventorySections} />}
      {activeView === 'protocol' && <ProtocolPanel planData={displayPlanData} versions={planVersions} papers={collectedPapers} />}

      {/* ── Chat panel ── */}
      <div style={{ flex: 1, display: activeView === 'chat' ? 'flex' : 'none', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>

        {activeTab === 'rachael' && (
          <div style={{ position: 'absolute', top: 8, right: 16, zIndex: 10, animation: shaking ? 'shake 0.45s ease' : 'none' }}>
            <style>{`.shake-anim { animation: shake 0.45s ease; } @keyframes shake { 0%,100%{transform:translateX(0)} 15%{transform:translateX(-4px)} 30%{transform:translateX(4px)} 45%{transform:translateX(-3px)} 60%{transform:translateX(3px)} 75%{transform:translateX(-2px)} 90%{transform:translateX(2px)} }`}</style>
          </div>
        )}

        {/* Tab bar */}
        <div style={{ display: 'flex', borderBottom: `1px solid ${borderColor}`, background: isRachael ? '#fff4ef' : '#ffffff', flexShrink: 0, position: 'relative', zIndex: 1 }}>
          {CHARACTERS.map(char => {
            const locked = isLocked(char.id)
            const active = activeTab === char.id
            const done = isDone(char.id)
            return (
              <button key={char.id} onClick={() => handleTabClick(char.id)} disabled={locked}
                className="flex-1 flex items-center gap-3 px-4 py-5 transition-all relative"
                style={{
                  background: active ? '#f5f3ef' : 'transparent',
                  opacity: locked ? 0.32 : 1,
                  cursor: locked ? 'not-allowed' : 'pointer',
                  borderBottom: active ? `2px solid ${char.avatarText}` : '2px solid transparent',
                }}
              >
                <div style={{ position: 'relative' }}>
                  <Avatar char={char} size={32} />
                  {done && (
                    <div style={{ position: 'absolute', bottom: -2, right: -2, width: 12, height: 12, borderRadius: '50%', background: '#1D9E75', border: '2px solid #fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <svg width="6" height="6" viewBox="0 0 6 6" fill="none"><path d="M1 3l1.5 1.5 2.5-3" stroke="#fff" strokeWidth="1.2" strokeLinecap="round" /></svg>
                    </div>
                  )}
                </div>
                <div style={{ textAlign: 'left' }}>
                  <div style={{ fontFamily: 'var(--font-playfair)', fontSize: 13, fontWeight: 600, color: active ? char.nameColor : '#555' }}>
                    {char.name}
                  </div>
                  <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#aaa', letterSpacing: '0.04em' }}>
                    {char.role}
                  </div>
                </div>
              </button>
            )
          })}
        </div>

        {/* Character header */}
        <div style={{
          padding: '12px 20px', background: activeChar.headerBg, borderBottom: `1px solid ${activeChar.bubbleBorder}`,
          display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0, position: 'relative', zIndex: 1,
        }}>
          <Avatar char={activeChar} size={40} />
          <div>
            <div style={{ fontFamily: 'var(--font-playfair)', fontSize: 16, fontWeight: 700, color: activeChar.nameColor, fontStyle: 'italic' }}>
              {activeChar.name}
            </div>
            <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#999', letterSpacing: '0.04em' }}>
              {activeChar.role}{' '}
              <MoodPill label={activeChar.moodPill} color={activeChar.nameColor} />
            </div>
          </div>
        </div>

        {/* Chat messages */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>

          {stage.messages.map((msg, i) => {
            if (msg.role === 'character') {
              const char = CHARACTERS.find(c => c.id === msg.characterId) ?? activeChar

              if (msg.isPlanCard) {
                return (
                  <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
                    <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: char.nameColor }}>
                      {char.name}{' '}
                    </span>
                    <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 13, color: activeChar.textColor, background: activeChar.bubbleBg, border: `1px solid ${activeChar.bubbleBorder}`, borderRadius: '4px 14px 14px 14px', padding: '10px 14px', maxWidth: '85%' }}>
                      <FormattedMessage text={msg.text} />
                    </div>
                    <PlanCard {...displayPlanData} papers={collectedPapers} />
                  </div>
                )
              }

              if (msg.isFaithProtocol && msg.planData) {
                return (
                  <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
                    <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: char.nameColor }}>
                      {char.name}{' '}
                    </span>
                    <FaithProtocolCard planData={msg.planData} papers={collectedPapers} />
                    <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 13, color: activeChar.textColor, background: activeChar.bubbleBg, border: `1px solid ${activeChar.bubbleBorder}`, borderRadius: '4px 14px 14px 14px', padding: '10px 14px', maxWidth: '85%' }}>
                      <FormattedMessage text={msg.text} />
                    </div>
                  </div>
                )
              }

              if (msg.isLiterature) {
                return (
                  <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: char.nameColor }}>{char.name}{' '}</span>
                    {msg.similarityFlag && <SimilarityBadge flag={msg.similarityFlag} />}
                    <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 13, color: activeChar.textColor, background: activeChar.bubbleBg, border: `1px solid ${activeChar.bubbleBorder}`, borderRadius: '4px 14px 14px 14px', padding: '10px 14px', maxWidth: '85%' }}>
                      <FormattedMessage text={msg.text} />
                    </div>
                    {msg.papers && <LiteratureCard papers={msg.papers} />}
                  </div>
                )
              }

              if (msg.isProtocolArtifact) {
                return (
                  <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: char.nameColor }}>{char.name}{' '}</span>
                    <ProtocolArtifactCard
                      protocols={msg.protocols}
                      tailoredProtocol={msg.tailoredProtocol}
                    />
                  </div>
                )
              }

              if (msg.isBudgetArtifact && msg.materialsBudget) {
                return (
                  <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: char.nameColor }}>{char.name}{' '}</span>
                    <BudgetArtifactCard materialsBudget={msg.materialsBudget} />
                  </div>
                )
              }

              return (
                <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {msg.trail && <ThinkingTrail steps={msg.trail} accentColor={char.nameColor} />}
                  <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: char.nameColor }}>{char.name}{' '}</span>
                  <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 13, color: activeChar.textColor, background: activeChar.bubbleBg, border: `1px solid ${activeChar.bubbleBorder}`, borderRadius: '4px 14px 14px 14px', padding: '10px 14px', maxWidth: '85%', lineHeight: 1.6 }}>
                    <FormattedMessage text={msg.text} />
                  </div>
                </div>
              )
            }

            return (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-end' }}>
                <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#aaa' }}>You{' '}</span>
                <div style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 13, color: '#1a1a1a', background: '#ffffff', border: '1px solid #e0ddd8', borderRadius: '14px 4px 14px 14px', padding: '10px 14px', maxWidth: '75%', lineHeight: 1.6 }}>
                  <FormattedMessage text={msg.text} />
                </div>
              </div>
            )
          })}

          {/* Eric live inventory — appears at the end, after messages */}
          {activeTab === 'eric' && ericInventorySections.length > 0 && (
            <div style={{ marginTop: 4 }}>
              <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#185FA5', letterSpacing: '0.06em', marginBottom: 6 }}>
                Eric · Live inventory
              </div>
              <InventoryTable sections={ericInventorySections} papers={collectedPapers} onUpdate={setEricInventorySections} />
            </div>
          )}

          {typing && activeTab === 'rachael' ? (
            <div style={{ padding: '6px 0' }}>
              <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: activeChar.nameColor, marginBottom: 4 }}>
                Rachael · thinking
              </div>
              <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#7a5a4d', marginBottom: 6 }}>
                {rachaelProgressText || RACHAEL_PROGRESS_STEPS[0]}
              </div>
              <ThinkingTrail steps={RACHAEL_TRAILS[Math.min(stage.messageCount, RACHAEL_TRAILS.length - 1)]} accentColor={activeChar.nameColor} />
            </div>
          ) : typing ? (
            <TypingDots char={activeChar} />
          ) : null}

          <div ref={chatEndRef} />
        </div>

        {/* Chips */}
        {!stage.done && !showMultiChoice && suggestedChips.length > 0 && (
          <div style={{ padding: '6px 16px', display: 'flex', gap: 5, flexWrap: 'wrap', borderTop: `1px solid ${borderColor}` }}>
            {suggestedChips.map(chip => (
              <button key={chip} onClick={() => { setInput(chip); inputRef.current?.focus() }}
                className="px-2.5 py-1 rounded-full border text-[10px] transition-all hover:border-[#aaa]"
                style={{ fontFamily: 'var(--font-ibm-plex-mono)', background: '#ffffff', borderColor: '#e0ddd8', color: '#666' }}>
                {chip}
              </button>
            ))}
          </div>
        )}

        {/* Eric: Talk to Faith strip */}
        {activeTab === 'eric' && ericReadyForFaith && !stages.eric.done && (
          <EricProceedStrip onProceed={handleEricProceed} />
        )}

        {/* Multi-choice */}
        {showMultiChoice && activeTab === 'rachael' && !stage.done && (
          <MultiChoiceInput options={LITERATURE_MULTI_CHOICES} onSelect={handleMultiChoiceSelect} disabled={typing} />
        )}

        {/* Input row */}
        {!(showMultiChoice && activeTab === 'rachael' && !stage.done) && (
          <div style={{ padding: '10px 16px', borderTop: `1px solid ${borderColor}`, display: 'flex', gap: 8, background: isRachael ? '#fff4ef' : '#ffffff', flexShrink: 0 }}>
            {canAdvance ? (
              <button onClick={handleAdvance}
                className="flex-1 px-4 py-2.5 rounded-xl text-sm font-medium transition-all"
                style={{ background: activeChar.avatarBg, color: activeChar.nameColor, border: `1px solid ${activeChar.bubbleBorder}`, fontFamily: 'var(--font-dm-sans)' }}
              >
                {activeTab === 'rachael' ? 'Talk to Eric →' : 'Talk to Faith →'}
              </button>
            ) : (
              <>
                <input
                  ref={inputRef}
                  value={input}
                  onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown}
                  disabled={typing || stage.done}
                  placeholder={`Reply to ${activeChar.name}...`}
                  className="flex-1 px-3.5 py-2 rounded-xl text-sm outline-none transition-all"
                  style={{ background: '#ffffff', border: '1px solid #e0ddd8', color: '#1a1a1a', fontFamily: 'var(--font-dm-sans)' }}
                />
                <button onClick={() => handleSend()}
                  disabled={typing || !input.trim() || stage.done}
                  className="px-3.5 py-2 rounded-xl text-sm font-medium border transition-all shrink-0"
                  style={{ background: '#ffffff', borderColor: '#e0ddd8', color: '#555', fontFamily: 'var(--font-dm-sans)', opacity: typing || !input.trim() ? 0.5 : 1 }}>
                  Send
                </button>
              </>
            )}
          </div>
        )}

        {/* Rachael readiness gauge */}
        {activeTab === 'rachael' && !stages.rachael.done && (
          <ReadinessGauge
            readiness={rachaelReadiness}
            messageCount={stages.rachael.messageCount}
            onBypass={handleBypassRachael}
            typing={typing}
          />
        )}
      </div>
    </div>
  )
}
