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
    const siteUtility = document.querySelector(".site-utility");
    const pageContent = document.querySelector(".page-content");
    const drawerToggle = document.querySelector(".sidebar-toggle");
    const drawerToggleIcon = drawerToggle?.querySelector("[data-sidebar-toggle-icon]");
    const drawerToggleLabel = drawerToggle?.querySelector("[data-sidebar-toggle-label]");
    const drawerScrim = document.querySelector("[data-sidebar-close]");
    const navigationClose = document.querySelector("[data-navigation-close]");
    const contextDrawer = document.querySelector("#context-drawer");
    const contextToggle = document.querySelector("[data-context-toggle]");
    const contextLinks = [...document.querySelectorAll(".context-strip-link")];
    const contextClose = document.querySelector("[data-context-close]");
    const contextScrim = document.querySelector("[data-context-scrim]");
    const themeToggle = document.querySelector(".theme-toggle");
    const themeIcon = themeToggle?.querySelector("[data-theme-icon]");
    const drawerMedia = window.matchMedia("(max-width: 900px)");
    const themeMedia = window.matchMedia("(prefers-color-scheme: dark)");
    const storedTheme = readStoredValue(window.localStorage, THEME_STORAGE_KEY);
    let followsSystemTheme = storedTheme !== "light" && storedTheme !== "dark";
    let contextOpen = readStoredContextOpen(window.localStorage);
    let drawerReturnFocus = drawerToggle;

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

    function setDrawer(open, returnFocus = false, focusTarget = drawerToggle) {
      const mobile = drawerMedia.matches;
      if (open && mobile) drawerReturnFocus = focusTarget || drawerToggle;
      body.classList.toggle("sidebar-open", open);
      drawerToggle?.setAttribute("aria-expanded", String(open));
      navigationShell?.toggleAttribute("inert", mobile && !open);
      siteUtility?.toggleAttribute("inert", mobile && open);
      pageContent?.toggleAttribute("inert", mobile && open);
      if (navigationClose) navigationClose.hidden = !(mobile && open);
      if (drawerToggleIcon) drawerToggleIcon.textContent = open ? "×" : "☰";
      if (drawerToggleLabel) drawerToggleLabel.textContent = open ? "关闭" : "导航";
      updateContextDrawer(mobile ? open : contextOpen);
      if (open && mobile) navigationClose?.focus();
      if (!open && returnFocus) drawerReturnFocus?.focus();
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
      updateContextDrawer(drawerMedia.matches ? body.classList.contains("sidebar-open") : contextOpen);
      if (persist) writeStoredContextOpen(window.localStorage, open);
      if (!open && returnFocus) contextToggle?.focus();
    }

    function setActiveContextLink(activeLink) {
      contextLinks.forEach((link) => {
        const active = link === activeLink;
        link.classList.toggle("is-active", active);
        if (active) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      });
    }

    function syncActiveContextLink() {
      if (!contextLinks.length) return;
      const currentHash = window.location.hash || "#top";
      const matchingLink = contextLinks.find((link) => {
        const targetHash = new URL(link.href, window.location.href).hash || "#top";
        return targetHash === currentHash || (
          targetHash !== "#top" && currentHash.startsWith(`${targetHash}-`)
        );
      });
      setActiveContextLink(matchingLink || contextLinks[0]);
    }

    setDrawer(false);
    setContextOpen(contextOpen);
    syncActiveContextLink();
    applyTheme(
      storedTheme === "light" || storedTheme === "dark"
        ? storedTheme
        : themeMedia.matches
          ? "dark"
          : "light",
    );

    contextToggle?.addEventListener("click", () => {
      if (drawerMedia.matches) {
        if (!body.classList.contains("sidebar-open")) setDrawer(true, false, contextToggle);
        return;
      }
      setContextOpen(!contextOpen, true);
    });
    contextLinks.forEach((link) => {
      link.addEventListener("click", () => setActiveContextLink(link));
    });
    window.addEventListener("hashchange", syncActiveContextLink);
    drawerToggle?.addEventListener("click", () => {
      const isOpen = body.classList.contains("sidebar-open");
      setDrawer(!isOpen, isOpen, drawerToggle);
    });
    navigationClose?.addEventListener("click", () => setDrawer(false, true));
    drawerScrim?.addEventListener("click", () => setDrawer(false, true));
    contextClose?.addEventListener("click", () => {
      if (drawerMedia.matches) setDrawer(false, true);
      else setContextOpen(false, true, true);
    });
    contextScrim?.addEventListener("click", () => setContextOpen(false, true, true));
    contextDrawer?.addEventListener("click", (event) => {
      if (!event.target.closest?.("a")) return;
      if (drawerMedia.matches) setDrawer(false, true);
      else setContextOpen(false, true, true);
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
    drawerMedia.addEventListener?.("change", () => {
      const activeElement = document.activeElement;
      const activeWasInNavigation = navigationShell?.contains(activeElement);
      const activeWasInContext = contextDrawer?.contains(activeElement);
      setDrawer(false);
      if (!activeWasInNavigation) return;

      const activeIsNowHidden =
        (drawerMedia.matches && navigationShell?.hasAttribute("inert")) ||
        activeElement === navigationClose ||
        (activeWasInContext && contextDrawer?.hasAttribute("inert"));
      if (!activeIsNowHidden) return;
      if (activeWasInContext || drawerReturnFocus === contextToggle) {
        contextToggle?.focus();
      } else if (drawerMedia.matches) {
        drawerToggle?.focus();
      } else {
        (navigationShell?.querySelector(".primary-nav-item.is-active") ||
          navigationShell?.querySelector(".primary-brand") ||
          contextToggle)?.focus();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (drawerMedia.matches && body.classList.contains("sidebar-open")) {
        setDrawer(false, true);
      } else if (root.dataset.contextOpen === "true") {
        setContextOpen(false, true, true);
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
