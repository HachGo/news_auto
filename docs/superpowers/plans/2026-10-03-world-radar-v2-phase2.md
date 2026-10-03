# World Radar v2 — Phase 2 implementation brief (all remaining parts)

Hand-off spec for the coding agent. Phase 1 (Trends explorer, Forecasts, Rules; `scripts/radar.py`) is
done and live on `main` (4d61bc8). This spec covers **everything else** in the v2 design.

The user approved all phases. Build them **in the order below**, with **one commit per phase**
(plus a test commit if you like). Run the full test suite and a Hugo build after every phase. Stop
and report if a phase can't be completed honestly.

- **Branch:** create `world-radar-v2-phase2` from `main`. **Do not push, and do not merge.** A push to
  `main` triggers the CI refresh and deploy.
- **Conventions:** same as Phase 1 — see section 1 of
  `docs/superpowers/plans/2026-10-03-world-radar-v2.md`. In short:
  - Chinese docstrings and comments
  - atomic writes that skip when content is unchanged, and no timestamps in generated JSON
  - every UI string in both i18n files
  - server-rendered Hugo, with only small JS
  - real data only
  - **the privacy rule**: `block_keywords` and `PRIVATE_RANK_RULES` never appear on the public
    site, and the political-content exclusion in ranking stays as it is
  - pages work at phone width (375px)
- **Design reference:** `docs/design/World Radar v2.dc.html`. All data in it is mock; copy the
  layout only. Relevant views: home (`isHome`, events with "Merged reports" and the ideas grid),
  `isIdeas` (~line 188), `isTrends` (~275, idea categories + "Why it is rising"), `isForecasts`
  (~354, Brier / market / calibration), `isLab` (~470). Strings are in `T`, `T2` and `LT`.
- **Dependencies:** none new, beyond what `scripts/requirements.txt` already has (requests,
  feedparser, PyYAML, openai, …). Write the TF-IDF yourself; do not add scikit-learn.
- **Every new fetcher must:**
  - support `--limit N` and `--dry-run` when run as a module
  - use a timeout and log `source + error` (never swallow errors)
  - not fail the run if it fails: the section is marked `failed` and the others continue
- **LLM:** reuse `common.build_llm_client()` and the existing `summarize` / JSON-call helpers in
  `common.py`. Every LLM step needs a no-key fallback, because tests and local runs have no key.

---

## Phase A — Event clustering ("Merged reports")

**Goal:** a home event can carry several reports of the same story, from different sources and in
both languages. The event shows "N reports · EN x · 中 y", and expanding it lists every report,
like the v2 home `e.sources` panel.

### A1. Keep the candidate pool

- `generators/ai.py`, `world.py` and `market.py` currently return only the selected items. Add
  `"candidates": candidates` to the returned dict. It stays in memory only and is never written to
  Markdown.
- Reused days (`load_published_post`) have no candidates. Handle that in A3.

### A2. New `scripts/cluster.py` (pure, deterministic)

- `tokens(text)`:
  - English words: lowercased; drop a small stop-word list and words shorter than 3 characters.
  - CJK: character bigrams.
- TF-IDF cosine with IDF computed over the day's pool. Two titles are the same story when
  similarity ≥ `SIMILARITY = 0.45`. This is a constant; tune it on real data (A5).
- **Cross-language:** every selected item is bilingual, because the model gives it `title_zh` /
  `title_en`. Compare a candidate against both titles of each selected item, using the candidate's
  own-language title. So:
  - an English candidate is matched against `title_en`
  - a Chinese candidate is matched against `title_zh`
- `cluster_events(selected_by_section, candidates_by_section)`:
  1. Assign each candidate to its best-matching selected item (above the threshold).
  2. Merge **selected** items that match each other across sections into one event. The higher
     score wins; the event gets the union of fields.
  3. Each event gets `reports: [{source, lang, title, link, published_at}]` (representative first,
     then newest first, deduped by link), `report_count`, `langs: {en, zh}` and
     `fields: [...]` (multi-label, like v2 chips).
