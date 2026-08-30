const sidebar = document.querySelector("#paper-sidebar");

function setYearExpanded(yearArchive, expanded) {
  if (!yearArchive) return;
  const yearToggle = yearArchive.querySelector(".archive-year-toggle");
  const content = yearArchive.querySelector(".archive-year-content");
  yearArchive.dataset.expanded = String(expanded);
  yearToggle?.setAttribute("aria-expanded", String(expanded));
  content?.setAttribute("aria-hidden", String(!expanded));
}

function revealMonthTab(tab) {
  const tablist = tab?.parentElement;
  if (!tablist) return;
  const tabRect = tab.getBoundingClientRect();
  const tablistRect = tablist.getBoundingClientRect();
  if (tabRect.left < tablistRect.left) {
    tablist.scrollLeft -= tablistRect.left - tabRect.left;
  } else if (tabRect.right > tablistRect.right) {
    tablist.scrollLeft += tabRect.right - tablistRect.right;
  }
}

function selectMonth(tab, { updateHash = false, focus = false } = {}) {
  const targetId = tab?.dataset.monthTarget;
  const yearArchive = tab?.closest("[data-archive-year]");
  if (!targetId || !yearArchive || tab.disabled) return;

  yearArchive.querySelectorAll("[data-month-target]").forEach((candidate) => {
    const selected = candidate === tab;
    candidate.setAttribute("aria-selected", String(selected));
    candidate.tabIndex = selected ? 0 : -1;
  });
  yearArchive.querySelectorAll(".archive-month-panel").forEach((panel) => {
    const active = panel.id === targetId;
    panel.dataset.active = String(active);
    panel.setAttribute("aria-hidden", String(!active));
  });
  setYearExpanded(yearArchive, true);
  revealMonthTab(tab);

  if (updateHash) window.history.replaceState(null, "", `#${targetId}`);
  if (focus) tab.focus();
}

document.querySelectorAll("[data-archive-year]").forEach((yearArchive) => {
  const yearToggle = yearArchive.querySelector(".archive-year-toggle");
  setYearExpanded(yearArchive, yearArchive.dataset.expanded === "true");
  yearToggle?.addEventListener("click", () => {
    setYearExpanded(yearArchive, yearArchive.dataset.expanded !== "true");
  });

  const tabs = [...yearArchive.querySelectorAll("[data-month-target]")];
  const selectedTab = tabs.find((tab) => tab.getAttribute("aria-selected") === "true");
  window.requestAnimationFrame(() => revealMonthTab(selectedTab));
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => selectMonth(tab, { updateHash: true }));
    tab.addEventListener("keydown", (event) => {
      const currentIndex = tabs.indexOf(tab);
      let nextIndex = null;
      if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
      if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabs.length - 1;
      if (nextIndex === null) return;
      event.preventDefault();
      selectMonth(tabs[nextIndex], { updateHash: true, focus: true });
    });
  });
});

function revealHashTarget({ scroll = false } = {}) {
  const id = decodeURIComponent(window.location.hash.slice(1));
  if (!id) return;
  const target = document.getElementById(id);
  if (!target) return;

  const monthPanel = target.matches(".archive-month-panel")
    ? target
    : target.closest(".archive-month-panel");
  if (monthPanel) {
    const tab = document.querySelector(`[data-month-target="${monthPanel.id}"]`);
    selectMonth(tab);
  }
  setYearExpanded(target.closest("[data-archive-year]"), true);

  let parent = target;
  while (parent) {
    if (parent.tagName === "DETAILS") parent.open = true;
    parent = parent.parentElement;
  }
  if (scroll) {
    window.requestAnimationFrame(() => target.scrollIntoView({ block: "start" }));
  }
}

document.querySelectorAll("[data-sidebar-action]").forEach((button) => {
  button.addEventListener("click", () => {
    const shouldOpen = button.dataset.sidebarAction === "expand";
    sidebar.querySelectorAll("details").forEach((details) => { details.open = shouldOpen; });
  });
});

window.addEventListener("hashchange", () => revealHashTarget({ scroll: true }));
revealHashTarget({ scroll: true });

