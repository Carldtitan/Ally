// The Loop: what Ally learned from its own patches, across the runs started here.
//
// Two loops at different timescales. Inside one run the patcher writes a fix,
// applies it, rebuilds and re-audits, so the contradiction comes from a rebuilt
// page rather than the model's own opinion. Between runs every patch outcome is
// written to a table and queried before the next patch, failures included.
//
// Everything here is counted from the runs the server reports. It is empty
// before you have run anything, and it fills as you do.

import { useEffect, useState } from 'react'
import { api, type Job } from '../api'
import { Icon } from '../Icon'

interface Attempt {
  order: number
  jobId: string
  url: string
  criterion: string
  component: string
  tries: number
  closed: number
  created: number
  lessons: number[]
  status: string
}

export function LoopTab({ onOpen }: { onOpen: (id: string) => void }) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let stop = false
    api.jobs()
      .then(async (d) => {
        const full = await Promise.all(
          d.jobs.map((j) => api.job(j.id).catch(() => null)))
        if (!stop) setJobs((full.filter(Boolean) as Job[]).reverse())
      })
      .catch(() => { /* stays empty */ })
      .finally(() => { if (!stop) setLoading(false) })
    return () => { stop = true }
  }, [])

  if (loading) return <div className="dashboard-page"><p className="muted">Reading runs…</p></div>

  const attempts: Attempt[] = []
  for (const job of jobs) {
    for (const p of job.patches) {
      attempts.push({
        order: attempts.length + 1,
        jobId: job.id,
        url: job.url,
        criterion: p.criterion,
        component: p.component,
        tries: p.patch_attempts,
        closed: p.closed,
        created: p.created,
        lessons: p.lesson_ids ?? [],
        status: p.status,
      })
    }
  }

  const closedOnes = attempts.filter((a) => a.status === 'closed')
  const tries = closedOnes.map((a) => a.tries)
  const mean = tries.length ? (tries.reduce((a, b) => a + b, 0) / tries.length) : null
  const oneShot = tries.filter((t) => t === 1).length
  const retrieved = attempts.reduce((n, a) => n + a.lessons.length, 0)
  const created = attempts.reduce((n, a) => n + a.created, 0)

  // Did effort fall as the table filled? First half against second, in the order
  // the fixes actually closed. With fewer than four there is nothing to compare.
  let trend: number | null = null
  if (tries.length >= 4) {
    const half = Math.floor(tries.length / 2)
    const a = tries.slice(0, half).reduce((x, y) => x + y, 0) / half
    const b = tries.slice(half).reduce((x, y) => x + y, 0) / (tries.length - half)
    trend = Math.round((b - a) * 100) / 100
  }

  return (
    <div className="dashboard-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Self-correction</span>
          <h1>The Loop</h1>
          <p>Every patch outcome is written down. Before the next patch on the
             same criterion, the matching rows go into the prompt, failures
             included and labelled as failures.</p>
        </div>
      </header>

      {attempts.length === 0 ? (
        <div className="quiet-panel">
          <strong>Nothing to learn from yet</strong>
          The loop fills as runs write patches.
        </div>
      ) : (
        <>
          <dl className="run-summary-bar">
            <div><dt>Fixes closed</dt><dd>{closedOnes.length}</dd></div>
            <div><dt>Attempts per fix</dt><dd>{mean === null ? '—' : mean.toFixed(2)}</dd></div>
            <div><dt>Closed first try</dt><dd>{oneShot} of {tries.length}</dd></div>
            <div><dt>Prior cases used</dt><dd>{retrieved}</dd></div>
            <div><dt>New issues created</dt><dd>{created}</dd></div>
            <div>
              <dt>Trend</dt>
              <dd>{trend === null ? 'not enough yet' : `${trend > 0 ? '+' : ''}${trend.toFixed(2)}`}</dd>
            </div>
          </dl>

          <section className="section">
            <div className="section-heading">
              <div>
                <span className="eyebrow">In the order they were attempted</span>
                <h2>Every patch, and what it had to learn from</h2>
              </div>
              <span className="section-count">{attempts.length}</span>
            </div>
            <table className="grid">
              <thead>
                <tr>
                  <th className="num">#</th><th>Criterion</th><th>Component</th>
                  <th>Result</th><th className="num">Tries</th>
                  <th>Prior cases in the prompt</th><th />
                </tr>
              </thead>
              <tbody>
                {attempts.map((a) => (
                  <tr key={`${a.jobId}-${a.order}`} className={a.status === 'closed' ? '' : 'dim'}>
                    <td className="num">{a.order}</td>
                    <td className="mono">{a.criterion}</td>
                    <td className="mono">{a.component}</td>
                    <td>
                      <span className={`status-label ${a.status === 'closed'
                        ? 'status-done' : 'status-attention'}`}>
                        <i aria-hidden="true" />{a.status.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td className="num">{a.tries}</td>
                    <td className="mono">
                      {a.lessons.length === 0
                        ? <span className="muted">nothing yet</span>
                        : a.lessons.join(', ')}
                    </td>
                    <td className="num">
                      <button className="button secondary" onClick={() => onOpen(a.jobId)}>
                        Run <Icon name="chevron-right" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="section">
            <div className="section-heading">
              <div><span className="eyebrow">What the table cannot do</span><h2>Scope</h2></div>
            </div>
            <div className="card">
              <p style={{ fontSize: 'var(--text-ui)' }}>
                The table records <strong>patch outcomes</strong>, so it can only
                reach patching. A finding that was never detected produces no row.
                The number above is effort per fix across findings already found,
                and says nothing about how many are found.
              </p>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
