(function () {
  "use strict";
  const root = document.querySelector(".trends-page");
  if (!root) return;
  const entries = Array.from(root.querySelectorAll("[data-entry]"));
  if (!entries.length) return;
  const details = Array.from(root.querySelectorAll(".topic-detail"));
  const fields = Array.from(root.querySelectorAll("button[data-field]"));
  const kinds = Array.from(root.querySelectorAll("button[data-kind]"));
  const requested = new URLSearchParams(location.search).get("field");
  let field = fields.some((button) => button.dataset.field === requested) ? requested : "all";
  let kind = "all";
  const fromHash = () => {
    try { return decodeURIComponent(location.hash.slice(1)); } catch (_) { return ""; }
  };
  let selected = fromHash();
  root.classList.add("is-enhanced");
  root.querySelector("[data-trends-filters]").hidden = false;

  function apply(updateHash) {
    const visible = entries.filter((entry) => (field === "all" || entry.dataset.field === field) && (kind === "all" || entry.dataset.kind === kind));
    if (!visible.some((entry) => entry.dataset.entry === selected)) selected = visible.length ? visible[0].dataset.entry : "";
    entries.forEach((entry) => {
      entry.hidden = !visible.includes(entry);
      if (entry.dataset.entry === selected) entry.setAttribute("aria-current", "true");
      else entry.removeAttribute("aria-current");
    });
    details.forEach((detail) => { detail.hidden = detail.id !== selected; });
    fields.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.field === field)));
    kinds.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.kind === kind)));
    root.querySelector("[data-filter-empty]").hidden = visible.length > 0;
    if (updateHash) {
      const url = new URL(location.href);
      if (field === "all") url.searchParams.delete("field");
      else url.searchParams.set("field", field);
      url.hash = selected;
      history.replaceState(null, "", url);
    }
  }
  entries.forEach((entry) => entry.addEventListener("click", (event) => {
    event.stopImmediatePropagation();
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    selected = entry.dataset.entry;
    apply(true);
  }, { capture: true }));
  fields.forEach((button) => button.addEventListener("click", () => { field = button.dataset.field; apply(true); }));
  kinds.forEach((button) => button.addEventListener("click", () => { kind = button.dataset.kind; apply(true); }));
  window.addEventListener("hashchange", () => { selected = fromHash(); apply(true); });
  apply(selected !== fromHash());
})();
