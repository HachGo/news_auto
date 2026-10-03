(function () {
  "use strict";
  // 实验室：选择跟踪器（与网址锚点同步），点击实体卡片筛选时间线。
  const root = document.querySelector("[data-lab]");
  if (!root) return;
  const cards = Array.from(root.querySelectorAll("[data-tracker]"));
  const details = Array.from(root.querySelectorAll("[data-lab-detail]"));
  if (!details.length) return;
  root.classList.add("is-enhanced");

  function select(id, updateHash) {
    if (!details.some((detail) => detail.id === id)) id = details[0].id;
    details.forEach((detail) => { detail.hidden = detail.id !== id; });
    cards.forEach((card) => {
      if (card.dataset.tracker === id) card.setAttribute("aria-current", "true");
      else card.removeAttribute("aria-current");
    });
    if (updateHash) history.replaceState(null, "", `#${id}`);
  }
  cards.forEach((card) => card.addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    select(card.dataset.tracker, true);
  }));
  window.addEventListener("hashchange", () => select(location.hash.slice(1), false));

  details.forEach((detail) => {
    const buttons = Array.from(detail.querySelectorAll("[data-entity]"));
    const items = Array.from(detail.querySelectorAll(".lab-timeline li"));
    const showing = detail.querySelector("[data-lab-showing]");
    let current = null;
    function filter(id) {
      current = current === id ? null : id;
      buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.entity === current)));
      items.forEach((item) => { item.hidden = !!current && !item.dataset.entities.split(" ").includes(current); });
      if (showing) {
        showing.hidden = !current;
        const active = buttons.find((b) => b.dataset.entity === current);
        showing.querySelector("[data-lab-filter-name]").textContent = active ? active.querySelector("strong").textContent : "";
      }
    }
    buttons.forEach((button) => button.addEventListener("click", () => filter(button.dataset.entity)));
    const clear = detail.querySelector("[data-lab-clear]");
    if (clear) clear.addEventListener("click", () => filter(current));
  });
  select(location.hash.slice(1), false);
}());
