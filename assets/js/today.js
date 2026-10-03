(function () {
  "use strict";

  const root = document.querySelector(".today");
  if (!root) return;
  const en = (document.documentElement.lang || "").toLowerCase().startsWith("en");

  // ---- 相对时间：服务端渲染绝对时间作兜底，脚本改成“3 小时前” ----
  const rtf = window.Intl && Intl.RelativeTimeFormat
    ? new Intl.RelativeTimeFormat(en ? "en" : "zh-CN", { numeric: "auto", style: en ? "narrow" : "short" })
    : null;

  function relative(iso) {
    const time = Date.parse(iso);
    if (!rtf || Number.isNaN(time)) return null;
    const seconds = (time - Date.now()) / 1000;
    const abs = Math.abs(seconds);
    if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
    if (abs < 86400 * 7) return rtf.format(Math.round(seconds / 86400), "day");
    return null;
  }

  root.querySelectorAll("time[data-relative]").forEach((el) => {
    const text = relative(el.dateTime);
    if (text) {
      el.title = el.textContent;
      el.textContent = text;
    }
  });
  const updated = root.querySelector("time[data-updated]");
  if (updated && updated.dataset.pattern) {
    const text = relative(updated.dateTime);
    if (text) {
      updated.title = updated.textContent;
      updated.textContent = updated.dataset.pattern.replace("{t}", text);
    }
  }

  // ---- 领域筛选 + 默认只显示前 N 条 ----
  const list = root.querySelector("[data-event-list]");
  if (!list) return;
  const items = Array.from(list.querySelectorAll(".event"));
  const limit = Number(list.dataset.limit) || 10;
  const showAll = root.querySelector("[data-show-all]");
  const empty = root.querySelector("[data-event-empty]");
  const buttons = Array.from(root.querySelectorAll("[data-field-filter] [data-field]"));
  const fields = buttons.map((button) => button.dataset.field);
  const state = { field: "all", expanded: false };

  const requested = new URLSearchParams(window.location.search).get("field");
  if (requested && fields.includes(requested)) state.field = requested;

  function apply() {
    const matching = items.filter((item) => state.field === "all" || item.dataset.field === state.field);
    items.forEach((item) => { item.hidden = true; });
    matching.forEach((item, index) => {
      item.hidden = !state.expanded && index >= limit;
      item.querySelector(".event-rank").textContent = String(index + 1).padStart(2, "0");
    });
    buttons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.field === state.field)));
    if (empty) empty.hidden = matching.length > 0;
    if (showAll) {
      showAll.hidden = matching.length <= limit;
      showAll.textContent = state.expanded
        ? showAll.dataset.labelLess
        : showAll.dataset.labelMore.replace("{n}", matching.length);
      showAll.setAttribute("aria-expanded", String(state.expanded));
    }
  }

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      state.field = button.dataset.field;
      state.expanded = false;
      const url = new URL(window.location.href);
      if (state.field === "all") url.searchParams.delete("field");
      else url.searchParams.set("field", state.field);
      window.history.replaceState(null, "", url);
      apply();
    });
  });

  if (showAll) {
    showAll.addEventListener("click", () => {
      state.expanded = !state.expanded;
      apply();
      if (!state.expanded) list.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }

  apply();
}());
