(function () {
  "use strict";
  // 创意页：范围（24h/7d/30d）、排序（最佳/最新/多站点）与类型筛选；服务端已按“7 天 · 最佳”渲染。
  const root = document.querySelector("[data-ideas]");
  if (!root) return;
  const list = root.querySelector("[data-idea-list]");
  if (!list) return;
  const cards = Array.from(list.children);
  const empty = root.querySelector("[data-idea-empty]");
  const counts = JSON.parse(root.querySelector("[data-idea-counts]").textContent);
  const hours = { "24h": 24, "7d": 168, "30d": 720 };
  const state = { type: "all", sort: "top", range: "7d" };
  const types = Array.from(root.querySelectorAll("[data-idea-type]")).map((button) => button.dataset.ideaType);

  const params = new URLSearchParams(window.location.search);
  if (types.includes(params.get("type"))) state.type = params.get("type");
  if (hours[params.get("range")]) state.range = params.get("range");

  const num = (card, key) => Number(card.dataset[key]) || 0;
  const order = {
    top: (a, b) => num(b, "final") - num(a, "final") || num(a, "age") - num(b, "age"),
    new: (a, b) => num(a, "age") - num(b, "age") || num(b, "final") - num(a, "final"),
    multi: (a, b) => num(b, "sites") - num(a, "sites") || num(b, "final") - num(a, "final"),
  };

  function apply() {
    const sorted = cards.slice().sort(order[state.sort]);
    let rank = 0;
    sorted.forEach((card) => {
      const show = num(card, "age") <= hours[state.range] && (state.type === "all" || card.dataset.type === state.type);
      card.hidden = !show;
      card.querySelector("[data-idea-rank]").textContent = show ? String(++rank).padStart(2, "0") : "";
      list.appendChild(card);
    });
    if (empty) empty.hidden = rank > 0;
    root.querySelectorAll("[data-type-count]").forEach((el) => {
      const key = el.dataset.typeCount;
      el.textContent = key === "all" ? counts.counts[state.range] : counts.types[state.range][key];
    });
    root.querySelectorAll("[data-idea-type]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.ideaType === state.type)));
    root.querySelectorAll("[data-idea-sort]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.ideaSort === state.sort)));
    root.querySelectorAll("[data-idea-range]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.ideaRange === state.range)));
  }

  function bind(selector, key, attr) {
    root.querySelectorAll(selector).forEach((button) => button.addEventListener("click", () => {
      state[key] = button.dataset[attr];
      if (key !== "sort") {
        const url = new URL(window.location.href);
        const value = state[key];
        if ((key === "type" && value === "all") || (key === "range" && value === "7d")) url.searchParams.delete(key);
        else url.searchParams.set(key, value);
        window.history.replaceState(null, "", url);
      }
      apply();
    }));
  }
  bind("[data-idea-type]", "type", "ideaType");
  bind("[data-idea-sort]", "sort", "ideaSort");
  bind("[data-idea-range]", "range", "ideaRange");
  root.querySelector("[data-idea-controls]").hidden = false;
  apply();
}());
