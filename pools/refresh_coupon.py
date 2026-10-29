#!/usr/bin/env python3
"""Auto-refresh pools/coupon.json from the real sources.

Runs on GitHub Actions daily (and on demand). Server-side, so CORS never
applies. Graceful: any source that fails keeps its previous values - the
coupon is never wiped by a bad fetch.

Sources:
  - Coupon fixtures + week number: poolsupdate.com/advance_fixtures.php
  - Market draw % (margin removed) + best prices: poolsagents.com (+ /week-N-2026/)
  - Expert banker keys: fortunesoccer.com/tips/week-N-football-tips/
  - Results (grading, after the weekend): ablefast.com/result/<date>
"""
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COUPON = ROOT / "pools" / "coupon.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125 Safari/537.36"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def load_current():
    if COUPON.exists():
        try:
            return json.loads(COUPON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"uk": None, "aussie": None, "experts": []}


def next_saturday(d):
    return d + timedelta(days=(5 - d.weekday()) % 7)


def parse_month_day(txt, year):
    m = re.search(r"(\d{1,2})\s+(\w{3})", txt.lower())
    if not m or m.group(2)[:3] not in MONTHS:
        return None
    try:
        return date(year, MONTHS[m.group(2)[:3]], int(m.group(1)))
    except ValueError:
        return None


def parse_poolsupdate(html):
    """Current week's 49 fixtures + week number + coupon date."""
    m = re.search(r"Currently showing:\s*Week (\d+) Pools fixtures \d+ \(From: ([^)]+)\)", html)
    if not m:
        return None
    week = int(m.group(1))
    frm = parse_month_day(m.group(2), date.today().year)
    if not frm:
        return None
    sat = next_saturday(frm)
    rows = {}
    for row in re.findall(r"\|\s*(\d{1,2})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", html):
        try:
            no = int(row[0])
        except ValueError:
            continue
        if 1 <= no <= 49:
            rows[no] = [row[1].strip(), row[2].strip()]
    if len(rows) < 40:
        return None
    matches = [{"no": n, "home": rows[n][0], "away": rows[n][1]} for n in sorted(rows)]
    return {"week": week, "date": sat.isoformat(), "matches": matches}


def parse_fs_fixtures(html):
    """FortuneSoccer advance-fixtures post -> numbered coupon rows."""
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    wm = re.search(r"WEEK:\s*(\d+)\s*;\s*SEASON:([^;]+);\s*DATE:\s*([0-9A-Za-z-]+)", txt)
    week = int(wm.group(1)) if wm else None
    date_s = None
    if wm:
        dm = re.match(r"(\d+)-(\d+)-(\d+)", wm.group(3).strip())
        if dm:
            date_s = "%04d-%02d-%02d" % (int(dm.group(3)), int(dm.group(2)), int(dm.group(1)))
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    matches = []
    for tr in rows:
        c = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip()
             for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
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
    return {"week": week, "date": date_s, "matches": matches}


def parse_poolsagents_week(html):
    """The week page's semantic coupon table: <tr id="noN"> with draw/price/book cells."""
    i = html.find('id="coupon"')
    if i < 0:
        return {}
    tbl = html[i:html.find("</table>", i)] if html.find("</table>", i) > 0 else html[i:i + 60000]
    out = {}
    for tr in re.findall(r'<tr id="no(\d{1,2})"[^>]*>(.*?)</tr>', tbl, re.S):
        no, body = int(tr[0]), tr[1]
        tds = re.findall(r'<td[^>]*>(.*?)</td>', body, re.S)
        if len(tds) < 5:
            continue
        draw = tds[2].strip().rstrip('%')
        price = tds[3].strip()
        book = re.sub(r'<[^>]+>', '', tds[4]).strip()
        if draw.isdigit() and 5 <= int(draw) <= 60:
            out[no] = {"drawPct": int(draw),
                       "drawPrice": float(price) if re.match(r'^\d+\.\d+$', price) else None,
                       "book": book or None}
    return out if len(out) >= 20 else {}


