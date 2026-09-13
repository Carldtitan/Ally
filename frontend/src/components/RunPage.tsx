// One run, split into four pages rather than one long scroll. Each page opens
// with its own tiles, so a reader gets the shape of that dataset before any
// table. The sub-nav carries the counts, so you can see where the content is
// without visiting each page.

import { useEffect, useRef, useState } from 'react'
import { api, type Job } from '../api'
import { Back, Check, Alert, Clock, Link as LinkIcon, Code, Branch } from '../Icons'
import { LiveView } from './LiveView'
import { Findings } from './Findings'

const STEPS = [
  { id: 'clone', label: 'Read the code' },
  { id: 'audit', label: 'Drive the page' },
  { id: 'fix', label: 'Write the fix' },
  { id: 'reaudit', label: 'Confirm it held' },
  { id: 'pr', label: 'Open the PR' },
]

type Page = 'summary' | 'recording' | 'findings' | 'changes'

function stepState(job: Job, id: string): string {
  const order = STEPS.map((s) => s.id)
  const at = order.indexOf(job.phase)
  const me = order.indexOf(id)
  if (job.status === 'failed' && me === at) return 'stopped'
  if (me < at) return 'done'
  if (me === at) return job.status === 'done' ? 'done' : 'now'
  return ''
}

function mmss(at: number, from: number): string {
  const s = Math.max(0, at - from)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}

interface Props {
  job: Job
  onUpdate: (job: Job) => void
  onBack: () => void
}

