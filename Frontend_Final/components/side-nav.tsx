'use client'

type NavView = 'chat' | 'literature' | 'tools' | 'protocol'

interface SideNavProps {
  activeView: NavView
  onViewChange: (view: NavView) => void
  hasLiterature: boolean
  hasTools: boolean
  hasProtocol: boolean
}

const NAV_ITEMS: { id: NavView; label: string; icon: React.ReactNode }[] = [
  {
    id: 'chat',
    label: 'Chat',
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path d="M2 3a1 1 0 011-1h10a1 1 0 011 1v7a1 1 0 01-1 1H9l-3 2v-2H3a1 1 0 01-1-1V3z" stroke="currentColor" strokeWidth="1.2" fill="none" />
      </svg>
    ),
  },
  {
    id: 'literature',
    label: 'Literature',
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <rect x="2" y="2" width="12" height="12" rx="1.5" stroke="currentColor" strokeWidth="1.2" fill="none" />
        <path d="M4.5 5.5h7M4.5 8h7M4.5 10.5h4" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: 'tools',
    label: 'Lab Tools',
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path d="M5 2v5l-2 3v2h10v-2l-2-3V2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <path d="M5 7h6" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: 'protocol',
    label: 'Protocol',
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path d="M3 2h10v12H3z" stroke="currentColor" strokeWidth="1.2" fill="none" />
        <path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      </svg>
    ),
  },
]

export type { NavView }

export function SideNav({ activeView, onViewChange, hasLiterature, hasTools, hasProtocol }: SideNavProps) {
  const isAvailable = (id: NavView) => {
    if (id === 'chat') return true
    if (id === 'literature') return hasLiterature
    if (id === 'tools') return hasTools
    if (id === 'protocol') return hasProtocol
    return false
  }

  return (
    <div style={{
      width: 52,
      flexShrink: 0,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      padding: '12px 0',
      borderRight: '1px solid #e0ddd8',
      background: '#faf9f7',
      gap: 4,
    }}>
      <div style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, fontWeight: 600, color: '#993C1D', letterSpacing: '0.1em', marginBottom: 12, textAlign: 'center' }}>
        N=3
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, width: '100%', padding: '0 6px' }}>
        {NAV_ITEMS.map((item) => {
          const active = activeView === item.id
          const available = isAvailable(item.id)
          return (
            <div key={item.id} style={{ position: 'relative' }}>
              <button
                onClick={() => available && onViewChange(item.id)}
                disabled={!available}
                title={`${item.label}${!available ? ' (locked)' : ''}`}
                className="relative flex items-center justify-center w-9 h-9 rounded-lg transition-all"
                style={{
                  width: '100%',
                  background: active ? '#ffffff' : 'transparent',
                  color: active ? '#1a1a1a' : available ? '#888' : '#ccc',
                  boxShadow: active ? '0 1px 3px rgba(0,0,0,0.08)' : 'none',
                  border: active ? '1px solid #e0ddd8' : '1px solid transparent',
                  cursor: available ? 'pointer' : 'not-allowed',
                  borderRadius: 8,
                  padding: '8px 0',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {item.icon}
                {!available && item.id !== 'chat' && (
                  <span style={{ position: 'absolute', top: 4, right: 4, width: 5, height: 5, borderRadius: '50%', background: '#e0ddd8' }} />
                )}
                {available && item.id !== 'chat' && !active && (
                  <span style={{ position: 'absolute', top: 4, right: 4, width: 5, height: 5, borderRadius: '50%', background: '#1D9E75' }} />
                )}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
