// The landing surface, composed the way AccessiFix composes one: a big page
// icon, the title and description over a rule, a Getting Started callout, the
// action row, then a stats grid.
//
// The earlier version was a bare heading over a two-field card and a lot of
// empty page. The tokens were right and the composition was not, which is what
// made it read as a different product.
//
// There was also a "how much of the page" selector offering "the loaded page"
// or "plus menus and dialogs". That is a question about our page-state
// machinery: whoever pastes a URL cannot answer it better than the agent can,
// so the recorder counts what the page declares and the job decides.

import { useEffect, useState } from 'react'
import { api, type Job } from '../api'

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
      .catch(() => { /* the grid shows zeroes; nothing is invented */ })
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
    <>
      <div className="notion-page-header">
        <div className="notion-page-icon" aria-hidden="true">⌨️</div>
        <h1 className="notion-page-title">Keyboard Accessibility Agent</h1>
        <p className="notion-page-description">
          Audit a live page the way a keyboard user meets it, patch the source
          behind it, re-audit to confirm the fix held, and open a pull request.
        </p>
      </div>

      <div className="notion-callout info">
        <span className="notion-callout-icon" aria-hidden="true">💡</span>
        <div>
          <strong>Getting Started</strong>
          <div style={{ marginTop: 2 }}>
            Paste the page as a visitor sees it and the repository behind it.
            Ally works out which file backs the page, and which states are worth
            tabbing, from the repository and the page itself.
          </div>
        </div>
      </div>

      <form className="notion-card" onSubmit={submit}>
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
            <span className="hint" id="repo-hint">
              {repoLooksWrong ? 'Expected github.com/owner/repo.' : ' '}
            </span>
          </div>
        </div>

        <div className="audit-actions">
          <button className="btn btn-primary" type="submit" disabled={busy || repoLooksWrong}>
            <span aria-hidden="true">🚀</span>
            {busy ? 'Starting…' : 'Audit and Fix'}
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => example('https://broken-app.vercel.app/2-1-1.html',
                                   'https://github.com/Carldtitan/Ally')}
          >
            <span aria-hidden="true">🐛</span>
            Try a page with defects
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => example('https://ally-clean-app.vercel.app/',
                                   'https://github.com/Carldtitan/Ally')}
          >
            <span aria-hidden="true">✅</span>
            Try a clean page
          </button>
        </div>

        {error && (
          <div className="notion-callout danger" style={{ marginTop: 16 }} role="alert">
            <span className="notion-callout-icon" aria-hidden="true">⚠️</span>
            <span>{error}</span>
          </div>
        )}
      </form>

      <div className="stats-grid">
        <div className="notion-card stat-card">
          <div>
            <div className="stat-label">Audits Run</div>
            <div className="stat-value tnum">{stats.runs}</div>
          </div>
          <span className="stat-card-emoji" aria-hidden="true">🔍</span>
        </div>
        <div className="notion-card stat-card">
          <div>
            <div className="stat-label">Findings</div>
            <div className="stat-value tnum">{stats.findings}</div>
          </div>
          <span className="stat-card-emoji" aria-hidden="true">⚠️</span>
        </div>
        <div className="notion-card stat-card">
          <div>
            <div className="stat-label">Pull Requests</div>
            <div className="stat-value tnum">{stats.prs}</div>
          </div>
          <span className="stat-card-emoji" aria-hidden="true">🔀</span>
        </div>
        <div className="notion-card stat-card">
          <div>
            <div className="stat-label">Criteria Covered</div>
            <div className="stat-value tnum">5</div>
          </div>
          <span className="stat-card-emoji" aria-hidden="true">📋</span>
        </div>
      </div>
    </>
  )
}