def parse_fortunesoccer(html):
    """Expert picks: '**N – Home vs Away**' ... 'Prediction: X-Y Team'."""
    picks = []
    blocks = re.split(r"\*\*(\d{1,2})\s*[–-]\s*", html)
    for i in range(1, len(blocks) - 1, 2):
        no = int(blocks[i])
        body = blocks[i + 1]
        if not (1 <= no <= 49):
            continue
        pm = re.search(r"Prediction:\s*([^<\n]{2,60})", body)
        if not pm:
            continue
        pred = pm.group(1).strip()
        score = re.match(r"(\d-\d)", pred)
        # first sentence of substance as the note
        txt = re.sub(r"<[^>]+>", " ", body)
        txt = re.sub(r"\s+", " ", txt)
        sm = re.search(r"(?:\*\*)?\s*([A-Z][^.!?]{40,180}[.!?])", txt)
        note = sm.group(1).strip() if sm else ""
        picks.append({"no": no, "pred": score.group(1) if score else pred[:12],
                      "note": note[:160]})
    return picks


def parse_ablefast_results(html, coupon_date):
    """Results per number from ablefast's semantic cells: data-home-score / data-away-score."""
    out = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        mn = re.search(r'coupon-number">(\d{1,2})<', tr)
        hs = re.search(r'data-home-score>(\d+)<', tr)
        aw = re.search(r'data-away-score>(\d+)<', tr)
        if mn and hs and aw:
            no = int(mn.group(1))
            if 1 <= no <= 49:
                out[no] = "%s-%s" % (hs.group(1), aw.group(1))
    return out if len(out) >= 20 else {}


PAPERS = ROOT / "pools" / "papers.json"
FS_PG = "https://www.fortunesoccer.com/wp-content/uploads/2026/{y}/week-{w}-{slug}-2026-page-{n}.jpg"
UF_PG = "https://www.ukfootballpools.com/wp-content/uploads/2026/{y}/week-{w}-{slug}-2026-page-{n}.jpg"
UF_SPECIAL = "https://www.ukfootballpools.com/wp-content/uploads/2026/{y}/week-{w}-right-on-fixtures-2026-{which}.jpg"


def probe(url):
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status == 200
    except Exception:
        return False


def harvest_fs_scans(week):
    """Find the week's scans from the FortuneSoccer posts that embed them
    (rsk / late-news / pool-paper / weekly-papers). Embedded images are
    thumbnails (-WxH suffix) - strip the suffix for the full-size sheet."""
    found = {}
    for post in ("https://www.fortunesoccer.com/rsk/week-%d-rsk-papers-2026/" % week,
                 "https://www.fortunesoccer.com/late-news/week-%d-pool-paper/" % week,
                 "https://www.fortunesoccer.com/pool-paper/this-week-%d/" % week,
                 "https://www.fortunesoccer.com/weekly-papers/week-%d-pools-papers/" % week):
        h = fetch(post)
        if not h:
            continue
        for u in re.findall(r'https://www\.fortunesoccer\.com/wp-content/uploads/[^"\']+?\.jpg', h):
            full = re.sub(r"-\d+x\d+\.jpg$", ".jpg", u)
            m = re.search(r"week-" + str(week) + r"-(.+?)-2026-(?:page-(\d+)|(front-page|back-page))\.jpg$", full)
            if not m:
                continue
            slug, pg, special = m.group(1), m.group(2), m.group(3)
            key = slug
            found.setdefault(key, [])
            if full not in found[key]:
                found[key].append(full)
    for k in found:
        found[k].sort()
    return found


