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
        return urllib.request.urlopen(req, timeout=25).status == 200
    except Exception:
        try:
            req = urllib.request.Request(url, headers=UA)
            r = urllib.request.urlopen(req, timeout=30)
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
        if not pages:
            print('%-24s no template (never had scans)' % p['id'])
            continue
        tmpl = re.sub(r'week-\d+-', 'week-%d-' % week, pages[0])
        tmpl = re.sub(r'/uploads/\d{4}/\d{2}/', '/uploads/{Y}/{M:02d}/', tmpl)
        tmpl = re.sub(r'page-\d+(\.\w+)$', r'page-{n}\1', tmpl)
        if '{n}' not in tmpl:
            print('%-24s odd template %s' % (p['id'], tmpl))
            continue
        found = []
        for (yy, mm) in months_around(today.year, today.month):
            base = tmpl.replace('{Y}', str(yy)).replace('{M:02d}', '%02d' % mm)
            for n, u in page_variants(base):
                if head_ok(u):
                    if u not in found:
                        found.append(u)
                elif n > 1 and found:
                    break
            if found:
                break
        if found:
            p['pages'] = found
            p['npages'] = len(found)
            p['keys'] = {}
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
