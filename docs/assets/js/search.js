(function initializeSearchModule(globalScope) {
  "use strict";

  const SECTION_LABELS = {
    learning: "学习一个",
    milestones: "身经百战",
    writings: "谈笑风生",
    journeys: "跑得还快",
  };
  const KIND_LABELS = { paper: "论文", model: "模型", article: "文章" };
  const EMPTY_GUIDANCE = "输入标题关键词开始搜索";
  const LOAD_FAILURE = "搜索索引加载失败，请刷新后重试";
  const NO_MATCH = "没有找到公开标题";

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function validatePayload(payload) {
    if (payload?.version !== 1 || !Array.isArray(payload.documents)) {
      throw new Error("Unsupported search index");
    }
    for (const document of payload.documents) {
      if (
        !document
        || typeof document.id !== "string"
        || typeof document.title !== "string"
        || typeof document.url !== "string"
        || !SECTION_LABELS[document.section]
        || !KIND_LABELS[document.kind]
      ) {
        throw new Error("Invalid search document");
      }
    }
    return payload.documents;
  }

  function createSearchController({
    body,
    closeButton,
    dialog,
    fetchImpl,
    input,
    results,
    status,
    triggers,
    window,
  }) {
    const core = globalScope.TogosSearchCore;
    if (!core?.searchTitles) throw new Error("Search core is unavailable");
    let documents = null;
    let indexRequest = null;
    let currentResults = [];
    let activeIndex = -1;
    let lastTrigger = null;
    let loadFailed = false;

    function resultUrl(document) {
      const siteRoot = body.dataset.siteRoot ?? "";
      return new URL(`${siteRoot}${document.url}`, window.location.href).href;
    }

    function renderResults() {
      results.innerHTML = currentResults
        .map((document, index) => {
          const active = index === activeIndex;
          const section = SECTION_LABELS[document.section];
          const kind = KIND_LABELS[document.kind];
          return `<a class="search-result${active ? " is-active" : ""}" `
            + `id="search-result-${index}" role="option" aria-selected="${active}" `
            + `data-result-index="${index}" href="${escapeHtml(resultUrl(document))}">`
            + `<strong>${escapeHtml(document.title)}</strong>`
            + `<span>${escapeHtml(section)} · ${escapeHtml(kind)}</span></a>`;
        })
        .join("");
      if (activeIndex >= 0) {
        input.setAttribute("aria-activedescendant", `search-result-${activeIndex}`);
      } else {
        input.removeAttribute("aria-activedescendant");
      }
    }

    function updateResults() {
      if (loadFailed) {
        status.textContent = LOAD_FAILURE;
        return;
      }
      if (!documents) {
        status.textContent = "正在加载公开标题…";
        return;
      }
      if (!core.normalizeTitle(input.value)) {
        currentResults = [];
        activeIndex = -1;
        status.textContent = EMPTY_GUIDANCE;
        renderResults();
        return;
      }
      currentResults = core.searchTitles(documents, input.value, 20);
      activeIndex = -1;
      status.textContent = currentResults.length ? `${currentResults.length} 个结果` : NO_MATCH;
      renderResults();
    }

    async function loadIndex() {
      if (!indexRequest) {
        const siteRoot = body.dataset.siteRoot ?? "";
        const indexUrl = new URL(`${siteRoot}search-index.json`, window.location.href);
        indexRequest = fetchImpl(indexUrl, { headers: { Accept: "application/json" } })
          .then((response) => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
          })
          .then(validatePayload);
      }
      documents = await indexRequest;
      return documents;
    }

    async function open(trigger = triggers[0] ?? null) {
      lastTrigger = trigger;
      if (!dialog.open) dialog.showModal();
      status.textContent = documents ? EMPTY_GUIDANCE : "正在加载公开标题…";
      try {
        await loadIndex();
        updateResults();
      } catch (error) {
        loadFailed = true;
        status.textContent = LOAD_FAILURE;
        results.innerHTML = "";
      }
      input.focus();
    }

    function close() {
      if (dialog.open) dialog.close();
    }

    function handleKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (!currentResults.length) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        activeIndex = (activeIndex + 1) % currentResults.length;
        renderResults();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        activeIndex = activeIndex <= 0 ? currentResults.length - 1 : activeIndex - 1;
        renderResults();
      } else if (event.key === "Enter" && activeIndex >= 0) {
        event.preventDefault();
        window.location.assign(resultUrl(currentResults[activeIndex]));
      }
    }

    triggers.forEach((trigger) => {
      trigger.addEventListener("click", () => open(trigger));
    });
    closeButton?.addEventListener("click", close);
    input.addEventListener("input", updateResults);
    input.addEventListener("keydown", handleKeydown);
    results.addEventListener?.("mousemove", (event) => {
      const index = Number(event.target.closest?.("[data-result-index]")?.dataset.resultIndex);
      if (Number.isInteger(index) && index !== activeIndex) {
        activeIndex = index;
        renderResults();
      }
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) close();
    });
    dialog.addEventListener("close", () => {
      lastTrigger?.focus();
      lastTrigger = null;
    });

    return { close, handleKeydown, open, updateResults };
  }

  function initSearch({ document, window, fetchImpl = window.fetch.bind(window) }) {
    const dialog = document.querySelector("#search-dialog");
    const input = document.querySelector("#search-input");
    const status = document.querySelector("[data-search-status]");
    const results = document.querySelector("[data-search-results]");
    const triggers = [...document.querySelectorAll("[data-search-trigger]")];
    if (!dialog || !input || !status || !results || !triggers.length) return null;
    const controller = createSearchController({
      body: document.body,
      closeButton: document.querySelector("[data-search-close]"),
      dialog,
      fetchImpl,
      input,
      results,
      status,
      triggers,
      window,
    });
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        controller.open(triggers[0]);
      }
    });
    return controller;
  }

  const api = { createSearchController, initSearch, validatePayload };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  globalScope.TogosSearch = api;
  if (typeof document !== "undefined" && typeof window !== "undefined") {
    initSearch({ document, window });
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
