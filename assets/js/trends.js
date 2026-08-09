(function () {
  "use strict";

  const root = document.querySelector(".trends-page");
  if (!root) return;

  const state = { data: null, period: "week" };
  const $ = (selector) => root.querySelector(selector);
  const $$ = (selector) => Array.from(root.querySelectorAll(selector));

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
      $("[data-trends-asof]").textContent = "暂不可用";
      $("[data-trends-quality]").textContent = "请查看上一期日报";
      $$("[data-period]").forEach((button) => { button.disabled = true; });
      $("[data-chart-empty]").textContent = "趋势数据暂不可用，稍后重试。";
    });

  $$("[data-period]").forEach((button) => {
    button.addEventListener("click", () => {
      state.period = button.dataset.period;
      $$("[data-period]").forEach((item) => item.setAttribute("aria-selected", String(item === button)));
      render();
    });
  });

  function render() {
    if (!state.data) return;
    const period = state.data.periods && state.data.periods[state.period];
    if (!period) return;
    const snapshot = state.data.snapshot || {};
    const quality = period.data_quality || {};
    const qualityPct = Math.round((quality.ratio || 0) * 100);
    $("[data-trends-asof]").textContent = snapshot.date || "未知日期";
    $("[data-trends-quality]").textContent = `${quality.status || "未知"} · 覆盖 ${qualityPct}%`;
    $("[data-period-label]").textContent = periodLabel(state.period);
    $("[data-coverage]").textContent = `${qualityPct}%`;
    $("[data-coverage-summary]").textContent = (quality.warnings || []).join("；") || "当前周期满足最低覆盖要求。";
    renderSummary(period);
    renderChart(period.series || []);
    renderTopics(period.topics || {});
    renderForecasts(state.data.forecasts || []);
    renderEvidence(period.evidence || []);
  }

  function renderSummary(period) {
    const topics = Object.values(period.topics || {});
    const tech = average(topics.map((item) => item.momentum).filter((value) => value !== null && value !== undefined));
    const market = period.market && period.market.latest_momentum;
    $("[data-technology-direction]").textContent = direction(tech);
    $("[data-technology-summary]").textContent = tech === null ? "样本不足，暂不判断。" : `主题动量 ${formatNumber(tech)}`;
    $("[data-market-direction]").textContent = direction(market);
    $("[data-market-summary]").textContent = market === null || market === undefined ? "行情信号不足，暂不判断。" : `市场信号 ${formatNumber(market)}`;
  }

  function renderTopics(topics) {
    const entries = Object.entries(topics).sort((a, b) => Math.abs(b[1].momentum || 0) - Math.abs(a[1].momentum || 0));
    $("[data-topic-list]").innerHTML = entries.length ? entries.map(([key, item]) => {
      const momentum = item.momentum;
      const cls = momentum > 0 ? "topic-momentum-positive" : momentum < 0 ? "topic-momentum-negative" : "";
      return `<div class="topic-row"><div><div class="topic-name">${escapeHtml(item.name || key)}</div><div class="topic-meta">${item.event_count || 0} 个事件 · ${item.source_count_peak || 0} 个来源</div></div><div class="topic-value ${cls}">${formatNumber(momentum)}</div><div class="topic-value">${formatNumber(item.activity)}</div></div>`;
    }).join("") : `<p class="muted">当前周期暂无主题数据。</p>`;
  }

  function renderForecasts(forecasts) {
    const relevant = forecasts.filter((item) => item.horizon === state.period);
    $("[data-forecast-list]").innerHTML = relevant.length ? relevant.map((item) => {
      const scenario = (item.scenarios || []).find((value) => value.name === "基准") || {};
      const drivers = (item.drivers || []).map((value) => value.name).filter(Boolean).join("、");
      return `<article class="forecast-card"><div class="forecast-top"><span class="forecast-name">${escapeHtml(scenario.name || "基准情景")}</span><span class="forecast-direction">${escapeHtml(directionLabel(item.direction))} · ${escapeHtml(item.confidence || "低")}可信度</span></div><p>${escapeHtml(scenario.description || item.reason || "当前数据不足。")}</p>${drivers ? `<div class="forecast-drivers">驱动：${escapeHtml(drivers)}</div>` : ""}</article>`;
    }).join("") : `<p class="muted">该周期暂未形成预测，通常需要更多历史样本。</p>`;
  }

  function renderEvidence(items) {
    $("[data-evidence-list]").innerHTML = items.length ? items.slice(0, 10).map((item) => `<li><a href="${escapeAttr(item.link || "#")}">${escapeHtml(item.title || "未命名事件")}</a><span class="evidence-meta">${escapeHtml(item.date || "未知日期")} · 重要性 ${formatNumber(item.importance)}</span></li>`).join("") : `<li class="muted">当前周期没有可展示的证据事件。</li>`;
  }

  function renderChart(series) {
    const svg = $("[data-trend-chart]");
    const empty = $("[data-chart-empty]");
    if (!series || series.length < 2) {
      svg.innerHTML = "";
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    const width = 900, height = 300, pad = { left: 34, right: 18, top: 18, bottom: 34 };
    const points = (key) => normalize(series.map((item) => item[key]));
    const tech = points("technology");
    const market = points("market");
    const x = (index) => pad.left + (width - pad.left - pad.right) * (index / Math.max(series.length - 1, 1));
    const y = (value) => pad.top + (height - pad.top - pad.bottom) * (1 - ((value - 80) / 40));
    const path = (values) => values.map((value, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" ");
    const grid = [80, 90, 100, 110, 120].map((value) => `<line x1="${pad.left}" x2="${width - pad.right}" y1="${y(value)}" y2="${y(value)}" stroke="currentColor" opacity=".12"/><text x="4" y="${y(value) + 4}" fill="currentColor" opacity=".55" font-size="11">${value}</text>`).join("");
    const labels = series.map((item, index) => index === 0 || index === series.length - 1 ? `<text x="${x(index)}" y="${height - 8}" text-anchor="middle" fill="currentColor" opacity=".55" font-size="11">${escapeHtml(item.date || "")}</text>` : "").join("");
    svg.innerHTML = `${grid}<path d="${path(tech)}" fill="none" stroke="var(--section-ai)" stroke-width="2.5" vector-effect="non-scaling-stroke"/><path d="${path(market)}" fill="none" stroke="var(--section-market)" stroke-width="2.5" vector-effect="non-scaling-stroke"/>${labels}`;
  }

  function normalize(values) {
    const valid = values.filter((value) => value !== null);
    if (!valid.length) return values.map(() => 100);
    const base = valid[0];
    const scale = Math.max(Math.abs(base), Math.max.apply(null, valid.map((value) => Math.abs(value))) * 0.25, 0.001);
    return values.map((value) => {
      if (value === null) return 100;
      return Math.max(80, Math.min(120, 100 + ((value - base) / scale) * 100));
    });
  }

  function average(values) { return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null; }
  function formatNumber(value) { return value === null || value === undefined || Number.isNaN(Number(value)) ? "暂无" : Number(value).toFixed(2); }
  function direction(value) { return value === null || value === undefined ? "数据不足" : value > 0.01 ? "偏强" : value < -0.01 ? "偏弱" : "震荡"; }
  function directionLabel(value) { return ({ positive: "偏强", neutral: "震荡", negative: "偏弱", insufficient_data: "数据不足" })[value] || "未知"; }
  function periodLabel(value) { return ({ week: "最近一周", month: "最近一月", quarter: "最近一季", year: "最近一年" })[value] || value; }
  function escapeHtml(value) { return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char])); }
  function escapeAttr(value) { return escapeHtml(value).replace(/javascript:/gi, ""); }
}());
