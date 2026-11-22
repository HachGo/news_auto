/* AI 工业革命观测台：八张 ECharts 图 + 时间轴回放。
   数字、预测表与来源表都已由服务端渲染；本脚本只负责图表，加载失败时页面其余部分仍完整可读。
   约定：颜色跟随实体（指数 / 公司 / 指标）而不是排名；不同单位的量分面绘制，不用双纵轴；
   标签来自数据文件，进入 tooltip 前一律转义。 */
(function () {
  "use strict";
  const root = document.querySelector(".revolution-page");
  const configNode = document.getElementById("revolution-config");
  if (!root || !configNode || !window.echarts) return;
  let config;
  try { config = JSON.parse(configNode.textContent); } catch (_) { return; }
  const L = config.labels || {};
  const lang = config.lang === "en" ? "en" : "zh";
  const locale = lang === "en" ? "en-US" : "zh-CN";
  const T = (obj) => (obj ? obj[lang] || obj.zh || "" : "");
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ESC[c]);
  const fmt = (v, d) => (v == null || !isFinite(v) ? "—" : Number(v).toLocaleString(locale, { maximumFractionDigits: d == null ? 2 : d, minimumFractionDigits: d == null ? 0 : d }));
  const RANGES = { "1y": 1, "3y": 3, "5y": 5, "10y": 10, all: null };
  const INDEX_SLOT = { D: 1, B: 2, S: 3, C: 4 };

  const state = { range: "5y", events: true, data: null, charts: {}, play: { i: null, timer: null }, compare: null, backtest: null, capexView: "amount" };
  try {
    const saved = new URLSearchParams(location.search).get("range") || localStorage.getItem("rev-range");
    if (saved in RANGES) state.range = saved;
  } catch (_) { /* 隐私模式 */ }

  // ---------- 主题 ----------
  function colors() {
    const css = getComputedStyle(root);
    const get = (name) => css.getPropertyValue(name).trim();
    return {
      slot: [null, get("--rev-1"), get("--rev-2"), get("--rev-3"), get("--rev-4")],
      ink: get("--rev-ink"), muted: get("--rev-muted"), line: get("--rev-line"), surface: get("--rev-surface"), model: get("--rev-model"),
      font: getComputedStyle(document.body).fontFamily,
    };
  }
  let C = colors();

  // ---------- 数据 ----------
  async function load() {
    const bust = (url) => url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
    const manifest = await fetch(bust(config.base + "manifest.json")).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
    const entries = await Promise.all(Object.entries(manifest.files).map(([name, info]) =>
      fetch(config.base + info.path + "?v=" + info.sha).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }).then((json) => [name, json])));
    return Object.assign({ manifest }, Object.fromEntries(entries));
  }

  // ---------- 公共选项 ----------
  const day = (s) => (s.length === 7 ? s + "-01" : s);
  function rangeWindow() {
    const years = RANGES[state.range];
    const end = new Date(state.data.indices.as_of).getTime();
    return years == null ? null : { start: end - years * 365.25 * 864e5, end };
  }
  function axisCommon() {
    return {
      axisLine: { lineStyle: { color: C.line } }, axisTick: { show: false },
      axisLabel: { color: C.muted, fontSize: 11, hideOverlap: true }, splitLine: { show: false },
    };
  }
  function valueAxis(extra) {
    return Object.assign({ type: "value", scale: true, axisLabel: { color: C.muted, fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: C.line, width: 1 } }, nameTextStyle: { color: C.muted, fontSize: 11, align: "left" } }, extra || {});
  }
  function timeAxis(extra) {
    return Object.assign({ type: "time" }, axisCommon(), extra || {});
  }
  function zoom(xIndex, full) {
    const win = full ? null : rangeWindow();
    const base = { xAxisIndex: xIndex, filterMode: "filter" };  // 过滤窗口外的点，纵轴随缩放重算
    if (win) Object.assign(base, { startValue: win.start, endValue: win.end });
    return [Object.assign({ type: "inside" }, base),
      Object.assign({ type: "slider", height: 18, bottom: 6, borderColor: C.line, backgroundColor: "transparent", fillerColor: "rgba(127,127,127,0.12)",
        dataBackground: { lineStyle: { color: C.muted, opacity: 0.4 }, areaStyle: { opacity: 0 } }, textStyle: { color: C.muted, fontSize: 10 },
        handleStyle: { color: C.surface, borderColor: C.muted }, moveHandleStyle: { color: C.line } }, base)];
  }
  function tooltip(formatter) {
    return { trigger: "axis", confine: true, backgroundColor: C.surface, borderColor: C.line, textStyle: { color: C.ink, fontSize: 12 },
      axisPointer: { type: "line", lineStyle: { color: C.muted, width: 1 } }, formatter };
  }
  function base(extra) {
    return Object.assign({
      animationDuration: 300, aria: { enabled: true }, textStyle: { fontFamily: C.font },
      legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 14, itemHeight: 3, textStyle: { color: C.muted, fontSize: 12 } },
      grid: { left: 48, right: 64, top: 64, bottom: 48 },
    }, extra);
  }
  // 行：值在前（醒目），系列名在后；用短线作图例键
  function row(color, name, value, extra) {
    return `<div style="display:flex;align-items:center;gap:8px;min-width:180px"><i style="display:inline-block;width:12px;height:2px;background:${color}"></i>` +
      `<strong style="font-family:var(--font-mono)">${esc(value)}</strong><span style="color:${C.muted}">${esc(name)}${extra ? " · " + esc(extra) : ""}</span></div>`;
  }
  // ECharts 把 "YYYY-MM-DD" 按本地时间解析，这里也按本地时间格式化（toISOString 会在东八区错一天）
  const pad = (n) => String(n).padStart(2, "0");
  function dateLabel(value) {
    if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10);
    const d = new Date(value);
    return isNaN(d) ? esc(value) : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }
  function addMonths(iso, k) {
    const total = Number(iso.slice(0, 4)) * 12 + Number(iso.slice(5, 7)) - 1 + k;
    return `${Math.floor(total / 12)}-${pad((total % 12) + 1)}-01`;
  }
  function eventLines() {
    if (!state.events) return [];
    return state.data.events.items.map((e) => ({
      xAxis: e.date, lineStyle: { color: C.muted, width: 1, type: "solid", opacity: 0.45 },
      label: { show: false, formatter: `${e.date}\n${T(e.title)}`, color: C.ink, fontSize: 11, backgroundColor: C.surface, padding: [3, 6], borderColor: C.line, borderWidth: 1 },
      emphasis: { label: { show: true } },
    }));
  }
  function refLine(y, label) {
    return { yAxis: y, lineStyle: { color: C.muted, width: 1, type: "solid", opacity: 0.8 }, label: { show: true, position: "insideStartTop", formatter: label, color: C.muted, fontSize: 10 } };
  }
  const markLines = (data) => ({ symbol: "none", silent: false, animation: false, data });
  const pairs = (rows) => (rows || []).map((r) => [day(r[0]), r[1]]);
  function line(name, data, color, extra) {
    return Object.assign({ name, type: "line", data, showSymbol: false, symbolSize: 8, connectNulls: false, lineStyle: { width: 2, color }, itemStyle: { color },
      emphasis: { focus: "series" } }, extra || {});
  }

  // ---------- 1. 四指数 ----------
  function indicesOption(cut) {
    const d = state.data.indices;
    const n = cut == null ? d.months.length : cut + 1;
    const series = d.order.map((key) => {
      const values = d.indices[key].values;
      const data = d.months.slice(0, n).map((m, i) => [day(m), values[i]]);
      return line(`${key} · ${T(d.meta[key].name)}`, data, C.slot[INDEX_SLOT[key]], {
        endLabel: { show: true, formatter: (p) => `${key} ${fmt(p.value[1], 1)}`, color: C.ink, fontSize: 11, fontFamily: "var(--font-mono)" },
        labelLayout: { moveOverlap: "shiftY" },
      });
    });
    series[0].markLine = markLines([refLine(50, L.rev_avg_line)].concat(eventLines()).concat(cut == null ? [] : [{
      xAxis: day(d.months[cut]), lineStyle: { color: C.ink, width: 1, type: "solid" }, label: { show: true, formatter: d.months[cut], color: C.ink, fontSize: 11 } }]));
    if (cut == null) {
      // 衍生预测：从最后一个读数连到 +1 / +3 月，虚线 = 预测
      d.order.forEach((key) => {
        const values = d.indices[key].values;
        let last = values.length - 1;
        while (last >= 0 && values[last] == null) last--;
        const items = d.derived[key] || [];
        if (last < 0 || !items.length) return;
        const data = [[day(d.months[last]), values[last], null]].concat(items.map((it) => [addMonths(day(d.months[last]), it.months), it.value, it.coverage]));
        series.push(line(`${key} · ${L.rev_tt_derived}`, data, C.slot[INDEX_SLOT[key]], {
          lineStyle: { width: 2, type: "dashed", color: C.slot[INDEX_SLOT[key]] }, showSymbol: true, symbol: "circle", symbolSize: 6, derived: true }));
      });
    }
    return base({
      legend: Object.assign(base({}).legend, { data: series.filter((s) => !s.derived).map((s) => s.name) }),
      tooltip: tooltip((params) => {
        if (!params.length) return "";
        const date = params[0].axisValue;
        const month = dateLabel(date).slice(0, 7);
        const i = d.months.indexOf(month);
        let html = `<div style="color:${C.muted};margin-bottom:4px">${esc(month)}</div>`;
        params.forEach((p) => {
          const key = p.seriesName.slice(0, 1);
          if (p.value[1] == null) return;
          const derived = p.seriesName.includes(L.rev_tt_derived);
          const cov = derived ? p.value[2] : (i >= 0 ? d.indices[key].coverage[i] : null);
          html += row(p.color, p.seriesName, fmt(p.value[1], 1), cov != null ? `${L.rev_tt_coverage} ${Math.round(cov * 100)}%` : "");
        });
        return html;
      }),
      xAxis: timeAxis(), yAxis: valueAxis(), dataZoom: zoom([0]), series,
    });
  }

  function snapshotOption(i) {
    const d = state.data.indices;
    return base({
      legend: { show: false }, grid: { left: 36, right: 16, top: 16, bottom: 28 },
      tooltip: { trigger: "item", confine: true, backgroundColor: C.surface, borderColor: C.line, textStyle: { color: C.ink, fontSize: 12 },
        formatter: (p) => row(p.color, p.name, fmt(p.value, 1), `${L.rev_tt_coverage} ${Math.round((d.indices[p.name].coverage[i] || 0) * 100)}%`) },
      xAxis: { type: "category", data: d.order, axisLine: { lineStyle: { color: C.line } }, axisTick: { show: false }, axisLabel: { color: C.ink, fontFamily: "var(--font-mono)" } },
      yAxis: valueAxis({ min: (v) => Math.min(30, Math.floor(v.min / 5) * 5), max: (v) => Math.max(70, Math.ceil(v.max / 5) * 5) }),
      series: [{ type: "bar", barMaxWidth: 36, data: d.order.map((k) => ({ value: d.indices[k].values[i], itemStyle: { color: C.slot[INDEX_SLOT[k]], borderRadius: [4, 4, 0, 0] } })),
        label: { show: true, position: "top", color: C.ink, fontSize: 11, formatter: (p) => (p.value == null ? L.rev_no_data : fmt(p.value, 1)) },
        markLine: markLines([refLine(50, "50")]) }],
    });
  }

  function setupPlayback() {
    const d = state.data.indices;
    const wrap = root.querySelector("[data-playback]");
    const snap = root.querySelector("[data-snapshot]");
    if (!wrap || !d.months.length) return;
    const scrub = wrap.querySelector("[data-scrub]");
    const label = wrap.querySelector("[data-scrub-label]");
    const button = wrap.querySelector("[data-play]");
    const list = snap.querySelector("[data-snapshot-events]");
    scrub.max = String(d.months.length - 1);
    scrub.value = scrub.max;
    wrap.hidden = false;
    snap.hidden = false;
    make("snapshot");
    function show(i, live) {
      state.play.i = live ? null : i;
      label.textContent = d.months[i];
      state.charts.snapshot.setOption(snapshotOption(i), true);  // 主题切换会重建实例，每次取当前实例
      // 只替换系列，保留用户当前的缩放
      state.charts.indices.setOption({ series: indicesOption(live ? null : i).series }, { replaceMerge: ["series"] });
      const end = day(d.months[i]).slice(0, 7) + "-31";
      const past = state.data.events.items.filter((e) => e.date <= end).slice(-4).reverse();
      list.replaceChildren(...[Object.assign(document.createElement("li"), { textContent: L.rev_events_until })].concat(past.map((e) => {
        const li = document.createElement("li");
        const strong = document.createElement("strong");
        strong.textContent = T(e.title);
        li.append(strong, document.createTextNode(`${e.date} · ${T(state.data.events.types[e.type])}`));
        return li;
      })));
    }
    function stop() {
      clearInterval(state.play.timer);
      state.play.timer = null;
      button.textContent = "▶";
      button.setAttribute("aria-label", L.rev_play);
    }
    scrub.addEventListener("input", () => { stop(); const i = Number(scrub.value); show(i, i === d.months.length - 1); });
    button.addEventListener("click", () => {
      if (state.play.timer) return stop();
      let i = Number(scrub.value);
      if (i >= d.months.length - 1) i = Math.max(0, d.months.length - 1 - 12 * (RANGES[state.range] || 30));
      button.textContent = "❚❚";
      button.setAttribute("aria-label", L.rev_pause);
      state.play.timer = setInterval(() => {
        scrub.value = String(i);
        show(i, i === d.months.length - 1);
        if (++i >= d.months.length) stop();
      }, matchMedia("(prefers-reduced-motion: reduce)").matches ? 600 : 160);
    });
    show(d.months.length - 1, true);
  }

  // ---------- 2. 金融压力（三面板共用时间轴） ----------
  function stressOption() {
    const s = state.data.series.series;
    const ind = state.data.series.indicators;
    const grids = [{ left: 48, right: 64, top: 64, height: "34%" }, { left: 48, right: 64, top: "54%", height: "15%" }, { left: 48, right: 64, top: "76%", height: "14%" }];
    const xAxis = grids.map((_, i) => timeAxis({ gridIndex: i, axisLabel: Object.assign(axisCommon().axisLabel, { show: i === 2 }) }));
    const yAxis = [valueAxis({ gridIndex: 0, name: "σ" }), valueAxis({ gridIndex: 1, name: T(ind.s_vix.name), splitNumber: 2 }),
      valueAxis({ gridIndex: 2, name: T(ind.s_hy.name) + " (pp)", splitNumber: 2 })];
    const series = [
      line(T(ind.s_nfci.name), pairs(s.s_nfci), C.slot[1], { xAxisIndex: 0, yAxisIndex: 0, markLine: markLines([refLine(0, L.rev_threshold)].concat(eventLines())) }),
      line(T(ind.s_stlfsi.name), pairs(s.s_stlfsi), C.slot[2], { xAxisIndex: 0, yAxisIndex: 0 }),
      line(T(ind.s_vix.name), pairs(s.s_vix), C.ink, { xAxisIndex: 1, yAxisIndex: 1, lineStyle: { width: 1.5, color: C.ink } }),
      line(T(ind.s_hy.name), pairs(s.s_hy), C.ink, { xAxisIndex: 2, yAxisIndex: 2, lineStyle: { width: 1.5, color: C.ink } }),
    ];
    return base({
      legend: Object.assign(base({}).legend, { data: [series[0].name, series[1].name] }),
      grid: grids, xAxis, yAxis, series, dataZoom: zoom([0, 1, 2]), axisPointer: { link: [{ xAxisIndex: "all" }] },
      tooltip: tooltip((params) => {
        if (!params.length) return "";
        let html = `<div style="color:${C.muted};margin-bottom:4px">${dateLabel(params[0].axisValue)}</div>`;
        params.forEach((p) => { if (p.value[1] != null) html += row(p.color, p.seriesName, fmt(p.value[1], 2), dateLabel(p.value[0])); });
        return html;
      }),
    });
  }

  // ---------- 3. 资本投入 ----------
  function capexOption() {
    const cx = state.data.series.capex;
    if (state.capexView === "share") {
      const sh = cx.share_gdp;
      const ind = state.data.series.indicators;
      const series = [
        line(T(ind.b_info_equip.name).replace(/（同比）| \(YoY\)/, ""), pairs(sh.info_equip), C.slot[1], { markArea: {
          silent: true, itemStyle: { color: "rgba(127,127,127,0.10)" }, label: { color: C.muted, fontSize: 11, position: "insideTop" },
          data: [[{ name: L.rev_dotcom, xAxis: "1995-01-01" }, { xAxis: "2001-12-31" }]] }, markLine: markLines(eventLines()) }),
        line(T(ind.b_software.name).replace(/（同比）| \(YoY\)/, ""), pairs(sh.software), C.slot[2]),
        line(T(ind.b_capex.name).replace(/（同比）| \(YoY\)/, ""), pairs(sh.hyperscaler), C.slot[3]),
      ].map((s) => Object.assign(s, { endLabel: { show: true, formatter: (p) => fmt(p.value[1], 2) + "%", color: C.ink, fontSize: 11 }, labelLayout: { moveOverlap: "shiftY" } }));
      return base({
        tooltip: tooltip((params) => `<div style="color:${C.muted};margin-bottom:4px">${dateLabel(params[0].axisValue)}</div>` +
          params.map((p) => (p.value[1] == null ? "" : row(p.color, p.seriesName, fmt(p.value[1], 2) + "%"))).join("")),
        xAxis: timeAxis({ min: "1990-01-01" }), yAxis: valueAxis({ name: "% GDP", min: 0 }), series,
        dataZoom: zoom([0], true),  // 与互联网周期对照需要全历史，不受全页时间范围限制
      });
    }
    const totals = Object.fromEntries(cx.total.map((r) => [r[0], r[1]]));
    // ECharts 按数组下标堆叠：各公司起始季度不同、个别季度缺失，必须先对齐到季度并集，缺失处留空（不填补）
    const quarters = Array.from(new Set(cx.companies.flatMap((co) => co.values.map((v) => v[0])))).sort();
    const series = cx.companies.map((co, i) => {
      const byQ = Object.fromEntries(co.values.map((v) => [v[0], v[1]]));
      return { name: co.name, type: "bar", stack: "capex", barMaxWidth: 14, data: quarters.map((q) => [q, byQ[q] == null ? null : byQ[q]]),
        itemStyle: { color: C.slot[i + 1], borderColor: C.surface, borderWidth: 1 }, emphasis: { focus: "series" } };
    });
    series[0].markLine = markLines(eventLines());
    return base({
      tooltip: tooltip((params) => {
        if (!params.length) return "";
        const date = dateLabel(params[0].axisValue);
        const q = `${date.slice(0, 4)}Q${Math.floor((Number(date.slice(5, 7)) - 1) / 3) + 1}`;
        let html = `<div style="color:${C.muted};margin-bottom:4px">${q}</div>`;
        params.forEach((p) => { if (p.value[1] != null) html += row(p.color, p.seriesName, "$" + fmt(p.value[1], 1) + "B"); });
        const total = totals[date];
        html += row(C.ink, L.rev_cap_total, total == null ? L.rev_no_data : "$" + fmt(total, 1) + "B");
        return html;
      }),
      xAxis: timeAxis(), yAxis: valueAxis({ name: "$B", min: 0 }), series, dataZoom: zoom([0]),
    });
  }
  function capexTools(host) {
    const group = document.createElement("div");
    group.className = "horizon-switch";
    group.setAttribute("role", "group");
    [["amount", L.rev_view_amount], ["share", L.rev_view_share]].forEach(([key, text]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = text;
      b.setAttribute("aria-pressed", String(state.capexView === key));
      b.addEventListener("click", () => {
        state.capexView = key;
        group.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        state.charts.capex.setOption(capexOption(), true);
      });
      group.append(b);
    });
    host.append(group);
  }

  // ---------- 4 / 6. 两面板代理指标 ----------
  function twoPanel(idTop, idBottom, zeroTop, zeroBottom) {
    const s = state.data.series.series;
    const ind = state.data.series.indicators;
    const grids = [{ left: 48, right: 64, top: 64, height: "32%" }, { left: 48, right: 64, top: "60%", height: "26%" }];
    const name = (id) => `${T(ind[id].name)}${ind[id].unit && ind[id].unit !== "%" ? " · " + ind[id].unit : ""}`;
    const top = line(name(idTop), pairs(s[idTop]), C.slot[1], { xAxisIndex: 0, yAxisIndex: 0,
      markLine: markLines((zeroTop ? [refLine(0, "0")] : []).concat(eventLines())) });
    const bottom = line(name(idBottom), pairs(s[idBottom]), C.slot[2], { xAxisIndex: 1, yAxisIndex: 1, markLine: zeroBottom ? markLines([refLine(0, "0")]) : undefined });
    return base({
      grid: grids, axisPointer: { link: [{ xAxisIndex: "all" }] },
      xAxis: [timeAxis({ gridIndex: 0, axisLabel: Object.assign(axisCommon().axisLabel, { show: false }) }), timeAxis({ gridIndex: 1 })],
      yAxis: [valueAxis({ gridIndex: 0, name: ind[idTop].unit }), valueAxis({ gridIndex: 1, name: ind[idBottom].unit })],
      series: [top, bottom], dataZoom: zoom([0, 1]),
      tooltip: tooltip((params) => `<div style="color:${C.muted};margin-bottom:4px">${dateLabel(params[0].axisValue)}</div>` +
        params.map((p) => (p.value[1] == null ? "" : row(p.color, p.seriesName, fmt(p.value[1], 2), dateLabel(p.value[0])))).join("")),
    });
  }

  // ---------- 4. 采用扩散（BTOS 两段口径 + 两个代理指标） ----------
  // 90% 抽样置信带：下界 + 带宽堆叠；BTOS 新旧口径措辞不同，分两条画、不连线
  function ciBand(rows, color, stack, xi) {
    const z = 1.645;
    const lo = rows.map((r) => [day(r[0]), r[2] == null ? null : +(r[1] - z * r[2]).toFixed(3)]);
    const width = rows.map((r) => [day(r[0]), r[2] == null ? null : +(2 * z * r[2]).toFixed(3)]);
    const common = { type: "line", stack, stackStrategy: "all", showSymbol: false, silent: true, lineStyle: { opacity: 0 }, xAxisIndex: xi, yAxisIndex: xi, tooltip: { show: false } };
    return [Object.assign({ name: stack + "_lo", data: lo }, common), Object.assign({ name: stack + "_w", data: width, areaStyle: { color, opacity: 0.18 } }, common)];
  }
  function diffusionOption() {
    const s = state.data.series.series;
    const ind = state.data.series.indicators;
    const grids = [{ left: 48, right: 72, top: 64, height: "30%" }, { left: 48, right: 72, top: "52%", height: "16%" }, { left: 48, right: 72, top: "75%", height: "15%" }];
    const btosNew = s.d_btos_ai || [], btosOld = s.d_btos_ai_old || [];
    const label = { show: true, formatter: (p) => fmt(p.value[1], 1) + "%", color: C.ink, fontSize: 11 };
    const series = [
      line(T(ind.d_btos_ai.name), pairs(btosNew), C.slot[1], { xAxisIndex: 0, yAxisIndex: 0, endLabel: label,
        markLine: markLines(eventLines().filter((e) => e.xAxis >= "2023-01-01")) }),
      line(T(ind.d_btos_ai_old.name), pairs(btosOld), C.slot[2], { xAxisIndex: 0, yAxisIndex: 0, endLabel: label }),
      ...ciBand(btosNew, C.slot[1], "ci_new", 0), ...ciBand(btosOld, C.slot[2], "ci_old", 0),
      line(T(ind.d_csd_emp.name), pairs(s.d_csd_emp), C.ink, { xAxisIndex: 1, yAxisIndex: 1, lineStyle: { width: 1.5, color: C.ink },
        markLine: markLines([refLine(0, "0")].concat(eventLines())) }),
      line(T(ind.d_softdev_postings.name), pairs(s.d_softdev_postings), C.ink, { xAxisIndex: 2, yAxisIndex: 2, lineStyle: { width: 1.5, color: C.ink } }),
    ];
    const se = {};
    btosNew.concat(btosOld).forEach((r) => { se[r[0]] = r[2]; });
    return base({
      legend: Object.assign(base({}).legend, { data: [series[0].name, series[1].name] }),
      grid: grids, axisPointer: { link: [{ xAxisIndex: "all" }] },
      xAxis: grids.map((_, i) => timeAxis({ gridIndex: i, axisLabel: Object.assign(axisCommon().axisLabel, { show: i === 2 }) })),
      yAxis: [valueAxis({ gridIndex: 0, name: "%" }), valueAxis({ gridIndex: 1, name: T(ind.d_csd_emp.name), splitNumber: 2 }),
        valueAxis({ gridIndex: 2, name: T(ind.d_softdev_postings.name), splitNumber: 2 })],
      series, dataZoom: zoom([0, 1, 2]),
      tooltip: tooltip((params) => {
        if (!params.length) return "";
        let html = `<div style="color:${C.muted};margin-bottom:4px">${dateLabel(params[0].axisValue)}</div>`;
        params.forEach((p) => {
          if (p.value[1] == null || p.seriesName.startsWith("ci_")) return;
          const d = dateLabel(p.value[0]);
          const ci = se[d] != null && p.seriesIndex < 2 ? `90%: ${fmt(p.value[1] - 1.645 * se[d], 1)}–${fmt(p.value[1] + 1.645 * se[d], 1)}` : d;
          html += row(p.color, p.seriesName, fmt(p.value[1], 1) + (p.seriesIndex < 2 ? "%" : ""), ci);
        });
        return html;
      }),
    });
  }

  // ---------- 5. 能力与算力 ----------
  function capabilityOption() {
    const cap = state.data.series.capability;
    return base({
      tooltip: { trigger: "item", confine: true, backgroundColor: C.surface, borderColor: C.line, textStyle: { color: C.ink, fontSize: 12 },
        formatter: (p) => {
          if (p.seriesType === "line") return row(p.color, L.rev_tt_frontier, `10^${fmt(p.value[1], 1)} FLOP`, dateLabel(p.value[0]));
          const [date, v, model, org] = p.value;
          return `<div style="color:${C.muted};margin-bottom:4px">${esc(date)}</div>${row(p.color, model, `10^${fmt(v, 1)} FLOP`, org)}`;
        } },
      xAxis: timeAxis(), yAxis: valueAxis({ name: "log10 FLOP", axisLabel: { color: C.muted, fontSize: 11, formatter: (v) => `1e${v}` } }),
      series: [
        { name: L.rev_tt_models, type: "scatter", data: cap.models, symbolSize: 7, itemStyle: { color: C.slot[1], opacity: 0.55, borderColor: C.surface, borderWidth: 1 },
          emphasis: { scale: 1.6, itemStyle: { opacity: 1 } }, markLine: markLines(eventLines()) },
        line(L.rev_tt_frontier, pairs(cap.frontier), C.ink, { step: "end", lineStyle: { width: 1.5, color: C.ink } }),
      ],
      dataZoom: zoom([0]),
    });
  }

  // ---------- 7. 多指标对比（z 值，同一纵轴） ----------
  function compareChoices() {
    const ind = state.data.series.indicators;
    const s = state.data.series.series;
    const list = state.data.indices.order.map((k) => ({ id: "idx_" + k, name: `${k} · ${T(state.data.indices.meta[k].name)}`, kind: "index" }));
    return list.concat(Object.keys(ind).filter((id) => (s[id] || []).length).map((id) => ({ id, name: T(ind[id].name), kind: ind[id].kind })));
  }
  function compareSeries(id) {
    if (id.startsWith("idx_")) {
      const k = id.slice(4);
      const d = state.data.indices;
      return d.months.map((m, i) => [day(m), d.indices[k].values[i]]).filter((p) => p[1] != null);
    }
    return pairs(state.data.series.series[id]);
  }
  function zscore(rows) {
    const xs = rows.map((r) => r[1]).filter((v) => v != null);
    const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
    const sd = Math.sqrt(xs.reduce((a, b) => a + (b - mean) * (b - mean), 0) / xs.length) || 1;
    return rows.map((r) => [r[0], r[1] == null ? null : +((r[1] - mean) / sd).toFixed(3), r[1]]);
  }
  function compareOption() {
    const choices = Object.fromEntries(compareChoices().map((c) => [c.id, c]));
    const series = state.compare.selected.map(({ id, slot }) => line(choices[id].name, zscore(compareSeries(id)), C.slot[slot], {
      endLabel: { show: true, formatter: (p) => fmt(p.value[1], 1), color: C.ink, fontSize: 11 }, labelLayout: { moveOverlap: "shiftY" } }));
    if (series[0]) series[0].markLine = markLines([refLine(0, "0")].concat(eventLines()));
    return base({
      tooltip: tooltip((params) => `<div style="color:${C.muted};margin-bottom:4px">${dateLabel(params[0].axisValue)}</div>` +
        params.map((p) => (p.value[1] == null ? "" : row(p.color, p.seriesName, `${fmt(p.value[1], 2)}σ`, `${fmt(p.value[2], 2)} · ${dateLabel(p.value[0])}`))).join("")),
      xAxis: timeAxis(), yAxis: valueAxis({ name: L.rev_zscore }), series, dataZoom: zoom([0]),
    });
  }
  function compareTools(host) {
    const choices = compareChoices();
    const defaults = ["b_capex", "s_nfci", "c_semis_ip"].filter((id) => choices.some((c) => c.id === id));
    state.compare = { selected: defaults.map((id, i) => ({ id, slot: i + 1 })) };
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = `${L.rev_select_series}（${L.rev_compare_max}）`;
    summary.style.cursor = "pointer";
    const box = document.createElement("div");
    box.className = "rev-chart-tools";
    box.style.marginTop = "8px";
    const inputs = [];
    function sync() {
      const chosen = new Set(state.compare.selected.map((s) => s.id));
      inputs.forEach(({ input, label, id }) => {
        input.checked = chosen.has(id);
        input.disabled = !input.checked && chosen.size >= 4;
        const sel = state.compare.selected.find((s) => s.id === id);
        label.style.setProperty("--swatch", sel ? C.slot[sel.slot] : "transparent");
      });
    }
    choices.forEach((c) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      const swatch = document.createElement("i");
      label.append(input, swatch, document.createTextNode(c.name));
      input.addEventListener("change", () => {
        if (input.checked) {
          const used = new Set(state.compare.selected.map((s) => s.slot));
          const slot = [1, 2, 3, 4].find((x) => !used.has(x));  // 槽位跟随指标，取消选择不会让其余指标换色
          if (slot) state.compare.selected.push({ id: c.id, slot });
        } else {
          state.compare.selected = state.compare.selected.filter((s) => s.id !== c.id);
        }
        sync();
        state.charts.compare.setOption(compareOption(), true);
      });
      inputs.push({ input, label, id: c.id });
      box.append(label);
    });
    details.append(summary, box);
    host.append(details);
    sync();
  }

  // ---------- 8. 预测回测 ----------
  function backtestChoices() {
    const out = [];
    state.data.forecasts.items.forEach((fc) => fc.horizons.forEach((h, j) => out.push({ key: `${fc.id}|${h.h}`, fc, h, label: `${T(fc.name)} · h=${h.h}` })));
    return out;
  }
  function backtestOption() {
    const choice = backtestChoices().find((c) => c.key === state.backtest);
    if (!choice) return base({ series: [] });
    const { fc, h } = choice;
    const path = h.path || [];
    const used = h.source === "model" ? C.slot[2] : C.slot[1];
    const actual = pairs(state.data.series.series[fc.id]).filter((p) => p[0] >= (path[0] ? path[0][0] : "1990-01-01"));
    const lo = path.map((p) => [p[0], p[4]]);
    const band = path.map((p) => [p[0], p[4] == null || p[5] == null ? null : +(p[5] - p[4]).toFixed(4)]);
    const series = [
      // 区间下界可能为负：stackStrategy "all" 才会把带宽叠在下界上（默认只叠同号值）
      { name: L.rev_tt_interval, type: "line", data: lo, stack: "band", stackStrategy: "all", lineStyle: { opacity: 0 }, showSymbol: false, silent: true, tooltip: { show: false } },
      { name: L.rev_tt_interval, type: "line", data: band, stack: "band", stackStrategy: "all", lineStyle: { opacity: 0 }, showSymbol: false, areaStyle: { color: used, opacity: 0.14 }, silent: true },
      line(L.rev_tt_actual, actual, C.ink, { markLine: markLines((h.event ? [refLine(h.event.above, L.rev_threshold)] : []).concat(eventLines())) }),
      line(L.rev_tt_baseline, path.map((p) => [p[0], p[2]]), C.slot[1], { lineStyle: { width: 1.5, type: "dashed", color: C.slot[1] } }),
      line(L.rev_tt_model, path.map((p) => [p[0], p[3]]), C.slot[2], { lineStyle: { width: 1.5, type: "dashed", color: C.slot[2] } }),
    ];
    if (fc.last) {
      const origin = [fc.last.date, fc.last.value];
      series.push(line(L.rev_tt_now, [origin, [h.target, h.point]], C.model, { showSymbol: true, symbolSize: 8, lineStyle: { width: 2, type: "dashed", color: C.model } }));
      if (h.q) {
        series.push({ name: L.rev_tt_now, type: "line", data: [origin, [h.target, h.q[0]]], stack: "now", stackStrategy: "all", lineStyle: { opacity: 0 }, showSymbol: false, silent: true, tooltip: { show: false } });
        series.push({ name: L.rev_tt_now, type: "line", data: [[origin[0], 0], [h.target, +(h.q[1] - h.q[0]).toFixed(4)]], stack: "now", stackStrategy: "all", lineStyle: { opacity: 0 },
          showSymbol: false, areaStyle: { color: C.model, opacity: 0.18 }, silent: true, tooltip: { show: false } });
      }
    }
    const byDate = Object.fromEntries(path.map((p) => [p[0], p]));
    return base({
      legend: Object.assign(base({}).legend, { data: [L.rev_tt_actual, L.rev_tt_baseline, L.rev_tt_model, L.rev_tt_now] }),
      tooltip: tooltip((params) => {
        if (!params.length) return "";
        const date = dateLabel(params[0].axisValue);
        const p = byDate[date];
        let html = `<div style="color:${C.muted};margin-bottom:4px">${esc(date)} · ${esc(fc.unit)}</div>`;
        params.forEach((x) => { if (x.seriesName !== L.rev_tt_interval && x.seriesName !== L.rev_tt_now && x.value[1] != null) html += row(x.color, x.seriesName, fmt(x.value[1], 2)); });
        if (p && p[4] != null) html += row(used, L.rev_tt_interval, `${fmt(p[4], 2)} ~ ${fmt(p[5], 2)}`);
        if (date === h.target) html += row(C.model, L.rev_tt_now, `${fmt(h.point, 2)}${h.q ? ` (${fmt(h.q[0], 2)} ~ ${fmt(h.q[1], 2)})` : ""}`);
        return html;
      }),
      xAxis: timeAxis(), yAxis: valueAxis({ name: fc.unit }), series, dataZoom: zoom([0]),
    });
  }
  function backtestTools(host) {
    const choices = backtestChoices();
    if (!choices.length) return;
    state.backtest = (choices.find((c) => c.fc.id === "s_nfci" && c.h.h === 13) || choices[0]).key;
    const select = document.createElement("select");
    select.setAttribute("aria-label", L.rev_select_forecast);
    choices.forEach((c) => select.append(new Option(c.label, c.key, false, c.key === state.backtest)));
    const status = document.createElement("span");
    status.className = "kind-chip";
    function sync() {
      const c = choices.find((x) => x.key === state.backtest);
      status.className = "kind-chip" + (c.h.status === "model" ? " kind-model" : "");
      status.textContent = `${L["rev_status_" + c.h.status]} · n=${c.h.backtest.n} · ${fmt(c.h.backtest.skill, 1)}%`;
    }
    select.addEventListener("change", () => { state.backtest = select.value; sync(); state.charts.backtest.setOption(backtestOption(), true); });
    host.append(select, status);
    sync();
  }

  // ---------- 装配 ----------
  const BUILDERS = {
    indices: () => indicesOption(state.play.i),
    stress: stressOption,
    capex: capexOption,
    diffusion: diffusionOption,
    capability: capabilityOption,
    semis: () => twoPanel("s_sox_heat", "c_semis_ip", true, true),
    compare: compareOption,
    backtest: backtestOption,
  };
  const TOOLS = { capex: capexTools, compare: compareTools, backtest: backtestTools };

  function make(id) {
    const node = root.querySelector(`[data-chart="${id}"]`);
    if (!node) return null;
    const existing = echarts.getInstanceByDom(node);
    if (existing) existing.dispose();
    const chart = echarts.init(node, null, { renderer: "canvas", locale: lang === "en" ? "EN" : "ZH" });
    state.charts[id] = chart;
    if (!node.dataset.observed && window.ResizeObserver) {
      new ResizeObserver(() => { const c = echarts.getInstanceByDom(node); if (c) c.resize(); }).observe(node);
      node.dataset.observed = "1";
    }
    return chart;
  }
  // 多面板图：过滤模式下各面板会按自己的数据范围定横轴（如 BTOS 2023 年才开始、高收益债只有 3 年），
  // 统一为所有面板数据的并集，竖直方向才对得齐
  function alignPanels(option) {
    if (!Array.isArray(option.xAxis) || option.xAxis.length < 2) return option;
    let lo = Infinity, hi = -Infinity;
    option.series.forEach((s) => (s.data || []).forEach((d) => {
      const t = Array.isArray(d) && d[1] != null ? new Date(d[0]).getTime() : NaN;
      if (!isNaN(t)) { lo = Math.min(lo, t); hi = Math.max(hi, t); }
    }));
    if (isFinite(lo)) option.xAxis.forEach((x) => Object.assign(x, { min: lo, max: hi }));
    return option;
  }
  function render(id) {
    const chart = make(id);
    if (!chart) return;
    try {
      chart.setOption(alignPanels(BUILDERS[id]()), true);
    } catch (err) {
      console.error("revolution chart", id, err);
      chart.dispose();
      const node = root.querySelector(`[data-chart="${id}"]`);
      node.replaceChildren(Object.assign(document.createElement("p"), { className: "rev-chart-error", textContent: L.rev_load_failed }));
    }
  }
  function renderAll() {
    Object.keys(BUILDERS).forEach(render);
    if (state.data && root.querySelector("[data-snapshot]") && !root.querySelector("[data-snapshot]").hidden) {
      const scrub = root.querySelector("[data-scrub]");
      const i = Number(scrub.value);
      const snap = make("snapshot");
      snap.setOption(snapshotOption(i), true);
    }
  }
  function applyRange() {
    const win = rangeWindow();
    Object.entries(state.charts).forEach(([id, chart]) => {
      if (id === "snapshot" || (id === "capex" && state.capexView === "share")) return;
      chart.dispatchAction(win ? { type: "dataZoom", startValue: win.start, endValue: win.end } : { type: "dataZoom", start: 0, end: 100 });
    });
  }

  function setupFilters() {
    const bar = root.querySelector("[data-rev-filters]");
    if (!bar) return;
    bar.hidden = false;
    bar.querySelectorAll("[data-range]").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.range === state.range));
      b.addEventListener("click", () => {
        state.range = b.dataset.range;
        bar.querySelectorAll("[data-range]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        try { localStorage.setItem("rev-range", state.range); } catch (_) { /* 忽略 */ }
        applyRange();
      });
    });
    const toggle = bar.querySelector("[data-events]");
    toggle.addEventListener("change", () => { state.events = toggle.checked; renderAll(); applyRange(); });
  }

  const canvases = root.querySelectorAll(".rev-canvas");
  canvases.forEach((n) => n.classList.add("is-loading"));
  load().then((data) => {
    state.data = data;
    canvases.forEach((n) => n.classList.remove("is-loading"));
    Object.entries(TOOLS).forEach(([id, fn]) => { const host = root.querySelector(`[data-tools="${id}"]`); if (host) fn(host); });
    setupFilters();
    renderAll();
    setupPlayback();
    // 主题切换：重新取色并重绘（深色是单独选定的色阶，不是自动反色）
    new MutationObserver(() => { C = colors(); renderAll(); })
      .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }).catch((err) => {
    console.error("revolution data", err);
    canvases.forEach((n) => {
      n.classList.remove("is-loading");
      n.replaceChildren(Object.assign(document.createElement("p"), { className: "rev-chart-error", textContent: L.rev_load_failed }));
    });
  });
})();
