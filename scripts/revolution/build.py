"""AI 工业革命观测台数据构建。

产物（schema 版本写在路径里，结构有不兼容变更时升到 v2，旧版本文件保留到页面切换完成）：
- static/data/revolution/v1/manifest.json   生成时间、方法版本、各文件哈希（前端用哈希做缓存失效）
- static/data/revolution/v1/indices.json    D/B/S/C 月度读数、覆盖率、成分 z 值、衍生预测
- static/data/revolution/v1/series.json     各指标原生频率序列（日度降采样为周末值）与资本投入对比数据
- static/data/revolution/v1/forecasts.json  成分级预测、回测路径与实盘记录
- static/data/revolution/v1/events.json     历史事件标记
- data/radar/revolution.json                Hugo 服务端渲染用摘要（无序列）
- history/revolution/forecast_log.jsonl     预测登记（只追加）
- history/revolution/resolution_log.jsonl   到期结算（只追加，按首次看到的发布值结算）
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path

from . import catalog, forecast, series, sources
from .catalog import EVENTS, EVENT_TYPES, FREQ_LABEL, INDEX_ORDER, INDICATORS, INDICES, KIND_LABEL, PENDING

SCHEMA = 1
METHOD_VERSION = "revolution-v1"
BACKTEST_POINTS = 160          # 回测路径图最多展示的样本外点数
# 预测样本起点：避开 1960–80 年代软件投资等序列的早期结构（同比动辄数百个百分点），回测从此后开始累计
FORECAST_FROM = "1990-01-01"
# 指数衍生预测：月份 → 各频率成分对应的预测期数
DERIVED_HORIZON = {1: {"weekly": 4, "monthly": 1}, 3: {"weekly": 13, "monthly": 3, "quarterly": 1}}


def step(day, freq, k=1):
    d = date.fromisoformat(day)
    if freq == "weekly":
        return (d + timedelta(days=7 * k)).isoformat()
    if freq == "monthly":
        return series.add_months(d, k).isoformat()
    if freq == "quarterly":
        return series.add_months(d, 3 * k).isoformat()
    raise ValueError(freq)


def step_ok(freq):
    return lambda a, b: step(a, freq) == b


def r(value, digits=3):
    return None if value is None else round(value, digits) + 0.0


def weekly_downsample(rows):
    """日度序列只保留每周最后一个交易日，控制 JSON 体积。"""
    out = {}
    for row in rows:
        year, week, _ = date.fromisoformat(row["date"]).isocalendar()
        out[(year, week)] = row
    return [out[k] for k in sorted(out)]


# ---------- 成分预测 ----------

def forecast_indicator(ind, rows):
    freq = series.native_freq(ind)
    rows = forecast.contiguous_tail([row for row in rows if row["date"] >= FORECAST_FROM], step_ok(freq))
    values = [row["value"] for row in rows]
    event = ind.get("event")
    horizons = []
    for h in ind["forecast"]:
        threshold = event["above"] if event and event["h"] == h else None
        items, last = forecast.walk_forward(values, h, event=threshold)
        if not last:
            continue
        stats = forecast.score(items, h, event=threshold)
        used, status = forecast.choose(stats)
        point = last[used]
        q = last.get(f"{used}_q")
        entry = {
            "h": h, "origin": rows[last["t"]]["date"], "target": step(rows[last["t"]]["date"], freq, h),
            "source": used, "status": status, "point": r(point), "baseline": r(last["baseline"]), "model": r(last["model"]),
            "q": [r(v) for v in q] if q else None, "b": r(last["b"]),
            "backtest": {"n": stats["n"], "skill": r(stats.get("skill", 0) * 100, 1), "dm_p": r(stats.get("dm_p")),
                         "mae_baseline": r(stats.get("mae_baseline")), "mae_model": r(stats.get("mae_model")),
                         "coverage": r((stats.get(f"coverage_{used}") or 0) * 100, 0) if stats.get(f"coverage_{used}") is not None else None,
                         "start": rows[stats["start"]]["date"] if stats["n"] else None,
                         "end": rows[stats["end"]]["date"] if stats["n"] else None},
            "path": [[step(rows[f["t"]]["date"], freq, h), r(f["realized"]), r(f["baseline"]), r(f["model"]),
                      r(f.get(f"{used}_q", [None, None])[0]), r(f.get(f"{used}_q", [None, None])[1])]
                     for f in items if "realized" in f][-BACKTEST_POINTS:],
        }
        if threshold is not None and "event" in stats:
            ev = stats["event"]
            e_used, e_status = forecast.choose({**ev, "n": ev["n"]})
            entry["event"] = {"above": threshold, "source": e_used, "status": e_status,
                              "p": r(last.get(f"p_{e_used}", None) * 100 if last.get(f"p_{e_used}") is not None else None, 0),
                              "p_baseline": r(last["p_baseline"] * 100, 0) if "p_baseline" in last else None,
                              "p_model": r(last["p_model"] * 100, 0) if "p_model" in last else None,
                              "p_rate": r(last["p_rate"] * 100, 0) if "p_rate" in last else None,
                              "brier_baseline": r(ev["brier_baseline"], 4), "brier_model": r(ev["brier_model"], 4),
                              "skill": r(ev["skill"] * 100, 1), "dm_p": r(ev["dm_p"]), "n": ev["n"], "rate": r(ev["rate"] * 100, 0)}
        horizons.append(entry)
    return {"id": ind["id"], "freq": freq, "unit": ind["unit"], "name": ind["name"], "index": ind["index"],
            "last": {"date": rows[-1]["date"], "value": r(rows[-1]["value"])} if rows else None,
            "sample_start": rows[0]["date"] if rows else None, "horizons": horizons}


def derived_index_forecast(fc_by_id, idx):
    """由成分预测推导的指数读数，不计分。

    有该周期预测的成分：点预测按当前扩展窗口均值 / 标准差换算成 z。
    没有预测的成分（如价格类、研究估算）：保持当前 z（即不变预测）。否则成分构成一变，
    平均值就会凭空跳动——那是口径变化，不是预测。coverage 只统计真正有预测的成分。
    """
    out = {}
    for key in INDEX_ORDER:
        members = [ind for ind in INDICATORS if ind["index"] == key]
        out[key] = []
        for months, mapping in DERIVED_HORIZON.items():
            parts, used = [], []
            for ind in members:
                current = idx["components"].get(ind["id"], [None])[-1] if idx["components"].get(ind["id"]) else None
                fc = fc_by_id.get(ind["id"])
                h = mapping.get(series.native_freq(ind))
                spec = next((x for x in fc["horizons"] if x["h"] == h), None) if fc and h else None
                state = series.z_state(idx["levels"].get(ind["id"], []))
                if spec is not None and state is not None and spec["point"] is not None and current is not None:
                    parts.append(ind["sign"] * max(-series.CLIP, min(series.CLIP, (spec["point"] - state[0]) / state[1])))
                    used.append(ind["id"])
                elif current is not None:
                    parts.append(ind["sign"] * current)
            if used:
                out[key].append({"months": months, "value": r(50 + 10 * sum(parts) / len(parts), 2),
                                 "coverage": r(len(used) / len(members), 2), "components": used})
    return out


# ---------- 预测登记与结算 ----------

def _read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_jsonl(path, records):
    if not records:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def update_ledger(folder, today, forecasts, transformed):
    """新起点的预测登记一次；目标期首次出现真实值时结算一次。两份日志都只追加，不改写。"""
    folder = Path(folder)
    log_path, res_path = folder / "forecast_log.jsonl", folder / "resolution_log.jsonl"
    logged = _read_jsonl(log_path)
    resolved = {item["key"] for item in _read_jsonl(res_path)}
    known = {item["key"] for item in logged}
    new = []
    for fc in forecasts:
        for spec in fc["horizons"]:
            key = f"{fc['id']}|{spec['origin']}|{spec['h']}"
            if key in known:
                continue
            new.append({"key": key, "id": fc["id"], "made_on": today, "origin": spec["origin"], "target": spec["target"],
                        "h": spec["h"], "source": spec["source"], "status": spec["status"], "point": spec["point"],
                        "baseline": spec["baseline"], "q": spec["q"], "p_event": (spec.get("event") or {}).get("p"),
                        "model_version": METHOD_VERSION})
    _append_jsonl(log_path, new)
    logged += new
    values = {ind_id: {row["date"]: row["value"] for row in rows} for ind_id, rows in transformed.items()}
    resolutions = []
    for item in logged:
        if item["key"] in resolved:
            continue
        actual = values.get(item["id"], {}).get(item["target"])
        if actual is None:
            continue
        q = item.get("q")
        resolutions.append({"key": item["key"], "resolved_on": today, "actual": r(actual),
                            "error": r(actual - item["point"]), "error_baseline": r(actual - item["baseline"]),
                            "covered": (q[0] <= actual <= q[1]) if q else None})
    _append_jsonl(res_path, resolutions)
    return logged, _read_jsonl(res_path)


def live_record(logged, resolutions):
    """实盘记录：只统计本站真实登记过、已到期的预测（与回测分开）。"""
    by_key = {item["key"]: item for item in logged}
    out = {}
    for res in resolutions:
        item = by_key.get(res["key"])
        if not item:
            continue
        rec = out.setdefault(item["id"], {"n": 0, "abs": 0.0, "abs_baseline": 0.0, "covered": 0, "with_q": 0})
        rec["n"] += 1
        rec["abs"] += abs(res["error"])
        rec["abs_baseline"] += abs(res["error_baseline"])
        if res["covered"] is not None:
            rec["with_q"] += 1
            rec["covered"] += bool(res["covered"])
    return {k: {"n": v["n"], "mae": r(v["abs"] / v["n"]), "mae_baseline": r(v["abs_baseline"] / v["n"]),
                "coverage": r(v["covered"] / v["with_q"] * 100, 0) if v["with_q"] else None} for k, v in out.items()}


# ---------- 数据来源与发布频率 ----------

def next_release(last_date, ind):
    """按「观测期末 + 一个频率周期 + 发布滞后」粗估下次发布；不定期序列不估计。"""
    freq = series.native_freq(ind)
    if ind["freq"] in ("daily", "event") or not last_date:
        return None
    nxt = step(last_date, freq)
    return (series.period_end(nxt, freq) + timedelta(days=ind["lag_days"])).isoformat()


def source_rows(transformed, raw, meta, today):
    rows = []
    for ind in INDICATORS:
        data = transformed.get(ind["id"], [])
        last = data[-1]["date"] if data else None
        freq = series.native_freq(ind)
        age_limit = series.MAX_AGE[freq] * 2 + ind["lag_days"]
        stale = bool(last) and (date.fromisoformat(today) - series.period_end(last, freq)).days > age_limit
        raw_keys = [k for k, _ in catalog.CAPEX_COMPANIES] if ind["raw"] == "CAPEX_TOTAL" else [ind["raw"]]
        info = [meta.get(k, {}) for k in raw_keys]
        gaps = []
        if ind["raw"] == "CAPEX_TOTAL":
            for key, company in catalog.CAPEX_COMPANIES:
                dates = [row["date"] for row in raw.get(key, [])]
                if dates:
                    expect, day = [], dates[0]
                    while day <= dates[-1]:
                        expect.append(day)
                        day = step(day, "quarterly")
                    gaps += [f"{company} {d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}" for d in sorted(set(expect) - set(dates))]
        rows.append({
            "id": ind["id"], "name": ind["name"], "index": ind["index"], "kind": ind["kind"], "kind_label": KIND_LABEL[ind["kind"]],
            "freq": ind["freq"], "freq_label": FREQ_LABEL[ind["freq"]], "unit": ind["unit"], "lag_days": ind["lag_days"],
            "source": ind["source"], "note": ind["note"], "in_index": bool(ind["index"]),
            "first": data[0]["date"] if data else None, "last": last, "count": len(data),
            "next_release": next_release(last, ind), "stale": stale,
            "fetched_on": min((i.get("fetched_on") or "") for i in info) or None,
            "fetch_ok": all(i.get("ok") for i in info), "gaps": gaps,
            "forecast": bool(ind["forecast"]),
        })
    return rows


# ---------- 汇总 ----------

def chart_series(transformed, raw):
    out = {}
    for ind in INDICATORS:
        rows = transformed.get(ind["id"], [])
        if ind["freq"] == "daily":
            rows = weekly_downsample(rows)
        out[ind["id"]] = [[row["date"], r(row["value"], 4)] for row in rows]
    gdp = {row["date"]: row["value"] for row in raw.get("GDP", [])}  # 十亿美元，季调年化

    def share(rows, scale=1.0):
        return [[row["date"], r(row["value"] * scale / gdp[row["date"]] * 100, 4)] for row in rows if row["date"] in gdp]

    capex = {"companies": [], "total": [], "share_gdp": {}}
    for key, company in catalog.CAPEX_COMPANIES:
        capex["companies"].append({"key": key, "name": company,
                                   "values": [[row["date"], r(row["value"] / 1e9, 3)] for row in raw.get(key, [])]})
    total = series.capex_total(raw)
    capex["total"] = [[row["date"], r(row["value"] / 1e9, 3)] for row in total]
    # 季度现金支出 × 4 / 季调年化 GDP：与 BEA 年化口径对齐
    capex["share_gdp"] = {
        "hyperscaler": share(total, 4 / 1e9),
        "info_equip": share(raw.get("INFO_EQUIP", [])),
        "software": share(raw.get("SOFTWARE", [])),
    }
    models = raw.get("EPOCH", [])
    capability = {
        "models": [[m["date"], r(math.log10(m["flop"]), 3), m["model"], m["organization"]] for m in models if m["date"] >= "2010-01-01"],
        "frontier": [[row["date"], row["value"]] for row in series.frontier(models)],
    }
    return out, capex, capability


def build(root, today, fetcher=None):
    root = Path(root)
    raw, meta = sources.load_all(root, today, fetcher=fetcher)
    transformed = {ind["id"]: series.transform(ind, raw) for ind in INDICATORS}
    idx = series.build_indices(transformed, date.fromisoformat(today))
    forecasts = [forecast_indicator(ind, transformed[ind["id"]]) for ind in INDICATORS
                 if ind["forecast"] and transformed[ind["id"]]]
    fc_by_id = {fc["id"]: fc for fc in forecasts}
    derived = derived_index_forecast(fc_by_id, idx)
    logged, resolutions = update_ledger(root / "history" / "revolution", today, forecasts, transformed)
    live = live_record(logged, resolutions)
    for fc in forecasts:
        fc["live"] = live.get(fc["id"], {"n": 0})
        fc["logged"] = sum(1 for item in logged if item["id"] == fc["id"])
    chart, capex, capability = chart_series(transformed, raw)
    sources_table = source_rows(transformed, raw, meta, today)
    gate = {"skill": round(forecast.GATE_SKILL * 100), "p": forecast.GATE_P, "min_oos": forecast.MIN_OOS,
            "min_interval": forecast.MIN_INTERVAL}
    indices_payload = {
        "as_of": today, "months": idx["months"], "order": INDEX_ORDER,
        "meta": {k: {"name": {"zh": v["zh"], "en": v["en"]}, "desc": v["desc"]} for k, v in INDICES.items()},
        "indices": idx["indices"], "components": idx["components"], "derived": derived,
    }
    files = {
        "indices": indices_payload,
        "series": {"as_of": today, "indicators": {row["id"]: {k: row[k] for k in ("name", "index", "kind", "freq", "unit")}
                                                   for row in sources_table},
                   "series": chart, "capex": capex, "capability": capability,
                   "kind_label": KIND_LABEL, "freq_label": FREQ_LABEL},
        "forecasts": {"as_of": today, "gate": gate, "items": forecasts},
        "events": {"types": EVENT_TYPES, "items": EVENTS},
    }
    return files, summary(indices_payload, forecasts, sources_table, gate, today)


def _latest(values, months):
    for i in range(len(values) - 1, -1, -1):
        if values[i] is not None:
            return i
    return None


def summary(indices_payload, forecasts, sources_table, gate, today):
    """Hugo 服务端渲染：指数最新读数、成分预测表、数据来源表。图表数据由浏览器另行加载。"""
    months = indices_payload["months"]
    cards = []
    for key in INDEX_ORDER:
        item = indices_payload["indices"][key]
        i = _latest(item["values"], months)
        prev = i - 12 if i is not None and i >= 12 and item["values"][i - 12] is not None else None
        cards.append({"key": key, "name": indices_payload["meta"][key]["name"], "desc": indices_payload["meta"][key]["desc"],
                      "value": item["values"][i] if i is not None else None, "month": months[i] if i is not None else None,
                      "coverage": round(item["coverage"][i] * 100) if i is not None else 0,
                      "change_12m": r(item["values"][i] - item["values"][prev], 1) if prev is not None else None,
                      "members": len(item["members"]),
                      "derived": indices_payload["derived"].get(key, [])})
    rows = []
    for fc in forecasts:
        for spec in fc["horizons"]:
            rows.append({"id": fc["id"], "name": fc["name"], "freq": fc["freq"], "unit": fc["unit"], "h": spec["h"],
                         "last": fc["last"], "target": spec["target"], "point": spec["point"], "q": spec["q"],
                         "source": spec["source"], "status": spec["status"], "backtest": spec["backtest"],
                         "event": spec.get("event"), "live": fc["live"], "logged": fc["logged"]})
    return {"as_of": today, "schema": SCHEMA, "method_version": METHOD_VERSION, "cards": cards, "forecasts": rows,
            "sources": sources_table, "pending": PENDING, "gate": gate, "events": len(EVENTS),
            "freq_label": FREQ_LABEL, "kind_label": KIND_LABEL}


def _dump(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"


def run(root, today, fetcher=None):
    from common import atomic_write_text
    root = Path(root)
    files, page = build(root, today, fetcher=fetcher)
    out_dir = root / "static" / "data" / "revolution" / f"v{SCHEMA}"
    manifest = {"schema": SCHEMA, "method_version": METHOD_VERSION, "as_of": today, "files": {}}
    for name, data in files.items():
        text = _dump(data)
        manifest["files"][name] = {"path": f"{name}.json", "sha": hashlib.sha256(text.encode()).hexdigest()[:12],
                                   "bytes": len(text.encode())}
        path = out_dir / f"{name}.json"
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            atomic_write_text(path, text)
    for path, data in ((out_dir / "manifest.json", manifest), (root / "data" / "radar" / "revolution.json", page)):
        text = _dump(data)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            atomic_write_text(path, text)
    return page
