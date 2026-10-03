(function () {
  "use strict";

  const root = document.querySelector(".trends-page");
  if (!root) return;

  const PERIODS = ["week", "month", "quarter", "year"];
  const LANG = (document.documentElement.lang || "").toLowerCase().startsWith("en") ? "en" : "zh";
  const STRINGS = {
    zh: {
      tech: "科技动量", market: "市场信号", unavailable: "暂不可用", seePrevious: "请查看上一期日报",
      chartUnavailable: "趋势数据暂不可用，稍后重试。", unknownDate: "未知日期", coverage: "覆盖",
      coverageOk: "当前周期满足最低覆盖要求。", techThin: "样本不足，暂不判断。", techValue: "主题动量 {v}",
      marketThin: "行情信号不足，暂不判断。", marketValue: "市场信号 {v}", topic: "主题", momentum: "动量",
      activity: "活跃度", topicMeta: "{e} 个事件 · {s} 个来源", noTopics: "当前周期暂无主题数据。",
      baseCase: "基准情景", confidence: "可信度", thinData: "当前数据不足。", drivers: "驱动：",
      noForecast: "该周期暂未形成预测，通常需要更多历史样本。", untitled: "未命名事件", importance: "重要性",
      noEvidence: "当前周期没有可展示的证据事件。", chartEmpty: "当前周期数据不足，暂不绘制趋势线。",
      noData: "暂无数据", none: "暂无", seriesChange: "{label}由 {a} 变为 {b}", seriesNone: "{label}暂无数据",
      range: "{first} 至 {last}，{parts}。", join: "，", listJoin: "；", driverJoin: "、",
      weekday: ["周日", "周一", "周二", "周三", "周四", "周五", "周六"],
      direction: { positive: "偏强", neutral: "震荡", negative: "偏弱", insufficient_data: "数据不足", unknown: "未知" },
      confidenceLevel: { high: "高", medium: "中", low: "低" },
      status: { ok: "数据充足", partial: "部分覆盖", unavailable: "数据缺失", unknown: "状态未知" },
      period: { week: "最近一周", month: "最近一月", quarter: "最近一季", year: "最近一年" },
      area: { news: "新闻", market: "行情", macro: "宏观" },
      newsCoverage: "新闻覆盖 {a}/{b} 天", sessions: "交易日 {a}/{b} 个", areaMissing: "{area}数据缺失",
      stale: "部分行情报价未更新",
    },
    en: {
      tech: "Tech momentum", market: "Market signal", unavailable: "Unavailable", seePrevious: "See the previous brief",
      chartUnavailable: "Trend data is unavailable right now; try again later.", unknownDate: "Unknown date",
      coverage: "coverage", coverageOk: "This period meets the minimum coverage.", techThin: "Too few samples to call.",
      techValue: "Topic momentum {v}", marketThin: "Not enough market signal to call.", marketValue: "Market signal {v}",
      topic: "Topic", momentum: "Momentum", activity: "Activity", topicMeta: "{e} events · {s} sources",
      noTopics: "No topic data in this period.", baseCase: "Base case", confidence: "confidence",
      thinData: "Not enough data yet.", drivers: "Drivers: ",
      noForecast: "No forecast for this period yet; it usually needs more history.", untitled: "Untitled event",
      importance: "importance", noEvidence: "No evidence events to show for this period.",
      chartEmpty: "Not enough data in this period to draw the trend.", noData: "No data", none: "n/a",
      seriesChange: "{label} moved from {a} to {b}", seriesNone: "{label} has no data",
      range: "{first} to {last}: {parts}.", join: "; ", listJoin: "; ", driverJoin: ", ",
      weekday: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
      direction: { positive: "Leaning up", neutral: "Range-bound", negative: "Leaning down", insufficient_data: "Not enough data", unknown: "Unknown" },
      confidenceLevel: { high: "High", medium: "Medium", low: "Low" },
      status: { ok: "Full data", partial: "Partial coverage", unavailable: "Data missing", unknown: "Unknown status" },
      period: { week: "Last week", month: "Last month", quarter: "Last quarter", year: "Last year" },
      area: { news: "News", market: "Market", macro: "Macro" },
      newsCoverage: "News coverage {a}/{b} days", sessions: "Trading sessions {a}/{b}", areaMissing: "{area} data missing",
      stale: "Some market quotes are stale",
    },
  }[LANG];
  const fill = (template, values) => template.replace(/\{(\w+)\}/g, (_, key) => (key in values ? values[key] : `{${key}}`));
  const pick = (zh, en) => (LANG === "en" && en ? en : zh);
  // 两条序列单位不同：分上下两栏各用自己的刻度（不做双轴，也不归一到起点 100——市场信号会跨 0）
  const CHART_SERIES = [
    { key: "technology", label: STRINGS.tech, color: "var(--trend-tech)", zero: false },
    { key: "market", label: STRINGS.market, color: "var(--trend-market)", zero: true },
  ];

  const $ = (selector) => root.querySelector(selector);
  const $$ = (selector) => Array.from(root.querySelectorAll(selector));
  const tabs = $$("[data-period]");
  const chart = $("[data-trend-chart]");
  const chartWrap = $("[data-trend-chart-wrap]");
  const tooltip = $("[data-trend-tooltip]");
  const state = { data: null, period: periodFromHash() || "week", series: [], layout: null, active: null };

  selectPeriod(state.period, false);

  fetch(root.dataset.trendsUrl, { headers: { Accept: "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error("trend data unavailable");
      return response.json();
    })
    .then((data) => {
      state.data = data;
      render();
    })
    .catch(() => {
      $("[data-trends-asof]").textContent = STRINGS.unavailable;
      $("[data-trends-quality]").textContent = STRINGS.seePrevious;
      tabs.forEach((button) => { button.disabled = true; });
      $("[data-chart-empty]").textContent = STRINGS.chartUnavailable;
    });

  // 周期切换：点击、方向键（tablist 规范）与地址栏 #week/#month… 同步，链接可直接分享到某个周期
  tabs.forEach((button) => {
    button.addEventListener("click", () => selectPeriod(button.dataset.period, true));
    button.addEventListener("keydown", (event) => {
      const index = tabs.indexOf(button);
      const target = {
        ArrowRight: tabs[(index + 1) % tabs.length],
        ArrowLeft: tabs[(index - 1 + tabs.length) % tabs.length],
        Home: tabs[0],
        End: tabs[tabs.length - 1],
      }[event.key];
      if (!target) return;
      event.preventDefault();
      target.focus();
      selectPeriod(target.dataset.period, true);
    });
  });

  window.addEventListener("hashchange", () => {
    const period = periodFromHash();
    if (period && period !== state.period) selectPeriod(period, false);
  });

  if ("ResizeObserver" in window) {
    let lastWidth = 0;
    new ResizeObserver(() => {
      const width = Math.round(chartWrap.clientWidth);
      if (width === lastWidth) return;
      lastWidth = width;
      renderChart();
    }).observe(chartWrap);
  } else {
    window.addEventListener("resize", renderChart);
  }

  chart.addEventListener("pointermove", (event) => {
    if (!state.layout) return;
    const rect = chart.getBoundingClientRect();
    const px = (event.clientX - rect.left) * (state.layout.width / rect.width);
    showPoint(nearestIndex(px));
  });
  chart.addEventListener("pointerleave", () => {
    if (document.activeElement !== chart) hidePoint();
  });
  chart.addEventListener("focus", () => {
    if (state.layout) showPoint(state.active ?? state.series.length - 1);
  });
  chart.addEventListener("blur", hidePoint);
  chart.addEventListener("keydown", (event) => {
    if (!state.layout) return;
    const last = state.series.length - 1;
    const current = state.active ?? last;
    const next = { ArrowLeft: current - 1, ArrowRight: current + 1, Home: 0, End: last }[event.key];
    if (event.key === "Escape") {
      hidePoint();
      chart.blur();
      return;
    }
    if (next === undefined) return;
    event.preventDefault();
    showPoint(Math.max(0, Math.min(last, next)));
  });

  function periodFromHash() {
    const value = window.location.hash.replace(/^#/, "");
    return PERIODS.includes(value) ? value : null;
  }

  function selectPeriod(period, updateHash) {
    state.period = period;
    tabs.forEach((item) => {
      const selected = item.dataset.period === period;
      item.setAttribute("aria-selected", String(selected));
      item.tabIndex = selected ? 0 : -1;
    });
    if (updateHash) window.history.replaceState(null, "", `#${period}`);
    render();
  }

  function render() {
    if (!state.data) return;
    const period = state.data.periods && state.data.periods[state.period];
    $("[data-period-label]").textContent = periodLabel(state.period);
    if (!period) {
      state.series = [];
      renderChart();
      renderTable([]);
      return;
    }
    const snapshot = state.data.snapshot || {};
    const quality = period.data_quality || {};
    const qualityPct = Math.round((quality.ratio || 0) * 100);
    $("[data-trends-asof]").textContent = snapshot.date || STRINGS.unknownDate;
    $("[data-trends-quality]").textContent = `${statusLabel(quality.status)} · ${STRINGS.coverage} ${qualityPct}%`;
    $("[data-coverage]").textContent = `${qualityPct}%`;
    $("[data-coverage-summary]").textContent = (quality.warnings || []).map(warningLabel).join(STRINGS.listJoin) || STRINGS.coverageOk;
    renderSummary(period);
    state.series = period.series || [];
    state.active = null;
    renderChart();
    renderTable(state.series);
    renderTopics(period.topics || {});
    renderForecasts(state.data.forecasts || []);
    renderEvidence(period.evidence || []);
  }

  function renderSummary(period) {
    const topics = Object.values(period.topics || {});
    const tech = average(topics.map((item) => item.momentum).filter((value) => value !== null && value !== undefined));
    const market = period.market && period.market.latest_momentum;
    $("[data-technology-direction]").textContent = direction(tech);
    $("[data-technology-summary]").textContent = tech === null ? STRINGS.techThin : fill(STRINGS.techValue, { v: formatNumber(tech) });
    $("[data-market-direction]").textContent = direction(market);
    $("[data-market-summary]").textContent = market === null || market === undefined ? STRINGS.marketThin : fill(STRINGS.marketValue, { v: formatNumber(market) });
  }

  function renderTopics(topics) {
    const entries = Object.entries(topics).sort((a, b) => Math.abs(b[1].momentum || 0) - Math.abs(a[1].momentum || 0));
    const head = `<div class="topic-row topic-head" aria-hidden="true"><div>${STRINGS.topic}</div><div class="topic-value">${STRINGS.momentum}</div><div class="topic-value">${STRINGS.activity}</div></div>`;
    $("[data-topic-list]").innerHTML = entries.length ? head + entries.map(([key, item]) => {
      const momentum = item.momentum;
      const cls = momentum > 0 ? "topic-momentum-positive" : momentum < 0 ? "topic-momentum-negative" : "";
      return `<div class="topic-row"><div><div class="topic-name">${escapeHtml(pick(item.name, item.name_en) || key)}</div><div class="topic-meta">${fill(STRINGS.topicMeta, { e: item.event_count || 0, s: item.source_count_peak || 0 })}</div></div><div class="topic-value ${cls}" title="${STRINGS.momentum}">${formatNumber(momentum)}</div><div class="topic-value" title="${STRINGS.activity}">${formatNumber(item.activity)}</div></div>`;
    }).join("") : `<p class="muted">${STRINGS.noTopics}</p>`;
  }

  function renderForecasts(forecasts) {
    const relevant = forecasts.filter((item) => item.horizon === state.period);
    $("[data-forecast-list]").innerHTML = relevant.length ? relevant.map((item) => {
      const scenario = (item.scenarios || []).find((value) => value.name === "基准") || {};
      const drivers = (item.drivers || []).map((value) => pick(value.name, value.name_en)).filter(Boolean).join(STRINGS.driverJoin);
      const name = pick(scenario.name, scenario.name_en) || STRINGS.baseCase;
      const description = pick(scenario.description, scenario.description_en) || STRINGS.thinData;
      return `<article class="forecast-card"><div class="forecast-top"><span class="forecast-name">${escapeHtml(name)}</span><span class="forecast-direction">${escapeHtml(directionLabel(item.direction))} · ${escapeHtml(confidenceLabel(item.confidence))} ${STRINGS.confidence}</span></div><p>${escapeHtml(description)}</p>${drivers ? `<div class="forecast-drivers">${STRINGS.drivers}${escapeHtml(drivers)}</div>` : ""}</article>`;
    }).join("") : `<p class="muted">${STRINGS.noForecast}</p>`;
  }

  function renderEvidence(items) {
    $("[data-evidence-list]").innerHTML = items.length ? items.slice(0, 10).map((item) => `<li><a href="${escapeHtml(safeUrl(item.link))}" target="_blank" rel="noopener">${escapeHtml(pick(item.title, item.title_en) || STRINGS.untitled)}</a><span class="evidence-meta">${escapeHtml(item.date || STRINGS.unknownDate)} · ${STRINGS.importance} ${formatNumber(item.importance)}</span></li>`).join("") : `<li class="muted">${STRINGS.noEvidence}</li>`;
  }

  function renderTable(series) {
    const table = $("[data-trend-table]");
    table.hidden = series.length === 0;
    $("[data-trend-table-body]").innerHTML = series.map((item) => `<tr><td>${escapeHtml(item.date || "")}</td><td>${formatNumber(item.technology)}</td><td>${formatNumber(item.market)}</td><td>${item.coverage === null || item.coverage === undefined ? STRINGS.none : `${Math.round(item.coverage * 100)}%`}</td></tr>`).join("");
  }

  // ---- 图表：两栏小多图，共享横轴；十字线 + 提示框，键盘可操作 ----

  function renderChart() {
    const series = state.series;
    const empty = $("[data-chart-empty]");
    hidePoint();
    state.layout = null;
    if (!series || series.length < 2) {
      chart.innerHTML = `<desc id="trend-chart-description">${STRINGS.chartEmpty}</desc>`;
      chart.removeAttribute("viewBox");
      chart.setAttribute("height", "0");
      empty.hidden = false;
      return;
    }
    empty.hidden = true;

    const width = Math.max(280, Math.round(chartWrap.clientWidth));
    const compact = width < 560;
    const pad = { left: compact ? 42 : 50, right: compact ? 48 : 60, top: 30 };
    const panelHeight = compact ? 112 : 140;
    const panelGap = 46;
    const axisBand = 28;
    const height = pad.top + panelHeight * 2 + panelGap + axisBand;
    const plotRight = width - pad.right;
    const n = series.length;
    const x = (index) => pad.left + (plotRight - pad.left) * (index / (n - 1));

    const panels = CHART_SERIES.map((meta, panelIndex) => {
      const top = pad.top + panelIndex * (panelHeight + panelGap);
      const values = series.map((item) => toNumber(item[meta.key]));
      const valid = values.filter((value) => value !== null);
      const scale = niceScale(valid, meta.zero, compact ? 3 : 4);
      const y = (value) => top + panelHeight * (1 - (value - scale.min) / (scale.max - scale.min));
      return { meta, top, values, valid, scale, y };
    });

    const parts = [`<desc id="trend-chart-description">${escapeHtml(describe(series, panels))}</desc>`];
    panels.forEach(({ meta, top, values, valid, scale, y }) => {
      parts.push(`<g class="chart-panel">`);
      parts.push(`<line class="series-key" x1="${pad.left}" x2="${pad.left + 16}" y1="${top - 14}" y2="${top - 14}" stroke="${meta.color}"/>`);
      parts.push(`<text class="panel-title" x="${pad.left + 22}" y="${top - 10}">${meta.label}</text>`);
      scale.ticks.forEach((tick) => {
        const ty = y(tick).toFixed(1);
        const isZero = meta.zero && Math.abs(tick) < scale.step / 1000;
        parts.push(`<line class="${isZero ? "zero-line" : "grid-line"}" x1="${pad.left}" x2="${plotRight}" y1="${ty}" y2="${ty}"/>`);
        parts.push(`<text class="tick" x="${pad.left - 8}" y="${ty}" dy="0.32em" text-anchor="end">${formatTick(tick, scale.step)}</text>`);
      });
      if (!valid.length) {
        parts.push(`<text class="tick" x="${(pad.left + plotRight) / 2}" y="${top + panelHeight / 2}" text-anchor="middle">${STRINGS.noData}</text>`);
        parts.push(`</g>`);
        return;
      }
      parts.push(`<path class="series-line" d="${linePath(values, x, y)}" stroke="${meta.color}"/>`);
      const lastIndex = lastValidIndex(values);
      const lx = x(lastIndex);
      const ly = y(values[lastIndex]);
      parts.push(`<circle class="series-dot" cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="4" fill="${meta.color}"/>`);
      parts.push(`<text class="end-label" x="${(lx + 8).toFixed(1)}" y="${ly.toFixed(1)}" dy="0.32em">${formatNumber(values[lastIndex])}</text>`);
      parts.push(`</g>`);
    });

    const axisY = pad.top + panelHeight * 2 + panelGap + 18;
    tickIndexes(n, Math.max(2, Math.floor((plotRight - pad.left) / 64))).forEach((index) => {
      const anchor = index === 0 ? "start" : index === n - 1 ? "end" : "middle";
      parts.push(`<text class="tick" x="${x(index).toFixed(1)}" y="${axisY}" text-anchor="${anchor}">${escapeHtml(shortDate(series[index].date))}</text>`);
    });

    const bottom = pad.top + panelHeight * 2 + panelGap;
    parts.push(`<g class="crosshair" data-crosshair visibility="hidden"><line class="crosshair-line" y1="${pad.top - 4}" y2="${bottom}"/>${panels.map((panel, i) => `<circle class="series-dot" data-crosshair-dot="${i}" r="4" fill="${panel.meta.color}"/>`).join("")}</g>`);

    chart.setAttribute("viewBox", `0 0 ${width} ${height}`);
    chart.setAttribute("height", String(height));
    chart.innerHTML = parts.join("");
    state.layout = { width, pad, plotRight, n, x, panels };
  }

  function nearestIndex(px) {
    const { pad, plotRight, n } = state.layout;
    const ratio = (px - pad.left) / (plotRight - pad.left);
    return Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1))));
  }

  function showPoint(index) {
    if (!state.layout) return;
    const { x, panels, width } = state.layout;
    const item = state.series[index];
    if (!item) return;
    state.active = index;
    const cx = x(index);
    const group = chart.querySelector("[data-crosshair]");
    group.setAttribute("visibility", "visible");
    const line = group.querySelector(".crosshair-line");
    line.setAttribute("x1", cx.toFixed(1));
    line.setAttribute("x2", cx.toFixed(1));
    panels.forEach((panel, i) => {
      const dot = group.querySelector(`[data-crosshair-dot="${i}"]`);
      const value = panel.values[index];
      if (value === null) {
        dot.setAttribute("visibility", "hidden");
        return;
      }
      dot.setAttribute("visibility", "visible");
      dot.setAttribute("cx", cx.toFixed(1));
      dot.setAttribute("cy", panel.y(value).toFixed(1));
    });

    tooltip.replaceChildren();
    const dateEl = document.createElement("div");
    dateEl.className = "trend-tooltip-date";
    dateEl.textContent = `${item.date || ""} ${weekday(item.date)}`.trim();
    tooltip.appendChild(dateEl);
    panels.forEach((panel) => {
      const row = document.createElement("div");
      row.className = "trend-tooltip-row";
      const key = document.createElement("i");
      key.className = "trend-tooltip-key";
      key.style.background = panel.meta.color;
      const value = document.createElement("strong");
      value.textContent = formatNumber(panel.values[index]);
      const label = document.createElement("span");
      label.textContent = panel.meta.label;
      row.append(key, value, label);
      tooltip.appendChild(row);
    });
    tooltip.hidden = false;

    const scale = chart.getBoundingClientRect().width / width;
    const left = cx * scale;
    const tipWidth = tooltip.offsetWidth;
    const flip = left + 14 + tipWidth > chartWrap.clientWidth;
    tooltip.style.left = `${Math.max(0, flip ? left - 14 - tipWidth : left + 14)}px`;
    tooltip.style.top = `${Math.round(state.layout.pad.top * scale)}px`;
  }

  function hidePoint() {
    tooltip.hidden = true;
    const group = chart.querySelector("[data-crosshair]");
    if (group) group.setAttribute("visibility", "hidden");
  }

  function niceScale(values, includeZero, count) {
    let min = values.length ? Math.min(...values) : 0;
    let max = values.length ? Math.max(...values) : 1;
    if (includeZero) {
      min = Math.min(min, 0);
      max = Math.max(max, 0);
    }
    if (min === max) {
      const spread = Math.abs(min) || 1;
      min -= spread / 2;
      max += spread / 2;
    }
    const rough = (max - min) / Math.max(count - 1, 1);
    const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
    const normalized = rough / magnitude;
    const step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude;
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const ticks = [];
    for (let value = lo; value <= hi + step / 2; value += step) ticks.push(Number(value.toFixed(10)));
    return { min: lo, max: hi, step, ticks };
  }

  function linePath(values, x, y) {
    let d = "";
    let drawing = false;
    values.forEach((value, index) => {
      if (value === null) {
        drawing = false;
        return;
      }
      d += `${drawing ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)}`;
      drawing = true;
    });
    return d;
  }

  function lastValidIndex(values) {
    for (let index = values.length - 1; index >= 0; index -= 1) {
      if (values[index] !== null) return index;
    }
    return -1;
  }

  // 等间距取横轴刻度，末尾总是标出最新日期
  function tickIndexes(n, maxTicks) {
    if (n <= maxTicks) return Array.from({ length: n }, (_, index) => index);
    const step = Math.ceil((n - 1) / Math.max(maxTicks - 1, 1));
    const result = [];
    for (let index = 0; index < n; index += step) result.push(index);
    if (n - 1 - result[result.length - 1] < step / 2) result[result.length - 1] = n - 1;
    else result.push(n - 1);
    return result;
  }

  function describe(series, panels) {
    const first = series[0].date;
    const last = series[series.length - 1].date;
    const parts = panels.map(({ meta, values }) => {
      const valid = values.filter((value) => value !== null);
      return valid.length
        ? fill(STRINGS.seriesChange, { label: meta.label, a: formatNumber(valid[0]), b: formatNumber(valid[valid.length - 1]) })
        : fill(STRINGS.seriesNone, { label: meta.label });
    });
    return fill(STRINGS.range, { first, last, parts: parts.join(STRINGS.join) });
  }

  function toNumber(value) {
    return value === null || value === undefined || Number.isNaN(Number(value)) ? null : Number(value);
  }
  function formatTick(value, step) {
    const decimals = Math.max(0, Math.min(3, -Math.floor(Math.log10(step))));
    return value.toFixed(decimals);
  }
  function shortDate(value) { return String(value || "").slice(5); }
  function weekday(value) {
    const date = new Date(`${value}T00:00:00`);
    return Number.isNaN(date.getTime()) ? "" : STRINGS.weekday[date.getDay()];
  }
  function average(values) { return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null; }
  function formatNumber(value) { return value === null || value === undefined || Number.isNaN(Number(value)) ? STRINGS.none : Number(value).toFixed(2); }
  function direction(value) { return directionLabel(value === null || value === undefined ? "insufficient_data" : value > 0.01 ? "positive" : value < -0.01 ? "negative" : "neutral"); }
  function directionLabel(value) { return STRINGS.direction[value] || STRINGS.direction.unknown; }
  function confidenceLabel(value) { return STRINGS.confidenceLevel[value] || STRINGS.confidenceLevel.low; }
  function statusLabel(value) { return STRINGS.status[value] || STRINGS.status.unknown; }
  function warningLabel(value) {
    const text = String(value);
    let match = text.match(/^news coverage (\d+)\/(\d+)$/);
    if (match) return fill(STRINGS.newsCoverage, { a: match[1], b: match[2] });
    match = text.match(/^market sessions (\d+)\/(\d+)$/);
    if (match) return fill(STRINGS.sessions, { a: match[1], b: match[2] });
    match = text.match(/^(\w+) data unavailable$/);
    if (match) return fill(STRINGS.areaMissing, { area: STRINGS.area[match[1]] || match[1] });
    if (text === "one or more market quotes are stale") return STRINGS.stale;
    return text;
  }
  function periodLabel(value) { return STRINGS.period[value] || value; }
  function safeUrl(value) { return /^https?:\/\//i.test(String(value || "")) ? String(value) : "#"; }
  function escapeHtml(value) { return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char])); }
}());
