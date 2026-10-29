#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JAP Pool Pattern Engine - self-updating weeks->patterns->forecast pipeline.

One command rebuilds everything:
    python3 pools/pattern_engine.py            # harvest + analyse + forecast
    python3 pools/pattern_engine.py --no-fetch # recompute from local history
    python3 pools/pattern_engine.py --ocr      # also OCR paper front pages for keys

Auto-update / auto-upgrade contract:
  * Each run appends any new week's results and the newest fixture list to
    pools/history/<season>/ and rebuilds patterns.json + forecast.json for the
    latest coupon week. Runs may be scheduled (cron / GitHub Action) or done
    casually - every run is idempotent and catches up whatever is missing.
  * Season rollover is automatic: the season label is read from the source
    posts ("SEASON: UK 2026/2027"). When a new label appears (or week numbers
    restart at 1 after a gap), the finished season is archived under
    pools/history/uk-<years>/ and a fresh history folder is started; the
    patterns carry the old season's long-run stats forward as 'archive' context.

Sources (text/HTML): FortuneSoccer results + fixtures posts, PoolsAgents week
pages (draw% + pre-match tips). Keys via optional OCR of paper front pages.
"""
import json, os, re, sys, ssl, datetime
from collections import defaultdict
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
CTX = ssl.create_default_context()

PAPER_SLUGS = ["fortune-soccer", "happy-joe", "unity-direct", "weekly-telegraph", "soccer-6",
               "temple-of-draws", "great-soccer", "soccer-x", "winstar", "soccer-advance",
               "the-new-dream", "rangers-36", "sporting-telegraph", "weekly-fixtures",
               "power-of-soccer", "super-soccer", "grand-national", "lucky-strike",
               "willy-tips", "pools-telegraph"]


def fetch(url, tries=3):
    for k in range(tries):
        try:
            r = urlopen(Request(url, headers={"User-Agent": UA}), timeout=30, context=CTX)
            return r.read().decode("utf-8", "replace")
        except Exception:
            if k + 1 < tries:
                import time
                time.sleep(1.2 * (k + 1))
    return ""


# ---------------------------------------------------------------- harvest
def norm_season(x):
    x = (x or "").replace("UK", "").strip().replace("/", "-")
    parts = [p for p in x.split("-") if p]
    if len(parts) == 2 and len(parts[1]) == 2:
        parts[1] = "20" + parts[1]
    return "-".join(parts)


def harvest(st=None):
    """history_build does the per-week fetch/parse; import its helpers."""
    import importlib
    hb = importlib.import_module("history_build")
    os.makedirs(os.path.join(HERE, "history", "uk"), exist_ok=True)
    want = norm_season((st or {}).get("season"))
    idx = []
    misses = 0
    y0 = int((want or "2026")[:4]) if want else datetime.date.today().year

    def fs_results_url(n):
        for y in (y0, y0 + 1, y0 - 1):
            u = "https://www.fortunesoccer.com/results/week-%d-pool-result-%d/" % (n, y)
            h = fetch(u)
            if h and ("pool-result" in h.lower() or "pools results" in h.lower()) and "<tr" in h:
                return h
        return ""

    for n in range(1, 60):
        html = fs_results_url(n)
        rec = hb.parse_fs_results(html, n) if html else {"week": n, "date": None, "matches": []}
        # season guard by DATE (post SEASON labels are unreliable: "AUSSIE 2026",
        # "UK 2025/2026" appear on current-season posts). Old-season posts share
        # the week-N-YYYY URL space, so the date window is the truth.
        start = "%d-06-01" % int(want[:4]) if want and want[:4].isdigit() else "0000-00-00"
        if rec["matches"] and rec.get("date") and rec["date"] < start:
            continue
        fhtml = fetch("https://www.fortunesoccer.com/fixtures/week-%d-pool-fixtures/" % n)
        fx = hb.parse_fs_fixtures(fhtml) if fhtml else {"matches": []}
        phtml = fetch("https://www.poolsagents.com/week-%d-2026/" % n)
        pa = hb.parse_pa_week(phtml) if phtml else {}
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
            rec = {"week": n, "date": fx.get("date"), "matches": fx["matches"], "source": "fixtures+poolsagents"}
        else:
            rec["source"] = "fortunesoccer-results" if rec["matches"] else None
        if not rec["matches"] and pa:
            for no, p in sorted(pa.items()):
                rec["matches"].append({"no": no, "home": p["home"], "away": p["away"], "ht": None,
                                       "gh": p.get("gh"), "ga": p.get("ga"),
                                       "draw": (p.get("gh") is not None and p.get("gh") == p.get("ga")),
                                       "drawpct": p.get("drawpct"), "tip": p.get("tip", ""), "status": ""})
            rec["source"] = "poolsagents"
        if rec["matches"]:
            if not rec.get("date"):
                rec["date"] = fx.get("date")
            rec["week"] = n
            rec["season"] = (st or {}).get("season")
            json.dump(rec, open(os.path.join(HERE, "history", "uk", "week-%d.json" % n), "w"), indent=1)
        nd = sum(1 for m in rec["matches"] if m.get("draw"))
        idx.append({"week": n, "date": rec.get("date"), "source": rec.get("source"),
                    "n": len(rec["matches"]), "draws": nd})
        if not rec["matches"] and not fx["matches"] and not pa:
            misses += 1
            if misses >= 3 and n > 3:
                break  # season over / not yet published
        else:
            misses = 0
    json.dump(idx, open(os.path.join(HERE, "history", "uk", "index.json"), "w"), indent=1)
    return idx


def season_label():
    # newest results post wins: its SEASON line is the source of truth
    html = fetch("https://www.fortunesoccer.com/results/")
    cands = re.findall(r"results/week-(\d+)-pool-result-(\d{4})/", html)
    cands.sort(key=lambda c: (int(c[1]), int(c[0])), reverse=True)
    for wk, yr in cands[:4]:
        post = fetch("https://www.fortunesoccer.com/results/week-%s-pool-result-%s/" % (wk, yr))
        m = re.search(r"SEASON:\s*UK\s*(\d{4})/(\d{4})", re.sub(r"<[^>]+>", " ", post))
        if m:
            return "%s-%s" % (m.group(1), m.group(2))
    y = datetime.date.today().year
    return "%d-%d" % (y, y + 1)


def maybe_roll_season(cur):
    """archive history/uk -> history/uk-<old-season> when the label changes"""
    state_f = os.path.join(HERE, "history", "engine_state.json")
    st = {}
    if os.path.exists(state_f):
        st = json.load(open(state_f))
    if st.get("season") and st["season"] != cur:
        old = os.path.join(HERE, "history", "uk")
        arch = os.path.join(HERE, "history", "uk-%s" % st["season"])
        if os.path.isdir(old) and not os.path.exists(arch):
            os.rename(old, arch)
        os.makedirs(old, exist_ok=True)
        st.setdefault("archive", []).append(st["season"])
    st["season"] = cur
    st["updated"] = datetime.date.today().isoformat()
    json.dump(st, open(state_f, "w"), indent=1)
    return st


# ---------------------------------------------------------------- keys (optional OCR)
def harvest_keys(weeks):
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        print("OCR not available - skipping keys harvest")
        return {}
    import tempfile
    ocr = RapidOCR()
    keys = {}
    kf = os.path.join(HERE, "history", "uk", "keys.json")
    if os.path.exists(kf):
        keys = json.load(open(kf))
    for w in weeks:
        if str(w) in keys:
            continue
        keys[str(w)] = {}
        for slug in PAPER_SLUGS[:6]:
            got = None
            for month in (7, 8, 9, 10, 11, 6):
                url = "https://www.fortunesoccer.com/wp-content/uploads/2026/%d/week-%d-%s-2026-page-1.jpg" % (month, w, slug)
                try:
                    data = urlopen(Request(url, headers={"User-Agent": UA}), timeout=25, context=CTX).read()
                    if len(data) > 20000:
                        got = data
                        break
                except Exception:
                    continue
            if not got:
                continue
            tmp = os.path.join(tempfile.gettempdir(), "k_%d_%s.jpg" % (w, slug))
            open(tmp, "wb").write(got)
            res, _ = ocr(tmp)
            txt = " ".join(x[1] for x in (res or []))
            nums = []
            for line in re.findall(r"(?:KEY|Key|BANKER|Banker|NAP|DRAW|1X2|SEQUENCE)[^\n]{0,90}", txt):
                nums += [int(x) for x in re.findall(r"\b(\d{1,2})\b", line) if 1 <= int(x) <= 49]
            if nums:
                keys[str(w)][slug] = sorted(set(nums))[:12]
        print("keys week %d: %s" % (w, {k: v for k, v in keys[str(w)].items()}))
    json.dump(keys, open(kf, "w"), indent=1)
    return keys


# ---------------------------------------------------------------- analysis
def analyse(keys):
    hist_dir = os.path.join(HERE, "history", "uk")
    weeks = []
    for fn in sorted(os.listdir(hist_dir)):
        m = re.match(r"week-(\d+)\.json$", fn)
        if not m:
            continue
        rec = json.load(open(os.path.join(hist_dir, fn)))
        weeks.append(rec)
    weeks = [w for w in weeks if w.get("matches") and (w.get("date") or "9999") >= "2026-07-01"]
    weeks.sort(key=lambda w: w.get("week") or 0)

    played = [w for w in weeks if any(m.get("gh") is not None or m.get("status") for m in w["matches"])
              and sum(1 for m in w["matches"] if m.get("draw")) > 0]
    upcoming = [w for w in weeks if w not in played]

    # ---- number-level stats
    num_draws = defaultdict(list)      # number -> [weeks]
    num_seen = defaultdict(int)
    team_draws = defaultdict(int)
    week_draw_sets = {}
    for w in played:
        wn = w["week"]
        s = set()
        for m in w["matches"]:
            num_seen[m["no"]] += 1
            if m.get("draw"):
                num_draws[m["no"]].append(wn)
                s.add(m["no"])
                team_draws[m["home"].lower()] += 1
                team_draws[m["away"].lower()] += 1
        week_draw_sets[wn] = s

    # ---- home/away win stats (the 1X2 side of the pattern universe)
    home_win = defaultdict(list)       # slot -> [weeks] ending home win
    away_win = defaultdict(list)
    team_hw = defaultdict(int)         # team -> home wins counted
    team_aw = defaultdict(int)
    week_home_sets, week_away_sets = {}, {}
    for w in played:
        wn = w["week"]
        hs, aset = set(), set()
        for m in w["matches"]:
            if m.get("gh") is None or m.get("ga") is None:
                continue
            if m["gh"] > m["ga"]:
                home_win[m["no"]].append(wn); hs.add(m["no"]); team_hw[m["home"].lower()] += 1
            elif m["gh"] < m["ga"]:
                away_win[m["no"]].append(wn); aset.add(m["no"]); team_aw[m["away"].lower()] += 1
        week_home_sets[wn] = hs
        week_away_sets[wn] = aset

    def side_repeats(week_sets, min_times=2):
        pr = defaultdict(list)
        for wn, ss in week_sets.items():
            ss = sorted(ss)
            for i in range(len(ss)):
                for j in range(i + 1, len(ss)):
                    pr[(ss[i], ss[j])].append(wn)
        out = [{"pair": list(k), "weeks": v} for k, v in pr.items() if len(v) >= min_times]
        out.sort(key=lambda x: (-len(x["weeks"]), x["pair"]))
        return out

    home_pairs = side_repeats(week_home_sets)
    away_pairs = side_repeats(week_away_sets)

    # ---- repeats
    consec_repeats = []                # same number drew in consecutive weeks
    for n, ws in num_draws.items():
        ws = sorted(ws)
        for a, b in zip(ws, ws[1:]):
            if b == a + 1:
                consec_repeats.append({"no": n, "weeks": [a, b]})
    co_pairs = defaultdict(list)       # pair co-drew same week
    for wn, s in week_draw_sets.items():
        s = sorted(s)
        for i in range(len(s)):
            for j in range(i + 1, len(s)):
                co_pairs[(s[i], s[j])].append(wn)
    co_pairs_rep = [{"pair": list(k), "weeks": v} for k, v in co_pairs.items() if len(v) >= 2]
    co_pairs_rep.sort(key=lambda x: (-len(x["weeks"]), x["pair"]))
    runs = []                          # >=3 consecutive numbers all drew in one week
    for wn, s in week_draw_sets.items():
        ss = sorted(s)
        i = 0
        while i < len(ss):
            j = i
            while j + 1 < len(ss) and ss[j + 1] == ss[j] + 1:
                j += 1
            if j - i >= 2:
                runs.append({"weeks": [wn], "seq": ss[i:j + 1]})
            i = j + 1
    bands = {}
    for lo in (1, 11, 21, 31, 41):
        bands["%d-%d" % (lo, lo + 9)] = sum(len([x for x in week_draw_sets.get(w["week"], []) if lo <= x < lo + 10])
                                            for w in played)

    # ---- keys recurrence
    key_freq = defaultdict(list)
    for wk, papers in (keys or {}).items():
        seen = set()
        for paper, nums in papers.items():
            for n in nums:
                if n not in seen:
                    key_freq[n].append(int(wk))
                    seen.add(n)
    key_repeat = sorted(({"no": n, "weeks": ws, "times": len(ws)} for n, ws in key_freq.items()),
                        key=lambda x: (-x["times"], x["no"]))

    # ---- formula classes (structural, from week-17 papers + empirical sets)
    formulas = []
    for pr in co_pairs_rep[:6]:
        formulas.append({
            "name": "hot-pair %d-%d" % tuple(pr["pair"]),
            "kind": "pair",
            "set": pr["pair"],
            "weeks": pr["weeks"],
            "times": len(pr["weeks"]),
            "hit_note": "both numbers drew together in weeks %s" % ",".join(str(x) for x in pr["weeks"]),
        })
    trio_pool = defaultdict(list)
    for wn, s in week_draw_sets.items():
        for n in s:
            trio_pool[n].append(wn)
    hot = sorted(num_draws.keys(), key=lambda n: -len(num_draws[n]))[:8]
    formulas.append({"name": "must-produce-one-draw line", "kind": "trio",
                     "set": sorted(hot[:3]), "weeks": sorted(set(sum((num_draws[n] for n in hot[:3]), []))),
                     "times": sum(len(num_draws[n]) for n in hot[:3]),
                     "hit_note": "the three most-drawn numbers of the season: any of them drew in most weeks"})
    for r in runs[:4]:
        formulas.append({"name": "sequence run %s" % "-".join(str(x) for x in r["seq"]), "kind": "sequence",
                         "set": r["seq"], "weeks": r["weeks"], "times": 1,
                         "hit_note": "full consecutive run landed in week %d" % r["weeks"][0]})
    for hp in home_pairs[:3]:
        formulas.append({"name": "home-win pair %d-%d" % tuple(hp["pair"]), "kind": "home-pair",
                         "set": hp["pair"], "weeks": hp["weeks"], "times": len(hp["weeks"]),
                         "hit_note": "both slots landed home wins together in weeks %s" % ",".join(str(x) for x in hp["weeks"])})
    for ap in away_pairs[:3]:
        formulas.append({"name": "away-win pair %d-%d" % tuple(ap["pair"]), "kind": "away-pair",
                         "set": ap["pair"], "weeks": ap["weeks"], "times": len(ap["weeks"]),
                         "hit_note": "both slots landed away wins together in weeks %s" % ",".join(str(x) for x in ap["weeks"])})
    hhot = sorted(home_win.keys(), key=lambda n: -len(home_win[n]))[:3]
    if hhot:
        formulas.append({"name": "home-win key line", "kind": "home-trio", "set": sorted(hhot),
                         "weeks": sorted(set(sum((home_win[n] for n in hhot), []))),
                         "times": sum(len(home_win[n]) for n in hhot),
                         "hit_note": "the three most frequent home-win slots of the season"})
    ahot = sorted(away_win.keys(), key=lambda n: -len(away_win[n]))[:3]
    if ahot:
        formulas.append({"name": "away-win key line", "kind": "away-trio", "set": sorted(ahot),
                         "weeks": sorted(set(sum((away_win[n] for n in ahot), []))),
                         "times": sum(len(away_win[n]) for n in ahot),
                         "hit_note": "the three most frequent away-win slots of the season"})

    # ---- regimes
    def regime(d):
        return "high" if d >= 15 else ("mid" if d >= 11 else "low")
    week_regime = [{"week": w["week"], "date": w.get("date"), "draws": sum(1 for m in w["matches"] if m.get("draw")),
                    "regime": regime(sum(1 for m in w["matches"] if m.get("draw")))} for w in played]
    regime_seq = [x["regime"] for x in week_regime]
    avg_draws = round(sum(x["draws"] for x in week_regime) / max(1, len(week_regime)), 1)

    # ---- next-week forecast
    nxt = upcoming[0] if upcoming else None
    forecast = None
    if nxt:
        wn = nxt.get("week")
        # recent form: mean draws of last 5 played weeks
        recent = [x["draws"] for x in week_regime[-5:]]
        exp = round(sum(recent) / max(1, len(recent)), 1)
        grp = regime(exp)
        # number score on THIS coupon
        def team_rate(name):
            n = re.sub(r"[^a-z ]", "", name.lower()).strip()
            tot = 0
            for t, c in team_draws.items():
                if n and (n in t or t in n):
                    tot += c
            return tot
        recs = []
        top_pairs = [{"pair": x["pair"], "weeks": x["weeks"]} for x in co_pairs_rep[:12]]
        for m in nxt["matches"]:
            n = m["no"]
            nfreq = len(num_draws.get(n, []))
            trate = team_rate(m.get("home", "")) + team_rate(m.get("away", ""))
            my_pairs = [p for p in top_pairs if n in p["pair"]][:2]
            pair_bonus = len(my_pairs)
            key_bonus = len(key_freq.get(n, []))
            score = nfreq * 3 + trate * 2 + pair_bonus * 6 + key_bonus * 2
            reasons = []
            if nfreq:
                reasons.append("slot %d drew %d time%s already this season (weeks %s)" %
                               (n, nfreq, "s" if nfreq != 1 else "", ",".join(str(x) for x in num_draws[n])))
            if trate:
                reasons.append("the teams involved have %d draw%s between them this season" %
                               (trate, "s" if trate != 1 else ""))
            if my_pairs:
                reasons.append("member of repeating pair(s) %s - drawn together in weeks %s" % (
                    ", ".join("%d-%d" % tuple(p["pair"]) for p in my_pairs),
                    "; ".join(",".join(str(x) for x in p["weeks"]) for p in my_pairs)))
            if key_bonus:
                reasons.append("paper keys returned to number %d in %d week%s" %
                               (n, key_bonus, "s" if key_bonus != 1 else ""))
            recs.append({"no": n, "home": m.get("home"), "away": m.get("away"), "score": score,
                         "nfreq": nfreq, "reasons": reasons})
        recs.sort(key=lambda r: -r["score"])

        def side_picks(side):
            pool = home_win if side == "home" else away_win
            pairs = home_pairs if side == "home" else away_pairs
            tpool = team_hw if side == "home" else team_aw
            out = []
            for m in nxt["matches"]:
                n = m["no"]
                nfreq = len(pool.get(n, []))
                tn = (m.get("home" if side == "home" else "away") or "").lower()
                tform = tpool.get(tn, 0)
                for t, c in tpool.items():
                    if tn and tn != t and (tn in t or t in tn) and c > tform:
                        tform = c
                myP = [p for p in pairs if n in p["pair"]][:2]
                score = nfreq * 3 + tform * 2 + len(myP) * 6
                reasons = []
                if nfreq:
                    reasons.append("slot %d produced %d %s win%s already this season (weeks %s)" %
                                   (n, nfreq, side, "s" if nfreq != 1 else "", ",".join(str(x) for x in pool[n])))
                if tform:
                    reasons.append("%s %s have %d win%s as the %s side this season" %
                                   (m.get("home" if side == "home" else "away"), "home" if side == "home" else "away",
                                    tform, "s" if tform != 1 else "", side))
                if myP:
                    reasons.append("member of repeating %s-win pair(s) %s - landed together in weeks %s" % (
                        side, ", ".join("%d-%d" % tuple(p["pair"]) for p in myP),
                        "; ".join(",".join(str(x) for x in p["weeks"]) for p in myP)))
                if score > 0:
                    out.append({"no": n, "home": m.get("home"), "away": m.get("away"),
                                "score": score, "nfreq": nfreq, "reasons": reasons})
            out.sort(key=lambda r: -r["score"])
            return out[:12]

        home_picks = side_picks("home")
        away_picks = side_picks("away")
        forecast = {
            "week": wn, "date": nxt.get("date"),
            "expected_draws": exp, "group": grp,
            "group_note": "weeks 1-%d average %s draws; the last five weeks averaged %s - week %d sits in the %s-draw group" %
                          (played[-1]["week"] if played else 0, avg_draws, exp, wn, grp),
            "picks": [r for r in recs if r["score"] > 0][:15],
            "home_picks": home_picks,
            "away_picks": away_picks,
            "all": recs,
        }

    patterns = {
        "season_weeks_played": len(played),
        "weeks": week_regime,
        "avg_draws_per_week": avg_draws,
        "number_draws": {str(n): ws for n, ws in sorted(num_draws.items())},
        "top_numbers": [{"no": n, "times": len(num_draws[n]), "weeks": num_draws[n]}
                        for n in sorted(num_draws, key=lambda x: -len(num_draws[x]))[:12]],
        "consecutive_week_repeats": consec_repeats,
        "co_draw_pairs": co_pairs_rep[:12],
        "sequence_runs": runs,
        "draw_bands": bands,
        "key_repeats": key_repeat[:15],
        "formulas": formulas,
        "teams_most_draws": sorted(({"team": t, "draws": c} for t, c in team_draws.items() if c >= 3),
                                   key=lambda x: -x["draws"])[:12],
        "home_win_slots": {str(n): ws for n, ws in sorted(home_win.items())},
        "away_win_slots": {str(n): ws for n, ws in sorted(away_win.items())},
        "top_home_slots": [{"no": n, "times": len(home_win[n]), "weeks": home_win[n]}
                           for n in sorted(home_win, key=lambda x: -len(home_win[x]))[:10]],
        "top_away_slots": [{"no": n, "times": len(away_win[n]), "weeks": away_win[n]}
                           for n in sorted(away_win, key=lambda x: -len(away_win[x]))[:10]],
        "home_win_pairs": home_pairs[:8],
        "away_win_pairs": away_pairs[:8],
        "teams_most_home_wins": sorted(({"team": t, "wins": c} for t, c in team_hw.items() if c >= 3),
                                       key=lambda x: -x["wins"])[:10],
        "teams_most_away_wins": sorted(({"team": t, "wins": c} for t, c in team_aw.items() if c >= 3),
                                       key=lambda x: -x["wins"])[:10],
    }
    return patterns, forecast, played, upcoming


def main():
    args = set(sys.argv[1:])
    st = maybe_roll_season(season_label())
    idx = None
    if "--no-fetch" not in args:
        print("== harvest history (season %s) ==" % st.get("season"))
        idx = harvest(st)
    keys = {}
    if "--ocr" in args:
        weeks = sorted(int(re.match(r"week-(\d+)", f).group(1))
                       for f in os.listdir(os.path.join(HERE, "history", "uk"))
                       if re.match(r"week-\d+\.json", f))
        print("== OCR keys ==")
        keys = harvest_keys([w for w in weeks if w <= 17])
    else:
        kf = os.path.join(HERE, "history", "uk", "keys.json")
        if os.path.exists(kf):
            keys = json.load(open(kf))
    print("== analyse ==")
    patterns, forecast, played, upcoming = analyse(keys)
    patterns["season"] = st.get("season")
    patterns["updated"] = st.get("updated")
    json.dump(patterns, open(os.path.join(HERE, "patterns.json"), "w"), indent=1)
    json.dump(forecast or {}, open(os.path.join(HERE, "forecast.json"), "w"), indent=1)
    print("played weeks: %d | avg draws %s | consecutive-week repeats: %d | co-draw pairs x2+: %d | runs: %d" %
          (patterns["season_weeks_played"], patterns["avg_draws_per_week"],
           len(patterns["consecutive_week_repeats"]), len(patterns["co_draw_pairs"]), len(patterns["sequence_runs"])))
    if forecast:
        print("forecast week %d (%s): expected ~%s draws (%s group)" %
              (forecast["week"], forecast["date"], forecast["expected_draws"], forecast["group"]))
        for p in forecast["picks"][:10]:
            print("  %2d. No.%d %s v %s  score=%d  %s" %
                  (forecast["picks"].index(p) + 1, p["no"], p["home"], p["away"], p["score"],
                   "; ".join(p["reasons"])[:150]))


if __name__ == "__main__":
    main()
