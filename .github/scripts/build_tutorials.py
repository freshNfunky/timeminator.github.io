#!/usr/bin/env python3
"""Build data/tutorials.json for the Tutorials page from the YouTube channel feed.

The site is a static GitHub Pages site, so there is no server to query YouTube at
request time. This script runs in CI (see .github/workflows/tutorials.yml) and on
demand: it reads the channel's public Atom feed, turns each video into a tutorial
entry, downloads the thumbnail into the repo (so visitors make no third-party
request until they click play), and writes a newest-first JSON the page renders.

No API key is needed — the Atom feed is public. The feed only carries the most
recent uploads, so existing entries are merged and kept as the channel grows.
Hand edits are possible two ways: edit data/tutorials.json directly, or put
per-video corrections in data/tutorials.overrides.json (keyed by video id):

    {
      "VIDEOID": { "title": "...", "blurb": "...", "lang": "de", "hidden": false }
    }

Overrides win over anything derived from the feed; "hidden": true drops a video.
"""

import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

CHANNEL_ID = "UCBpYnsGOS-SYxcJdy5tdw_g"  # youtube.com/@TIMEMINATOR
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_PATH = os.path.join(ROOT, "data", "tutorials.json")
OVERRIDES_PATH = os.path.join(ROOT, "data", "tutorials.overrides.json")
THUMB_DIR = os.path.join(ROOT, "assets", "tutorials")
THUMB_WEB = "assets/tutorials"  # path as referenced from the page

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

# Whole-word markers used only to guess a video's language for the DE/EN filter.
DE_MARKERS = (" der ", " die ", " das ", " und ", " mit ", " wie ", " man ", " sie ",
              " für ", " auf ", " dieses ", " zeit", "projekt", "buch", "erklär",
              "ä", "ö", "ü", "ß")
EN_MARKERS = (" the ", " this ", " with ", " how ", " you ", " your ", " and ", " for ",
              " book", " time", " project", " tool", " self", " hosted")


def guess_lang(text):
    t = " " + text.lower() + " "
    de = sum(t.count(m) for m in DE_MARKERS)
    en = sum(t.count(m) for m in EN_MARKERS)
    return "de" if de > en else "en"


def make_blurb(description):
    """A short, clean sentence: the useful lead before the boilerplate / link."""
    if not description:
        return ""
    text = description.strip()
    # Cut at the first link or hard break — the boilerplate pitch follows it.
    for sep in ("http://", "https://", "\n", "  "):
        i = text.find(sep)
        if i > 0:
            text = text[:i]
    text = re.sub(r"\s+", " ", text).strip(" .…-")
    if len(text) > 180:
        cut = text[:180]
        text = cut[: cut.rfind(" ")] if " " in cut else cut
        text = text.rstrip() + "…"
    return text


def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": "timeminator-tutorials-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return data if binary else data.decode("utf-8")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def main():
    feed = ET.fromstring(fetch(FEED_URL))

    # Start from what we already have (keyed by id) so nothing is lost when a
    # video ages out of the feed's recent-uploads window.
    existing = {v["id"]: v for v in load_json(DATA_PATH, [])}
    overrides = load_json(OVERRIDES_PATH, {})

    for entry in feed.findall("a:entry", NS):
        vid = entry.find("yt:videoId", NS).text
        title = (entry.find("a:title", NS).text or "").strip()
        published = entry.find("a:published", NS).text
        desc_el = entry.find("media:group/media:description", NS)
        desc = desc_el.text if desc_el is not None else ""

        item = existing.get(vid, {})
        item.update({
            "id": vid,
            "title": title,
            "published": published,
            "blurb": make_blurb(desc),
            "lang": guess_lang(f"{title} {desc}"),
        })
        existing[vid] = item

    os.makedirs(THUMB_DIR, exist_ok=True)
    out = []
    for item in existing.values():
        ov = overrides.get(item["id"], {})
        if ov.get("hidden"):
            continue
        merged = {**item, **{k: v for k, v in ov.items() if k != "hidden"}}

        # Self-host the thumbnail so the page needs no Google request on load.
        thumb_file = os.path.join(THUMB_DIR, f"{merged['id']}.jpg")
        if not os.path.exists(thumb_file):
            for name in ("maxresdefault.jpg", "hqdefault.jpg"):
                try:
                    img = fetch(f"https://i.ytimg.com/vi/{merged['id']}/{name}", binary=True)
                    if len(img) > 1500:  # YouTube serves a tiny placeholder when a size is missing
                        with open(thumb_file, "wb") as f:
                            f.write(img)
                        break
                except Exception as e:  # noqa: BLE001 - keep going, page falls back to remote thumb
                    print(f"  ! thumbnail {merged['id']} {name}: {e}", file=sys.stderr)
        merged["thumb"] = f"{THUMB_WEB}/{merged['id']}.jpg" if os.path.exists(thumb_file) else ""
        out.append(merged)

    out.sort(key=lambda v: v.get("published", ""), reverse=True)

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Wrote {len(out)} tutorials to {os.path.relpath(DATA_PATH, ROOT)}")


if __name__ == "__main__":
    main()
