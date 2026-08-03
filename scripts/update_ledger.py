#!/usr/bin/env python3
"""
Rebuild the "Upstream" section of README.md from the GitHub API.

It lists every pull request and issue mauriciopaim has opened on a repo he does
not own, plus anything in data/credits.json (work a maintainer authored and
credited him for, which no author search can find).

Run locally:   GITHUB_TOKEN=$(gh auth token) python3 scripts/update_ledger.py
In CI:         GITHUB_TOKEN is provided by actions/checkout
"""

import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

USER = "mauriciopaim"
ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
CREDITS = ROOT / "data" / "credits.json"
START = "<!-- LEDGER:START -->"
END = "<!-- LEDGER:END -->"

TOKEN = os.environ.get("GITHUB_TOKEN", "")
TITLE_MAX = 78


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
    cut = title[:TITLE_MAX].rsplit(" ", 1)[0]
    return cut + "..."


def stars(n):
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def collect():
    items = []

    for kind in ("pr", "issue"):
        for it in search(f"author:{USER} type:{kind} -user:{USER}"):
            if kind == "pr":
                merged = bool(it.get("pull_request", {}).get("merged_at"))
                state = "merged" if merged else it["state"]
            else:
                state = it["state"]
            items.append(
                {
                    "repo": repo_of(it),
                    "url": it["html_url"],
                    "title": it["title"],
                    "state": state,
                    "kind": kind,
                    "date": it["created_at"][:10],
                    "role": None,
                    "shipped": None,
                }
            )

    if CREDITS.exists():
        for c in json.loads(CREDITS.read_text()):
            c.setdefault("kind", "pr")
            c.setdefault("role", None)
            c.setdefault("shipped", None)
            items.append(c)

    return items


def render(items):
    by_repo = {}
    for it in items:
        by_repo.setdefault(it["repo"], []).append(it)

    meta = {}
    for repo in by_repo:
        try:
            r = api(f"repos/{repo}")
            meta[repo] = (r["stargazers_count"], r.get("description") or "")
        except urllib.error.HTTPError:
            meta[repo] = (0, "")

    shipped = sum(1 for i in items if i["state"] == "merged")
    landed = sum(1 for i in items if i["state"] in ("merged", "closed"))
    open_ = sum(1 for i in items if i["state"] == "open")

    lines = [
        f"`{shipped} shipped` &nbsp; `{landed - shipped} resolved` &nbsp; "
        f"`{open_} open` &nbsp; `{len(by_repo)} projects`",
        "",
    ]

    def repo_rank(repo):
        rows = by_repo[repo]
        return (
            -sum(1 for r in rows if r["state"] == "merged"),
            -meta[repo][0],
        )

    for repo in sorted(by_repo, key=repo_rank):
        star, _ = meta[repo]
        lines.append(f"**[{repo}](https://github.com/{repo})** &nbsp;·&nbsp; {stars(star)} stars")
        lines.append("")
        rows = sorted(
            by_repo[repo],
            key=lambda r: ({"merged": 0, "closed": 1, "open": 2}[r["state"]], r["date"]),
        )
        for r in rows:
            bits = [f"`{r['state']}`", f"[{shorten(r['title'])}]({r['url']})"]
            tail = []
            if r.get("shipped"):
                tail.append(f"shipped in {r['shipped']}")
            if r.get("role"):
                tail.append(r["role"])
            line = "- " + " &nbsp; ".join(bits)
            if tail:
                line += "  \n  <sub>" + ", ".join(tail) + "</sub>"
            lines.append(line)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


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