const summaryDialog = document.querySelector("#summary-dialog");
const summaryDialogTitle = summaryDialog?.querySelector("#summary-dialog-title");
const summaryDialogContent = summaryDialog?.querySelector("[data-summary-content]");
const summaryDocumentCache = new Map();
let summaryTrigger = null;

function setSummaryDialogContent(markup, { error = false } = {}) {
  if (!summaryDialogContent) return;
  summaryDialogContent.classList.toggle("has-error", error);
  summaryDialogContent.innerHTML = markup;
}

async function loadSummaryDocument(link) {
  const sourceUrl = new URL(link.dataset.summaryUrl || link.href, window.location.href);
  sourceUrl.hash = "";
  const cacheKey = sourceUrl.href;
  if (!summaryDocumentCache.has(cacheKey)) {
    const request = fetch(cacheKey, { headers: { Accept: "text/html" } })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then((documentText) => new DOMParser().parseFromString(documentText, "text/html"));
    summaryDocumentCache.set(cacheKey, request);
    request.catch(() => summaryDocumentCache.delete(cacheKey));
  }
  return summaryDocumentCache.get(cacheKey);
}

async function openSummaryDialog(link) {
  if (!summaryDialog?.showModal || !summaryDialogContent) return;
  summaryTrigger = link;
  const paperTitle = link.closest("tr")?.querySelector(".paper-title")?.textContent?.trim();
  if (summaryDialogTitle) summaryDialogTitle.textContent = paperTitle || "论文要点";
  setSummaryDialogContent('<p class="muted">正在加载…</p>');
  summaryDialog.showModal();

  try {
    const parsed = await loadSummaryDocument(link);
    const articleId = link.dataset.summaryId || new URL(link.href).hash.slice(1);
    const article = parsed.getElementById(articleId);
    if (!article) throw new Error("Summary content is missing");
    setSummaryDialogContent(article.innerHTML);
  } catch (error) {
    setSummaryDialogContent(
      '<p>要点加载失败，请稍后重试，或使用链接直接打开总结页面。</p>',
      { error: true },
    );
  }
}

document.addEventListener("click", (event) => {
  const link = event.target.closest("[data-summary-url]");
  if (!link || !summaryDialog?.showModal) return;
  event.preventDefault();
  openSummaryDialog(link);
});

summaryDialog?.querySelector("[data-summary-close]")?.addEventListener("click", () => {
  summaryDialog.close();
});

summaryDialog?.addEventListener("click", (event) => {
  if (event.target === summaryDialog) summaryDialog.close();
});

summaryDialog?.addEventListener("close", () => {
  summaryTrigger?.focus();
  summaryTrigger = null;
});

document.querySelectorAll("[data-drag-scroll]").forEach((viewport) => {
  let pointerId = null;
  let startX = 0;
  let startScrollLeft = 0;

  function finishDrag() {
    if (pointerId !== null && viewport.hasPointerCapture?.(pointerId)) {
      viewport.releasePointerCapture(pointerId);
    }
    pointerId = null;
    viewport.classList.remove("is-dragging");
  }

  viewport.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("a, button")) return;
    pointerId = event.pointerId;
    startX = event.clientX;
    startScrollLeft = viewport.scrollLeft;
    viewport.setPointerCapture?.(pointerId);
    viewport.classList.add("is-dragging");
  });

  viewport.addEventListener("pointermove", (event) => {
    if (event.pointerId !== pointerId) return;
    viewport.scrollLeft = startScrollLeft - (event.clientX - startX);
  });

  viewport.addEventListener("pointerup", finishDrag);
  viewport.addEventListener("pointercancel", finishDrag);

  viewport.addEventListener("keydown", (event) => {
    const amount = Math.max(220, viewport.clientWidth * .6);
    if (event.key === "ArrowRight") viewport.scrollBy({ left: amount, behavior: "smooth" });
    else if (event.key === "ArrowLeft") viewport.scrollBy({ left: -amount, behavior: "smooth" });
    else if (event.key === "Home") viewport.scrollTo({ left: 0, behavior: "smooth" });
    else if (event.key === "End") viewport.scrollTo({ left: viewport.scrollWidth, behavior: "smooth" });
    else return;
    event.preventDefault();
  });
});