- Do not add a 48-hour cross-day window in this phase. Clustering is same-day only.

### A3. `brief.py`

- `build_brief` takes the clusters. Events gain `fields`, `reports`, `report_count` and `langs`.
- Keep `field` as the primary field so existing filters keep working.
- `stats.fields` counts an event under each of its fields.
- For reused entries, keep the previous `reports` through the existing `_merge` / `old` mechanism,
  so a same-day rerun never loses clusters.
- `schema` → 2. `brief_latest.html` must still render schema-1 files.

### A4. Templates

- In `today_event.html`:
  - show a chip for each field
  - add `reports · EN x · 中 y` to the meta line
  - the expanded panel lists every report (source, lang, title, time), styled like the v2
    "Merged reports" panel
- Single-report events look the same as today.
- The home field filter matches if **any** of the event's fields matches; `today.js` needs updating
  for this.

### A5. Tests and verification

- **Tests:** zh↔en merge through the bilingual selected item; no false merge for unrelated titles
  that share one common word; cross-section merge; reused-day stability; schema-1 brief still renders.
- **Verification:** run clustering on a real candidate pool (`--dry-run` against live RSS is fine)
  and report merge counts and a few examples to the user. Pick the threshold from that.

---

## Phase B — Ideas pillar

**Goal:** the v2 Ideas page and the home "02 · Ideas" grid, built on real idea sources.

### B1. Sources

Use **keyless sources only**, one adapter file each under `scripts/sources/ideas/`, each exposing
`fetch(limit) -> list[item]`. Verify each endpoint live before relying on it, and drop any source
that doesn't work. Do not scrape HTML, and obey robots.txt and site terms.

| id | Source | Endpoint | Signal |
|---|---|---|---|
| `show_hn` | Show HN | HN Algolia API `https://hn.algolia.com/api/v1/search_by_date?tags=show_hn` (last 48h) | points, comments |
| `github` | GitHub | REST search `created:>{date-7d}` sorted by stars; use `GITHUB_TOKEN` if set (Actions provides one; add `env: GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}` to the fetch step) | stars |
| `v2ex` | V2EX 分享创造 | `https://www.v2ex.com/api/topics/show.json?node_name=create` | replies |
| `hackaday` | Hackaday | RSS `https://hackaday.com/blog/feed/` | comments (`slash_comments`) |
| `instructables` | Instructables | find a working official RSS feed; skip the source if none exists | — |
| `sspai` | 少数派 | RSS `https://sspai.com/feed` | — (no signal) |

**Item schema:** the brief's common schema, stored as JSON.

```json
{"id": "", "source": "show_hn", "url": "", "title": "", "summary": "", "lang": "en|zh",
 "published_at": "", "fetched_at": "", "signals": {"upvotes": 0, "comments": 0, "stars": 0}}
```

Store a link and a short summary only (≤ 300 characters), never full text.

### B2. Storage and scoring

New module `scripts/ideas.py`.

**Storage:** `data/ideas/<date>.json` holds the day's fetched items plus their enrichment. Keep 60
days. This history is what the 24h / 7d / 30d ranges and the decay are computed from.

**Dedupe:**
- Same URL → one item.
- Cross-site duplicates → TF-IDF from `cluster.py` on English titles. Use `title_en` from
  enrichment for Chinese items. Matched items become one idea with several `srcs`.

**Score:**
- For each source signal, take the percentile within that source over the stored 30 days.
- Sources without signals get 50.
- Weighted mean, weights: money/backers 1.0 > saves/stars 0.8 > upvotes 0.6 > comments 0.4. The
  current sources have no money signal; keep the weight for later.
- Then `final = round(weighted * 0.5 ** (age_hours / (24 * 7)) + 3 * (n_sites - 1))`. This is the
  v2 formula: half-life 7 days, +3 per extra site.
