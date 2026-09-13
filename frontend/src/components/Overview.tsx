// Start a run, and see the runs this machine has done. Nothing on this screen
// is compiled in: the list is whatever the server reports.

import { useEffect, useState } from 'react'
import { api, type Job } from '../api'
import { Play, Alert } from '../Icons'

interface Props {
  onStarted: (job: Job) => void
  onOpen: (id: string) => void
}

type Row = {
  id: string; url: string; repo: string; status: string
  phase: string; findings: number; pr_url: string
}

export function Overview({ onStarted, onOpen }: Props) {
  const [url, setUrl] = useState('')
  const [repo, setRepo] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [rows, setRows] = useState<Row[]>([])

  useEffect(() => {
    api.jobs().then((d) => setRows(d.jobs)).catch(() => setRows([]))
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

  return (
    <div className="page">
      <div className="head">
        <span className="eyebrow">Ally</span>
        <h1>Audit a page, then fix it</h1>
      </div>

      <form className="panel" onSubmit={submit}>
        <div className="two-up">
          <div className="field">
            <label htmlFor="url">Live page</label>
            <input
              id="url" className="input" type="url" required
              autoComplete="url" spellCheck={false}
              placeholder="https://yoursite.com/checkout"
              value={url} onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="repo">Repository</label>
            <input
              id="repo" className="input" type="text" required spellCheck={false}
              placeholder="https://github.com/owner/repo"
              value={repo} onChange={(e) => setRepo(e.target.value)}
              aria-invalid={repoLooksWrong}
              aria-describedby={repoLooksWrong ? 'repo-err' : undefined}
            />
            {repoLooksWrong && (
              <span className="muted" id="repo-err" style={{ fontSize: 12 }}>
                Expected github.com/owner/repo
              </span>
            )}
          </div>
        </div>

        <div className="form-row">
          <button className="btn btn-go" type="submit" disabled={busy || repoLooksWrong}>
            <Play />
            {busy ? 'Starting' : 'Start a run'}
          </button>
        </div>

        {error && (
          <div className="note bad" style={{ marginTop: 18 }} role="alert">
            <Alert />
            <span>{error}</span>
          </div>
        )}
      </form>

      <section className="section">
        <div className="section-head">
          <div>
            <span className="eyebrow">Runs</span>
            <h2>{rows.length === 0 ? 'Nothing yet' : `${rows.length} on this machine`}</h2>
          </div>
        </div>

        {rows.length === 0 ? (
          <div className="empty">
            <strong>No runs yet</strong>
            Start one above and it appears here while it works.
          </div>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>Page</th><th>Repository</th><th>State</th>
                <th className="num">Findings</th><th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="mono" style={{ maxWidth: 320, overflow: 'hidden',
                                                textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.url}
                  </td>
                  <td className="mono">
                    {r.repo.replace(/^https?:\/\/(www\.)?github\.com\//, '')}
                  </td>
                  <td>
                    <span className={`pill ${r.status === 'done' ? 'ok'
                      : r.status === 'failed' ? 'bad'
                      : 'go'}`}>
                      {r.status === 'running' ? r.phase : r.status}
                    </span>
                  </td>
                  <td className="num">{r.findings}</td>
                  <td className="num">
                    <button className="btn btn-sm" onClick={() => onOpen(r.id)}>Open</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
