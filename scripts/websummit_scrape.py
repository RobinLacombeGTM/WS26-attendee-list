#!/usr/bin/env python3
"""
Export the Web Summit attendee directory you can already browse with your own ticket.

The attendee portal (attend.websummit.com) is server-rendered. Its directory loads 50 cards per
request from one endpoint:
  GET https://attend.websummit.com/<event>/discovery/attendances.turbo_stream?page=N&filters...
Your browser calls it with a session cookie. This script reads that cookie from a cURL command you
copy from your own browser and save to a file. The cookie is never printed.

The directory comes back in a different random order on every request, so paging through it
misses people. The export works by filters instead: a filter slice with fewer than 50 people fits
on one page and is complete. Full slices are split further (attendee type, country, industry,
company size) until each one fits.

Commands:
  probe    2 requests: checks the session and lists the attendee types and their filters
  slice    saves every filter slice to <out>/raw/ (one request every 2.5 s, stops at the first refusal)
  build    turns the saved slices into <out>/attendees.csv (no network)

Safeguards built in:
  - one request at a time, at least 2.5 seconds apart (Web Summit blocks bursts)
  - stops at once on 401, 403, 429 or a redirect to the login page; no retry loop
  - `slice` needs --budget N and never sends more than N requests
  - an interrupted export resumes where it stopped: saved slices are never requested twice

Usage:
  python3 websummit_scrape.py probe --curl websummit_curl.txt
  python3 websummit_scrape.py slice --curl websummit_curl.txt --budget 1300
  python3 websummit_scrape.py slice --curl websummit_curl.txt --budget 400 --types partner,growth,beta,speaker
  python3 websummit_scrape.py build
"""

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:  # build needs no network, so only fail when a request is made
    requests = None

HOST = "https://attend.websummit.com"
PAGE_SIZE = 50
THROTTLE = 2.5            # seconds between requests, never lower
MAX_PAGES = 400           # safety ceiling when a slice cannot be split further
DIMS = ["attendee_type", "countries", "industries", "sizes"]
STOP_CODES = {401: "session expired: copy a fresh cURL from your browser and rerun (the export resumes)",
              403: "access refused by Web Summit: stop here, do not retry",
              429: "Web Summit asked to slow down: stop here, wait at least an hour before resuming"}

PEOPLE_COLS = ["user_id", "first_name", "last_name", "title", "company_name", "company_type", "industry",
               "country", "badge", "occupation", "partner_type", "business_types", "linked_in",
               "company_website", "company_linkedin", "profile_url"]

CARD_SPLIT = re.compile(r'<div class="card w-100 mb-2 ?">')


# ------------------------------------------------------------------ auth --
def read_session(curl_path: Path) -> str:
    """Return the cookie string from a cURL file copied from the browser. Never printed."""
    if not curl_path.exists():
        raise SystemExit(f"[auth] {curl_path} not found. Save the copied cURL command in that file first.")
    try:
        os.chmod(curl_path, 0o600)
    except OSError:
        pass
    text = curl_path.read_text()
    m = (re.search(r"(?:-b|--cookie)\s+'([^']*)'", text) or re.search(r'(?:-b|--cookie)\s+"([^"]*)"', text)
         or re.search(r"cookie:\s*([^'\"\n]+)", text, re.I))
    if not m or "_attendee_portal_session" not in m.group(1):
        raise SystemExit("[auth] no Web Summit session cookie in that cURL. Copy a request named "
                         "'attendances.turbo_stream' (Network tab, right-click > Copy > Copy as cURL).")
    print("[auth] session cookie found (not shown)", file=sys.stderr)
    return m.group(1).strip()


def headers(cookie: str, event: str, kind: str = "stream") -> dict:
    h = {"user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/130.0 Safari/537.36",
         "referer": f"{HOST}/{event}/discovery?active_tab=attendances&connection_filter=all",
         "cookie": cookie}
    if kind == "stream":
        h.update({"accept": "text/vnd.turbo-stream.html, text/html, application/xhtml+xml",
                  "turbo-frame": "next-page-attendances"})
    else:
        h["accept"] = "text/html"
    return h


