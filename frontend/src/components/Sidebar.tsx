import { IconKeyboard, IconPlay, IconChart, IconLoop, IconSun, IconMoon } from '../icons'

export type Tab = 'new' | 'runs' | 'benchmark' | 'loop'

interface Props {
  tab: Tab
  setTab: (t: Tab) => void
  theme: 'light' | 'dark'
  setTheme: (t: 'light' | 'dark') => void
  openFindings: number
}

const NAV: { id: Tab; label: string; Icon: typeof IconPlay }[] = [
  { id: 'new', label: 'New audit', Icon: IconPlay },
  { id: 'runs', label: 'Past runs', Icon: IconKeyboard },
]
const EVIDENCE: { id: Tab; label: string; Icon: typeof IconPlay }[] = [
  { id: 'benchmark', label: 'Benchmark', Icon: IconChart },
  { id: 'loop', label: 'The loop', Icon: IconLoop },
]

export function Sidebar({ tab, setTab, theme, setTheme, openFindings }: Props) {
  return (
    <aside className="notion-sidebar">
      <div className="notion-sidebar-header">
        <span className="notion-sidebar-mark" aria-hidden="true">
          <IconKeyboard size={15} />
        </span>
        <span>
          <span className="notion-sidebar-title">Ally</span>
          <span className="notion-sidebar-sub">Keyboard accessibility</span>
        </span>
      </div>

      <nav className="notion-sidebar-nav" aria-label="Sections">
        {NAV.map(({ id, label, Icon }) => (
          <button
            key={id}
            className={`notion-sidebar-item ${tab === id ? 'active' : ''}`}
            aria-current={tab === id ? 'page' : undefined}
            onClick={() => setTab(id)}
          >
            <Icon />
            {label}
            {id === 'runs' && openFindings > 0 && (
              <span className="notion-sidebar-badge tnum">{openFindings}</span>
            )}
          </button>
        ))}

        <span className="notion-sidebar-label">Evidence</span>
        {EVIDENCE.map(({ id, label, Icon }) => (
          <button
            key={id}
            className={`notion-sidebar-item ${tab === id ? 'active' : ''}`}
            aria-current={tab === id ? 'page' : undefined}
            onClick={() => setTab(id)}
          >
            <Icon />
            {label}
          </button>
        ))}
      </nav>

      <div className="notion-sidebar-foot">
        <button
          className="notion-sidebar-item"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        >
          {theme === 'dark' ? <IconSun /> : <IconMoon />}
          {theme === 'dark' ? 'Light appearance' : 'Dark appearance'}
        </button>
      </div>
    </aside>
  )
}
