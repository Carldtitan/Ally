"""Ask the repository what pages the site has, instead of crawling for them.

Crawling `a[href]` only ever finds what the entry page chooses to link. On
BitEstate the router declares ten routes and the landing page links to two of
them; the other eight are behind a login, so a crawler reports a ten-page app as
a two-page one. The repository has no such blind spot: a route is written down
in the source whether or not anything links to it yet.

Four conventions, because four is what these projects actually use:

  Next.js App Router    app/**/page.tsx          -> /**
  Next.js Pages Router  pages/**.tsx             -> /**
  Client-side router    path="/thing" in src/**  -> /thing
  Plain static          **/*.html                -> /**.html

Dynamic segments are skipped. `app/property/[id]/page.tsx` and `path="/p/:id"`
name a shape, not a page, and guessing an id produces a 404 that would then be
audited as if it were a screen.
"""

from __future__ import annotations

import re
import sys
import pathlib
from urllib.parse import urljoin, urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import weave
except ImportError:
    weave = None


def _op(fn):
    return weave.op()(fn) if weave else fn


#: A path with a dynamic segment names a shape, not a page.
DYNAMIC = re.compile(r"(\[[^\]]+\]|:[A-Za-z_]|\*|\.\.\.)")
#: Route groups and private folders are organisation, not URL.
GROUP = re.compile(r"^[\(_]")


def _from_app_router(files: list[str]) -> list[str]:
    out = []
    for f in files:
        m = re.match(r"^(?:src/)?app/(.*)page\.(tsx|jsx|ts|js)$", f)
        if not m:
            continue
        segs = [s for s in m.group(1).strip("/").split("/") if s]
        if any(GROUP.match(s) for s in segs):
            segs = [s for s in segs if not GROUP.match(s)]
        route = "/" + "/".join(segs)
        if DYNAMIC.search(route):
            continue
        out.append(route.rstrip("/") or "/")
    return out


def _from_pages_router(files: list[str]) -> list[str]:
    out = []
    for f in files:
        m = re.match(r"^(?:src/)?pages/(.+)\.(tsx|jsx|ts|js)$", f)
        if not m:
            continue
        p = m.group(1)
        if p.startswith("_") or p.startswith("api/"):
            continue
        route = "/" + ("" if p == "index" else p.removesuffix("/index"))
        if DYNAMIC.search(route):
            continue
        out.append(route.rstrip("/") or "/")
    return out


def _from_html(files: list[str]) -> list[str]:
    out = []
    for f in files:
        if not f.lower().endswith((".html", ".htm")):
            continue
        # Strip a web-root prefix: public/about.html is served at /about.html.
        p = re.sub(r"^(public|static|dist|site|www|build)/", "", f)
        out.append("/" + ("" if p.lower() in ("index.html", "index.htm") else p))
    return out


@_op
def routes_from_repo(session, checkout: str, base_url: str,
                     limit: int = 8) -> list[str]:
    """Absolute URLs for the pages this repository declares.

    The entry URL always comes first, then the rest in the order the source
    lists them, deduplicated against it.
    """
    listing = session.exec(
        f"cd {checkout} && git ls-files | head -3000", timeout=180)
    files = [f.strip() for f in (listing.result or "").splitlines() if f.strip()]
    if not files:
        return []

    routes = _from_app_router(files) + _from_pages_router(files) + _from_html(files)

    # A client-side router writes its routes in source rather than in the file
    # tree, so read them out of it. BitEstate is one: ten routes in the config,
    # one index.html on disk.
    if len(routes) <= 1:
        grep = session.exec(
            "cd " + checkout + " && grep -rhoE "
            "'path=[\"'\"'\"'][^\"'\"'\"']+[\"'\"'\"']' src app 2>/dev/null "
            "| sort -u | head -40", timeout=180)
        for line in (grep.result or "").splitlines():
            m = re.search(r"""path=["']([^"']+)["']""", line)
            if not m:
                continue
            route = m.group(1)
            if not route.startswith("/") or DYNAMIC.search(route):
                continue
            routes.append(route.rstrip("/") or "/")

    base = base_url.rstrip("/")
    origin = f"{urlparse(base).scheme}://{urlparse(base).netloc}"
    seen, out = set(), []
    for route in routes:
        url = urljoin(origin + "/", route.lstrip("/"))
        url = url.rstrip("/") or origin
        if url in seen:
            continue
        seen.add(url)
        out.append(url)

    # The URL the user gave leads, whatever the source order says.
    entry = base or origin
    out = [entry] + [u for u in out if u.rstrip("/") != entry.rstrip("/")]
    return out[:limit]
