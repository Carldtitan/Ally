// Watching one job: the phase rail, the log, what was found, what was changed,
// and the pull request. This is the screen the demo lives on, so every state it
// can be in has been drawn: queued, running, finished, failed, and finished with
// nothing wrong.

import { useEffect, useRef, useState } from 'react'
import { api, type Job } from '../api'
import { IconCheck, IconAlert, IconClock, IconExternal, IconCode, IconLoop } from '../icons'
import { LiveView } from './LiveView'
import { Findings } from './Findings'

const PHASES: { id: string; label: string }[] = [
  { id: 'clone', label: 'Read the code' },
  { id: 'audit', label: 'Tab the page' },
  { id: 'fix', label: 'Write the fix' },
  { id: 'reaudit', label: 'Confirm it held' },
  { id: 'pr', label: 'Open the PR' },
]

function railState(job: Job, phase: string): string {
  const order = PHASES.map((p) => p.id)
  const at = order.indexOf(job.phase)
  const me = order.indexOf(phase)
  if (job.status === 'failed' && me === at) return 'failed'
  if (me < at) return 'done'
  if (me === at) return job.status === 'done' ? 'done' : 'active'
  return ''
}

function clock(at: number, started: number): string {
  const s = Math.max(0, at - started)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}

interface Props {
  job: Job
  onUpdate: (job: Job) => void
}

