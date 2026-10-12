#!/usr/bin/env python3
"""
ats_normalizers.py — read Greenhouse / Ashby / Lever job boards as one schema.

Why this exists
---------------
Greenhouse, Ashby and Lever all serve their job boards as public JSON at
predictable URLs. No login, no API key, no headless browser. The catch is that
each vendor picked a different shape, a different timestamp format, and a
different key for "the URL of this posting" — so a pipeline that reads more
than one vendor needs three normalizers.

This module is those three normalizers, in one file, standard library only.

Endpoints
---------
    greenhouse  https://boards-api.greenhouse.io/v1/boards/{slug}/jobs      -> {"jobs": [...]}
    ashby       https://api.ashbyhq.com/posting-api/job-board/{slug}        -> {"jobs": [...]}
    lever       https://api.lever.co/v0/postings/{slug}?mode=json           -> [ ... ]  (bare array)

Normalized schema (one dict per posting)
----------------------------------------
    provider    greenhouse | ashby | lever
    slug        the board slug the row came from
    id          vendor-side posting id, string
    title
    location    human-readable location, or None
    department  team / department name, or None
    url         public URL of the posting
    updatedAt   ISO 8601 UTC string, or None   <- vendors disagree on format; this fixes it

Usage
-----
    python3 ats_normalizers.py stripe                        # auto-detect provider
    python3 ats_normalizers.py greenhouse:stripe             # explicit
    python3 ats_normalizers.py https://jobs.ashbyhq.com/openai
    python3 ats_normalizers.py stripe --limit 5 --json

    # as a library
    from ats_normalizers import fetch, detect
    rows = fetch("greenhouse:stripe")

Notes
-----
* Public endpoints, but not yours. Keep the delay, keep the concurrency low.
  Default delay is 0 because a single call is a single call; the CLI keeps it
  for multi-board runs — see --delay.
* Check the vendor terms before redistributing postings. Postings often carry
  personal data (recruiter names, emails); handle accordingly.
* MIT licensed. Written with AI assistance and verified by hand.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
import time
import urllib.error
import urllib.request

__all__ = [
    "fetch", "detect", "fetch_greenhouse", "fetch_ashby", "fetch_lever",
    "normalize_timestamp", "PROVIDERS", "DEFAULT_HOSTS",
]

UA = "ats-normalizers/1.0 (+https://github.com/yff124/apify-actors)"
TIMEOUT = 25

PROVIDERS = ("greenhouse", "ashby", "lever")

# careers-page host -> provider. Used by detect().
DEFAULT_HOSTS = {
    "job-boards.greenhouse.io": "greenhouse",
    "boards.greenhouse.io": "greenhouse",
    "boards-api.greenhouse.io": "greenhouse",
    "jobs.ashbyhq.com": "ashby",
    "api.ashbyhq.com": "ashby",
    "jobs.lever.co": "lever",
    "api.lever.co": "lever",
}


# --------------------------------------------------------------------- helpers

def _get_json(url: str, timeout: int = TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def normalize_timestamp(value):
    """Return an ISO 8601 UTC string, or None.

    Greenhouse/Ashby hand back ISO strings; Lever hands back epoch
    milliseconds as an int. Sorting a mixed array without this produces
    silent nonsense rather than an error.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        n = int(value)
        if n > 10_000_000_000:      # milliseconds
            n //= 1000
        try:
            return _dt.datetime.fromtimestamp(n, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip().replace("Z", "+00:00")
        try:
            d = _dt.datetime.fromisoformat(s)
        except ValueError:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return d.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# -------------------------------------------------------------------- providers

def fetch_greenhouse(slug: str, timeout: int = TIMEOUT):
    """GET boards-api.greenhouse.io/v1/boards/{slug}/jobs"""
    data = _get_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs" % slug, timeout)
    rows = []
    for j in data.get("jobs", []):
        rows.append({
            "provider": "greenhouse",
            "slug": slug,
            "id": str(j.get("id")) if j.get("id") is not None else None,
            "title": _clean(j.get("title")),
            "location": _clean((j.get("location") or {}).get("name")),
            "department": _clean(", ".join(
                d.get("name", "") for d in (j.get("departments") or []) if d.get("name")) or None),
            "url": _clean(j.get("absolute_url")),
            "updatedAt": normalize_timestamp(j.get("updated_at")),
        })
    return rows


def fetch_ashby(slug: str, timeout: int = TIMEOUT):
    """GET api.ashbyhq.com/posting-api/job-board/{slug}"""
    data = _get_json("https://api.ashbyhq.com/posting-api/job-board/%s" % slug, timeout)
    rows = []
    for j in data.get("jobs", []):
        # Ashby nests location fields differently per posting type.
        loc = j.get("location")
        if isinstance(loc, dict):
            loc = loc.get("name") or loc.get("locationName")
        rows.append({
            "provider": "ashby",
            "slug": slug,
            "id": str(j.get("id")) if j.get("id") is not None else None,
            "title": _clean(j.get("title")),
            "location": _clean(loc) or _clean(j.get("locationName")),
            "department": _clean(j.get("department")) or _clean(j.get("team")),
            "url": _clean(j.get("jobUrl")) or _clean(j.get("applyUrl")),
            "updatedAt": normalize_timestamp(j.get("publishedAt") or j.get("updatedAt")),
        })
    return rows


def fetch_lever(slug: str, timeout: int = TIMEOUT):
    """GET api.lever.co/v0/postings/{slug}?mode=json — returns a BARE ARRAY."""
    data = _get_json("https://api.lever.co/v0/postings/%s?mode=json" % slug, timeout)
    if isinstance(data, dict):          # error payloads come back as objects
        data = data.get("data", [])
    rows = []
    for j in data:
        cats = j.get("categories") or {}
        rows.append({
            "provider": "lever",
            "slug": slug,
            "id": str(j.get("id")) if j.get("id") is not None else None,
            "title": _clean(j.get("text")),
            "location": _clean(cats.get("location")),
            "department": _clean(cats.get("team")) or _clean(cats.get("department")),
            "url": _clean(j.get("hostedUrl")),
            "updatedAt": normalize_timestamp(j.get("createdAt")),
        })
    return rows


_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "ashby": fetch_ashby,
    "lever": fetch_lever,
}