export function RunPage({ job, onUpdate, onBack }: Props) {
  const [page, setPage] = useState<Page>('summary')
  const [err, setErr] = useState('')
  const logRef = useRef<HTMLDivElement>(null)
  const live = job.status === 'queued' || job.status === 'running'

  useEffect(() => {
    if (!live) return
    let stop = false
    const id = window.setInterval(async () => {
      try {
        const next = await api.job(job.id)
        if (!stop) onUpdate(next)
      } catch (e) {
        if (!stop) setErr(e instanceof Error ? e.message : 'Lost contact with the server.')
      }
    }, 1500)
    return () => { stop = true; window.clearInterval(id) }
  }, [job.id, live, onUpdate])

  useEffect(() => {
    const el = logRef.current
    if (!el || !live) return
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 60) el.scrollTop = el.scrollHeight
  }, [job.events.length, live])

  const failed = job.findings.filter((f) => f.status === 'failed')
  const undecided = job.findings.filter((f) => f.status === 'not_evaluated')
  const closed = job.patches.reduce((n, p) => n + p.closed, 0)
  const created = job.patches.reduce((n, p) => n + p.created, 0)
  const stops = Object.values(job.recordings).reduce((n, r) => n + (r.stops?.length ?? 0), 0)
  const states = Object.keys(job.recordings).length
  const diffLines = job.diff ? job.diff.split('\n').length : 0

  const PAGES: { id: Page; label: string; n?: number }[] = [
    { id: 'summary', label: 'Summary' },
    { id: 'recording', label: 'Recording', n: stops },
    { id: 'findings', label: 'Findings', n: failed.length },
    { id: 'changes', label: 'Changes', n: job.patches.length },
  ]

  return (
    <div className="page">
      <div className="head">
        <button className="btn btn-sm" onClick={onBack} style={{ marginBottom: 16 }}>
          <Back /> All runs
        </button>
        <span className="eyebrow">{job.repo.replace(/^https?:\/\/(www\.)?github\.com\//, '')}</span>
        <h1 style={{ fontSize: 26, marginTop: 6, overflowWrap: 'anywhere' }}>{job.url}</h1>
        <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
          <span className={`pill ${job.status === 'done' ? 'ok'
            : job.status === 'failed' ? 'bad' : 'go'}`}>
            {job.status === 'running' ? job.phase : job.status}
          </span>
          <span className="pill flat"><Clock size={11} /> {job.elapsed}s</span>
          {job.source && <span className="pill flat">{job.source}</span>}
        </div>
      </div>

      <nav className="subnav" aria-label="This run">
        {PAGES.map((p) => (
          <button
            key={p.id}
            aria-current={page === p.id ? 'page' : undefined}
            onClick={() => setPage(p.id)}
          >
            {p.label}
            {p.n !== undefined && p.n > 0 && <span className="n">{p.n}</span>}
          </button>
        ))}
      </nav>

      {err && <div className="note hold" style={{ marginBottom: 16 }}><Alert />{err}</div>}

      {page === 'summary' && (
        <>
          <div className="steps">
            {STEPS.map((s, i) => (
              <div key={s.id} className={`step ${stepState(job, s.id)}`}>
                <span className="n">{String(i + 1).padStart(2, '0')}</span>
                <span className="t">{s.label}</span>
              </div>
            ))}
          </div>

          <div className="tiles" style={{ marginBottom: 18 }}>
            <div className="tile">
              <small>Findings</small>
              <strong className={failed.length ? 'bad' : 'ok'}>{failed.length}</strong>
            </div>
            <div className="tile">
              <small>Unresolved</small>
              <strong className={undecided.length ? 'hold' : ''}>{undecided.length}</strong>
            </div>
            <div className="tile"><small>Closed</small><strong className={closed ? 'ok' : ''}>{closed}</strong></div>
            <div className="tile"><small>New issues</small><strong className={created ? 'bad' : ''}>{created}</strong></div>
            <div className="tile"><small>States</small><strong>{states}</strong></div>
            <div className="tile"><small>Stops</small><strong>{stops}</strong></div>
          </div>

          {job.status === 'failed' && (
            <div className="note bad" role="alert" style={{ marginBottom: 16 }}>
              <Alert /><span>{job.error}</span>
            </div>
          )}
          {job.status === 'done' && failed.length === 0 && (
            <div className="note ok" style={{ marginBottom: 16 }}>
              <Check /><span>Nothing failed. No edit was made.</span>
            </div>
          )}
          {job.pr_url && (
            <div className="note ok" style={{ marginBottom: 16 }}>
              <Branch />
              <span>
                <a href={job.pr_url} target="_blank" rel="noreferrer">
                  {job.pr_url.replace(/^https?:\/\/(www\.)?github\.com\//, '')}
                </a>{' '}— {closed} closed{created > 0 && `, ${created} new`}
              </span>
            </div>
          )}
          {job.pr_blocked && !job.pr_url && (
            <div className="note hold" style={{ marginBottom: 16 }}>
              <Alert /><span>{job.pr_blocked}</span>
            </div>
          )}

          <div className="panel">
            <div className="section-head" style={{ marginBottom: 12 }}>
              <h2>Log</h2>
              {job.trace_url && (
                <a href={job.trace_url} target="_blank" rel="noreferrer"
                   style={{ fontSize: 12.5 }}>
                  Trace <LinkIcon size={11} />
                </a>
              )}
            </div>
            <div className="log" ref={logRef} aria-live="polite">
              {job.events.length === 0 && <div className="log-row"><span className="msg">Starting</span></div>}
              {job.events.map((e, i) => (
                <div className={`log-row ${e.level}`} key={i}>
                  <span className="at">{mmss(e.at, job.started)}</span>
                  <span className="ph">{e.phase}</span>
                  <span className="msg">{e.message}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {page === 'recording' && (
        Object.keys(job.recordings).length === 0 ? (
          <div className="empty"><strong>No recording yet</strong>Frames appear as each state is driven.</div>
        ) : (
          <>
            <div className="tiles" style={{ marginBottom: 18 }}>
              <div className="tile"><small>States</small><strong>{states}</strong></div>
              <div className="tile"><small>Stops</small><strong>{stops}</strong></div>
              <div className="tile">
                <small>Reachable</small>
                <strong>{Object.values(job.recordings)[0]?.focusable_total ?? '—'}</strong>
              </div>
            </div>
            <LiveView recordings={job.recordings} />
          </>
        )
      )}

      {page === 'findings' && (
        job.findings.length === 0 ? (
          <div className="empty"><strong>Nothing reported yet</strong>Findings appear once the page has been driven.</div>
        ) : (
          <>
            <div className="tiles" style={{ marginBottom: 18 }}>
              <div className="tile"><small>Failed</small><strong className={failed.length ? 'bad' : 'ok'}>{failed.length}</strong></div>
              <div className="tile"><small>Passed</small><strong>{job.findings.length - failed.length - undecided.length}</strong></div>
              <div className="tile"><small>Unresolved</small><strong className={undecided.length ? 'hold' : ''}>{undecided.length}</strong></div>
              <div className="tile"><small>Checks run</small><strong>{job.findings.length}</strong></div>
            </div>
            <Findings findings={job.findings} axe={job.axe} />
          </>
        )
      )}

      {page === 'changes' && (
        job.patches.length === 0 && !job.diff ? (
          <div className="empty"><strong>Nothing changed</strong>No patch was written for this run.</div>
        ) : (
          <>
            <div className="tiles" style={{ marginBottom: 18 }}>
              <div className="tile"><small>Patches</small><strong>{job.patches.length}</strong></div>
              <div className="tile"><small>Closed</small><strong className={closed ? 'ok' : ''}>{closed}</strong></div>
              <div className="tile"><small>New issues</small><strong className={created ? 'bad' : ''}>{created}</strong></div>
              <div className="tile"><small>Diff lines</small><strong>{diffLines}</strong></div>
            </div>

            {job.patches.length > 0 && (
              <table className="grid" style={{ marginBottom: 24 }}>
                <thead>
                  <tr>
                    <th>Criterion</th><th>Component</th><th>Result</th>
                    <th className="num">Tries</th><th className="num">Closed</th>
                  </tr>
                </thead>
                <tbody>
                  {job.patches.map((p, i) => (
                    <tr key={i} className={p.status === 'closed' ? '' : 'faint'}>
                      <td className="mono">{p.criterion}</td>
                      <td className="mono">{p.component}</td>
                      <td>
                        <span className={`pill ${p.status === 'closed' ? 'ok' : 'hold'}`}>
                          {p.status.replace(/_/g, ' ')}
                        </span>
                      </td>
                      <td className="num">{p.patch_attempts}</td>
                      <td className="num">{p.closed}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {job.diff && (
              <>
                <div className="section-head">
                  <div><span className="eyebrow">Applied all or nothing</span><h2>Diff</h2></div>
                  <Code />
                </div>
                <div className="diff">
                  {job.diff.split('\n').map((line, i) => {
                    const cls = line.startsWith('+') ? 'add'
                      : line.startsWith('-') ? 'del'
                      : line.startsWith('@@') ? 'meta'
                      : line.startsWith('diff ') || line.startsWith('index ') ? 'hdr' : ''
                    return <div className={cls} key={i}>{line || ' '}</div>
                  })}
                </div>
              </>
            )}
          </>
        )
      )}
    </div>
  )
}
