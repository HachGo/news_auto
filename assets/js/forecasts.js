(function () {
  "use strict";
  const root = document.querySelector(".forecasts-page");
  if (!root) return;
  const tabs = Array.from(root.querySelectorAll("[data-forecast-tab]"));
  const sections = Array.from(root.querySelectorAll(".forecast-section"));
  root.classList.add("is-enhanced");
  function select(id, updateHash) {
    if (!sections.some((section) => section.id === id)) id = "open";
    sections.forEach((section) => { section.hidden = section.id !== id; });
    tabs.forEach((tab) => {
      if (tab.dataset.forecastTab === id) tab.setAttribute("aria-current", "true");
      else tab.removeAttribute("aria-current");
    });
    if (updateHash) history.replaceState(null, "", `#${id}`);
  }
  tabs.forEach((tab) => tab.addEventListener("click", (event) => {
    event.stopImmediatePropagation();
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    select(tab.dataset.forecastTab, true);
  }, { capture: true }));
  window.addEventListener("hashchange", () => select(location.hash.slice(1), false));
  select(location.hash.slice(1), false);
})();
