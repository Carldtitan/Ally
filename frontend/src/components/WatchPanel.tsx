// The browser, live.
//
// Ally drives a real Chromium inside the sandbox under Xvfb, and the sandbox has
// published a noVNC stream of that desktop the whole time -- the run just never
// carried the URL. This is the difference between reading that a page was driven
// and watching it happen.

import { useState } from 'react'
import { Icon } from '../Icon'

export function WatchPanel({ url, live }: { url: string; live: boolean }) {
  const [open, setOpen] = useState(live)
  if (!url) return null

  return (
    <section className="section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Live</span>
          <h2>The browser Ally is driving</h2>
          <p>The sandbox desktop, streamed. What you see is the page being tabbed
             through, in real time.</p>
        </div>
        <div className="page-action-row">
          <button className="button secondary" onClick={() => setOpen(!open)}>
            <Icon name={open ? 'close' : 'eye'} />
            {open ? 'Hide' : 'Show'}
          </button>
          <a className="button secondary" href={url} target="_blank" rel="noreferrer">
            <Icon name="external" /> Full screen
          </a>
        </div>
      </div>

      {open && (
        <div className="frame" style={{ aspectRatio: '1024 / 740' }}>
          <iframe
            src={url}
            title="The sandbox desktop Ally is driving"
            style={{ width: '100%', height: '100%', border: 0, display: 'block' }}
            allow="clipboard-read; clipboard-write"
          />
        </div>
      )}
    </section>
  )
}
