#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The weekly UK/Aussie pools pipeline, end to end:

    1. refresh_coupon.py  - pull the week's fixtures into coupon.json
    2. fetch_papers.py    - harvest the paper scans for that week
    3. extract_keys.py    - read the banker/NAP/draw keys off the scans (OCR)
    4. pattern_engine.py  - recompute sequences, patterns, formulas, forecast

Idempotent - safe to run daily. Scheduled by .github/workflows/pools-update.yml
so the pools section keeps itself current until the season rolls.
"""
import json, os, subprocess, sys

POOL = os.path.dirname(os.path.abspath(__file__))


def sh(args):
    print('+', ' '.join(os.path.basename(a) for a in args), flush=True)
    subprocess.run(args, cwd=POOL, check=False)


def main():
    sh([sys.executable, os.path.join(POOL, 'refresh_coupon.py')])
    week = None
    try:
        cpn = json.load(open(os.path.join(POOL, 'coupon.json'), encoding='utf-8'))
        week = cpn.get('week') or cpn.get('uk', {}).get('week')
    except Exception as e:
        print('coupon read failed:', e)
    print('coupon week:', week)
    if week:
        sh([sys.executable, os.path.join(POOL, 'fetch_papers.py'), '--week', str(week)])
        sh([sys.executable, os.path.join(POOL, 'extract_keys.py')])
    sh([sys.executable, os.path.join(POOL, 'pattern_engine.py')])
    print('weekly pools update complete')


if __name__ == '__main__':
    main()