# ----------------------------------------------------------------------- detect

def detect(target: str):
    """Work out (provider, slug) from a careers URL, a 'provider:slug', or a bare slug.

    Returns (provider_or_None, slug_or_None). provider is None when only a bare
    slug was given — callers should then try the providers in order.
    """
    target = (target or "").strip()
    if not target:
        return None, None

    if ":" in target and "/" not in target:
        head, tail = target.split(":", 1)
        if head.lower() in PROVIDERS:
            return head.lower(), tail.strip() or None

    if "://" in target or target.startswith("www.") or "/" in target:
        url = target if "://" in target else "https://" + target
        m = re.match(r"https?://([^/]+)/([^/?#]+)", url)
        if m:
            host, first = m.group(1).lower(), m.group(2)
            provider = DEFAULT_HOSTS.get(host)
            if provider is None:
                for known, p in DEFAULT_HOSTS.items():
                    if host.endswith(known):
                        provider = p
                        break
            # /careers and /jobs are not slugs; the slug usually follows.
            if provider and first.lower() in ("careers", "jobs", "job", "openings"):
                rest = url.split("/", 4)
                first = rest[4].split("/")[0] if len(rest) > 4 else ""
            return provider, (first or None)

    # bare slug
    if re.fullmatch(r"[A-Za-z0-9._-]+", target):
        return None, target
    return None, None


# ------------------------------------------------------------------------ fetch

def fetch(target: str, provider: str | None = None, limit: int | None = None,
          timeout: int = TIMEOUT, delay: float = 0.0):
    """Fetch and normalize one board.

    target      bare slug, 'provider:slug', or a careers URL
    provider    force a provider (overrides detection)
    limit       truncate the result
    delay       seconds to sleep BEFORE the request (politeness; default 0)

    A board that exists but has no openings is a success with an empty list —
    not an error. Test for that before concluding "wrong slug".
    """
    detected, slug = detect(target)
    provider = (provider or detected or "").lower() or None
    if not slug:
        raise ValueError("could not work out a slug from %r" % target)
    if provider and provider not in _FETCHERS:
        raise ValueError("unknown provider %r (expected one of %s)"
                         % (provider, ", ".join(PROVIDERS)))

    if delay:
        time.sleep(delay)

    if provider:
        rows = _FETCHERS[provider](slug, timeout)
    else:
        # Bare slug: try each provider until one answers. An empty-but-valid
        # board stops the search too — it is a real answer, not a miss.
        rows, errors = [], []
        for p in PROVIDERS:
            try:
                rows = _FETCHERS[p](slug, timeout)
                provider = p
                break
            except urllib.error.HTTPError as e:
                errors.append("%s:HTTP%d" % (p, e.code))
            except Exception as e:                       # network / parse
                errors.append("%s:%s" % (p, type(e).__name__))
        else:
            raise RuntimeError("no provider answered for slug %r (%s)"
                               % (slug, ", ".join(errors)))

    rows = [r for r in rows if r.get("title")]
    return rows[:limit] if limit else rows


# -------------------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Read a Greenhouse / Ashby / Lever job board as one normalized schema.")
    ap.add_argument("target", help="bare slug, provider:slug, or a careers URL")
    ap.add_argument("--provider", choices=PROVIDERS, default=None,
                    help="force a provider instead of auto-detecting")
    ap.add_argument("--limit", type=int, default=0, help="only print the first N rows")
    ap.add_argument("--json", action="store_true", help="print raw JSON instead of a table")
    ap.add_argument("--delay", type=float, default=0.0,
                    help="seconds to sleep before the request (be polite on bulk runs)")
    args = ap.parse_args(argv)

    try:
        rows = fetch(args.target, provider=args.provider,
                     limit=args.limit or None, delay=args.delay)
    except Exception as e:
        print("error: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if not rows:
        print("0 postings (the board answered, it just has nothing open right now)")
        return 0

    print("%s  slug=%s  %d posting(s)%s"
          % (rows[0]["provider"], rows[0]["slug"], len(rows),
             "  (truncated)" if args.limit and len(rows) == args.limit else ""))
    for r in rows:
        loc = r["location"] or "-"
        print("  %-56s  %-24s  %s" % (r["title"][:56], loc[:24], r["updatedAt"] or "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
