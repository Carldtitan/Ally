// The primary surface. Two fields: where the page lives, where its code lives.
// Everything else is a default, because a person pasting a URL should not have
// to tell the agent which file backs it -- the agent works that out from the
// clone.

import { useState } from 'react'
import { api, type Job } from '../api'
import { IconPlay, IconTarget, IconGitBranch, IconAlert } from '../icons'

const STATE_SETS: { id: string; label: string; states: string[]; hint: string }[] = [
  { id: 'quick', label: 'The loaded page', states: ['loaded'],
    hint: 'One Tab run. Fastest, and enough for most pages.' },
  { id: 'generic', label: 'Plus menus and dialogs', states: ['loaded', 'menu-generic', 'dialog-generic'],
    hint: 'Also opens whatever declares itself a menu or a dialog and tabs that too.' },
]

interface Props {
  onStarted: (job: Job) => void
}

export function NewAudit({ onStarted }: Props) {
  const [url, setUrl] = useState('')
  const [repo, setRepo] = useState('')
  const [depth, setDepth] = useState('quick')
  const [fix, setFix] = useState(true)
  const [pr, setPr] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const repoLooksWrong = repo.trim() !== '' && !/github\.com\/[^/]+\/[^/]+/.test(repo)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const states = STATE_SETS.find((s) => s.id === depth)!.states
      const job = await api.startAudit(url.trim(), repo.trim(), states, fix, pr)
      onStarted(job)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The run could not be started.')
    } finally {
      setBusy(false)
    }
  }

  function useExample(exUrl: string, exRepo: string) {
    setUrl(exUrl)
    setRepo(exRepo)
    setError('')
  }

  return (
    <>
      <h1>Fix the keyboard on a page you already shipped</h1>
      <p className="lede" style={{ marginTop: 6 }}>
        Give Ally the live page and the repository behind it. It tabs through the
        page like a keyboard user, finds what the keyboard cannot reach, edits the
        source, rebuilds, re-audits to confirm the fix held, and opens a pull
        request.
      </p>

      <form className="panel" style={{ marginTop: 20 }} onSubmit={submit}>
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
            <span className="hint">The page as a visitor sees it, running.</span>
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
              {repoLooksWrong
                ? 'Expected github.com/owner/repo.'
                : 'Ally finds the file that backs the page itself.'}
            </span>
          </div>
        </div>

        <div className="field" style={{ marginTop: 14 }}>
          <label htmlFor="depth">How much of the page</label>
          <select
            id="depth"
            className="input"
            value={depth}
            onChange={(e) => setDepth(e.target.value)}
            style={{ maxWidth: 320 }}
          >
            {STATE_SETS.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          <span className="hint">{STATE_SETS.find((s) => s.id === depth)!.hint}</span>
        </div>

        <div className="audit-actions">
          <button className="btn btn-primary" type="submit" disabled={busy || repoLooksWrong}>
            <IconPlay />
            {busy ? 'Starting…' : fix ? 'Audit and fix' : 'Audit only'}
          </button>

          <div className="audit-toggles">
            <label className="toggle">
              <input type="checkbox" checked={fix} onChange={(e) => setFix(e.target.checked)} />
              Write the fix
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={pr}
                disabled={!fix}
                onChange={(e) => setPr(e.target.checked)}
              />
              Open a pull request
            </label>
          </div>
        </div>

        {error && (
          <div className="callout danger" style={{ marginTop: 14 }} role="alert">
            <IconAlert />
            <span>{error}</span>
          </div>
        )}

        <div className="example-row">
          <span className="hint">Try it on:</span>
          <button
            type="button"
            className="example-btn"
            onClick={() => useExample('https://broken-app.vercel.app/2-1-1.html',
                                      'https://github.com/Carldtitan/Ally')}
          >
            a page with known keyboard defects
          </button>
          <button
            type="button"
            className="example-btn"
            onClick={() => useExample('https://ally-clean-app.vercel.app/',
                                      'https://github.com/Carldtitan/Ally')}
          >
            a page with none
          </button>
        </div>
      </form>

      <div className="pair" style={{ marginTop: 18 }}>
        <div className="panel">
          <h3 style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <IconTarget /> What it looks for
          </h3>
          <p className="hint" style={{ marginTop: 7 }}>
            Five WCAG criteria that need a keyboard rather than a parser: whether
            every control can be reached, whether focus can get stuck, whether the
            Tab order follows the page, whether the focus indicator is visible,
            and whether anything is drawn over the focused element.
          </p>
        </div>
        <div className="panel">
          <h3 style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <IconGitBranch /> What it changes
          </h3>
          <p className="hint" style={{ marginTop: 7 }}>
            Literal find-and-replace edits in your source, applied all-or-nothing.
            After each patch the page is rebuilt and re-audited, so a fix that did
            not hold is retried with the new recording in hand rather than
            reported as done.
          </p>
        </div>
      </div>
    </>
  )
}
