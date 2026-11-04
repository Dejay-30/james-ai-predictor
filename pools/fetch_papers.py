#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Harvest the week's paper scans into pools/papers.json.

Learns each paper's URL pattern from the previous week's scans and rolls the
week number forward (probing adjacent month folders). Idempotent: skips papers
that already carry the target week. Run weekly via pools/weekly_update.py.

    python3 pools/fetch_papers.py --week 19
"""
import json, os, re, sys, urllib.request
from datetime import date

POOL_DIR = os.path.dirname(os.path.abspath(__file__))
PAPERS_JSON = os.path.join(POOL_DIR, 'papers.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36'}


def head_ok(url):
    try:
        req = urllib.request.Request(url, headers=UA, method='HEAD')
        return urllib.request.urlopen(req, timeout=8).status == 200
    except Exception:
        try:
            req = urllib.request.Request(url, headers=UA)
            r = urllib.request.urlopen(req, timeout=12)
            ok = r.status == 200
            r.read(64)
            return ok
        except Exception:
            return False


def months_around(y, m):
    out = []
    for dm in (0, -1, 1):
        mm, yy = m + dm, y
        while mm < 1:
            mm += 12; yy -= 1
        while mm > 12:
            mm -= 12; yy += 1
        if (yy, mm) not in out:
            out.append((yy, mm))
    return out


def page_variants(base):
    """base holds {Y} {M} and a page-{n} marker; yield concrete URLs per n"""
    for n in range(1, 13):
        for fmt in (str(n), '%02d' % n):
            yield n, base.replace('{n}', fmt)


def probe_month(base):
    """probe one month folder: page 1 must exist or the month is dead;
    then roll pages forward until the first miss (max 12)."""
    found = []
    n1 = [base.replace('{n}', f) for f in ('1', '01')]
    if not any(head_ok(u) for u in n1):
        return found
    for u in n1:
        if head_ok(u):
            found.append(u)
            break
    for n in range(2, 13):
        hit = None
        for fmt in (str(n), '%02d' % n):
            u = base.replace('{n}', fmt)
            if head_ok(u):
                hit = u
                break
        if not hit:
            break
        found.append(hit)
    return found


def main():
    args = sys.argv[1:]
    week = int(args[args.index('--week') + 1]) if '--week' in args else None
    force = '--force' in args
    pj = json.load(open(PAPERS_JSON, encoding='utf-8'))
    if week is None:
        week = int(pj.get('week') or 0) + 1
    today = date.today()
    changed = 0
    for p in pj.get('papers', []):
        pages = p.get('pages') or []
        if pages and ('week-%d-' % week) in pages[0] and not force:
            print('%-24s already week %d' % (p['id'], week))
            continue
        found = []
        if pages:
            tmpl = re.sub(r'week-\d+-', 'week-%d-' % week, pages[0])
            tmpl = re.sub(r'/uploads/\d{4}/\d{2}/', '/uploads/{Y}/{M:02d}/', tmpl)
            tmpl = re.sub(r'page-\d+(\.\w+)$', r'page-{n}\1', tmpl)
            if '{n}' not in tmpl:
                print('%-24s odd template %s' % (p['id'], tmpl))
                tmpl = None
            if tmpl:
                for (yy, mm) in months_around(today.year, today.month):
                    base = tmpl.replace('{Y}', str(yy)).replace('{M:02d}', '%02d' % mm)
                    found = probe_month(base)
                    if found:
                        break
        if not found:
            # catalog probe: the known week-N scan pattern on both hosts - this
            # is what keeps papers.json alive even when the pack has no template
            for host in ('fortunesoccer', 'ukfootballpools'):
                for (yy, mm) in months_around(today.year, today.month):
                    base = ('https://www.%s.com/wp-content/uploads/%d/%02d/week-%d-%s-2026-page-{n}.jpg'
                            % (host, yy, mm, week, p['id']))
                    found = probe_month(base)
                    if found:
                        break
                if found:
                    break
        if found:
            p['pages'] = found
            p['npages'] = len(found)
            p['keys'] = {}
            p.pop('keysWeek', None)
            p['note'] = 'Week %d scans harvested %s. Run extract_keys.py to read the keys.' % (week, date.today().isoformat())
            changed += 1
            print('%-24s %d pages' % (p['id'], len(found)))
        else:
            print('%-24s no week %d scans found (kept previous)' % (p['id'], week))
    pj['week'] = week
    json.dump(pj, open(PAPERS_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('papers.json: %d papers harvested for week %d' % (changed, week))


if __name__ == '__main__':
    main()
