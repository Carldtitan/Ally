// AccessiFix's sidebar, structure and markup as it ships:
//
//   .sidebar
//     .brand-row      .brand > BrandMark + name
//     .sidebar-context  <small>Target</small><strong>owner/repo</strong>
//     .side-nav       .nav-item[aria-current="page"] > Icon + <span>
//     .sidebar-bottom .account-link > .avatar + .account-copy + chevron

import { BrandMark, Icon, type IconName } from '../Icon'

export type Tab = 'new' | 'runs' | 'benchmark' | 'loop'

interface Props {
  tab: Tab
  setTab: (t: Tab) => void
  target: string
  openFindings: number
}

const NAV: { id: Tab; label: string; icon: IconName }[] = [
  { id: 'new', label: 'Overview', icon: 'home' },
  { id: 'runs', label: 'Runs', icon: 'activity' },
  { id: 'benchmark', label: 'Findings', icon: 'warning' },
  { id: 'loop', label: 'The loop', icon: 'target' },
]

export function Sidebar({ tab, setTab, target, openFindings }: Props) {
  return (
    <aside className="sidebar" aria-label="Main">
      <div className="brand-row">
        <span className="brand">
          <BrandMark />
          <span>Ally</span>
        </span>
      </div>

      <p className="sidebar-context">
        <small>Target</small>
        <strong>{target || 'None yet'}</strong>
      </p>

      <nav className="side-nav" aria-label="Sections">
        {NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            className="nav-item"
            aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => setTab(item.id)}
            style={{ width: '100%', background: 'none', cursor: 'pointer', textAlign: 'left' }}
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
            {item.id === 'runs' && openFindings > 0 && (
              <span className="section-count" style={{ marginLeft: 'auto' }}>
                {openFindings}
              </span>
            )}
          </button>
        ))}
      </nav>

      <div className="sidebar-bottom">
        <span className="account-link">
          <span className="avatar" aria-hidden="true">AL</span>
          <span className="account-copy">
            <strong>Ally</strong>
            <span>Keyboard accessibility agent</span>
          </span>
        </span>
      </div>
    </aside>
  )
}
