#!/usr/bin/env python3
"""
Safeguard tests for the websummit-attendee-list skill. No network: Web Summit is replaced by a fake
server that serves synthetic attendees (no real people) in a new random order on every request.
Run from the repository root: python3 -I tests/test_skill.py
"""

import contextlib
import csv
import io
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import websummit_scrape as s  # noqa: E402

s.THROTTLE = 0.0
SECRET = "SESSION-VALUE-must-never-be-printed"
EVENT = "lis26"

TYPES = ["Alpha", "Beta", "Growth", "Partner", "Speaker", "Attendee"]
COUNTRIES = [f"Country {i}" for i in range(12)]
INDUSTRIES = ["SaaS", "Security", "Fintech", "Health"]
SIZES = ["2-4 employees", "51-200 employees", "1001-5000 employees"]


def people(n=420, seed=7):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        # Country 0 is crowded (more than 50 people of one type) to force splits on the next filters
        country = "Country 0" if i % 3 == 0 else rnd.choice(COUNTRIES)
        out.append({"id": f"{i:08d}-0000-4000-8000-000000000000", "name": f"Test Person{i}",
                    "type": rnd.choice(TYPES), "country": country, "industry": rnd.choice(INDUSTRIES),
                    "size": rnd.choice(SIZES + [""]), "title": "CEO", "company": f"Company {i % 150}"})
    return out


def card(p):
    return (f'<div class="card w-100 mb-2 "><a href="/{EVENT}/profiles/{p["id"]}">'
            f'<span class="mt-2 mt-sm-0">{p["name"]}</span></a>'
            f'<span class="badge-secondary x">{p["type"]}</span>'
            f'<p class="mb-1 fs-12 y">{p["title"]} at {p["company"]}</p>'
            f'<i class="bi-buildings"></i> <span>{p["industry"]}</span>'
            f'<i class="bi-geo-alt"></i> <span>{p["country"]}</span></div>')


def discovery_html():
    def sel(dim, labels):
        return (f'<select name="filters[{dim}][]">' +
                "".join(f'<option value="{l}">{l}</option>' for l in labels) + "</select>")
    return (sel("attendee_type", [t.lower() for t in TYPES]) + sel("countries", COUNTRIES) +
            sel("industries", INDUSTRIES) + sel("sizes", SIZES))


class Resp:
    def __init__(self, code, text="", ctype="text/vnd.turbo-stream.html; charset=utf-8"):
        self.status_code, self.text, self.headers = code, text, {"content-type": ctype}


class FakeSession:
    """Answers like the attendee portal: filters are OR within a dimension, AND across dimensions."""

    def __init__(self, code=200, data=None):
        self.code, self.data, self.calls, self.rnd = code, data or people(), [], random.Random(1)

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=True):
        self.calls.append(url)
        if self.code != 200:
            return Resp(self.code)
        if "attendances.turbo_stream" not in url:
            return Resp(200, discovery_html(), "text/html")
        f = {}
        for k, v in (params or []):
            if k.startswith("filters["):
                f.setdefault(k[8:-3], set()).add(str(v))
        page = int(dict(params or []).get("page", 1))
        sel = [p for p in self.data
               if (not f.get("attendee_type") or p["type"].lower() in f["attendee_type"])
               and (not f.get("countries") or p["country"] in f["countries"])
               and (not f.get("industries") or p["industry"] in f["industries"])
               and (not f.get("sizes") or p["size"] in f["sizes"])]
        self.rnd.shuffle(sel)  # a new random order on every request, like the real portal
        chunk = sel[(page - 1) * s.PAGE_SIZE: page * s.PAGE_SIZE]
        return Resp(200, "<turbo-stream>" + "".join(card(p) for p in chunk) + "</turbo-stream>")


def run(cmd, tmp, session, budget=0, types="", curl_text=None):
    curl = Path(tmp) / "curl.txt"
    curl.write_text(curl_text or "curl 'https://attend.websummit.com/lis26/discovery/attendances.turbo_stream"
                                 f"?page=2' -b '_attendee_portal_session={SECRET}; other=1'")
    args = type("A", (), {"curl": curl, "event": EVENT, "out": Path(tmp) / "out",
                          "raw_dir": Path(tmp) / "out" / "raw", "budget": budget, "types": types})()
    out, err, code = io.StringIO(), io.StringIO(), None
    orig = s.requests.Session
    s.requests.Session = lambda: session
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            {"probe": s.cmd_probe, "slice": s.cmd_slice, "build": s.cmd_build}[cmd](args)
    except SystemExit as e:
        code = str(e)
    finally:
        s.requests.Session = orig
    return out.getvalue() + err.getvalue() + (code or ""), code


