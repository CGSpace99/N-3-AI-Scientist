'use client'

import type { Paper } from '@/components/literature-card'

interface LiteraturePanelProps {
  papers: Paper[]
  relevantIndices?: Set<number>
  onToggleRelevant?: (i: number) => void
}

export function LiteraturePanel({ papers, relevantIndices, onToggleRelevant }: LiteraturePanelProps) {
  if (papers.length === 0) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: '#bbb', padding: 40 }}>
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
          <rect x="4" y="4" width="24" height="24" rx="3" stroke="currentColor" strokeWidth="1.5" fill="none" />
          <path d="M9 11h14M9 16h14M9 21h8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        <span style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 13, color: '#bbb', textAlign: 'center' }}>
          Literature will appear here after Rachael reviews your first message.
        </span>
      </div>
    )
  }

  const relevantCount = relevantIndices?.size ?? 0

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #e0ddd8', background: '#faf9f7', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <rect x="1" y="1" width="12" height="12" rx="2" stroke="#993C1D" strokeWidth="1.2" fill="none" />
          <path d="M3 4h8M3 7h8M3 10h5" stroke="#993C1D" strokeWidth="1" strokeLinecap="round" />
        </svg>
        <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#555', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
          Database scan
        </span>
        <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#999', marginLeft: 2 }}>
          {papers.length} results
        </span>
        {relevantCount > 0 && (
          <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#993C1D', background: '#fff4ef', padding: '1px 5px', borderRadius: 4, border: '1px solid #f5c4b3' }}>
            {relevantCount} marked relevant
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          {relevantCount > 0 && (
            <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#bbb' }}>click paper to mark</span>
          )}
          <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#999', padding: '2px 6px', border: '1px solid #e0ddd8', borderRadius: 4 }}>Rachael</span>
        </div>
      </div>

      {relevantCount === 0 && (
        <div style={{ padding: '8px 16px', background: '#fffdf9', borderBottom: '1px solid #f0ede8' }}>
          <p style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#aaa', margin: 0 }}>
            Click any paper to mark it as most relevant — it will be highlighted in orange.
          </p>
        </div>
      )}

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {papers.map((paper, i) => {
          const isRelevant = relevantIndices?.has(i) ?? false
          return (
            <div
              key={i}
              onClick={() => onToggleRelevant?.(i)}
              style={{
                padding: '14px 16px',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                cursor: 'pointer',
                background: isRelevant ? '#fff4ef' : '#ffffff',
                borderLeft: isRelevant ? '3px solid #993C1D' : '3px solid transparent',
                borderBottom: '1px solid #f0ede8',
                transition: 'all 0.12s',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#bbb' }}>#{i + 1}</span>
                {isRelevant && (
                  <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#993C1D', background: '#fff4ef', border: '1px solid #f5c4b3', padding: '1px 5px', borderRadius: 3 }}>
                    ✓ Relevant
                  </span>
                )}
                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <div style={{ width: 40, height: 3, background: '#f0ede8', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ width: `${paper.similarity}%`, height: '100%', background: '#993C1D', borderRadius: 2 }} />
                  </div>
                  <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#993C1D' }}>{paper.similarity}%</span>
                </div>
              </div>

              <p style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, fontWeight: 500, color: '#1a1a1a', margin: 0, lineHeight: 1.45 }}>
                {paper.title}
              </p>
              <p style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#777', margin: 0 }}>
                {paper.authors}
              </p>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#999' }}>{paper.journal}</span>
                <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#bbb' }}>{paper.year}</span>
              </div>

              {paper.url && (
                <div onClick={e => e.stopPropagation()}>
                  <a href={paper.url} target="_blank" rel="noopener noreferrer"
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#185FA5', textDecoration: 'none' }}>
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                      <path d="M2 8l6-6M8 8V2H2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                    </svg>
                    View protocol ↗
                  </a>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