# --------------------------------------------------------------- network --
class Client:
    """One request at a time, a fixed pause between requests, a hard request budget."""

    def __init__(self, cookie: str, event: str, budget: int):
        if requests is None:
            raise SystemExit("The `requests` package is missing: run `python3 -m pip install requests`")
        self.s, self.cookie, self.event, self.budget = requests.Session(), cookie, event, budget
        self.sent, self.last = 0, 0.0

    def get(self, url: str, params=None, kind: str = "stream") -> str:
        if self.sent >= self.budget:
            raise SystemExit(f"[budget] {self.sent} requests sent, budget reached. Rerun with a fresh "
                             "--budget only if the user agrees; saved slices are kept.")
        for attempt in (1, 2):
            wait = THROTTLE - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.sent += 1
            self.last = time.time()
            r = self.s.get(url, params=params, headers=headers(self.cookie, self.event, kind), timeout=30,
                           allow_redirects=False)
            if r.status_code in STOP_CODES:
                raise SystemExit(f"[stop] HTTP {r.status_code}: {STOP_CODES[r.status_code]}")
            if r.status_code in (301, 302, 303, 307, 308):
                raise SystemExit("[stop] redirected to the login page: the session expired or was signed out. "
                                 "Copy a fresh cURL and rerun (the export resumes).")
            if r.status_code >= 500 and attempt == 1 and self.sent < self.budget:
                print(f"[server] HTTP {r.status_code}, one retry in 10 s", file=sys.stderr)
                time.sleep(10)
                continue
            if r.status_code != 200:
                raise SystemExit(f"[stop] HTTP {r.status_code} from Web Summit: stopping")
            ctype = r.headers.get("content-type", "")
            if kind == "stream" and "turbo-stream" not in ctype:
                raise SystemExit(f"[stop] unexpected answer ({ctype or 'no type'}): possibly a security check. "
                                 "Stop here, open the portal in your browser, do not retry.")
            return r.text
        raise SystemExit("[stop] Web Summit server error twice: stopping")

    def page(self, filters: list, n: int) -> str:
        params = [("connection_filter", "all"), ("q", "")] + list(filters) + [("page", n)]
        return self.get(f"{HOST}/{self.event}/discovery/attendances.turbo_stream", params)

    def discovery(self) -> str:
        return self.get(f"{HOST}/{self.event}/discovery?active_tab=attendances&connection_filter=all",
                        kind="html")


# --------------------------------------------------------------- parsing --
def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_cards(page_html: str, event: str) -> list:
    rows = []
    for chunk in CARD_SPLIT.split(page_html)[1:]:
        pid = re.search(rf'href="/{re.escape(event)}/profiles/([0-9a-f-]{{36}})"', chunk)
        if not pid:
            continue
        name = re.search(r'<span class="mt-2 mt-sm-0">(.*?)</span>', chunk, re.S)
        badges = re.findall(r'<span class="badge-secondary[^"]*">(.*?)</span>', chunk, re.S)
        headline = re.search(r'<p class="mb-1 fs-12[^"]*">(.*?)</p>', chunk, re.S)
        industry = re.search(r'bi-buildings[^>]*></i>\s*<span[^>]*>(.*?)</span>', chunk, re.S)
        country = re.search(r'bi-geo-alt[^>]*></i>\s*<span[^>]*>(.*?)</span>', chunk, re.S)
        hl = _text(headline.group(1)) if headline else ""
        title, company = (hl.split(" at ", 1) if " at " in hl else (hl, ""))
        full = _text(name.group(1)) if name else ""
        first, _, last = full.partition(" ")
        badge_list = list(dict.fromkeys(_text(b) for b in badges))  # a card can repeat a type
        badge = " | ".join(badge_list)
        rows.append({"user_id": pid.group(1), "first_name": first, "last_name": last,
                     "title": title.strip(), "company_name": company.strip(),
                     "company_type": "; ".join(b.lower() for b in badge_list), "badge": badge,
                     "industry": _text(industry.group(1)) if industry else "",
                     "country": _text(country.group(1)) if country else "",
                     "profile_url": f"{HOST}/{event}/profiles/{pid.group(1)}"})
    return rows


