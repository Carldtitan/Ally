// AccessiFix's sidebar, emoji and all. The structure its CSS depends on:
//
//   .notion-sidebar            space-between
//     .notion-sidebar-top        header + nav
//     .notion-sidebar-footer     pinned to the bottom
//   .notion-sidebar-item       space-between
//     .notion-sidebar-item-label   icon + text together on the left
//     .notion-sidebar-badge        optional, right
//
// An earlier pass replaced every emoji with drawn SVG on a general design
// principle. The brief pins this look and the emoji are part of it -- Notion
// uses emoji as page and nav icons natively, and AccessiFix is a Notion
// pastiche. They are aria-hidden; the label beside each one carries the name.

export type Tab = 'new' | 'runs' | 'benchmark' | 'loop'

interface Props {
  tab: Tab
  setTab: (t: Tab) => void
  theme: 'light' | 'dark'
  setTheme: (t: 'light' | 'dark') => void
  openFindings: number
}

const MAIN: { id: Tab; label: string; emoji: string }[] = [
  { id: 'new', label: 'New Audit', emoji: '🎯' },
  { id: 'runs', label: 'Workspace', emoji: '💻' },
]
const EVIDENCE: { id: Tab; label: string; emoji: string }[] = [
  { id: 'benchmark', label: 'Benchmark', emoji: '📊' },
  { id: 'loop', label: 'The Loop', emoji: '🔄' },
]

export function Sidebar({ tab, setTab, theme, setTheme, openFindings }: Props) {
  const item = (m: { id: Tab; label: string; emoji: string }, badge = 0) => (
    <button
      key={m.id}
      className={`notion-sidebar-item ${tab === m.id ? 'active' : ''}`}
      aria-current={tab === m.id ? 'page' : undefined}
      onClick={() => setTab(m.id)}
    >
      <span className="notion-sidebar-item-label">
        <span className="sidebar-emoji" aria-hidden="true">{m.emoji}</span>
        {m.label}
      </span>
      {badge ? <span className="notion-sidebar-badge tnum">{badge}</span> : null}
    </button>
  )

  return (
    <aside className="notion-sidebar">
      <div className="notion-sidebar-top">
        <div className="notion-sidebar-header">
          <span className="notion-sidebar-avatar" aria-hidden="true">⌨️</span>
          <span className="notion-sidebar-identity">
            <span className="notion-sidebar-title">Ally</span>
            <span className="notion-sidebar-sub">Keyboard Accessibility</span>
          </span>
        </div>

        <nav className="notion-sidebar-nav" aria-label="Sections">
          {MAIN.map((m) => item(m, m.id === 'runs' ? openFindings : 0))}
          <span className="notion-sidebar-section">Evidence</span>
          {EVIDENCE.map((m) => item(m))}
        </nav>
      </div>

      <div className="notion-sidebar-footer">
        <button
          className="notion-sidebar-item"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        >
          <span className="notion-sidebar-item-label">Appearance</span>
          <span className="notion-sidebar-item-label" style={{ fontWeight: 600 }}>
            <span className="sidebar-emoji" aria-hidden="true">
              {theme === 'dark' ? '🌙' : '☀️'}
            </span>
            {theme === 'dark' ? 'Dark' : 'Light'}
          </span>
        </button>
      </div>
    </aside>
  )
}
