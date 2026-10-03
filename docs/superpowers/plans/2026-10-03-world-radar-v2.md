# World Radar v2 — implementation brief (Phase 1)

Hand-off spec for the coding agent. The user approved the plan on 2026-10-03. Work on branch
`world-radar-v2`, which is already created from local `main` (a88f819; 2 commits ahead of `origin/main`).
**Do not push, and do not merge into `main`**: a push to `main` triggers the CI refresh and deploy.

## 0. Background

- Design source: Claude Design project "World Radar redesign", file `World Radar v2.dc.html`.
  **Local copy: `docs/design/World Radar v2.dc.html`** — read it for exact layout and styling. The Claude Design link needs a login, so use this copy.
  - Format: the markup is HTML with inline styles, and `{{ ... }}` values are filled from a `<script>` class at the bottom (`renderVals()` / `extra()`). `sc-for` is a loop and `sc-if` a conditional.
  - Views: Trends is the `isTrends` block (line ~275), Forecasts `isForecasts` (~354) and Rules `isRules` (~622). UI strings are in `T`/`T2`/`RT` (~730–893).
  - Colours: `c` (light/dark), `fg`/`chipBg`/`dot` (hue per field: finance 150, ai_tech 280, politics→world 25/30). These map to the existing CSS tokens in `base.css`.
  - **All data in that file is mock.** Copy the layout, not the numbers or texts.
  - v2 keeps the v1 home page, which is already built on `main`.
  - v2 adds 5 pages: Ideas, Trends (topic explorer), Forecasts, Lab, Rules.
- Project rule: **real data only**. Mock features that have no data are adapted or left out; nothing gets invented.
- What data exists today:
  - `data/trends/daily/*.json`: 55 days of snapshots.
    - `topic_metrics`: 6 AI topics, each with `activity`, `event_count`, `source_count` and `sentiment`. Sentiment is always 0, so don't use it.
    - `market_quotes`: 11 quotes, each with `name`, `price` and `change_pct`.
    - `news_signals`: AI and market headlines with `title`, `title_en`, `link`, `source`, `topics`, `importance` and `published_at`.
  - `data/trends/forecasts/<date>.json`: 4 rule-based forecasts per day, one per horizon (week/month/quarter/year).
    - Each has `direction` (positive/neutral/negative/insufficient_data) and `confidence` (low/medium/high).
    - Each also has `drivers` (topic, name, momentum), 3 template `scenarios`, `invalidation_conditions` (Chinese only), `target_date` and `data_snapshot`.
  - `data/trends/evaluations/<date>.json`: about 73 resolved forecasts in total.
    - Each is a full forecast plus `status` (correct/incorrect/unresolved) and `realized_result.direction` / `evaluated_at`.
- Out of scope for this phase: Ideas, Lab trackers, event clustering, probability/Brier forecasts, and LLM "why rising" text. Do **not** add nav items or empty pages for them.

## 1. Conventions (must follow)

- Python 3.12 with no new dependencies. Docstrings and comments are in **Chinese**, short, like the existing scripts.
- JSON writes use `common.atomic_write_text`. When the content has not changed, skip the write so same-day reruns create no commit. See `brief.write_brief`.
- Generated JSON has **no timestamps**, except where existing files already have them.
- Hugo templates go in `layouts/` and follow the style of `layouts/_partials/today.html`.
  - CSS tokens come from `assets/css/extended/base.css`: `--bg --surface --ink --muted --line --soft`, `--field-<f>`, `--field-<f>-fg` and `--field-<f>-bg`, where `<f>` is `finance`, `ai_tech` or `world`.
  - Reuse the existing classes in `today.css`: `.panel`, `.block-head`, `.tag-<field>`, `.spark`, `.field-btn`, `.dot-<field>`, `.mono`.
