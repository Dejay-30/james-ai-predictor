#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read the key votes out of the paper scan pages into pools/papers.json.

Strategy: OCR every page, map each annotated row (NAP / XCB / XXB / CBK /
DRAW ...) back to its coupon slot through the fixture team names (coupon.json),
and collect the boxed pair panels (JOKER PAIR / TRIPLE PAIR BANKERS).

    python3 pools/extract_keys.py                 # all papers -> papers.json
    python3 pools/extract_keys.py --paper bob-morton   # dry run for one paper
"""
import io, json, os, re, subprocess, sys, tempfile, urllib.request
from concurrent.futures import ThreadPoolExecutor

POOL_DIR = os.path.dirname(os.path.abspath(__file__))
PAPERS_JSON = os.path.join(POOL_DIR, 'papers.json')
COUPON_JSON = os.path.join(POOL_DIR, 'coupon.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36'}

ANN = re.compile(r'\b(NAP|JAP|IAP|XCBK|XXCBK|XXBK|XXB|XCB|CBK|DRAW|BANKERS?|TIPS?|CHOICE|PAIRS?|DANKERS|BANKARS|NAp)\b', re.I)
KIND = {
    'nap': {'nap', 'jap', 'iap'}, 'banker': {'xcbk', 'xxcbk', 'xxbk', 'xxb', 'xcb', 'cbk', 'banker', 'bankers', 'dankers', 'bankars'},
    'draw': {'draw'}, 'tips': {'tip', 'tips'}, 'choice': {'choice'},
}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read()


def ocr(img, psm=6):
    with tempfile.NamedTemporaryFile(suffix='.img', delete=False) as f:
        f.write(img); tmp = f.name
    try:
        return subprocess.run(['tesseract', tmp, 'stdout', '--psm', str(psm)],
                              capture_output=True, timeout=180).stdout.decode('utf-8', 'replace')
    finally:
        os.unlink(tmp)


def norm(s):
    return re.sub(r'[^A-Z]', '', s.upper())


def load_fixtures():
    cpn = json.load(open(COUPON_JSON, encoding='utf-8'))
    fx = []
    for m in cpn.get('uk', {}).get('matches', []):
        fx.append((str(m['no']), m['home'], m['away'], norm(m['home']), norm(m['away'])))
    return fx


def team_in(seg, fx):
    n = norm(seg)
    best = None
    for no, h, a, nh, na in fx:
        for nm in (nh, na):
            if len(nm) >= 4 and nm in n:
                score = len(nm)
                if best is None or score > best[0]:
                    best = (score, no)
    return best[1] if best else None


def parse(text, fx):
    keys = {'banker': [], 'nap': [], 'draw': [], 'tips': [], 'pairs': []}

    def add(kind, no):
        if no and no not in keys[kind]:
            keys[kind].append(no)

    for ln in text.splitlines():
        ms = list(ANN.finditer(ln))
        for idx, m in enumerate(ms):
            tok = m.group(1).lower()
            kind = None
            for k, toks in KIND.items():
                if tok in toks:
                    kind = k; break
            if not kind:
                continue
            seg_start = ms[idx - 1].end() if idx else 0
            seg = ln[seg_start:m.start()]
            if kind in ('banker', 'nap', 'draw'):
                add(kind, team_in(seg, fx))
            elif kind == 'tips':
                add('tips', team_in(seg, fx))
        # boxed number panels: label line then a numbers-only line
        for kind, rx in (('nap', re.compile(r'\bN\.?A\.?P\.?\b', re.I)),
                         ('banker', re.compile(r'\b[BD]A[NK]+ERS?\b', re.I))):
            m = rx.search(ln)
            if m:
                chunk = ln[m.end():]
                ns = re.findall(r'(?<![\d.])([1-9]|[1-4]\d)(?![\d.])', chunk)
                if 1 <= len(ns) <= 8:
                    for n in ns[:8]:
                        add(kind, n)
        # pair panels: 6-32 / 28 x 23
        for a, b in re.findall(r'\b([1-9]|[1-4]\d)\s*[-xX/]\s*([1-9]|[1-4]\d)\b', ln):
            a, b = int(a), int(b)
            if a == b or min(a, b) < 2:
                continue
            p = '%dx%d' % (a, b)
            if p not in keys['pairs']:
                keys['pairs'].append(p)
    caps = {'banker': 8, 'nap': 5, 'draw': 12, 'tips': 5, 'pairs': 6}
    for k, cap in caps.items():
        keys[k] = keys[k][:cap]
    return {k: v for k, v in keys.items() if v}


POOL_EXEC = ThreadPoolExecutor(max_workers=3)


def main():
    pj = json.load(open(PAPERS_JSON, encoding='utf-8'))
    fx = load_fixtures()
    only = sys.argv[sys.argv.index('--paper') + 1] if '--paper' in sys.argv else None
    changed = 0
    for p in pj.get('papers', []):
        if only and p['id'] != only:
            continue
        pages = p.get('pages') or []
        if not pages:
            print('%-24s no scans' % p['id']); continue
        def one(u):
            try:
                return ocr(get(re.sub(r'-\d+x\d+(\.\w+)$', r'\1', u)))
            except Exception as e:
                print('%-24s fetch/ocr fail %s' % (p['id'], str(e)[:60]))
                return ''
        text = '\n'.join(list(POOL_EXEC.map(one, pages[:3])))
        k = parse(text, fx)
        if only:
            print('---', p['id'], '->', json.dumps(k)); return
        if k:
            p['keys'] = k
            p['note'] = 'Keys read from the week %s scans.' % pj.get('week')
            changed += 1
            print('%-24s %s' % (p['id'], json.dumps(k)[:150]))
        else:
            print('%-24s no keys recognised on the sheets' % p['id'])
    if not only:
        json.dump(pj, open(PAPERS_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('papers.json updated: %d papers with keys / %d' % (changed, len(pj.get('papers', []))))


if __name__ == '__main__':
    main()
