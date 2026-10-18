#!/usr/bin/env python3
"""Collect GitHub repository traffic (clones + repo page views) and append it to
a long-term CSV history under .github/traffic-data/.

The GitHub Traffic API only returns the last 14 days, so this runs on a weekly
schedule and merges each pull into the history by date (the API is authoritative
for the days it reports, so overlapping days are overwritten, never doubled).

NOTE: "views" here are views of the REPOSITORY PAGE on github.com, NOT visits to
the published website (timeminator.com). GitHub Pages has no built-in web
analytics; website visitors are measured separately via Matomo.

Env: REPO ("owner/name"), GH_TOKEN (needs administration:read + metadata:read).
"""
import csv
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

REPO = os.environ["REPO"]
TOKEN = os.environ["GH_TOKEN"]
OUT = Path(".github/traffic-data")
OUT.mkdir(parents=True, exist_ok=True)


def api(path: str):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "timeminator-traffic-collector",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def merge_timeseries(filename: str, rows: list) -> dict:
    """Merge API rows ({timestamp,count,uniques}) into a date-keyed CSV."""
    path = OUT / filename
    data: dict[str, tuple[int, int]] = {}
    if path.exists():
        with path.open() as fh:
            for row in csv.DictReader(fh):
                data[row["date"]] = (int(row["count"]), int(row["uniques"]))
    for r in rows:
        d = r["timestamp"][:10]
        data[d] = (int(r["count"]), int(r["uniques"]))
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "count", "uniques"])
        for d in sorted(data):
            w.writerow([d, data[d][0], data[d][1]])
    return data


def totals(data: dict, days: int) -> tuple[int, int]:
    """Sum counts over the last `days` recorded days; peak-daily uniques as a
    conservative proxy (daily uniques cannot be summed without double-counting)."""
    recent = [data[d] for d in sorted(data)[-days:]]
    return sum(c for c, _ in recent), max((u for _, u in recent), default=0)


def main() -> int:
    clones = api("traffic/clones?per=day").get("clones", [])
    views = api("traffic/views?per=day").get("views", [])
    cl = merge_timeseries("clones.csv", clones)
    vw = merge_timeseries("views.csv", views)

    (OUT / "referrers.json").write_text(
        json.dumps(api("traffic/popular/referrers"), indent=2) + "\n"
    )
    (OUT / "paths.json").write_text(
        json.dumps(api("traffic/popular/paths"), indent=2) + "\n"
    )

    cl_total = sum(c for c, _ in cl.values())
    vw_total = sum(c for c, _ in vw.values())
    cl14, cl14u = totals(cl, 14)
    vw14, vw14u = totals(vw, 14)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    span = f"{min(cl) if cl else '—'} … {max(cl) if cl else '—'}"

    (OUT / "README.md").write_text(
        f"""# Traffic history — `{REPO}`

_Last updated: {now}_

Long-term history of **repository** traffic (git clones + github.com repo-page
views), collected weekly via `.github/workflows/traffic-stats.yml` because the
GitHub Traffic API only exposes a rolling 14-day window.

> ⚠️ These are **not website visitors.** "Views" = views of the repo page on
> github.com, not visits to **timeminator.com** (served by GitHub Pages, which
> has no built-in analytics). Website traffic is measured separately via Matomo.

| Metric | Last 14 days | All-time recorded |
|---|---|---|
| Git clones | {cl14} (peak {cl14u} unique/day) | {cl_total} |
| Repo page views | {vw14} (peak {vw14u} unique/day) | {vw_total} |

Recorded span: {span}

Files:
- `clones.csv` — daily `date,count,uniques`
- `views.csv` — daily `date,count,uniques`
- `referrers.json` / `paths.json` — latest 14-day snapshot (not time-series)
"""
    )
    print(f"clones: 14d={cl14} all={cl_total} | views: 14d={vw14} all={vw_total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