- Export the breakdown fields as v2 shows them: per-source percentile, weighted, decay factor,
  boost, final.

**Enrichment** (one batched DeepSeek call per day, JSON output):
- `type`: one of `hack|product|method|wish|design`. Leave out `backed`, since there is no
  Kickstarter source.
- `why`: one line, "why it's clever", in zh and en.
- `who`: who it's for, in zh and en.
- `effort`: 1–3.
- `title_zh` / `title_en`.

No-key fallback:
- `type` from a per-source default: show_hn/github/hackaday → hack, v2ex → product,
  instructables → method, sspai → method.
- `why` = truncated summary.
- `who` / `effort` omitted.
- The other language's title = the original title.

**Export:** `data/radar/ideas.json` contains:
- the ranked list for each range (24h / 7d / 30d)
- counts by type
- stats: today count, number of sources, multi-site count
- `sources` health: name, access kind, today's count, and status `ok`, `failed` or `empty` (real
  status from the run, not v2's mock "rate-limited")
- weights, so the "How the score works" panel shows real values

### B3. Pages

- **`content/ideas/_index{,.en}.md` + `layouts/ideas/list.html`**, following the v2 `isIdeas` view:
  - stats; type chips with counts; sort (Top / New / Multi-site) and range (24h / 7d / 30d)
    controls
  - cards showing rank, type, score, title (a link to the source), why, who / effort / age, a
    "On N sites" chip, and source chips with signals, plus an expandable score breakdown
  - aside: "How the score works" and "Sources today"
  - Server-render all ranges; JS switches range, sort and type. Without JS, the 7d / Top view is
    shown.
- **Home:** "02 · Ideas" (top 6 for 7d, with type tabs as in v2) replaces the Deep-reads grid.
  - Deep reads stay at `/deep`, linked from the Ideas block head ("Deep reads →") and still listed
    on News.
- **Nav, both languages:** Today · News · Ideas · Trends · Forecasts · Lab · Rules. Deep reads
  leaves the top nav (Lab is added in Phase E; add the item then).
- **Rules page** (`method.build_rules`):
  - Add the idea sources to `sources`, with pillar = Ideas and access API / RSS.
  - Add an "Idea scoring" group (weights, half-life, boost) under Analysis.
- **Footer sources line:** add the idea sources.
- `fetch_news.py` runs the ideas pipeline as its own guarded step. The workflow `git add` gains
  `data/ideas`. Ideas run daily with the existing schedule.

### B4. Tests

- Percentile, decay and boost maths, checked against a hand-computed v2-style example.
- Cross-site merge.
- Each adapter's parser runs against a saved fixture response; tests make no network calls.
- No-key fallback.
- Ranges and sorting.
- Privacy test still passes.

---

## Phase C — Trends: idea categories + "Why it is rising"

**Idea categories:**
- In `radar.build_trends`, add one entry per idea type with `kind: "idea"` and field `ai_tech`.
- Series = the daily count of ideas of that type, from `data/ideas`.
- Same z-score maths as topics. Only include it once there are ≥ 8 days of ideas history; before
  that, the kind toggle hides the "Idea categories" option.
- The Trends kind toggle becomes All / News topics / Idea categories / Market.
- `related` for an idea entry = its top ideas from the last 7 days.

**Why it is rising:**
- One DeepSeek call per day for the entries with `z >= 2`. Input: the entry name + its related
  headlines or ideas.
- Output: one or two sentences per entry, in zh and en, grounded only in the given titles.
- Stored in `data/radar/explanations/<date>.json`, so reruns reuse it and no extra calls are made.
- Shown as "Why it is rising" with a "Model explanation" tag, as in v2.
- No key or no output → the block is hidden. Never fake it.

**Early signal:**
- If an idea category crossed z ≥ 2 on a day when no news topic matching its keywords was rising,
  show the v2 "Early signal" line.
