// Two fields and a button.
//
// There was a "how much of the page" selector here, offering "the loaded page"
// or "plus menus and dialogs". That is a question about our internals: whoever
// pastes a URL does not know or care which page states we tab, and cannot answer
// it better than we can. The agent looks at the page and decides -- it adds the
// menu and dialog passes only when the page actually has something that declares
// itself a menu or a dialog.

import { useState } from 'react'
import { api, type Job } from '../api'
import { IconPlay, IconAlert } from '../icons'

interface Props {
  onStarted: (job: Job) => void
}

export function NewAudit({ onStarted }: Props) {
  const [url, setUrl] = useState('')
  const [repo, setRepo] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

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
    <>
      <h1 className="notion-page-title">Fix the keyboard on a page you already shipped</h1>
      <p className="notion-page-description" style={{ marginTop: 6 }}>
        Ally tabs through the live page, edits the source behind it, and opens a
        pull request.
      </p>

      <form className="notion-card" style={{ marginTop: 20 }} onSubmit={submit}>
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
              {repoLooksWrong ? 'Expected github.com/owner/repo.' : ' '}
            </span>
          </div>
        </div>

        <div className="audit-actions">
          <button className="btn btn-primary" type="submit" disabled={busy || repoLooksWrong}>
            <IconPlay />
            {busy ? 'Starting…' : 'Audit and fix'}
          </button>
        </div>

        {error && (
          <div className="notion-callout danger" style={{ marginTop: 14 }} role="alert">
            <IconAlert />
            <span>{error}</span>
          </div>
        )}

        <div className="example-row">
          <span className="hint">Try:</span>
          <button
            type="button"
            className="example-btn"
            onClick={() => {
              setUrl('https://broken-app.vercel.app/2-1-1.html')
              setRepo('https://github.com/Carldtitan/Ally')
              setError('')
            }}
          >
            a page with known defects
          </button>
          <button
            type="button"
            className="example-btn"
            onClick={() => {
              setUrl('https://ally-clean-app.vercel.app/')
              setRepo('https://github.com/Carldtitan/Ally')
              setError('')
            }}
          >
            a page with none
          </button>
        </div>
      </form>
    </>
  )
}
