(function initializeModule(globalScope) {
  "use strict";

  const COLLAPSE_STORAGE_KEY = "togos-secondary-sidebar-collapsed";
  const THEME_STORAGE_KEY = "arxiv-theme";

  function readStoredValue(storage, key) {
    try {
      return storage?.getItem(key) ?? null;
    } catch (error) {
      return null;
    }
  }

  function readStoredCollapse(storage) {
    return readStoredValue(storage, COLLAPSE_STORAGE_KEY) === "true";
  }

  function writeStoredCollapse(storage, collapsed) {
    try {
      storage?.setItem(COLLAPSE_STORAGE_KEY, String(collapsed));
    } catch (error) {
      // Collapse remains usable for this page when storage is unavailable.
    }
  }

  function initSiteShell({ document, window }) {
    const root = document.documentElement;
    const body = document.body;
    const navigationShell = document.querySelector("#navigation-shell");
    const drawerToggle = document.querySelector(".sidebar-toggle");
    const drawerScrim = document.querySelector("[data-sidebar-close]");
    const collapseToggle = document.querySelector("[data-context-collapse]");
    const collapseIcon = collapseToggle?.querySelector("[data-context-collapse-icon]");
    const collapseLabel = collapseToggle?.querySelector("[data-context-collapse-label]");
    const themeToggle = document.querySelector(".theme-toggle");
    const themeIcon = themeToggle?.querySelector("[data-theme-icon]");
    const themeMedia = window.matchMedia("(prefers-color-scheme: dark)");
    const storedTheme = readStoredValue(window.localStorage, THEME_STORAGE_KEY);
    let followsSystemTheme = storedTheme !== "light" && storedTheme !== "dark";

    function updateThemeControl(theme) {
      const isDark = theme === "dark";
      if (themeIcon) themeIcon.textContent = isDark ? "☀" : "☾";
      themeToggle?.setAttribute("aria-label", isDark ? "切换到浅色主题" : "切换到深色主题");
      themeToggle?.setAttribute("title", isDark ? "切换到浅色主题" : "切换到深色主题");
      themeToggle?.setAttribute("aria-pressed", String(isDark));
    }

    function applyTheme(theme, persist = false) {
      root.dataset.theme = theme;
      updateThemeControl(theme);
      if (!persist) return;
      try {
        window.localStorage?.setItem(THEME_STORAGE_KEY, theme);
      } catch (error) {
        // Theme remains usable for this page when storage is unavailable.
      }
    }

    function setDrawer(open) {
      body.classList.toggle("sidebar-open", open);
      drawerToggle?.setAttribute("aria-expanded", String(open));
    }

    function setCollapsed(collapsed, persist = false) {
      if (collapsed) root.dataset.secondaryCollapsed = "true";
      else delete root.dataset.secondaryCollapsed;
      collapseToggle?.setAttribute("aria-expanded", String(!collapsed));
      if (collapseIcon) collapseIcon.textContent = collapsed ? "›" : "‹";
      if (collapseLabel) {
        collapseLabel.textContent = collapsed ? "展开二级导航" : "折叠二级导航";
      }
      if (persist) writeStoredCollapse(window.localStorage, collapsed);
    }

    setCollapsed(readStoredCollapse(window.localStorage));
    applyTheme(
      storedTheme === "light" || storedTheme === "dark"
        ? storedTheme
        : themeMedia.matches
          ? "dark"
          : "light",
    );

    collapseToggle?.addEventListener("click", () => {
      setCollapsed(root.dataset.secondaryCollapsed !== "true", true);
    });
    drawerToggle?.addEventListener("click", () => {
      setDrawer(!body.classList.contains("sidebar-open"));
    });
    drawerScrim?.addEventListener("click", () => setDrawer(false));
    navigationShell?.addEventListener("click", (event) => {
      if (event.target.closest?.("a")) setDrawer(false);
    });
    themeToggle?.addEventListener("click", () => {
      followsSystemTheme = false;
      applyTheme(root.dataset.theme === "dark" ? "light" : "dark", true);
    });
    themeMedia.addEventListener?.("change", (event) => {
      if (followsSystemTheme) applyTheme(event.matches ? "dark" : "light");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") setDrawer(false);
    });

    return { setCollapsed, setDrawer };
  }

  const api = { COLLAPSE_STORAGE_KEY, initSiteShell, readStoredCollapse };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  globalScope.TogosSiteShell = api;
  if (typeof document !== "undefined" && typeof window !== "undefined") {
    initSiteShell({ document, window });
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