- Only do this if you can define the matching honestly. Otherwise skip it and say so in the report.

---

## Phase D — Probability forecasts (market questions only) + Brier

**Goal:** the v2 Forecasts view with real probabilities, Brier scores and calibration, using only
questions that can be resolved automatically from stored quotes.

### D1. Question generation

`scripts/trends/market_forecast.py`, rule-based, no LLM.

- **When:** every day, for each quote with ≥ 20 days of history, for the horizons 7 days and
  30 days. To keep the volume small, only create a new question when the previous one for that
  quote / horizon has resolved.
- **Question:** "Will {name} close above {threshold} on or after {deadline}?" with `threshold` =
  today's close.
  - Close above vs. below is enough. Optionally add a ±1σ threshold variant; keep at most
    11 × 2 open questions.
- **Probability:** use a drift-and-volatility model on the stored daily `change_pct`.
  - σ = stdev over 20 days; μ = mean of the last 20 days, shrunk by 0.5.
  - `p = Φ(μ·t / (σ·√t))`, where t is in trading days (≈ 5 per week, 21 per month).
  - Clamp `p` to [0.05, 0.95], round to a whole %, and store it with `model_version: "market-v1"`.
- **Rationale string**, zh and en, built from the numbers, e.g. "20-day volatility 1.2%/day; recent
  drift +0.1%/day".
- **Resolution rule** text, zh and en: "Close on the first stored trading day on or after the
  deadline (source: Eastmoney / Sina / Yahoo via the market section)".

### D2. Resolution

- On the first daily snapshot with `trading_date >= deadline`, record outcome 1 or 0 and the Brier
  score `(p - o)^2`. Append the result to `data/trends/market_resolutions/<date>.json`.
- Forecasts are never overwritten (same rule as the existing direction forecasts).
- A missing quote leaves the question unresolved; it is retried on the next day for up to 5
  trading days, then marked `void`.

### D3. Baseline

- There is no prediction-market data. As the v2 "market" comparison, show a **climatology
  baseline**: always predicting the historical up-day frequency of that quote.
- Show both its Brier score and ours. Label it "Baseline", not "Market".

### D4. Pages

- `radar.build_forecasts` adds `questions`:
  - `open`: questions, each with p, deadline, days left, rationale and resolution.
  - `resolved`: questions with outcome, ours, baseline and Brier.
  - `record`: Brier ours / baseline, plus resolved and open counts.
  - `calibration`: 5 bins (0–20 … 80–100), each with predicted mean, observed frequency and n.
- **Forecasts page:**
  - The **Open** tab lists market questions (v2 style: % in large type plus a bar). The
    combined-trend direction calls move to a secondary "Direction calls" block.
  - **Resolved:** the v2 table with columns Question / Outcome / Ours / Baseline / Brier.
  - **Calibration:** v2 bars (observed) plus a line (predicted mean). Below 20 resolved questions,
    show a "collecting data" note instead of the chart.
  - Keep the existing direction track record as its own small panel.
- **Home Outlook:** show the top 3 open market questions (v2 home forecast cards). The header link
  reads "Brier x.xxx · N resolved" once N ≥ 1, and otherwise falls back to the current text.
- **Rules → Analysis:** add the forecast model, the resolution rule and the "baseline is
  climatology" note.

### D5. Tests

- Φ maths and clamping.
- One-open-question-per-quote-and-horizon rule.
- Resolution and the trading-date rule.
- Void after 5 days.
- Brier and calibration bins.
- Never overwriting stored forecasts.

---

## Phase E — Lab trackers

**Goal:** the v2 Lab page, as long-term keyword trackers defined in config. It is a static site,
so there is **no "New tracker" form**. Instead, show an "Add a tracker by editing
`scripts/trackers.yaml`" link to GitHub.

### E1. Config

`scripts/trackers.yaml`:

