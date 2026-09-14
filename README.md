# James AI Predictor ⚽

Multi-sport betting analytics in **one self-contained HTML file** — no server,
no database, no build step. Open `index.html` anywhere and it runs.

**Live site:** `https://<username>.github.io/james-ai-predictor/`

## What it does

- **Fixtures + live scores** that load themselves on open — API-Sports →
  SofaScore → ESPN, whichever answers first (keyless fallbacks mean it never
  comes up empty).
- **Real book odds on every match** — ESPN/DraftKings keyless 1X2 (opening +
  current price), upgraded to SofaScore multi-book averages where reachable,
  football.com as the last gap-filler. ▲▼ movement arrows update as prices move.
- **One-tap match analysis** — a Poisson model calibrated to the *current*
  match odds: xG, every market (1X2, double chance, O/U 1.5–3.5, BTTS,
  1st-half), value flags, most-likely scores, odds movement history with
  sparkline + favourite verdict, and a bookmaker comparison table.
- **Daily predictions** that build themselves — ranked picks with VALUE
  badges against the live odds.
- **🔥 Trending** — today + tomorrow's most-followed matches, live pinned
  on top, with a keyless ESPN fallback list.
- **League tables** — keyless live standings for 10 competitions (EPL,
  Championship, La Liga, Serie A, Bundesliga, Ligue 1, Primeira, Eredivisie,
  Brasileirão, Champions League).
- **Betslip + acca analysis**, plus the betPawa virtual-league predictor.

## Data sources

| Source | Use | Key |
|---|---|---|
| ESPN (site.api / site.web.api) | fixtures, odds, tables, trending fallback | none |
| SofaScore | odds (multi-book), fixtures fallback, trending | none |
| football.com | odds backup | none (hosted proxy only) |
| API-Sports | H2H history, injuries, team stats, other sports | free 100/day — optional |

## Updating

Replace `index.html` with a newer build and push. The app version is stamped
in the ☰ menu (e.g. *v6 · 10 Sep 2026*).

## Custom domain

Buy a domain, then add a `CNAME` file containing your domain (e.g.
`www.jamesaipredictor.com`) and set the DNS records shown in
Settings → Pages → Custom domain.

---

*Model estimates only — not betting advice. 18+. Please gamble responsibly.*