export function JobRun({ job, onUpdate }: Props) {
  const [err, setErr] = useState('')
  const logRef = useRef<HTMLDivElement>(null)
  const live = job.status === 'queued' || job.status === 'running'

  useEffect(() => {
    if (!live) return
    let stop = false
    const tick = async () => {
      try {
        const next = await api.job(job.id)
        if (!stop) onUpdate(next)
      } catch (e) {
        if (!stop) setErr(e instanceof Error ? e.message : 'Lost contact with the server.')
      }
    }
    const id = window.setInterval(tick, 1500)
    return () => { stop = true; window.clearInterval(id) }
  }, [job.id, live, onUpdate])

  useEffect(() => {
    // Follow the log while work is happening, but never yank a reader who has
    // scrolled up to read something.
    const el = logRef.current
    if (!el || !live) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60
    if (atBottom) el.scrollTop = el.scrollHeight
  }, [job.events.length, live])

  const failed = job.findings.filter((f) => f.status === 'failed')
  const closed = job.patches.reduce((n, p) => n + p.closed, 0)
  const created = job.patches.reduce((n, p) => n + p.created, 0)
  const lessons = job.patches.reduce((n, p) => n + p.lesson_ids.length, 0)

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h1 style={{ fontSize: '1.15rem' }}>{job.url}</h1>
        <span className="tag info">{job.repo.replace(/^https?:\/\/(www\.)?github\.com\//, '')}</span>
        {job.source && <span className="tag mono">{job.source}</span>}
        <span className="tag" style={{ marginLeft: 'auto' }}>
          <IconClock size={12} />
          <span className="tnum">{job.elapsed}s</span>
        </span>
      </div>

      <div className="rail" role="list" aria-label="Progress">
        {PHASES.map((p, i) => (
          <div key={p.id} className={`rail-step ${railState(job, p.id)}`} role="listitem">
            <span className="n">{String(i + 1).padStart(2, '0')}</span>
            <span className="t">{p.label}</span>
          </div>
        ))}
      </div>

      {job.status === 'failed' && (
        <div className="callout danger" role="alert" style={{ marginBottom: 14 }}>
          <IconAlert />
          <span><b>The run stopped.</b> {job.error}</span>
        </div>
      )}
      {err && (
        <div className="callout warn" style={{ marginBottom: 14 }}>
          <IconAlert /><span>{err}</span>
        </div>
      )}
      {job.status === 'done' && failed.length === 0 && (
        <div className="callout ok" style={{ marginBottom: 14 }}>
          <IconCheck />
          <span>
            <b>Nothing to fix.</b> Every check that could run reached a verdict and
            none of them failed, so no edit was made.
          </span>
        </div>
      )}

      {job.pr_url && (
        <div className="callout ok" style={{ marginBottom: 14 }}>
          <IconCheck />
          <span>
            <b>Pull request open.</b>{' '}
            <a href={job.pr_url} target="_blank" rel="noreferrer">
              {job.pr_url.replace(/^https?:\/\/(www\.)?github\.com\//, '')}
            </a>{' '}
            &mdash; {closed} finding{closed === 1 ? '' : 's'} closed
            {created > 0 && `, ${created} new one${created === 1 ? '' : 's'} created`}.
          </span>
        </div>
      )}
      {job.pr_blocked && !job.pr_url && (
        <div className="callout warn" style={{ marginBottom: 14 }}>
          <IconAlert /><span>{job.pr_blocked}</span>
        </div>
      )}

      <div className="panel">
        <div className="panel-head">
          <h2>What happened</h2>
          {job.trace_url && (
            <a href={job.trace_url} target="_blank" rel="noreferrer" className="hint">
              Full trace in Weave <IconExternal size={11} />
            </a>
          )}
        </div>
        <div className="log" ref={logRef} aria-live="polite" aria-atomic="false">
          {job.events.length === 0 && <div className="log-row"><span className="msg">Starting…</span></div>}
          {job.events.map((e, i) => (
            <div className={`log-row ${e.level}`} key={i}>
              <span className="at tnum">{clock(e.at, job.started)}</span>
              <span className="ph">{e.phase}</span>
              <span className="msg">{e.message}</span>
            </div>
          ))}
        </div>
      </div>

      {Object.keys(job.recordings).length > 0 && (
        <div className="panel">
          <div className="panel-head">
            <h2>The page, as the keyboard found it</h2>
            <span className="hint">Select a stop to see that moment</span>
          </div>
          <LiveView recordings={job.recordings} />
        </div>
      )}

      {job.findings.length > 0 && (
        <div className="panel">
          <div className="panel-head">
            <h2>Findings</h2>
            <span className="hint">
              {failed.length} failed of {job.findings.length} checks
            </span>
          </div>
          <Findings findings={job.findings} axe={job.axe} />
        </div>
      )}

      {job.patches.length > 0 && (
        <div className="panel">
          <div className="panel-head">
            <h2>Patches</h2>
            <span className="hint">
              {lessons > 0
                ? `${lessons} prior case${lessons === 1 ? '' : 's'} retrieved from earlier fixes`
                : 'First pass: nothing to retrieve yet'}
            </span>
          </div>
          <table className="grid">
            <thead>
              <tr>
                <th>Criterion</th><th>Component</th><th>Result</th>
                <th className="num">Attempts</th><th className="num">Closed</th>
                <th>Learned from</th>
              </tr>
            </thead>
            <tbody>
              {job.patches.map((p, i) => (
                <tr key={i} className={p.status === 'closed' ? '' : 'dim'}>
                  <td className="mono">{p.criterion}</td>
                  <td className="mono">{p.component}</td>
                  <td>
                    <span className={`tag ${p.status === 'closed' ? 'passed' : 'skipped'}`}>
                      {p.status.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="num">{p.patch_attempts}</td>
                  <td className="num">{p.closed}</td>
                  <td className="mono">
                    {p.lesson_ids.length > 0
                      ? <span title="Rows from the lessons table that went into this prompt">
                          <IconLoop size={11} /> {p.lesson_ids.join(', ')}
                        </span>
                      : <span className="hint">nothing yet</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {job.diff && (
        <div className="panel">
          <div className="panel-head">
            <h2 style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <IconCode /> The change
            </h2>
            <span className="hint">Applied all-or-nothing, then re-audited</span>
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
        </div>
      )}
    </>
  )
}
