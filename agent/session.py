"""One Daytona sandbox, reused across states, producing Recordings.

The sandbox is remote compute. Weave tracing runs here, in the orchestrator,
never inside the sandbox: api.wandb.ai is not on Daytona's Tier 2 allowlist, so
a trace written from in there would silently fail.

Screenshot bytes cross into `ally.storage.save_screenshot` and are never seen
again. What travels on is the ref it returned.
"""

from __future__ import annotations

import io
import os
import json
import time
import base64

from ally import storage
from .browser import CHROME_FLAGS, STATES, build_runner
from .recording import Candidate, Recording, Stop


class Session:
    """A started sandbox with Chromium and a virtual display."""

    def __init__(self, sandbox_id: str | None = None) -> None:
        from daytona import Daytona, DaytonaConfig

        self.client = Daytona(DaytonaConfig(
            api_key=os.environ["DAYTONA_API_KEY"],
            api_url=os.environ.get("DAYTONA_API_URL", "https://app.daytona.io/api"),
        ))
        if sandbox_id:
            self.sb = self.client.get(sandbox_id)
            if str(self.sb.state) != "SandboxState.STARTED":
                self.client.start(self.sb)
                self.sb = self.client.get(sandbox_id)
            self._owned = False
        else:
            from daytona import CreateSandboxFromSnapshotParams
            self.sb = self.client.create(CreateSandboxFromSnapshotParams(
                public=True, auto_stop_interval=30,
                labels={"project": "ally", "purpose": "audit"}))
            self._owned = True
        self.id = self.sb.id
        self._ready = False

    # -- lifecycle --------------------------------------------------------

    def start_browser(self) -> None:
        if self._ready:
            return
        self.sb.computer_use.start()
        self.sb.process.exec(
            f"pkill -f chromium; sleep 2; DISPLAY=:0 nohup chromium {CHROME_FLAGS} "
            "about:blank > /tmp/chromium.log 2>&1 & echo ok", timeout=150)
        self.sb.process.exec("pip install --quiet websocket-client 2>&1 | tail -1; true",
                             timeout=240)
        time.sleep(3)
        self._ready = True

    def watch_url(self) -> str:
        """The live noVNC view. The port root serves a directory index; the
        viewer itself is /vnc.html."""
        return (self.sb.get_preview_link(6080).url.rstrip("/")
                + "/vnc.html?autoconnect=true&resize=scale")

    def close(self) -> None:
        if self._owned:
            try:
                self.client.delete(self.sb)
            except Exception:
                pass

    # -- recording --------------------------------------------------------

    def record(self, url: str, state: str, run_id: str,
               max_tabs: int = 40) -> Recording:
        """Drive one state and return its Recording."""
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}; known: {sorted(STATES)}")
        self.start_browser()

        self.sb.fs.upload_file(build_runner(url, state, max_tabs).encode(),
                               "/tmp/ally_record.py")
        res = self.sb.process.exec("cd /tmp && python3 ally_record.py 2>&1 | tail -4",
                                   timeout=600)
        out = (res.result or "").strip()
        line = next((l for l in out.splitlines() if l.startswith("RESULT")), None)
        if not line:
            return Recording(url=url, state=state, state_reached=False,
                             reach_note=f"the recorder produced no result: {out[:200]}")
        raw = json.loads(line[len("RESULT "):])
        return self._assemble(raw, run_id)

    def _assemble(self, raw: dict, run_id: str) -> Recording:
        rec = Recording(
            url=raw["url"], state=raw["state"],
            state_reached=raw["state_reached"], reach_note=raw["reach_note"],
            truncated=raw.get("truncated", False),
            page_height=raw.get("page_height", 0),
        )
        prev_png: bytes | None = None
        for s in raw.get("stops", []):
            png = base64.b64decode(s.pop("png_b64") or "") or None
            ref = None
            if png:
                ref = storage.save_screenshot(run_id, rec.state, s["index"], png)
            stop = Stop(
                index=s["index"], tag=s["tag"], role=s.get("role"), name=s.get("name"),
                x=s["x"], y=s["y"], w=s["w"], h=s["h"], selector=s["selector"],
                screenshot=ref, obscured_by=s.get("obscured_by"),
            )
            if prev_png is not None and png is not None and s["index"] > 0:
                stop.focus_delta = crop_diff(prev_png, png, stop)
            rec.stops.append(stop)
            prev_png = png

        for c in raw.get("candidates", []):
            rec.candidates.append(Candidate(
                selector=c["selector"], tag=c["tag"], role=c.get("role"),
                name=c.get("name"), x=c["x"], y=c["y"], w=c["w"], h=c["h"],
                focusable=bool(c.get("focusable")),
                sources=tuple(c.get("sources", ())),
            ))
        return rec


def crop_diff(before: bytes, after: bytes, stop: Stop, pad: int = 8) -> float | None:
    """Fraction of pixels that changed around the focused element.

    Cropped to the element plus a small margin, because the focus indicator is
    drawn just outside the box and a whole-page diff would be swamped by
    scrolling. Returns None when the crop is empty or Pillow is unavailable, so
    the check reports not_evaluated rather than inventing a number.
    """
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    try:
        a = Image.open(io.BytesIO(before)).convert("RGB")
        b = Image.open(io.BytesIO(after)).convert("RGB")
    except Exception:
        return None
    if a.size != b.size:
        return None

    # Screenshots are viewport-sized, so crop in viewport space. The recorder
    # stores document coordinates, so subtract the scroll implied by the frame.
    left = max(0, stop.x - pad)
    top = max(0, stop.y - pad)
    right = min(a.width, stop.x + stop.w + pad)
    bottom = min(a.height, stop.y + stop.h + pad)
    if right <= left or bottom <= top:
        # The element scrolled out of the captured frame: compare whole frames
        # rather than reporting a number for a region we did not see.
        box = None
    else:
        box = (left, top, right, bottom)

    if box:
        a, b = a.crop(box), b.crop(box)
    diff = ImageChops.difference(a, b).convert("L")
    total = diff.width * diff.height
    if total == 0:
        return None
    changed = sum(count for value, count in
                  zip(range(256), diff.histogram()) if value > 12)
    return changed / total
