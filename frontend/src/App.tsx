import { useEffect, useState } from 'react'
import { api, type Job } from './api'
import { Overview } from './components/Overview'
import { RunPage } from './components/RunPage'
import { Play, Pulse } from './Icons'

export default function App() {
  const [job, setJob] = useState<Job | null>(null)

  useEffect(() => {
    document.title = job ? `${job.url} — Ally` : 'Ally'
  }, [job])

  async function open(id: string) {
    try { setJob(await api.job(id)) } catch { /* the list stays put */ }
  }

  const open_ = job?.findings.filter((f) => f.status === 'failed').length ?? 0

  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>

      <nav className="rail" aria-label="Main">
        <span className="wordmark">
          <span className="mark" aria-hidden="true" />
          Ally
        </span>

        <div className="rail-nav">
          <button
            className="rail-link"
            aria-current={job ? undefined : 'page'}
            onClick={() => setJob(null)}
          >
            <Play size={15} />
            New run
          </button>
          {job && (
            <button className="rail-link" aria-current="page">
              <Pulse size={15} />
              This run
              {open_ > 0 && <span className="count">{open_}</span>}
            </button>
          )}
        </div>

        {job && (
          <div className="rail-foot">
            <div className="rail-target">
              <small>Target</small>
              <strong>{job.repo.replace(/^https?:\/\/(www\.)?github\.com\//, '')}</strong>
            </div>
          </div>
        )}
      </nav>

      <main className="stage" id="main">
        {job
          ? <RunPage job={job} onUpdate={setJob} onBack={() => setJob(null)} />
          : <Overview onStarted={setJob} onOpen={open} />}
      </main>
    </div>
  )
}
