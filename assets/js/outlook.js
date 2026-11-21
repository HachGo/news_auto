/* 趋势与预测页：周 / 月 / 季度切换 + 资产走势图（历史收盘 + 预测扇形，内联 SVG）。
   数字与区间已由服务端渲染；脚本只负责切换和画图，失败时页面仍完整可读。 */
(function () {
  "use strict";
  const root = document.querySelector(".trends-page");
  const configNode = document.getElementById("outlook-config");
  if (!root || !configNode) return;
  let config;
  try { config = JSON.parse(configNode.textContent); } catch (_) { return; }
  const NS = "http://www.w3.org/2000/svg";
  const WINDOW = { week: 40, month: 84, quarter: 252 };  // 历史可见交易日数：约为周期的 4–8 倍，预测区占图宽约五分之一
  const HORIZONS = ["week", "month", "quarter"];
  const buttons = Array.from(root.querySelectorAll("[data-set-horizon]"));
  let data = null;
  let horizon = "month";
  try {
    const saved = new URLSearchParams(location.search).get("h") || localStorage.getItem("outlook-horizon");
    if (HORIZONS.includes(saved)) horizon = saved;
  } catch (_) { /* 隐私模式下 localStorage 不可用 */ }

  function setHorizon(next, remember) {
    horizon = next;
    root.dataset.horizon = next;
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.setHorizon === next)));
    if (remember) {
      try { localStorage.setItem("outlook-horizon", next); } catch (_) { /* 忽略 */ }
    }
    drawAll();
  }
  buttons.forEach((b) => b.addEventListener("click", () => setHorizon(b.dataset.setHorizon, true)));

  const lang = config.lang === "en" ? "en-US" : "zh-CN";
  function fmt(value) {
    const digits = Math.abs(value) >= 1000 ? 0 : Math.abs(value) >= 100 ? 1 : 2;
    return value.toLocaleString(lang, { maximumFractionDigits: digits, minimumFractionDigits: digits });
  }
  function niceTicks(lo, hi, count) {
    const raw = (hi - lo) / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
    return ticks;
  }
  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    if (parent) parent.appendChild(node);
    return node;
  }

  function draw(container, asset, key) {
    const spec = asset.horizons[key];
    if (!spec) return;
    const hist = asset.series.slice(-WINDOW[key]);
    const fan = spec.fan;
    const n = hist.length;
    const total = n - 1 + fan[fan.length - 1].k;
    const width = Math.max(240, container.clientWidth);
    const height = 150;
    const pad = { l: 8, r: 52, t: 10, b: 22 };
    const values = hist.map((p) => p[1]).concat(fan.map((p) => p.lo), fan.map((p) => p.hi));
    let lo = Math.min.apply(null, values);
    let hi = Math.max.apply(null, values);
    const margin = (hi - lo) * 0.06 || hi * 0.01;
    lo -= margin; hi += margin;
    const x = (i) => pad.l + (i / total) * (width - pad.l - pad.r);
    const y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (height - pad.t - pad.b);

    container.textContent = "";
    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "outlook-svg", "aria-hidden": "true" }, container);
    niceTicks(lo, hi, 3).forEach((v) => {
      el("line", { x1: pad.l, x2: width - pad.r, y1: y(v), y2: y(v), class: "grid" }, svg);
      const t = el("text", { x: width - pad.r + 6, y: y(v) + 3, class: "tick" }, svg);
      t.textContent = fmt(v);
    });
    const today = x(n - 1);
    el("line", { x1: today, x2: today, y1: pad.t, y2: height - pad.b, class: "today" }, svg);
    // 预测扇形（80% 区间）与中位数
    const upper = fan.map((p) => `${x(n - 1 + p.k)},${y(p.hi)}`);
    const lower = fan.slice().reverse().map((p) => `${x(n - 1 + p.k)},${y(p.lo)}`);
    el("polygon", { points: upper.concat(lower).join(" "), class: "fan" }, svg);
    el("polyline", { points: fan.map((p) => `${x(n - 1 + p.k)},${y(p.mid)}`).join(" "), class: "median" }, svg);
    el("polyline", { points: hist.map((p, i) => `${x(i)},${y(p[1])}`).join(" "), class: "history" }, svg);
    el("circle", { cx: today, cy: y(hist[n - 1][1]), r: 4, class: "end-dot" }, svg);
    [[pad.l, hist[0][0], "start"], [today - 4, hist[n - 1][0], "end"], [width - pad.r, fan[fan.length - 1].d, "end"]].forEach(([px, label, anchor]) => {
      const t = el("text", { x: px, y: height - 6, class: "tick", "text-anchor": anchor }, svg);
      t.textContent = key === "quarter" && anchor === "start" ? label : label.slice(5);  // 季度视图跨年，起点带年份
    });

    // 悬停：十字线吸附到最近的交易日（历史）或预测节点
    const cross = el("line", { y1: pad.t, y2: height - pad.b, class: "cross", visibility: "hidden" }, svg);
    const tip = document.createElement("div");
    tip.className = "outlook-tip";
    tip.hidden = true;
    container.appendChild(tip);
    function show(index) {
      let px, rows;
      if (index <= n - 1) {
        const p = hist[Math.max(0, index)];
        px = x(Math.max(0, index));
        rows = [[p[0], ""], [fmt(p[1]), config.labels.close]];
      } else {
        const p = fan.reduce((best, f) => Math.abs(n - 1 + f.k - index) < Math.abs(n - 1 + best.k - index) ? f : best, fan[0]);
        px = x(n - 1 + p.k);
        rows = [[`${p.d} · ${config.labels.forecast}`, ""], [fmt(p.mid), config.labels.median], [`${fmt(p.lo)} – ${fmt(p.hi)}`, config.labels.range]];
      }
      cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
      tip.textContent = "";
      rows.forEach(([value, label], i) => {
        const row = document.createElement("div");
        const strong = document.createElement(i === 0 ? "span" : "strong");
        strong.textContent = value;
        row.appendChild(strong);
        if (label) { const s = document.createElement("small"); s.textContent = label; row.appendChild(s); }
        tip.appendChild(row);
      });
      tip.hidden = false;
      const left = Math.min(Math.max(px + 10, 0), width - tip.offsetWidth - 4);
      tip.style.left = `${px > width * 0.6 ? Math.max(0, px - tip.offsetWidth - 10) : left}px`;
    }
    function hide() { cross.setAttribute("visibility", "hidden"); tip.hidden = true; }
    let current = n - 1;
    svg.addEventListener("pointermove", (event) => {
      const rect = svg.getBoundingClientRect();
      const ratio = (event.clientX - rect.left - pad.l) / (rect.width - pad.l - pad.r);
      current = Math.round(Math.min(1, Math.max(0, ratio)) * total);
      show(current);
    });
    svg.addEventListener("pointerleave", hide);
    container.tabIndex = 0;
    container.onkeydown = (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      current = Math.min(total, Math.max(0, current + (event.key === "ArrowRight" ? 1 : -1)));
      show(current);
    };
    container.onblur = hide;
  }

  function drawAll() {
    if (!data) return;
    root.querySelectorAll(`[data-chart][data-horizon="${horizon}"]`).forEach((node) => {
      const asset = data.get(node.dataset.chart);
      if (asset) draw(node, asset, horizon);
    });
  }

  setHorizon(horizon, false);
  fetch(config.src, { credentials: "same-origin" })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((payload) => {
      data = new Map(payload.assets.map((a) => [a.key, a]));
      root.classList.add("has-charts");
      drawAll();
    })
    .catch(() => { /* 图表数据加载失败时保留服务端渲染的数字 */ });
  let timer;
  window.addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(drawAll, 150); });
})();