```yaml
trackers:
  - id: musk
    type: entities          # entities | domain
    name: {zh: 马斯克旗下公司, en: Musk companies}
    since: 2026-10-03
    entities:
      - {id: tesla, name: {zh: 特斯拉, en: Tesla}, aliases: [Tesla, 特斯拉, TSLA]}
      - {id: spacex, name: {zh: SpaceX, en: SpaceX}, aliases: [SpaceX, Starship, 星舰, Starlink, 星链]}
      # xAI / Grok, X, Neuralink, Boring Company, Elon Musk / 马斯克
  - id: space
    type: domain
    name: {zh: 太空与航天, en: Space & aerospace}
    since: 2026-10-03
    keywords: [launch, rocket, satellite, Starship, Artemis, 航天, 火箭, 卫星, 发射, 商业航天]
```

Ship the two trackers from the design, with real aliases. Make `since` the date of the first run.

### E2. Matching

`scripts/lab.py`:
- **Where:** all stored items. That means brief events (all three sections, including every
  report from Phase A) for the days where `data/brief` exists, plus `data/trends/daily`
  `news_signals` for older days.
- **How:** case-insensitive. ASCII aliases use word boundaries; CJK aliases use substring
  matching. Dedupe items by link.
- **Backfill** from the stored history on the first run, and label backfilled days as such.
- **Per entity:** mentions over 7 days, change vs. the previous 7 days, a 30-day daily series
  (sparkline), and the latest headline.
- **Per tracker:** total mentions over 7 days, events over 30 days, distinct sources, and the
  EN / 中 split.
- **Timeline:** the newest 30 matched items, each with date, entity, title (zh / en), report
  count, field chips and link.
- **Domain trackers:** use the same stats and timeline (no entity cards). Add the "Rising in this
  domain" rows: the radar trend entries whose related items match the tracker keywords. If
  nothing matches honestly, show nothing.
- Leave out **Upcoming**, the **launch tables** and **launch share**, because no data source
  exists for them.
- **Export:** `data/radar/lab.json`.

### E3. Page

- `content/lab/_index{,.en}.md` + `layouts/lab/list.html`, following v2 `isLab`:
  - tracker cards in a sticky left column, with type, name, keyword preview, "since" date and the
    7-day count
  - the selected tracker's header, keywords and stats
  - entity cards (click to filter the timeline, as in v2)
  - the timeline
- Select with anchors (`#musk`) plus small JS.
- **Nav:** add Lab before Rules.
- **Rules → Fetching:** add a "Trackers" row with the tracker count and a link to the YAML file.

### E4. Tests

- Alias matching: word boundary vs. CJK.
- Dedupe.
- The 7-day change.
- Backfill from both storage formats.
- An empty tracker renders the "Collecting" state.

---

## Final verification (report the results to the user)

1. Run `python3 -m pytest -q`. The suite currently passes 169 tests.
2. Run the full pipeline once locally with network access but **no** `DEEPSEEK_API_KEY`, so the
   fallbacks are exercised. Then report:
   - the counts per idea source and which ones failed
   - cluster merge examples
   - the number of open market questions
   - the tracker counts
3. Build with Hugo 0.148.2 extended. Download it, keep the binary outside the repo, and never
   commit it:
   - Download: `curl -sSL https://github.com/gohugoio/hugo/releases/download/v0.148.2/hugo_extended_0.148.2_linux-amd64.tar.gz | tar xz hugo`
   - Build: `hugo --minify --printI18nWarnings -d /tmp/wr-public`
   - It must finish with no errors and no i18n warnings.
   - Check every page in both languages: `/`, `/ideas/`, `/trends/`, `/forecasts/`, `/lab/`,
     `/rules/`.
4. If a browser is available, check the pages at 375px and 1280px, in light and dark mode.
5. Commit each phase on `world-radar-v2-phase2`. **Do not push.**
6. If any phase had to be cut down because data was not available, list exactly what was left out
   and why.
