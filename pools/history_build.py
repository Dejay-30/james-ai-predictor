#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""history_build.py - UK pool history weeks 1..N for the pattern/formula study.

Sources (text/HTML, no OCR needed):
  - FortuneSoccer results posts: /results/week-N-pool-result-2026/
      -> 49 rows: no, home, away, HT, FT, status + week date line
  - FortuneSoccer fixtures posts: /fixtures/week-N-pool-fixtures/
      -> numbered coupon for not-yet-played weeks
  - PoolsAgents week pages: /week-N-2026/ (fallback + draw% + pre-match tip)

Writes pools/history/uk/week-N.json per week and history/uk/index.json.
"""
import json, os, re, ssl, sys
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "history", "uk")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
CTX = ssl.create_default_context()


def fetch(url):
    try:
        r = urlopen(Request(url, headers={"User-Agent": UA}), timeout=30, context=CTX)
        return r.read().decode("utf-8", "replace")
    except Exception:
        return ""


def cells_of(tr):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]


def parse_fs_results(html, url_week=None):
    """-> {week, date, matches: [{no, home, away, ht, gh, ga, draw}]}"""
    txt = re.sub(r"<[^>]+>", " ", html)
    m = re.search(r"WEEK:\s*(\d+)\s*;\s*SEASON:([^;]+);\s*DATE:\s*([0-9A-Za-z-]+)", txt)
    season = (m.group(2).strip() if m else "")
    # the post title/URL wins: some posts mislabel the inner table header
    tm = re.search(r"week-(\d+)-pool-result", html) or re.search(r"Week\s+(\d+)\s+Pool Result\s+for\s+Sat\s+(\d+)\s*,?\s*([A-Za-z]+)\s*,?\s*(\d{4})", txt)
    week = url_week or (int(tm.group(1)) if tm else None) or (int(m.group(1)) if m else None)
    date_raw = (m.group(3) if m else "").strip()          # e.g. 24-October-2026
    months = {mn: i + 1 for i, mn in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"])}
    dm = re.match(r"(\d+)-([A-Za-z]+)-(\d+)", date_raw)
    date = None
    if dm:
        mo = 0
        for k, v in months.items():
            if k.lower().startswith(dm.group(2).lower()[:3]):
                mo = v
        date = "%s-%02d-%02d" % (dm.group(3), mo, int(dm.group(1)))
    # title date (Sat 17, Oct 2026) overrides a mislabeled inner header
    tm2 = re.search(r"Week\s+\d+\s+Pool Result\s+for\s+Sat\s+(\d+)\s*,?\s*([A-Za-z]+)\s*,?\s*(\d{4})", txt)
    if tm2:
        mo = 0
        for k, v in months.items():
            if k.lower().startswith(tm2.group(2).lower()[:3]):
                mo = v
        date = "%s-%02d-%02d" % (tm2.group(3), mo, int(tm2.group(1)))
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    matches = []
    for tr in rows:
        c = cells_of(tr)
        if len(c) == 6 and re.fullmatch(r"\d+", c[0]):
            sc = re.fullmatch(r"(\d+)-:-?(\d+)", c[4])
            if sc:
                ft = [int(sc.group(1)), int(sc.group(2))]
                draw = ft[0] == ft[1]
            else:
                # Void/PP rows: the Status column carries the pools-panel verdict
                ft = [None, None]
                draw = "draw" in (c[5] or "").lower()
            matches.append({"no": int(c[0]), "home": c[1], "away": c[2],
                            "ht": c[3], "gh": ft[0], "ga": ft[1],
                            "draw": draw, "status": c[5]})
    return {"week": week, "date": date, "season": season, "matches": matches}


def parse_fs_fixtures(html):
    """numbered coupon for an upcoming week -> {week, date, matches}"""
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    wm = re.search(r"WEEK:\s*(\d+)\s*;\s*SEASON:([^;]+);\s*DATE:\s*([0-9A-Za-z-]+)", txt)
    week = int(wm.group(1)) if wm else None
    date = None
    if wm:
        d = wm.group(3).strip()
        dm = re.match(r"(\d+)-(\d+)-(\d+)", d) or re.match(r"(\d+)/(\d+)/(\d+)", d)
        if dm:
            date = "%04d-%02d-%02d" % (int(dm.group(3)), int(dm.group(2)), int(dm.group(1)))
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    matches = []
    for tr in rows:
        c = cells_of(tr)
        if len(c) >= 2 and re.fullmatch(r"\d+", c[0] or ""):
            toks = [x for x in c[1:] if x]
            home = away = day = ""
            m = re.match(r"(.+?)\s+v\s+(.+)", toks[0]) if toks else None
            if m:
                home, away = m.group(1).strip(), m.group(2).strip()
                day = toks[-1] if len(toks) > 1 else ""
            elif len(toks) >= 2:
                home, away = toks[0], toks[1]
                day = toks[-1] if len(toks) > 2 else ""
            if home and away:
                matches.append({"no": int(c[0]), "home": home, "away": away, "day": day})
    return {"week": week, "date": date, "matches": matches}


def parse_pa_week(html):
    """poolsagents week page rows: [no, fixture, score, drawpct-or-FT, tip]"""
    rows = re.findall(r"<tr[^>]*id=\"no(\d+)\"[^>]*>(.*?)</tr>", html, re.S)
    out = {}
    for no, r in rows:
        c = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip()
             for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if len(c) < 3:
            continue
        fm = re.match(r"(.+?)\s+v\s+(.+)", c[1])
        sc = re.match(r"(\d+)\s*[–-]\s*(\d+)", c[2] or "")
        pct = re.match(r"(\d+)%", c[3] or "") if len(c) > 3 else None
        out[int(no)] = {
            "home": fm.group(1).strip() if fm else c[1],
            "away": fm.group(2).strip() if fm else "",
            "gh": int(sc.group(1)) if sc else None, "ga": int(sc.group(2)) if sc else None,
            "drawpct": int(pct.group(1)) if pct else None,
            "tip": (c[4] if len(c) > 4 else "") or "",
        }
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    idx = []
    for n in range(1, 20):
        html = fetch("https://www.fortunesoccer.com/results/week-%d-pool-result-2026/" % n)
        rec = parse_fs_results(html, n) if html else {"week": None, "date": None, "matches": []}
        if rec["matches"]:
            rec["week"] = n
            src = "fortunesoccer-results"
        else:
            rec = {"week": n, "date": None, "matches": []}
            src = None
        # fixtures post (upcoming weeks / cross-check names)
        fhtml = fetch("https://www.fortunesoccer.com/fixtures/week-%d-pool-fixtures/" % n)
        fx = parse_fs_fixtures(fhtml) if fhtml else {"matches": []}
        # poolsagents fallback + draw% + pre-match tip
        phtml = fetch("https://www.poolsagents.com/week-%d-2026/" % n)
        pa = parse_pa_week(phtml) if phtml else {}
        for m in rec["matches"]:
            p = pa.get(m["no"]) or {}
            m["drawpct"] = p.get("drawpct")
            m["tip"] = p.get("tip", "")
        if not rec["matches"] and fx["matches"]:
            for m in fx["matches"]:
                p = pa.get(m["no"]) or {}
                m.update({"ht": None, "gh": p.get("gh"), "ga": p.get("ga"),
                          "draw": (p.get("gh") is not None and p.get("gh") == p.get("ga")),
                          "drawpct": p.get("drawpct"), "tip": p.get("tip", ""), "status": ""})
            rec = {"week": n, "date": fx.get("date"), "matches": fx["matches"]}
            src = "fortunesoccer-fixtures+poolsagents"
        elif not rec["matches"] and pa:
            for no, p in sorted(pa.items()):
                rec["matches"].append({"no": no, "home": p["home"], "away": p["away"], "ht": None,
                                       "gh": p.get("gh"), "ga": p.get("ga"),
                                       "draw": (p.get("gh") is not None and p.get("gh") == p.get("ga")),
                                       "drawpct": p.get("drawpct"), "tip": p.get("tip", ""), "status": ""})
            rec["week"] = n
            src = "poolsagents"
        rec["source"] = src
        if rec["matches"] or fx["matches"]:
            with open(os.path.join(OUT, "week-%d.json" % n), "w") as f:
                json.dump(rec, f, indent=1)
        nd = sum(1 for m in rec["matches"] if m.get("draw"))
        idx.append({"week": n, "date": rec.get("date"), "source": src,
                    "n": len(rec["matches"]), "draws": nd,
                    "fixtures_post": bool(fx["matches"]), "poolsagents": bool(pa)})
        print("week %2d: src=%s rows=%d draws=%s date=%s" % (n, src, len(rec["matches"]),
              nd if rec["matches"] else "-", rec.get("date")))
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump(idx, f, indent=1)


if __name__ == "__main__":
    main()
