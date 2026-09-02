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

  function readStoredContextOpen(storage) {
    return readStoredValue(storage, COLLAPSE_STORAGE_KEY) === "false";
  }

  function writeStoredContextOpen(storage, open) {
    try {
      storage?.setItem(COLLAPSE_STORAGE_KEY, String(!open));
    } catch (error) {
      // The context drawer remains usable for this page when storage is unavailable.
    }
  }

  function initSiteShell({ document, window }) {
    const root = document.documentElement;
    const body = document.body;
    const navigationShell = document.querySelector("#navigation-shell");
    const drawerToggle = document.querySelector(".sidebar-toggle");
    const drawerToggleIcon = drawerToggle?.querySelector("[data-sidebar-toggle-icon]");
    const drawerToggleLabel = drawerToggle?.querySelector("[data-sidebar-toggle-label]");
    const drawerScrim = document.querySelector("[data-sidebar-close]");
    const contextDrawer = document.querySelector("#context-drawer");
    const contextToggle = document.querySelector("[data-context-toggle]");
    const contextClose = document.querySelector("[data-context-close]");
    const contextScrim = document.querySelector("[data-context-scrim]");
    const themeToggle = document.querySelector(".theme-toggle");
    const themeIcon = themeToggle?.querySelector("[data-theme-icon]");
    const drawerMedia = window.matchMedia("(max-width: 900px)");
    const themeMedia = window.matchMedia("(prefers-color-scheme: dark)");
    const storedTheme = readStoredValue(window.localStorage, THEME_STORAGE_KEY);
    let followsSystemTheme = storedTheme !== "light" && storedTheme !== "dark";
    let contextOpen = readStoredContextOpen(window.localStorage);

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

    function setDrawer(open, returnFocus = false) {
      body.classList.toggle("sidebar-open", open);
      drawerToggle?.setAttribute("aria-expanded", String(open));
      navigationShell?.toggleAttribute("inert", drawerMedia.matches && !open);
      if (drawerToggleIcon) drawerToggleIcon.textContent = open ? "×" : "☰";
      if (drawerToggleLabel) drawerToggleLabel.textContent = open ? "关闭" : "导航";
      if (drawerMedia.matches) updateContextDrawer(open || contextOpen);
      if (!open && returnFocus && drawerMedia.matches) drawerToggle?.focus();
    }

    function updateContextDrawer(open) {
      if (open) root.dataset.contextOpen = "true";
      else delete root.dataset.contextOpen;
      contextDrawer?.setAttribute("aria-hidden", String(!open));
      contextDrawer?.toggleAttribute("inert", !open);
      contextToggle?.setAttribute("aria-expanded", String(open));
    }

    function setContextOpen(open, persist = false, returnFocus = false) {
      contextOpen = open;
      updateContextDrawer(open);
      if (persist) writeStoredContextOpen(window.localStorage, open);
      if (!open && returnFocus) contextToggle?.focus();
    }

    setDrawer(false);
    setContextOpen(contextOpen);
    applyTheme(
      storedTheme === "light" || storedTheme === "dark"
        ? storedTheme
        : themeMedia.matches
          ? "dark"
          : "light",
    );

    contextToggle?.addEventListener("click", () => {
      setContextOpen(root.dataset.contextOpen !== "true", true);
    });
    drawerToggle?.addEventListener("click", () => {
      const isOpen = body.classList.contains("sidebar-open");
      setDrawer(!isOpen, isOpen);
    });
    drawerScrim?.addEventListener("click", () => setDrawer(false, true));
    contextClose?.addEventListener("click", () => setContextOpen(false, true, true));
    contextScrim?.addEventListener("click", () => setContextOpen(false, true, true));
    contextDrawer?.addEventListener("click", (event) => {
      if (event.target.closest?.("a")) setContextOpen(false, true, true);
    });
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
    drawerMedia.addEventListener?.("change", () => setDrawer(false));
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (root.dataset.contextOpen === "true") {
        setContextOpen(false, true, true);
      } else if (body.classList.contains("sidebar-open")) {
        setDrawer(false, true);
      }
    });

    return { setContextOpen, setDrawer };
  }

  const api = { COLLAPSE_STORAGE_KEY, initSiteShell, readStoredContextOpen };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  globalScope.TogosSiteShell = api;
  if (typeof document !== "undefined" && typeof window !== "undefined") {
    initSiteShell({ document, window });
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