def refresh_papers(week, coupon_date):
    """Roll papers.json to the current coupon week. Pages are only replaced
    when scans for the NEW week are actually found - old-week sheets can
    never masquerade as the new week."""
    if not PAPERS.exists():
        return
    try:
        pj = json.loads(PAPERS.read_text(encoding="utf-8"))
    except Exception:
        return
    if pj.get("week") == week and pj.get("date") == coupon_date:
        stale = any(p.get("pages") and ("week-%d" % week) not in " ".join(p["pages"])
                    for p in pj.get("papers", []))
        if not stale:
            print("papers: already on week %d - keys untouched" % week)
            return
        print("papers: week %d label held stale page URLs - re-harvesting" % week)
    harvest = harvest_fs_scans(week)
    months = []
    cm = int(coupon_date[5:7]) if len(coupon_date) >= 7 else 10
    for dm in (0, 1, -1, 2):
        mm = cm + dm
        if 1 <= mm <= 12 and mm not in months:
            months.append(mm)
    n_changed = 0
    seen = set()
    for p in pj.get("papers", []):
        seen.add(p["id"])
        pages = harvest.get(p["id"], [])
        if not pages and p["id"] == "right-on-fixtures":
            for y in months:
                pages = [u for u in (UF_SPECIAL.format(y=y, w=week, which=w)
                                     for w in ("front-page", "back-page")) if probe(u)]
                if pages:
                    break
        elif not pages:
            tpl = UF_PG if any("ukfootballpools.com" in u for u in p.get("pages", [])) else FS_PG
            for y in months:
                pages = []
                for n in range(1, 25):
                    u = tpl.format(y=y, w=week, slug=p["id"], n=n)
                    if not probe(u):
                        break
                    pages.append(u)
                if pages:
                    break
        if pages:
            p["pages"] = pages
            n_changed += 1
        else:
            p["pages"] = []          # never keep the old week's sheets
        p["keys"] = {}               # keys were read from the OLD week's scans
        p["note"] = ("Week %d scans are up - open them on the Forecast papers tab. Keys not yet "
                     "re-read from the new sheets; ask 'refresh the papers' to have them extracted."
                     % week) if pages else ("Week %d scans not found yet for this paper - the tab "
                                           "auto-scans and will surface them when they publish." % week)
    # titles discovered on the new week's posts but missing from the pack
    for slug, pages in sorted(harvest.items()):
        if slug in seen or not pages:
            continue
        name = " ".join(w.capitalize() for w in slug.split("-"))
        pj["papers"].append({"id": slug, "name": name, "family": "Weekly papers",
                             "npages": len(pages), "pages": pages, "keys": {},
                             "note": "Week %d scans are up - open them on the Forecast papers tab." % week})
        n_changed += 1
    pj["week"] = week
    pj["date"] = coupon_date
    pj["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    tmp = PAPERS.with_suffix(".tmp")
    tmp.write_text(json.dumps(pj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(PAPERS)
    print("papers: rolled to week %d (%d papers with fresh scans, %d discovered on the week's posts)" %
          (week, n_changed, len(harvest)))


def main():
    cur = load_current()
    coupon = {"uk": cur.get("uk"), "aussie": cur.get("aussie"),
              "aussieNote": cur.get("aussieNote"), "experts": cur.get("experts", [])}

    # 1. fixtures + week
    try:
        pu = parse_poolsupdate(fetch("https://poolsupdate.com/advance_fixtures.php"))
    except Exception as e:
        print("poolsupdate failed:", e); pu = None
    if pu:
        prev = coupon["uk"] or {}
        same_week = prev.get("week") == pu["week"] and prev.get("matches")
        coupon["uk"] = {"week": pu["week"], "season": prev.get("season", "2026/2027"),
                        "date": pu["date"], "matches": pu["matches"],
                        "expectedDraws": prev.get("expectedDraws"),
                        "strongest": prev.get("strongest"),
                        "credit": "Coupon: the published pools coupon (PoolsUpdate). "
                                  "Market draw % (margin removed) + best prices: PoolsAgents.com. "
                                  "Expert picks: FortuneSoccer."}
        # carry results forward within the same week
        if same_week:
            prev_res = {m["no"]: m.get("result") for m in prev["matches"]}
            for m in coupon["uk"]["matches"]:
                m["result"] = prev_res.get(m["no"])
        else:
            for m in coupon["uk"]["matches"]:
                m["result"] = None
    # 1b. roll-on-stale fallback: PoolsUpdate can lag a day or two after the
    # next coupon's fixtures publish. When the stored week's Saturday has
    # passed, rebuild from FortuneSoccer's official advance fixtures post
    # (numbered exactly like the printed coupon). The past week stays fully
    # browsable under the app's Pools calendar (pools/history/uk/).
    target = next_saturday(date.today())
    uk_now = coupon.get("uk") or {}
    if uk_now.get("date") and date.fromisoformat(uk_now["date"]) < target:
        stale_week = int(uk_now.get("week") or 0)
        fs = None
        for n in range(stale_week + 1, stale_week + 5):
            h = fetch("https://www.fortunesoccer.com/fixtures/week-%d-pool-fixtures/" % n)
            fx = parse_fs_fixtures(h) if h else None
            if fx and fx.get("matches") and fx.get("date") and date.fromisoformat(fx["date"]) == target:
                fs = fx
                fs["week"] = n
                break
        if fs:
            coupon["uk"] = {"week": fs["week"], "season": uk_now.get("season", "2026/2027"),
                            "date": fs["date"],
                            "matches": [{"no": m["no"], "home": m["home"], "away": m["away"],
                                         "league": m.get("league", ""),
                                         "drawPct": None, "drawPrice": None, "book": None,
                                         "result": None} for m in fs["matches"]],
                            "expectedDraws": None, "strongest": None,
                            "credit": "Coupon: auto-generated from the official FortuneSoccer advance "
                                      "fixtures post (PoolsUpdate has not published this week yet). "
                                      "Market draw % + best prices: PoolsAgents.com fill in as they land."}
            print("coupon: rolled to week %d from the FortuneSoccer fixtures post (PoolsUpdate still showing week %d)" % (fs["week"], stale_week))
        else:
            print("coupon: week %d is stale but no fixtures post found yet for %s" % (stale_week, target))
    uk = coupon["uk"]
    if not uk:
        print("no coupon basis - keeping previous file")
        write(coupon)
        return

    # 2. market draw % + prices
    week_no = uk["week"]
    try:
        pa = parse_poolsagents_week(fetch("https://www.poolsagents.com/week-%d-2026/" % week_no))
    except Exception as e:
        print("poolsagents failed:", e); pa = {}
    for m in uk["matches"]:
        info = pa.get(m["no"])
        if info:
            m["drawPct"] = info["drawPct"]; m["drawPrice"] = info["drawPrice"]; m["book"] = info["book"]
        elif not m.get("drawPct"):
            m["drawPct"] = None; m["drawPrice"] = None; m["book"] = None
    priced = [m for m in uk["matches"] if m.get("drawPct")]
    if priced:
        uk["expectedDraws"] = round(sum(m["drawPct"] for m in priced) / 100.0, 1)
        uk["strongest"] = [m["no"] for m in sorted(priced, key=lambda x: -x["drawPct"])[:6]]

    # 3. expert picks (fresh each run for the current week)
    picks = []
    try:
        picks = parse_fortunesoccer(fetch("https://www.fortunesoccer.com/tips/week-%d-football-tips/" % week_no))
    except Exception as e:
        print("fortunesoccer failed:", e)
    if picks:
        coupon["experts"] = [{"source": "FortuneSoccer",
                              "url": "https://www.fortunesoccer.com/tips/week-%d-football-tips/" % week_no,
                              "picks": picks}]
    else:
        # stale picks from a previous week must not survive a week roll
        old_url = ""
        if coupon.get("experts"):
            old_url = (coupon["experts"][0] or {}).get("url", "")
        if ("week-%d" % week_no) not in old_url:
            coupon["experts"] = []

    # 4. results (grading) once the coupon date has passed
    d = date.fromisoformat(uk["date"])
    if date.today() >= d:
        try:
            res = parse_ablefast_results(fetch("https://ablefast.com/result/" + uk["date"]), uk["date"])
            if res:
                for m in uk["matches"]:
                    if m["no"] in res:
                        m["result"] = res[m["no"]]
        except Exception as e:
            print("ablefast failed:", e)

    # 5. aussie season detection
    try:
        ab = fetch("https://ablefast.com/")
        if "AUSSIE" in ab[:6000]:
            coupon["aussieNote"] = ("The Aussie pools coupon is active this week - the Australian "
                                    "season runs roughly November to June.")
        else:
            coupon["aussie"] = None
            coupon["aussieNote"] = ("The Aussie pools coupon runs its own season (roughly Nov-Jun). "
                                    "No Aussie coupon this week - the active coupon is the UK 49.")
    except Exception as e:
        print("ablefast season check failed:", e)

    coupon["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    refresh_papers(uk["week"], uk["date"])
    write(coupon)
    graded = sum(1 for m in uk["matches"] if m.get("result"))
    print("week %d | %d matches | %d priced | %d expert picks | %d graded" %
          (uk["week"], len(uk["matches"]), len(priced), len(coupon["experts"][0]["picks"]) if coupon["experts"] else 0, graded))


def write(coupon):
    COUPON.parent.mkdir(parents=True, exist_ok=True)
    old = COUPON.read_text(encoding="utf-8") if COUPON.exists() else ""
    new = json.dumps(coupon, ensure_ascii=False, indent=1)
    if new == old:
        print("no change")
        return
    tmp = COUPON.with_suffix(".tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(COUPON)
    print("coupon.json updated")


if __name__ == "__main__":
    sys.exit(main())
