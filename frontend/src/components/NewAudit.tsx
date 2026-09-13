// The overview surface, on AccessiFix's page furniture:
// .dashboard-page > .page-header (eyebrow, h1, p, .page-action-row) then
// .section > .section-heading and .card / .cell.

import { useEffect, useState } from 'react'
import { api, type Job } from '../api'
import { Icon } from '../Icon'

interface Props {
  onStarted: (job: Job) => void
}

export function NewAudit({ onStarted }: Props) {
  const [url, setUrl] = useState('')
  const [repo, setRepo] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [stats, setStats] = useState({ runs: 0, findings: 0, prs: 0 })

  useEffect(() => {
    api.jobs()
      .then((d) => setStats({
        runs: d.jobs.length,
        findings: d.jobs.reduce((n, j) => n + j.findings, 0),
        prs: d.jobs.filter((j) => j.pr_url).length,
      }))
      .catch(() => { /* the cells read zero; nothing is invented */ })
  }, [])

  const repoLooksWrong = repo.trim() !== '' && !/github\.com\/[^/]+\/[^/]+/.test(repo)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      onStarted(await api.startAudit(url.trim(), repo.trim(), [], true, true))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The run could not be started.')
    } finally {
      setBusy(false)
    }
  }

  function example(exUrl: string, exRepo: string) {
    setUrl(exUrl)
    setRepo(exRepo)
    setError('')
  }

  return (
    <div className="dashboard-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Overview</span>
          <h1>Keyboard access, audited and fixed</h1>
          <p>
            One run is one complete pass: tab the live page, find what the
            keyboard cannot reach, patch the source, re-audit to confirm the fix
            held, open a pull request.
          </p>
        </div>
      </header>

      <form className="card" onSubmit={submit}>
        <div className="audit-form">
          <div className="field">
            <label htmlFor="page-url">Live page</label>
            <input
              id="page-url"
              className="input mono"
              type="url"
              required
              autoComplete="url"
              spellCheck={false}
              placeholder="https://yoursite.com/checkout"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>

          <div className="field">
            <label htmlFor="repo-url">Repository</label>
            <input
              id="repo-url"
              className="input mono"
              type="text"
              required
              spellCheck={false}
              placeholder="https://github.com/owner/repo"
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              aria-invalid={repoLooksWrong}
              aria-describedby="repo-hint"
            />
            <span className="muted" style={{ fontSize: 'var(--text-caption)' }} id="repo-hint">
              {repoLooksWrong
                ? 'Expected github.com/owner/repo.'
                : 'Ally finds the file that backs the page itself.'}
            </span>
          </div>
        </div>

        <div className="field-row">
          <button className="button primary large" type="submit" disabled={busy || repoLooksWrong}>
            <Icon name="play" />
            {busy ? 'Starting…' : 'Start a run'}
          </button>
          <button
            type="button"
            className="button secondary"
            onClick={() => example('https://broken-app.vercel.app/2-1-1.html',
                                   'https://github.com/Carldtitan/Ally')}
          >
            <Icon name="warning" />
            A page with defects
          </button>
          <button
            type="button"
            className="button secondary"
            onClick={() => example('https://ally-clean-app.vercel.app/',
                                   'https://github.com/Carldtitan/Ally')}
          >
            <Icon name="check" />
            A page with none
          </button>
        </div>

        {error && (
          <p className="status-label status-blocked" style={{ marginTop: 16 }} role="alert">
            <i aria-hidden="true" />
            {error}
          </p>
        )}
      </form>

      <section className="section">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Ledger</span>
            <h2>What this machine has done</h2>
            <p>Read from the runs on disk, not from memory.</p>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
          <div className="cell">
            <small>Runs</small>
            <strong className="mono">{stats.runs}</strong>
          </div>
          <div className="cell">
            <small>Findings</small>
            <strong className="mono">{stats.findings}</strong>
          </div>
          <div className="cell">
            <small>Pull requests</small>
            <strong className="mono">{stats.prs}</strong>
          </div>
          <div className="cell">
            <small>Criteria covered</small>
            <strong className="mono">5</strong>
          </div>
        </div>
      </section>
    </div>
  )
}