- Pages are rendered server-side. JS is limited to small progressive-enhancement scripts in the style of `assets/js/today.js`, loaded from `layouts/_partials/extend_head.html` and conditioned on the page layout.
- Bilingual: every user-facing string goes in **both** `i18n/en.yaml` and `i18n/zh-cn.yaml`. Data strings use `{zh, en}` dicts, and the template picks a language with `$lang := cond (eq site.Language.Lang "en") "en" "zh"`.
- **Privacy rule:** never show `block_keywords` or `PRIVATE_RANK_RULES` on the public site. `tests/test_method.py` already enforces this for the old page; keep an equivalent assertion.
- Pages must work at phone width with no horizontal page scroll. Wide tables go in an `overflow-x:auto` wrapper.

## 2. Pipeline — new `scripts/radar.py`

Pure functions with no network calls. Outputs go to `data/radar/`, which Hugo reads as `site.Data.radar`.

### 2.1 Move the shared helpers from `brief.py` into `radar.py`

Move these and make them public names in `radar.py`:
- `_load_daily` → `load_daily(folder, date_str, days)`
- `_zscore` → `zscore`
- `_bars` → `bars`
- `_topic_activity` → `topic_activity`
- `_quote_field` → `quote_field`

`brief.py` imports them. `brief.rising()` output must stay **byte-identical**.

### 2.2 `build_trends(trend_dir, date_str) -> dict` → `data/radar/trends.json`

```json
{
  "as_of": "2026-10-03",
  "window": 30,
  "rising_z": 2.0,
  "entries": [
    {
      "id": "chips_compute",
      "kind": "topic",
      "field": "ai_tech",
      "name": {"zh": "芯片与算力", "en": "Chips & compute"},
      "z": 2.4,
      "rising": true,
      "spark": [12, 40, 100],
      "stats": [{"k": "heat", "v": "0.85"}, {"k": "mean", "v": "0.41"}, {"k": "change_7d", "v": "+38%"}, {"k": "mentions", "v": "2 · 2"}],
      "chart": {
        "bars": [{"d": "2026-09-04", "v": 0.4, "b": 0.0, "h": 23.5, "recent": false}],
        "band": {"b": 10.2, "h": 30.1},
        "zero": 0.0,
        "dates": ["2026-09-04", "2026-09-18", "2026-10-03"]
      },
      "related": [{"title": {"zh": "...", "en": "..."}, "link": "...", "source": "...", "date": "2026-10-02"}],
      "forecasts": ["week", "month"]
    }
  ]
}
```

Load the rows with `load_daily(trend_dir/"daily", date_str, 31)`. The last row is "today"; the 30 rows before it are the baseline. If there are fewer than 8 rows, `entries` is `[]`.

**Topics** (`trends.config.TOPICS`, 6 entries):
- Series = `topic_activity(row, key)`.
- z = `zscore(series[-1], series[-31:-1], floor=0.1)`, the same formula as `brief.rising`.
- Stats:
  - `heat`: today's activity, 2 decimals.
  - `mean`: baseline mean, 2 decimals.
  - `change_7d`: sum of the last 7 days vs. the 7 days before, as a signed integer %. Use `"—"` when the earlier sum is 0.
  - `mentions`: `f"{event_count} · {source_count}"`, read from today's `topic_metrics`.
- Field `ai_tech`.