def parse_filter_options(page_html: str) -> dict:
    """{dimension: [(value, label)]} from the filter <select> menus of the discovery page."""
    opts = {}
    for dim in DIMS:
        m = re.search(rf'<select[^>]*name="filters\[{dim}\]\[\]"[^>]*>([\s\S]*?)</select>', page_html)
        if not m:
            raise SystemExit(f"[parse] filter '{dim}' not found on the discovery page: the portal changed. Stop.")
        opts[dim] = [(v, html.unescape(lbl).strip()) for v, lbl in
                     re.findall(r'<option value="([^"]*)">(.*?)</option>', m.group(1)) if v]
    return opts


# ---------------------------------------------------------------- probe --
def cmd_probe(args):
    c = Client(read_session(args.curl), args.event, budget=2)
    opts = parse_filter_options(c.discovery())
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    (args.raw_dir / "discovery.json").write_text(json.dumps(opts), encoding="utf-8")
    cards = parse_cards(c.page([], 1), args.event)
    if not cards:
        raise SystemExit("[probe] the session works but the directory page is empty. Check you can see "
                         "attendees in the portal in your browser.")
    print(f"Session works: page 1 shows {len(cards)} attendee cards.")
    print("Attendee types: " + ", ".join(v for v, _ in opts["attendee_type"]))
    print(f"Filters: {len(opts['countries'])} countries, {len(opts['industries'])} industries, "
          f"{len(opts['sizes'])} company sizes.")
    print("\nFull directory (Web Summit Lisbon, ~15,000+ people): budget about 1,300 requests, "
          f"~{1300 * THROTTLE / 60:.0f} min. Only some attendee types (e.g. --types partner,growth,beta): "
          "budget about 400. Requests not needed are not sent.")
    print("Next step, only with the user's OK:  slice --budget N  [--types ...]")


# ---------------------------------------------------------------- slice --
class Slicer:
    def __init__(self, client: Client, opts: dict, raw_dir: Path, event: str):
        self.c, self.opts, self.event = client, opts, event
        self.dir = raw_dir / "slices"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self.dir / "manifest.jsonl"
        self.done = {}
        if self.manifest.exists():
            for line in self.manifest.read_text().splitlines():
                rec = json.loads(line)
                self.done[rec["key"]] = rec["cards"]
        self.incomplete = []

    @staticmethod
    def filters(constraints: dict) -> list:
        return [(f"filters[{d}][]", v) for d in DIMS if d in constraints for v in constraints[d]]

    def fetch(self, constraints: dict, page: int = 1) -> int:
        f = self.filters(constraints)
        key = json.dumps([f, page])
        if key in self.done:
            return self.done[key]
        page_html = self.c.page(f, page)
        n = len(parse_cards(page_html, self.event))
        name = hashlib.sha1(key.encode()).hexdigest()[:16]
        (self.dir / f"{name}.html").write_text(page_html, encoding="utf-8")
        with self.manifest.open("a") as fh:
            fh.write(json.dumps({"key": key, "file": name, "cards": n}) + "\n")
        self.done[key] = n
        if self.c.sent % 25 == 0:
            print(f"[slice] {self.c.sent} requests sent, {len(self.done)} slices saved", file=sys.stderr)
        return n

    def resolve(self, constraints: dict, depth: int, values: list) -> None:
        """Fetch the slice; if full, bisect the value list, or go one dimension deeper."""
        dim = DIMS[depth]
        c = {**constraints, dim: values}
        if self.fetch(c) < PAGE_SIZE:
            return
        if len(values) > 1:
            mid = len(values) // 2
            self.resolve(constraints, depth, values[:mid])
            self.resolve(constraints, depth, values[mid:])
        elif depth + 1 < len(DIMS):
            nxt = DIMS[depth + 1]
            self.resolve(c, depth + 1, [v for v, _ in self.opts[nxt]])
            if nxt == "sizes":  # people without a company size are invisible to every size slice
                self.paginate(c)
        else:
            self.paginate(c)

    def paginate(self, constraints: dict) -> None:
        """A slice that cannot be split: walk its pages once (random order, so possibly incomplete)."""
        self.incomplete.append(constraints)
        page = 2
        while page <= MAX_PAGES and self.fetch(constraints, page) > 0:
            page += 1