def built(tmp):
    with open(Path(tmp) / "out" / "attendees.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    return bool(cond)


def enrich_checks():
    import enrich as e
    ok = True
    r = {"first_name": "Jane", "last_name": "Doe", "company_name": "Acme Robotics Oy", "domain": "acmerobotics.fi"}
    for url, ev, want in (
            ("https://fi.linkedin.com/in/janedoe", "Jane Doe - CEO - Acme Robotics | LinkedIn", "accepted"),
            ("https://www.linkedin.com/in/janedoe", "Jane Doe - CEO | LinkedIn", "review"),
            ("https://www.linkedin.com/in/johnsmith", "John Smith - CEO - Acme Robotics", "rejected"),
            ("https://www.linkedin.com/in/janedoe", "Jane Doe - Director - Barclays Robotics Bank", "review"),
            ("https://www.linkedin.com/in/janedoe2", "Jane Doe - Director - Barclays Bank", "review"),
            ("https://www.linkedin.com/company/acme", "Jane Doe - CEO - Acme Robotics", "rejected")):
        got = e.judge_person(r, url, ev)[0]
        ok &= check(f"judge_person: {ev[:40]!r} -> {want}", got == want, got)
    A = lambda live, approve: type("A", (), {"live": live, "approve": approve})()
    ok &= check("gate: dry run by default", not e.gate(A(False, None), 5))
    ok &= check("gate: --live without --approve refused", not e.gate(A(True, None), 5))
    ok &= check("gate: --approve with another count refused", not e.gate(A(True, 3), 5))
    ok &= check("gate: --live --approve N runs", e.gate(A(True, 5), 5))
    return ok


def queue_check():
    """The ICP filter keeps a person whose card shows several types (Partner + Women in tech)."""
    import enrich as e
    with tempfile.TemporaryDirectory() as t:
        att, icp = Path(t) / "a.csv", Path(t) / "icp.json"
        with att.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=s.PEOPLE_COLS, restval="")
            w.writeheader()
            w.writerow({"user_id": "1", "first_name": "A", "last_name": "B", "title": "CEO", "company_name": "X",
                        "company_type": "partner; women in tech", "industry": "SaaS", "country": "France"})
            w.writerow({"user_id": "2", "first_name": "C", "last_name": "D", "title": "CEO", "company_name": "Y",
                        "company_type": "attendee", "industry": "SaaS", "country": "France"})
            w.writerow({"user_id": "3", "first_name": "E", "last_name": "F", "title": "CEO", "company_name": "Z",
                        "company_type": "partner", "industry": "Health", "country": "France"})
        icp.write_text('{"company_types": ["partner"], "industries": ["SaaS"]}')
        args = type("A", (), {"attendees": str(att), "icp": str(icp), "n": 10})()
        w = e.Work(Path(t) / "enrichment")
        with contextlib.redirect_stdout(io.StringIO()):
            e.cmd_queue(args, w)
        kept = [r["user_id"] for r in w.queue()]
    return check("ICP queue: attendee type and industry filters (multi-type card kept)", kept == ["1"], kept)


def main():
    ok = True
    for code in (401, 403, 429, 302):
        with tempfile.TemporaryDirectory() as t:
            fs = FakeSession(code=code)
            text, stop = run("slice", t, fs, budget=50)
            ok &= check(f"HTTP {code}: stops after 1 request, no retry", stop and len(fs.calls) == 1,
                        f"{len(fs.calls)} calls")
    with tempfile.TemporaryDirectory() as t:
        fs = FakeSession(code=503)
        text, stop = run("slice", t, fs, budget=50)
        ok &= check("HTTP 503: one retry then stop", stop and len(fs.calls) == 2, f"{len(fs.calls)} calls")
    with tempfile.TemporaryDirectory() as t:
        fs = FakeSession()
        text, stop = run("slice", t, fs, budget=0)
        ok &= check("slice without --budget refuses to start", stop and not fs.calls)
    with tempfile.TemporaryDirectory() as t:
        fs = FakeSession()
        text, stop = run("slice", t, fs, budget=7)
        ok &= check("budget 7: never more than 7 requests", stop and "budget" in stop and len(fs.calls) == 7,
                    f"{len(fs.calls)} calls")
        fs2 = FakeSession()
        text, stop = run("slice", t, fs2, budget=5000)
        ok &= check("resume: discovery and saved slices not requested again",
                    not stop and fs2.calls and all("turbo_stream" in u for u in fs2.calls),
                    f"second run {len(fs2.calls)} calls, stop={stop}")
        run("build", t, FakeSession())
        got = {r["user_id"] for r in built(t)}
        want = {p["id"] for p in people()}
        ok &= check("complete export despite the random order (split by filters)", got == want,
                    f"{len(got)}/{len(want)} people")
        ok &= check("build fills name, title, company, type", all(r["first_name"] and r["title"] and
                    r["company_name"] and r["company_type"] for r in built(t)))
    with tempfile.TemporaryDirectory() as t:
        fs = FakeSession()
        text, stop = run("slice", t, fs, budget=5000, types="partner,speaker")
        run("build", t, FakeSession())
        types = {r["company_type"] for r in built(t)}
        n_want = sum(1 for p in people() if p["type"] in ("Partner", "Speaker"))
        ok &= check("--types: only those attendee types, all of them", types == {"partner", "speaker"}
                    and len(built(t)) == n_want, f"{types}, {len(built(t))}/{n_want}")
        text, stop = run("slice", t, FakeSession(), budget=50, types="nonsense")
        ok &= check("--types: unknown type refused with the list of known ones", stop and "Known" in stop)
    with tempfile.TemporaryDirectory() as t:
        fs = FakeSession()
        text, stop = run("probe", t, fs)
        ok &= check("probe sends exactly 2 requests", len(fs.calls) == 2, f"{len(fs.calls)} calls")
        ok &= check("probe lists the attendee types and the budget", "partner" in text and "--budget" in text)
        text2, _ = run("slice", t, FakeSession(), budget=40)
        ok &= check("session cookie never printed (probe, slice)", SECRET not in text + text2)
    with tempfile.TemporaryDirectory() as t:
        fs = FakeSession()
        text, stop = run("probe", t, fs, curl_text="curl https://example.com -b 'other=1'")
        ok &= check("cURL without the session cookie: clear error, no request", stop and not fs.calls)
    with tempfile.TemporaryDirectory() as t:
        fs = FakeSession()
        orig_get = fs.get
        fs.get = lambda url, **k: (Resp(200, "<html>security check</html>", "text/html")
                                   if "turbo_stream" in url else orig_get(url, **k))
        text, stop = run("slice", t, fs, budget=50)
        ok &= check("HTML page instead of the directory (security check): stops", stop and "unexpected" in stop,
                    stop)
    ok &= enrich_checks()
    ok &= queue_check()
    print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