**Market** (one per quote name in the last row's `market_quotes`):
- Series = `change_pct` per row, with `None` when missing.
- z = `zscore(today, known history, floor=0.25)`.
- Stats:
  - `change`: today, `"+0.31%"`.
  - `mean`: baseline mean %.
  - `change_7d`: price now vs. 7 rows ago, as %.
  - `price`: 2 decimals.
- Field `finance`, `id = "quote-<name>"`.
- English name from `generators.market.QUOTE_NAMES_EN`.

**Chart** (precomputed so the template only sets CSS percentages):
- Use the last 30 points.
- The scale covers the band and spans `lo = min(0, values, band_low)` to `hi = max(values, band_high)`.
- The band is the baseline mean ± the spread used by `zscore`, i.e. `max(pstdev, |mean|*0.25, floor)`. Export that spread from `zscore`'s logic; don't duplicate a different formula.
- Each bar runs from the zero line to its value: `b` is the bottom % and `h` the height %. Negative values hang below the zero line.
- `zero` = zero-line position %. `recent` = last 3 bars, and only when `rising`.
- `dates`: first, middle and last dates.
- A missing value becomes `h: 0`.

**Other entry fields:**
- `spark`: `bars(series[-14:])`. Market sparks use `relative=True` over price.
- `related` (topics only): `news_signals` from the last 7 rows whose `topics` contain the key.
  - Dedupe by `id`, sort by `importance` desc then date desc, keep at most 5.
  - Title is `{zh: title, en: title_en or title}`; date is the row date.
  - Markets have `[]`.
- `forecasts`: horizons of the latest open forecasts whose `drivers[].topic` equals the key.

**Entry filtering and order:** drop entries whose z is `None`. Sort by z desc. `rising` = `z >= 2.0`.

### 2.3 `build_forecasts(trend_dir, date_str) -> dict` → `data/radar/forecasts.json`

```json
{
  "as_of": "2026-10-03",
  "open": [{"horizon": "week", "direction": "negative", "confidence": "high", "created": "2026-10-03",
            "target_date": "2026-10-10", "days_left": 7,
            "drivers": [{"topic": "policy_safety", "name": {"zh": "", "en": ""}, "momentum": 0.38}],
            "scenarios": [{"name": {"zh": "基准", "en": "Base case"}, "direction": "negative", "description": {"zh": "", "en": ""}}],
            "invalidation": [{"zh": "", "en": ""}]}],
  "resolved": [{"id": "trend-week-2026-09-26", "horizon": "week", "created": "2026-09-26", "target_date": "2026-10-03",
                "direction": "negative", "confidence": "high", "observed": "negative", "correct": true}],
  "record": {"resolved": 73, "correct": 34, "rate": 47, "open": 4,
             "by_horizon": [{"horizon": "week", "resolved": 40, "correct": 20, "rate": 50}]},
  "calibration": [{"confidence": "low", "n": 0, "correct": 0, "rate": null}]
}
```

- `open`: forecasts in the newest `forecasts/*.json` with stem ≤ `date_str`, in the order week/month/quarter/year.
  - Move the zh/en mapping from `brief._forecasts` here as `forecast_entry(f)`, and make `brief._forecasts` call it. Extra keys in brief JSON are fine.
- `resolved`: all evaluations with status correct/incorrect, deduped by `forecast_id`, sorted by `target_date` desc, keeping at most 50.
  - `record` and `calibration` are computed over **all** of them, not just the 50.
  - `rate` is a rounded integer %, or `null` when n = 0. `by_horizon` only lists horizons with n > 0.
- `calibration`: hit rate per confidence level. The page shows it as the stand-in for v2's probability-calibration chart, with a 50% "coin flip" reference line.
- Add English for the invalidation strings, `"数据覆盖率低于最低阈值"` and `"主要驱动主题在下一周期明显降温"`, and for reason `"数据不足"`, to `trends/forecast.py` next to `SCENARIO_EN`, then use them.

### 2.4 Writers

- `write_radar(trend_dir, date_str, out_dir)` writes both files. Each write is skipped when the content hasn't changed.

### 2.5 Rules data — `scripts/method.py`

Replace the markdown generator with `build_rules(config) -> dict` and `write_rules(config, path)`, which writes to `data/radar/rules.json` and skips the write when unchanged.

- **Keep** `site_label`, `site_home`, `feed_link_cell`, `SECTION_META` and `MARKET_EXTRA_SOURCES`.
- **Remove** `build_method_page` and `write_method_page`.
- **Delete** `content/method.md`.

Output shape: all labels and values are `{zh, en}`.

```json
{
  "sections": [
    {"key": "fetch", "steps": [0, 1], "name": {}, "desc": {}, "groups": [
      {"title": {}, "rows": [
        {"label": {}, "desc": {}, "kind": "value|locked|chips|list", "value": {}, "chips": []}
      ]}
    ]}
  ],
  "sources": [
    {"name": {}, "section": "ai", "site": "techcrunch.com", "href": "https://techcrunch.com/", "rss": "...",
     "category": {}, "access": "RSS|API", "max_items": 10, "ai_filter": false}
  ]
}
```

The steps bar lists 7 stages: Adapters, Normalize, Dedupe, Enrich, Store, Analyze, Website. `steps` holds the indexes of the stages each section highlights. Make the step labels i18n keys.

Sections, using real values only:

- **fetch** (steps 0, 1):
  - Schedule: "Daily 06:00 Beijing time, and on every push to main"; same-day reruns reuse finished sections.
  - Limits, values from `settings`: `hours_window` h, `total_limit`, `per_source_limit`, `deep_limit`, `deep_per_source_limit`.
  - Locked rows, all true today:
    - Store link + short summary only.
    - A failed section never blocks the others, and errors are logged with the source name.
- **filter** (step 2):
  - AI keyword filter: `chips` = `config["ai_keywords"]`; applies to feeds with `ai_filter: true`.
  - Dedupe: seen-link fingerprints kept about 30 days; same story → most authoritative report (`RANK_RULES[1]`).
  - Do **not** include `block_keywords`.
- **analyze** (steps 3, 5):
  - Model: `common.DEEPSEEK_MODEL`.
  - Importance bands: a `list` of `SCORE_BANDS` rows.
    - Add `SCORE_BANDS_EN` and `RANK_RULES_EN` in `method.py`, keyed by band or by index.
    - Translate faithfully; the Chinese source is in `common.py`.
  - Highlight ≥ `HIGHLIGHT_SCORE`.
  - Trends:
    - rising z ≥ 2 on the Trends page; the home list shows the top 5 with z > 0
    - baseline 30 days, minimum 7 days
    - topics as chips (`TOPICS` name / name_en)
  - Forecasts:
    - rule model `rules-v1`, 4 horizons
    - resolved by the sign of cross-asset market momentum on the target date
    - locked: no probabilities until calibrated
- **publish** (steps 4, 6):
  - Static site on GitHub Pages, in Chinese + English.
  - Locked rows:
    - "not financial advice" disclaimer
    - no automated trading
    - API key lives in GitHub Actions secrets and is never committed
    - forecast records are never overwritten; results are appended

`sources`:
- Every feed from `config["feeds"]`, using `site_label` / `site_home` (or `homepage`).
- Category: `{zh: category, en: common.category_en(category)}`.
- Plus `MARKET_EXTRA_SOURCES` with access `API`. EN names: Eastmoney, Jin10 / Forex Factory, CNINFO.

### 2.6 `scripts/fetch_news.py`

- Replace the method-page block with `write_rules(config, ROOT/"data"/"radar"/"rules.json")`. It runs every time; it's cheap and only writes on change.
- Add a `write_radar(...)` block after the brief block, in its own `try/except` that prints `[error] ...` (existing pattern).
- `.github/workflows/daily.yml` "Commit new content": remove `content/method.md` and add `data/radar`.

## 3. Pages

### 3.1 Nav

In `hugo.toml`, for both languages: Today · News · Deep reads · Trends · Forecasts (`/forecasts`, weight 50) · Rules (`/rules`, weight 60). Chinese names: 预测, 规则.

- `layouts/_partials/header.html`: add active states for `forecasts` and `rules`.
- Footer: replace the `/method` "Methodology (Chinese)" link with Rules, and update the i18n key.

### 3.2 Trends — rewrite `layouts/trends/list.html`; replace `assets/js/trends.js`

The layout follows the v2 `isTrends` view:

- **Header:**
  - updated dot + `as_of`, h1, subtitle ("Daily volume per topic compared with its 30-day baseline. A z-score of 2 or more marks a topic as rising.").
  - stats: Rising (count of `rising`), Watching (the rest), Window `30d`.
- **Filter bar:**
  - field chips (All / Finance / AI & Tech) with counts; reuse `.field-btn`.
  - segmented kind toggle: All / News topics / Market.
- **Left column:** one row per entry, as an `<a href="#<id>">`.
  - Name, plus a dot and kind label.
  - 14-bar spark; reuse `.spark`.
  - z, formatted `%+.1f`, in the field fg colour when rising and muted otherwise.
- **Right column:** one `<section id="<id>" class="topic-detail">` per entry. Only the selected one is visible.
  - Without JS: CSS `:target`, with the first entry shown by default.
  - With JS: the script toggles `hidden` and keeps the URL hash in sync.
  - Contents:
    - chips (field tag + kind)
    - name (h2)
    - big z + label ("z-score" when rising, "Watching" otherwise)
    - a 4-stat grid, labels from i18n `stat_<k>`
    - 180px chart: an absolutely positioned band div (`bottom:{b}%; height:{h}%`), a zero line, and bars (`bottom:{b}%; height:{h}%`), with recent bars in the field colour
    - date axis (3 labels)
    - note "Shaded band: 30-day baseline ± usual spread"
    - Related events: list of links opening in a new tab; omit the block when empty
    - Linked forecast card(s) → `/forecasts/#open`, showing horizon + direction from `site.Data.radar.forecasts.open`
- **Empty state** when there are no entries.
- **Drop** the old period dashboard (period tabs, chart, evidence, method panel), its unused i18n keys, and the unused `trends.css` rules.
  - `static/data/trends/*.json` generation stays as is.
- **JS:** field and kind filtering, plus selection. When the current selection is filtered out, select the first visible entry. `?field=` works the same as on the home page.

### 3.3 Forecasts — new section

Create `content/forecasts/_index.md` and `_index.en.md` (titles 预测 / Forecasts) and `layouts/forecasts/list.html`, following the v2 `isForecasts` view:

- **Header:** h1 + subtitle: "Rule-based calls on the combined tech-and-market trend. Each is checked automatically at its target date. Directions and confidence only, no probabilities until we have a calibrated record."
- **Track record panel**, in two halves:
  - Left: big numbers for hit rate %, resolved, correct and open, plus the by-horizon hit rate as small rows.
  - Right: "Calibration" — one bar per confidence level, with height = hit rate %, a horizontal 50% coin-flip reference line, the label and `n=`. Use "—" when n = 0.
- **Tabs:** Open / Resolved / Scenarios, as anchored sections `#open`, `#resolved`, `#scenarios`.
  - Without JS, all three are shown stacked. The JS turns them into tabs and follows the hash.
- **Open:** one `<details>` card per forecast.
  - Summary: horizon label (reuse i18n `horizon_*`), "Combined tech & market trend", the direction label (reuse `direction_*`) coloured by direction, a 3-step confidence meter (reuse the home `.fc-meter` style), due date and "N days left".
  - Expanded: 3 columns — Drivers (name + signed momentum), "How it resolves" (fixed i18n text), "What would change it" (invalidation list).
- **Resolved:** a table in an overflow wrapper.
  - Columns: Forecast (horizon + created date), Target date, Called (direction + confidence), Actual, Result (✓ green chip / ✗ muted chip).
  - Footnote: "Latest 50 shown; record covers all N."
- **Scenarios:** use the `year` open forecast.
  - "Driving forces" chips = its drivers.
  - 3 cards lettered A, B, C, each with the scenario name, a direction tag and the description.
  - Disclaimer line.
- **Home links** (`layouts/_partials/today.html`): the Outlook header link → `/forecasts/`; the scenario card → `/forecasts/#scenarios` (currently `/trends#year`).

### 3.4 Rules — replace `content/method.md`

- Create `content/rules.md` and `content/rules.en.md` with front matter: `title`, `layout: "rules"`, `url: "/rules/"` (the EN page gets `/en/rules/` automatically from the language prefix; check this in the build output), `summary`, `body_class: "section-rules"`.
- Template: `layouts/rules.html`. Check how `archives`/`search` layouts resolve in this Hugo version and follow the same pattern.
- Layout follows the v2 `isRules` view, **read-only**:
  - h1 + subtitle: "Principles for how the site fetches, filters and analyzes content. Values shown are the live configuration."
  - On the right, a button-styled link "Edit on GitHub ↗" → `{githubURL}/blob/main/scripts/feeds.yaml`.
  - The pipeline steps bar.
  - Left sticky nav listing the 4 sections (number, name, desc), as anchors.
  - Every section rendered in sequence, each with groups and rows:
    - `value`: right-aligned mono text.
    - `locked`: soft pill "Always on".
    - `chips`: pills.
    - `list`: label/desc rows.
  - A sources table after the fetch section.
  - The JS is optional; anchors are enough.

### 3.5 Home — `layouts/_partials/today.html`

- Each rising row becomes a link to `/trends/#<id>`. Brief rising ids are already topic keys or `quote-<name>`, which match the trends entry ids.
- Make the two forecast-link changes from §3.3.
- Nothing else changes.

### 3.6 CSS

Put new styles in new files under `assets/css/extended/` (e.g. `forecasts.css`, `rules.css`) and rewrite `trends.css`. PaperMod bundles everything in `extended/`.

- Visual reference: v2 uses 12px radius cards, 1px `--line` borders, mono 11–13px meta text, uppercase 13px section heads with 0.06em tracking, and 40px h1 with -0.03em tracking.
- Check both themes (`[data-theme="dark"]`).

## 4. Tests (pytest, `tests/`)

- **`test_radar.py`:**
  - Synthetic daily rows written to `tmp_path`. Cover:
    - z equals `brief.rising` for the same topic
    - chart band, zero line and bar maths for a series containing negative values
    - `change_7d` "—" when the earlier sum is 0
    - related dedupe, sorting and limit 5
    - forecasts link
    - fewer than 8 rows → `entries == []`
  - Forecasts:
    - open order
    - resolved dedupe and sort
    - record/by_horizon/calibration maths
    - no evaluations → rate `None`
  - `write_*` doesn't rewrite unchanged files (compare mtime or return value).
- **`test_method.py`:** rewrite it for `build_rules`.
  - Every feed is present, with both languages.
  - `site`/`href` are correct; keep the existing `site_label`/`feed_link_cell` tests.
  - **block keywords and PRIVATE_RANK_RULES text are absent** from `json.dumps(build_rules(config))`.
- **`test_regressions.py`:** swap the `content/method.md` byte-stability check for `data/radar/rules.json`, and add `data/radar/trends.json`.
- **`test_workflow.py`:** add a test that the commit step adds `data/radar` and no longer adds `content/method.md`.
- **`test_brief.py`:** must still pass unchanged (imports adjusted if needed).

## 5. Verification (report the results to the user)

1. `python3 -m pytest -q`. The baseline before this work was **160 passed**.
2. Run `python3 -c "..."` (or a `__main__` block in `radar.py`) on the real `data/trends`, write `data/radar/*.json`, and spot-check:
   - the rising topics match `brief.rising(...)` for 2026-10-03
   - the record counts match a manual count of the evaluation files
3. Hugo 0.148.2 extended (the CI version):
   - Download: `curl -sSL https://github.com/gohugoio/hugo/releases/download/v0.148.2/hugo_extended_0.148.2_linux-amd64.tar.gz | tar xz hugo`.
     - Keep the binary outside the repo, or delete it afterwards. Never commit it.
   - Run `hugo --minify -d /tmp/wr-public`. It must report no errors and no `warning` about missing i18n keys; use `--printI18nWarnings`.
   - Confirm that these exist and contain real data: `index.html`, `en/index.html`, `trends/index.html`, `en/trends/index.html`, `forecasts/index.html`, `en/forecasts/index.html`, `rules/index.html` and `en/rules/index.html`.
   - `data/brief/` doesn't exist locally (CI creates it), so the home page shows its "brief missing" state. That is expected.
4. If a browser is available, check the 3 new pages at 375px and 1280px width in light and dark mode.
5. Commit on `world-radar-v2` in logical commits (pipeline, pages, tests). **Do not push.**

## 6. Phase 2+ (do NOT build; listed so you don't half-build them)

- Lab trackers (YAML-configured keyword trackers)
- Ideas pillar (adapters + percentile scoring)
- Event clustering
- Probability forecasts + Brier
- LLM "why it is rising" explanations