def load_opts(c: Client, raw_dir: Path) -> dict:
    saved = raw_dir / "discovery.json"
    if saved.exists():
        return json.loads(saved.read_text(encoding="utf-8"))
    opts = parse_filter_options(c.discovery())
    raw_dir.mkdir(parents=True, exist_ok=True)
    saved.write_text(json.dumps(opts), encoding="utf-8")
    return opts


def cmd_slice(args):
    if not args.budget:
        raise SystemExit("[budget] run `probe` first, show the user the request count, then pass --budget N")
    c = Client(read_session(args.curl), args.event, budget=args.budget)
    opts = load_opts(c, args.raw_dir)
    types = [v for v, _ in opts["attendee_type"]]
    if args.types:
        want = [t.strip().lower() for t in args.types.split(",") if t.strip()]
        known = {v.lower(): v for v in types}
        unknown = [t for t in want if t not in known]
        if unknown:
            raise SystemExit(f"[slice] unknown attendee type {unknown}. Known: {', '.join(types)}")
        types = [known[t] for t in want]
    s = Slicer(c, opts, args.raw_dir, args.event)
    for t in types:  # one attendee type at a time: a partial run still yields whole types
        s.resolve({}, 0, [t])
    print(f"[slice] done: {c.sent} requests this run, {len(s.done)} slices saved", file=sys.stderr)
    if s.incomplete:
        print(f"[slice] {len(s.incomplete)} slices could not be split below 50 people; their pages were "
              "walked once and may miss a few people.", file=sys.stderr)
    print("Export finished. Delete the cURL file now: it holds your login session.")


# ---------------------------------------------------------------- build --
def cmd_build(args):
    files = sorted((args.raw_dir / "slices").glob("*.html"))
    if not files:
        raise SystemExit(f"No saved slices in {args.raw_dir / 'slices'}. Run `slice` first.")
    people = {}
    for f in files:
        for p in parse_cards(f.read_text(encoding="utf-8"), args.event):
            prev = people.setdefault(p["user_id"], {})
            for k, v in p.items():  # a card recurs across slices: keep the first non-empty value
                if v and not prev.get(k):
                    prev[k] = v
    rows = list(people.values())
    out = args.out / "attendees.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PEOPLE_COLS, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)
    rate = lambda k: f"{100 * sum(bool(r.get(k)) for r in rows) / max(len(rows), 1):.0f}%"
    print(f"{len(rows)} attendees -> {out}")
    print(f"Filled: title {rate('title')} · company {rate('company_name')} · industry {rate('industry')} · "
          f"country {rate('country')} · type {rate('badge')}. Web Summit hides LinkedIn profiles: "
          "enrichment finds them for your targets.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["probe", "slice", "build"])
    ap.add_argument("--curl", type=Path, default=Path("websummit_curl.txt"), help="file holding the copied cURL")
    ap.add_argument("--event", default="lis26", help="event id, as in attend.websummit.com/<event>/...")
    ap.add_argument("--out", type=Path, default=Path("websummit-list"), help="output folder")
    ap.add_argument("--raw-dir", type=Path, default=None, help="saved slices (default: <out>/raw)")
    ap.add_argument("--budget", type=int, default=0, help="slice: maximum number of requests to send")
    ap.add_argument("--types", default="", help="slice: only these attendee types, comma-separated")
    args = ap.parse_args()
    args.raw_dir = args.raw_dir or args.out / "raw"
    {"probe": cmd_probe, "slice": cmd_slice, "build": cmd_build}[args.command](args)


if __name__ == "__main__":
    main()
