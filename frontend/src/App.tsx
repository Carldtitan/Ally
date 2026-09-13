import { useEffect, useState } from 'react'
import { api, type Job } from './api'
import { Sidebar, type Tab } from './components/Sidebar'
import { NewAudit } from './components/NewAudit'
import { JobRun } from './components/JobRun'
import { Benchmark, Loop } from './components/Evidence'
import { Icon } from './Icon'

export default function App() {
  const [tab, setTab] = useState<Tab>('new')
  // Light unless someone chose otherwise, exactly as AccessiFix does. Following
  // prefers-color-scheme instead meant a machine set to dark never saw the
  // template's actual face: Notion white, grey sidebar, charcoal text, blue
  // accent. Dark is a variant of this world, not the default view of it.
  const [job, setJob] = useState<Job | null>(null)
  const [past, setPast] = useState<{ id: string; url: string; repo: string
                                     status: string; phase: string
                                     findings: number; pr_url: string }[]>([])
  const [pastErr, setPastErr] = useState('')

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
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <Sidebar
        tab={tab}
        setTab={setTab}
        target={job ? job.repo.replace(/^https?:\/\/(www\.)?github\.com\//, '') : ''}
        openFindings={openFindings}
      />

      <div className="app-main">

        <main className="dashboard-page" id="main">
          {tab === 'new' && <NewAudit onStarted={started} />}

          {tab === 'runs' && (
            job ? (
              <JobRun job={job} onUpdate={setJob} />
            ) : (
              <>
                <h1 >Past runs</h1>
                {pastErr && (
                  <div className="status-label status-blocked" style={{ marginTop: 12 }}>
                    <Icon name="eye" /><span>{pastErr}</span>
                  </div>
                )}
                {past.length === 0 ? (
                  <div className="quiet-panel" style={{ marginTop: 18 }}>
                    <strong>Nothing has run yet on this machine.</strong>
                    Start one from New audit and it will appear here as it works.
                  </div>
                ) : (
                  <table className="grid" style={{ marginTop: 16 }}>
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
                            <span className={`status-label ${p.status === 'done' ? 'status-done'
                              : p.status === 'failed' ? 'status-blocked' : 'status-live'}`}>
                              {p.status === 'running' ? `${p.status} · ${p.phase}` : p.status}
                            </span>
                          </td>
                          <td className="num">{p.findings}</td>
                          <td>
                            {p.pr_url
                              ? <a href={p.pr_url} target="_blank" rel="noreferrer">open</a>
                              : <span className="muted">—</span>}
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
