#!/usr/bin/env python3
"""
Rebuild the "Upstream" section of README.md from the GitHub API.

Two outputs:
  1. assets/stats-{light,dark}.svg  the headline numbers, as a designed panel.
     GitHub strips CSS from markdown, so SVG is the only way to get real type
     hierarchy on a profile page.
  2. the table between the LEDGER markers in README.md, merged-first.

It lists every pull request and issue mauriciopaim has opened on a repo he does
not own, plus anything in data/credits.json (work a maintainer authored and
credited him for, which no author search can find).

Run locally:   GITHUB_TOKEN=$(gh auth token) python3 scripts/update_ledger.py
In CI:         GITHUB_TOKEN is provided by actions/checkout
"""

import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

USER = "mauriciopaim"
ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
CREDITS = ROOT / "data" / "credits.json"
ASSETS = ROOT / "assets"
RAW = f"https://raw.githubusercontent.com/{USER}/{USER}/main/assets"
START = "<!-- LEDGER:START -->"
END = "<!-- LEDGER:END -->"

TOKEN = os.environ.get("GITHUB_TOKEN", "")
TITLE_MAX = 88

SANS = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

THEMES = {
    "light": {"bg": "#FFFFFF", "line": "#E5E5E5", "ink": "#111111", "muted": "#666666"},
    "dark": {"bg": "#0B0B0B", "line": "#272727", "ink": "#EDEDED", "muted": "#8A8A8A"},
}


def api(path):
    req = urllib.request.Request(
        "https://api.github.com/" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "mauriciopaim-profile-ledger",
            **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def search(query):
    q = urllib.parse.quote(query)
    return api(f"search/issues?q={q}&per_page=100&sort=created&order=desc")["items"]


def repo_of(item):
    return "/".join(item["repository_url"].split("/")[-2:])


def shorten(title):
    title = title.strip().rstrip(".")
    if len(title) <= TITLE_MAX:
        return title
    return title[:TITLE_MAX].rsplit(" ", 1)[0] + "..."


def stars(n):
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def collect():
    items = []

    for kind in ("pr", "issue"):
        for it in search(f"author:{USER} type:{kind} -user:{USER}"):
            if kind == "pr":
                state = "merged" if it.get("pull_request", {}).get("merged_at") else it["state"]
            else:
                state = it["state"]
            items.append(
                {
                    "repo": repo_of(it),
                    "url": it["html_url"],
                    "title": it["title"],
                    "state": state,
                    "date": it["created_at"][:10],
                    "role": None,
                    "shipped": None,
                }
            )

    if CREDITS.exists():
        for c in json.loads(CREDITS.read_text()):
            c.setdefault("role", None)
            c.setdefault("shipped", None)
            items.append(c)

    return items


def stat_svg(cells, theme):
    """A four-cell panel. Big numeral over a small caps label, thin dividers."""
    t = THEMES[theme]
    w, h = 880, 132
    cw = w / len(cells)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="'
        + ", ".join(f"{v} {label.lower()}" for v, label in cells)
        + '">',
        f'<rect width="{w}" height="{h}" fill="{t["bg"]}"/>',
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" fill="none" stroke="{t["line"]}"/>',
    ]
    for i, (value, label) in enumerate(cells):
        x = i * cw + 34
        if i:
            out.append(
                f'<line x1="{i * cw:.0f}" y1="22" x2="{i * cw:.0f}" y2="{h - 22}" '
                f'stroke="{t["line"]}" stroke-width="1"/>'
            )
        out.append(
            f'<text x="{x:.0f}" y="76" font-family="{SANS}" font-size="46" '
            f'font-weight="600" letter-spacing="-1.6" fill="{t["ink"]}">{value}</text>'
        )
        out.append(
            f'<text x="{x:.0f}" y="102" font-family="{SANS}" font-size="11" '
            f'font-weight="600" letter-spacing="1.9" fill="{t["muted"]}">{label}</text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def render(items):
    repos = sorted({i["repo"] for i in items})
    meta = {}
    for repo in repos:
        try:
            r = api(f"repos/{repo}")
            meta[repo] = r["stargazers_count"]
        except urllib.error.HTTPError:
            meta[repo] = 0

    shipped = sum(1 for i in items if i["state"] == "merged")
    resolved = sum(1 for i in items if i["state"] == "closed")
    open_ = sum(1 for i in items if i["state"] == "open")

    cells = [
        (str(shipped), "SHIPPED"),
        (str(resolved), "RESOLVED"),
        (str(open_), "OPEN"),
        (str(len(repos)), "PROJECTS"),
    ]

    digest = ""
    for theme in ("light", "dark"):
        svg = stat_svg(cells, theme)
        (ASSETS / f"stats-{theme}.svg").write_text(svg)
        digest += svg
    # Camo caches by URL, so a changed file at a stable URL can serve stale.
    version = hashlib.sha256(digest.encode()).hexdigest()[:8]

    rank = {"merged": 0, "closed": 1, "open": 2}
    rows = sorted(items, key=lambda r: (rank[r["state"]], -meta[r["repo"]], r["date"]))

    lines = [
        "<picture>",
        f'  <source media="(prefers-color-scheme: dark)" srcset="{RAW}/stats-dark.svg?v={version}">',
        f'  <img alt="{shipped} shipped, {resolved} resolved, {open_} open, '
        f'{len(repos)} projects" src="{RAW}/stats-light.svg?v={version}">',
        "</picture>",
        "",
        "| | Contribution | Project |",
        "|:--|:--|:--|",
    ]

    for r in rows:
        note = []
        if r.get("shipped"):
            note.append(f"shipped in {r['shipped']}")
        if r.get("role"):
            note.append(r["role"])
        cell = f"[{shorten(r['title'])}]({r['url']})"
        if note:
            cell += "<br><sub>" + ", ".join(note) + "</sub>"
        project = (
            f"[{r['repo'].split('/')[1]}](https://github.com/{r['repo']})"
            f"<br><sub>{stars(meta[r['repo']])} stars</sub>"
        )
        lines.append(f"| `{r['state']}` | {cell} | {project} |")

    return "\n".join(lines) + "\n"


def main():
    items = collect()
    if not items:
        print("no items found, refusing to blank the section", file=sys.stderr)
        return 1

    body = render(items)
    text = README.read_text()
    if START not in text or END not in text:
        print(f"markers {START} / {END} missing from README.md", file=sys.stderr)
        return 1

    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    new = f"{head}{START}\n\n{body}\n{END}{tail}"

    if new == text:
        print("ledger unchanged")
        return 0

    README.write_text(new)
    print(f"ledger updated: {len(items)} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
