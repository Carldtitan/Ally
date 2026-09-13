import { useEffect, useState } from 'react'
import { api, type Job } from './api'
import { Sidebar, type Tab } from './components/Sidebar'
import { NewAudit } from './components/NewAudit'
import { JobRun } from './components/JobRun'
import { Benchmark, Loop } from './components/Evidence'
import { IconInfo } from './icons'

const CRUMB: Record<Tab, string> = {
  new: 'New audit',
  runs: 'Past runs',
  benchmark: 'Benchmark',
  loop: 'The loop',
}

export default function App() {
  const [tab, setTab] = useState<Tab>('new')
  // Light unless someone chose otherwise, exactly as AccessiFix does. Following
  // prefers-color-scheme instead meant a machine set to dark never saw the
  // template's actual face: Notion white, grey sidebar, charcoal text, blue
  // accent. Dark is a variant of this world, not the default view of it.
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('notion-theme')
    return saved === 'dark' ? 'dark' : 'light'
  })
  const [job, setJob] = useState<Job | null>(null)
  const [past, setPast] = useState<{ id: string; url: string; repo: string
                                     status: string; phase: string
                                     findings: number; pr_url: string }[]>([])
  const [pastErr, setPastErr] = useState('')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('notion-theme', theme)
  }, [theme])

  useEffect(() => {
    if (tab !== 'runs') return
    api.jobs().then((d) => setPast(d.jobs))
      .catch((e) => setPastErr(String(e.message ?? e)))
  }, [tab])

  const openFindings = job?.findings.filter((f) => f.status === 'failed').length ?? 0

  function started(j: Job) {
    setJob(j)
    setTab('runs')
  }

  return (
    <div className="notion-layout">
      <a className="skip-link" href="#main">Skip to content</a>
      <Sidebar
        tab={tab}
        setTab={setTab}
        theme={theme}
        setTheme={setTheme}
        openFindings={openFindings}
      />

      <div className="notion-frame">
        <div className="notion-top-bar">
          <div className="notion-breadcrumbs">
            <span>Ally</span>
            <span aria-hidden="true">/</span>
            <span className="notion-breadcrumbs-item">{CRUMB[tab]}</span>
          </div>
          {job && (job.status === 'running' || job.status === 'queued') && (
            <span className="notion-tag blue">
              running · {job.phase}
            </span>
          )}
        </div>

        <main className="notion-content" id="main">
          {tab === 'new' && <NewAudit onStarted={started} />}

          {tab === 'runs' && (
            job ? (
              <JobRun job={job} onUpdate={setJob} />
            ) : (
              <>
                <h1 className="notion-page-title">Past runs</h1>
                {pastErr && (
                  <div className="notion-callout danger" style={{ marginTop: 12 }}>
                    <IconInfo /><span>{pastErr}</span>
                  </div>
                )}
                {past.length === 0 ? (
                  <div className="empty" style={{ marginTop: 18 }}>
                    <strong>Nothing has run yet on this machine.</strong>
                    Start one from New audit and it will appear here as it works.
                  </div>
                ) : (
                  <table className="notion-table" style={{ marginTop: 16 }}>
                    <thead>
                      <tr>
                        <th>Page</th><th>Repository</th><th>State</th>
                        <th className="num">Findings</th><th>Pull request</th>
                      </tr>
                    </thead>
                    <tbody>
                      {past.map((p) => (
                        <tr key={p.id}>
                          <td className="mono">{p.url}</td>
                          <td className="mono">
                            {p.repo.replace(/^https?:\/\/(www\.)?github\.com\//, '')}
                          </td>
                          <td>
                            <span className={`notion-tag ${p.status === 'done' ? 'green'
                              : p.status === 'failed' ? 'red' : 'blue'}`}>
                              {p.status === 'running' ? `${p.status} · ${p.phase}` : p.status}
                            </span>
                          </td>
                          <td className="num">{p.findings}</td>
                          <td>
                            {p.pr_url
                              ? <a href={p.pr_url} target="_blank" rel="noreferrer">open</a>
                              : <span className="hint">—</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            )
          )}

          {tab === 'benchmark' && <Benchmark />}
          {tab === 'loop' && <Loop />}
        </main>
      </div>
    </div>
  )
}
