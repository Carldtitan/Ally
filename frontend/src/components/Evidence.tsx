// The two evidence screens, both fed from runs that actually happened. Nothing
// here is computed in the component: if an artifact is missing, the row says so
// rather than showing a zero.

import { useEffect, useState } from 'react'
import { api, type BenchmarkPayload, type LoopPayload } from '../api'
import { IconInfo, IconExternal, IconLoop } from '../icons'

export function Benchmark() {
  const [data, setData] = useState<BenchmarkPayload | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api.benchmark().then(setData).catch((e) => setErr(String(e.message ?? e)))
  }, [])

  if (err) return <div className="notion-callout danger"><IconInfo /><span>{err}</span></div>
  if (!data) return <p className="hint">Reading the scored runs…</p>

  const axeItems = data.fixture.length
    ? data.fixture[data.fixture.length - 1].rows.flatMap((r) =>
        r.axe_items.map((i) => ({ crit: r.criterion, ...i })))
    : []

  return (
    <>
      <h1 className="notion-page-title">Benchmark</h1>
      <p className="notion-page-description" style={{ marginTop: 6 }}>
        Fifteen defects, five criteria, three instances each, planted on pages
        generated from a clean control app. Two runs side by side, with what changed
        between them.
      </p>

      <div className="pair" style={{ marginTop: 18 }}>
        {data.fixture.map((run) => (
          <div className="notion-card" key={run.tag}>
            <span className="notion-tag mono">{run.tag}</span>
            <div className={`stat-value ${run.found === run.planted ? 'good' : 'bad'}`}
                 style={{ marginTop: 8 }}>
              {run.found}<span className="of">/{run.planted}</span>
            </div>
            <span className="stat-label">defects found</span>

            <table className="notion-table" style={{ marginTop: 12 }}>
              <thead>
                <tr>
                  <th>Criterion</th><th className="num">Recall</th>
                  <th className="num">Not eval.</th><th className="num">False pos.</th>
                  <th className="num">axe</th>
                </tr>
              </thead>
              <tbody>
                {run.rows.map((r) => (
                  <tr key={r.criterion} className={r.run ? '' : 'dim'}>
                    <td className="mono">{r.criterion}</td>
                    {r.run ? (
                      <>
                        <td className="num">
                          <b>{r.found}/{r.planted}</b>
                        </td>
                        <td className="num">{r.not_evaluated || '—'}</td>
                        <td className="num">{r.false_positives || '—'}</td>
                        <td className="num">{r.axe_wcag} WCAG</td>
                      </>
                    ) : (
                      <td colSpan={4} className="hint">not run</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>

            <p className="changed">
              <b>What changed</b>
              {run.changed}
            </p>
          </div>
        ))}
      </div>

      <div className="notion-card">
        <h2>axe-core ran on every one of these pages</h2>
        <p style={{ marginTop: 7, fontSize: '0.86rem' }}>
          It reported <b>no WCAG violation on any of them</b>, on pages carrying
          fifteen planted WCAG keyboard defects. That is not a criticism of axe:
          none of these five criteria is in its scope, which is the reason this
          agent exists.
        </p>
        {axeItems.length > 0 && (
          <ul style={{ margin: '10px 0 0 20px', fontSize: '0.83rem', lineHeight: 1.7 }}>
            {axeItems.map((i, n) => (
              <li key={n}>
                <code className="mono">{i.id}</code> on {i.crit} &mdash; {i.help}{' '}
                <span className="notion-tag">best practice, not a success criterion</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {data.unknown.length > 0 && (
        <>
          <h2 style={{ marginTop: 26 }}>The same checks on a site nobody built for us</h2>
          <p className="notion-page-description" style={{ marginTop: 6 }}>
            {data.unknown[0].url} &mdash; a real commercial page. There is no
            manifest on a live site, so there is no recall to compute. The numbers
            are how many elements were named and how much of the page was examined.
          </p>
          <div className="pair" style={{ marginTop: 14 }}>
            {data.unknown.map((run) => (
              <div className="notion-card" key={run.key}>
                <span className="notion-tag mono">{run.label}</span>
                <div className="stat-value" style={{ marginTop: 8 }}>{run.targets.length}</div>
                <span className="stat-label">elements named</span>
                <table className="notion-table" style={{ marginTop: 12 }}>
                  <thead>
                    <tr>
                      <th>Criterion</th><th className="num">Examined</th>
                      <th className="num">Failed</th><th className="num">Undecided</th>
                      <th className="num">Excluded</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.rows.map((r) => (
                      <tr key={r.criterion}>
                        <td className="mono">{r.criterion}</td>
                        <td className="num">{r.examined}</td>
                        <td className="num">{r.failed || '—'}</td>
                        <td className="num">{r.undecided || '—'}</td>
                        <td className="num">{r.excluded || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="changed"><b>What changed</b>{run.changed}</p>
              </div>
            ))}
          </div>
        </>
      )}

      <p className="hint" style={{ marginTop: 16 }}>
        Every run above is an evaluation in{' '}
        <a href={data.weave} target="_blank" rel="noreferrer">
          Weave <IconExternal size={11} />
        </a>, with the datasets, prompts and scorers it used.
      </p>
    </>
  )
}

export function Loop() {
  const [data, setData] = useState<LoopPayload | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api.loop().then(setData).catch((e) => setErr(String(e.message ?? e)))
  }, [])

  if (err) return <div className="notion-callout danger"><IconInfo /><span>{err}</span></div>
  if (!data) return <p className="hint">Reading the loop runs…</p>

  const arms = [data.control, data.treatment].filter(Boolean) as NonNullable<typeof data.control>[]

  return (
    <>
      <h1 className="notion-page-title">The loop</h1>
      <p className="notion-page-description" style={{ marginTop: 6 }}>
        Inside one run the patcher writes a fix, applies it, rebuilds and
        re-audits, so the contradiction comes from a rebuilt page rather than from
        the model&rsquo;s own opinion. Between runs every patch outcome is written
        to a table and queried before the next patch, failures included and
        labelled as failures.
      </p>

      {arms.length === 2 && (
        <div className="notion-card" style={{ marginTop: 18 }}>
          <h2>Control and treatment, five pages each</h2>
          <p style={{ marginTop: 7, fontSize: '0.86rem' }}>
            Control closed {arms[0].n_closed} findings at <b>{arms[0].mean_attempts}</b>{' '}
            patch attempts each. Treatment closed {arms[1].n_closed} at{' '}
            <b>{arms[1].mean_attempts}</b>, retrieving {arms[1].retrieved_total} prior
            cases and creating {arms[1].created} new findings. The control arm is what
            makes the comparison mean anything: the same five pages in the same order
            with nothing retrieved.
          </p>
          <p className="hint" style={{ marginTop: 8 }}>
            Every lesson row id below links into the Weave trace for the patch call
            that received it, so retrieval can be opened rather than taken on trust.
          </p>
        </div>
      )}

      <div className="pair" style={{ marginTop: 14 }}>
        {arms.map((a) => (
          <div className="notion-card" key={a.tag}>
            <span className="notion-tag mono">{a.arm} · lessons {a.lessons}</span>
            <div className="stat-value" style={{ marginTop: 8 }}>{a.mean_attempts ?? '—'}</div>
            <span className="stat-label">patch attempts per closed finding</span>
            <table className="notion-table" style={{ marginTop: 12 }}>
              <thead>
                <tr>
                  <th className="num">#</th><th>Criterion</th><th>Component</th>
                  <th className="num">Attempts</th><th>Lesson rows</th>
                </tr>
              </thead>
              <tbody>
                {a.closed.map((r) => (
                  <tr key={r.order}>
                    <td className="num">{r.order}</td>
                    <td className="mono">{r.criterion}</td>
                    <td className="mono">{r.component}</td>
                    <td className="num">{r.patch_attempts}</td>
                    <td>
                      {r.lesson_ids.length === 0 ? (
                        <span className="hint">nothing to retrieve</span>
                      ) : r.trace ? (
                        <a href={r.trace} target="_blank" rel="noreferrer" className="mono">
                          <IconLoop size={11} /> {r.lesson_ids.join(', ')}
                        </a>
                      ) : (
                        <span className="mono">{r.lesson_ids.join(', ')}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="changed"><b>Arm</b>{a.changed}</p>
          </div>
        ))}
      </div>
    </>
  )
}
