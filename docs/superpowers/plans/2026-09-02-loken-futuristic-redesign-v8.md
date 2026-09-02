# LOKEN Futuristic Redesign V8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the generated static knowledge site as the approved LOKEN modular-specimen interface, with inline search, a collapsible context drawer, an in-page paper summary reader, and distinct layouts for all four themes.

**Architecture:** Keep the Python static generators and public data contracts unchanged. `shared.site_shell` owns the LOKEN brand, global navigation, inline search, context drawer, and common asset loading; theme renderers only emit semantic page content. Existing vanilla JavaScript modules retain their public module names while changing the search and summary presentation from dialogs to inline panels.

**Tech Stack:** Python 3.12, generated HTML, vanilla CSS, vanilla JavaScript, local `unittest`, Node syntax checks, self-hosted Space Grotesk and IBM Plex Mono font assets.

**Spec:** `docs/superpowers/specs/2026-09-02-loken-futuristic-redesign-v8-design.md`

## Global Constraints

- Website-visible branding becomes `LOKEN`; repository names, GitHub URLs, environment variables, package names, and public routes remain unchanged.
- Do not modify `README.md`.
- Do not change JSON schemas, search-index fields, summary publication data, or existing deep-link anchors.
- Do not implement the V9 automation migration, a real map service, city data, photo upload, or a finished Logo.
- The context navigation must not repeat the theme name or description and must consume no content width while collapsed.
- Search is always directly visible; `Ctrl/Cmd + K` focuses it and no search dialog remains.
- Paper key points render in the right-side panel on desktop and immediately after the selected paper row on mobile.
- Local feature tests must be deleted before every commit and must never be staged, committed, pushed, or included in a PR.
- Generated HTML is updated through the generators, never hand-edited; `README.md` remains byte-identical.

---

## File Structure

- `src/shared/site_shell.py`: single source of truth for visible brand, numbered primary navigation, inline search, context drawer, common asset version, and journey placeholder structure.
- `docs/assets/css/site.css`: all visual tokens, shell layout, four theme layouts, dark mode, breakpoints, focus states, and reduced-motion rules.
- `docs/assets/fonts/`: self-hosted Latin display and utility fonts plus their upstream license files.
- `docs/assets/js/search.js`: inline combobox controller and keyboard behavior.
- `docs/assets/js/site-shell.js`: primary mobile drawer, context drawer, stored state, theme toggle, Escape behavior, and focus return.
- `docs/assets/js/sidebar.js`: paper archive tabs plus the in-page summary panel controller.
- `src/papers/site.py`: learning header, paper workspace, summary-panel markup, summary links, and journey-page generation.
- `src/milestones/publisher.py`: model-lineage overview and selected model specimen markup.
- `src/writings/rendering.py`: LOKEN titles, editorial article listing, public source rail, and narrow article layout.
- `src/writings/importers/weread/workflow.py`: LOKEN branding for generated local preview pages.
- `docs/**/*.html`, `docs/search-index.json`, `docs/writings/manifest.json`: regenerated public output only.

---

### Task 1: LOKEN Brand, Fonts, and Inline Search

**Files:**
- Create: `docs/assets/fonts/space-grotesk-latin.woff2`
- Create: `docs/assets/fonts/ibm-plex-mono-latin-400.woff2`
- Create: `docs/assets/fonts/ibm-plex-mono-latin-600.woff2`
- Create: `docs/assets/fonts/OFL-Space-Grotesk.txt`
- Create: `docs/assets/fonts/OFL-IBM-Plex-Mono.txt`
- Modify: `src/shared/site_shell.py`
- Modify: `src/papers/site.py`
- Modify: `src/writings/rendering.py`
- Modify: `src/writings/importers/weread/workflow.py`
- Modify: `docs/assets/js/search.js`
- Modify: `docs/assets/css/site.css`
- Test locally only: `tests/test_v8_brand_search.py`

**Interfaces:**
- Produces: `SITE_NAME = "LOKEN"`, `ASSET_VERSION = "5"`, `render_inline_search() -> str`, and the stable DOM hooks `[data-search-root]`, `#search-input`, `[data-search-popover]`, `[data-search-status]`, `[data-search-results]`.
- Preserves: `globalScope.TogosSearch`, `validatePayload(payload)`, and search-index schema version 1.

- [ ] **Step 1: Write the failing shell and search tests**

Create the ignored local file with assertions equivalent to:

```python
from pathlib import Path
import unittest
from shared.site_shell import render_site_page


class LokenShellTests(unittest.TestCase):
    def test_shell_uses_loken_and_inline_search_without_dialog(self):
        html = render_site_page(
            output_file=Path("docs/index.html"),
            output_root=Path("docs"),
            active_section="learning",
            page_title="LOKEN",
            meta_description="test",
            secondary_navigation='<a href="#today">Today</a>',
            main_content='<h1 id="today">Today</h1>',
        )
        self.assertIn('aria-label="LOKEN 首页"', html)
        self.assertIn('placeholder="搜索文章标题"', html)
        self.assertIn('data-search-popover', html)
        self.assertNotIn('id="search-dialog"', html)
        self.assertNotIn('EXHIBITION', html)
        self.assertNotIn('TO/GOS', html)
```

Add a Node-backed test fixture that calls `createSearchController` with a fake input, popover, results, status, fetch, and window, then asserts focus loads the index, input renders results grouped under the four section labels, Escape hides results without clearing `input.value`, and `Ctrl/Cmd + K` focuses the input.

- [ ] **Step 2: Run the tests and verify the old shell fails**

Run: `python -m unittest tests.test_v8_brand_search -v`

Expected: FAIL because the current shell renders `TO/GOS` and `#search-dialog`.

- [ ] **Step 3: Add verified self-hosted font assets**

Resolve the current npm versions with `npm view @fontsource-variable/space-grotesk version` and `npm view @fontsource/ibm-plex-mono version`, then pack those exact versions in a temporary directory. Extract `files/space-grotesk-latin-wght-normal.woff2`, `files/ibm-plex-mono-latin-400-normal.woff2`, `files/ibm-plex-mono-latin-600-normal.woff2`, and each package license. Rename them to the paths listed above, record package versions and SHA-256 values in the commit body or implementation notes, and delete the tarballs/extraction directory. Do not load Google Fonts or another CDN at runtime.

Add these exact declarations at the start of `site.css`:

```css
@font-face {
  font-family: "Space Grotesk";
  src: url("../fonts/space-grotesk-latin.woff2") format("woff2");
  font-style: normal;
  font-weight: 300 700;
  font-display: swap;
}
@font-face {
  font-family: "IBM Plex Mono";
  src: url("../fonts/ibm-plex-mono-latin-400.woff2") format("woff2");
  font-style: normal;
  font-weight: 400;
  font-display: swap;
}
@font-face {
  font-family: "IBM Plex Mono";
  src: url("../fonts/ibm-plex-mono-latin-600.woff2") format("woff2");
  font-style: normal;
  font-weight: 600;
  font-display: swap;
}
```

- [ ] **Step 4: Implement the shared LOKEN shell and inline search DOM**

In `site_shell.py`, add `SITE_NAME = "LOKEN"` and `ASSET_VERSION = "5"`. Render the brand as a stable mark plus wordmark:

```python
brand_href = html.escape(site_root + SECTIONS[0].route, quote=True)
brand = (
    f'<a class="primary-brand" href="{brand_href}" aria-label="LOKEN 首页">'
    '<span class="brand-mark" aria-hidden="true">LK</span>'
    '<span class="brand-wordmark">LOKEN</span></a>'
)
```

Replace `_render_search_dialog()` and the search trigger with `render_inline_search()`:

```html
<div class="site-search" data-search-root>
  <label class="site-search-field" for="search-input">
    <span aria-hidden="true">⌕</span>
    <input id="search-input" type="search" placeholder="搜索文章标题" role="combobox"
           aria-autocomplete="list" aria-controls="search-results" aria-expanded="false">
    <kbd>Ctrl K</kbd>
  </label>
  <div class="search-popover" data-search-popover hidden>
    <p class="search-status" data-search-status aria-live="polite">输入标题关键词开始搜索</p>
    <div id="search-results" class="search-results" data-search-results role="listbox"></div>
  </div>
</div>
```

Update visible page titles and footer labels to LOKEN while leaving URLs, `TOGOS_WSL_*`, package names, Python module names, and GitHub repository URLs unchanged.

- [ ] **Step 5: Refactor search.js around an inline combobox**

Change `createSearchController` to consume `{ body, fetchImpl, input, popover, results, root, status, window }`. `open()` becomes `focusSearch()` and must load the index, unhide the popover when there is status or content, and focus the input. `closeResults()` hides the popover, clears active descendant state, and keeps `input.value`. A document pointer handler closes only when the event target is outside `root`.

Group ranked matches by `learning`, `milestones`, `writings`, and `journeys` in that order while preserving relevance order inside each group. Keep ArrowDown, ArrowUp, Home/End where currently supported, Enter navigation, cached index loading, HTML escaping, and error copy.

- [ ] **Step 6: Add shell/search styles and run the focused tests**

Use `--void`, `--carbon`, `--gallery`, `--white`, `--grid`, `--signal-blue`, and `--live-mint` variables. The desktop search field is `min(22rem, 42vw)` wide and `2.75rem` high; results are absolutely positioned below it. At `max-width: 600px`, place the field on a full second utility row without converting it into a dialog.

Run: `python -m unittest tests.test_v8_brand_search -v`

Expected: PASS.

- [ ] **Step 7: Delete local tests, verify staging, and commit**

Delete `tests/test_v8_brand_search.py` and any companion JS fixture through `apply_patch`. Verify `git status --short` contains no `tests/` paths.

Run: `git diff --check`

Stage only font assets/licenses, shared shell, affected generators, `search.js`, and `site.css`. Run `git diff --cached --check`.

Commit: `feat: establish the LOKEN site shell`

---

### Task 2: Collapsible Context Drawer and Responsive Navigation

**Files:**
- Modify: `src/shared/site_shell.py`
- Modify: `docs/assets/js/site-shell.js`
- Modify: `docs/assets/css/site.css`
- Test locally only: `tests/test_v8_navigation.py`
- Test locally only: `tests/v8_site_shell.test.js`

**Interfaces:**
- Produces: `#context-drawer`, `[data-context-toggle]`, `[data-context-close]`, and `setContextOpen(open: boolean, persist?: boolean, returnFocus?: boolean)`.
- Preserves: storage key `togos-secondary-sidebar-collapsed`, `globalScope.TogosSiteShell`, primary navigation routes, and no-JavaScript navigation links.

- [ ] **Step 1: Write failing drawer structure and controller tests**

Assert the shell includes numbered theme labels `01` through `04`, a context trigger with `aria-controls="context-drawer"`, and the theme description only inside `.section-intro`, never inside the context drawer. Also assert the complete context links remain present in HTML without JavaScript.

In the local Node fixture assert: missing storage defaults the drawer to closed; click opens it; Escape closes it and restores focus; persisted `false` reopens it on a later initialization; mobile primary navigation still uses its own `sidebar-open` state.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m unittest tests.test_v8_navigation -v`

Run: `node tests/v8_site_shell.test.js`

Expected: FAIL because the current context sidebar consumes permanent grid width and defaults open.

- [ ] **Step 3: Render the new context drawer**

Change `render_primary_navigation` to prefix visible theme metadata with `01 / PAPER SIGNALS`, `02 / MODEL ARCHIVE`, `03 / FIELD NOTES`, and `04 / CITY MEMORY` while keeping full Chinese labels.

Change `render_context_sidebar` to emit:

```html
<aside class="context-drawer" id="context-drawer" aria-label="本页目录">
  <header class="context-drawer-header">
    <span>INDEX</span>
    <button type="button" data-context-close aria-label="关闭本页目录">×</button>
  </header>
  <nav id="context-navigation" class="context-navigation">{secondary_navigation}</nav>
</aside>
```

Place a visible `INDEX ☰` button with `[data-context-toggle]` in the content utility row. Do not render the current theme name or description in the drawer.

- [ ] **Step 4: Implement independent primary and context drawer state**

Keep the mobile primary navigation state in `setDrawer`. Replace `setCollapsed` with `setContextOpen`. Interpret stored `"false"` as open and all other/missing values as closed so the new design does not squeeze content by default. Set `inert` and `aria-hidden` while closed. Close on Escape, scrim click, close button, or navigation link; return focus only when a user action closes the drawer.

- [ ] **Step 5: Implement the modular rail and drawer CSS**

Desktop: `9.375rem` black/white primary rail, `3.875rem` utility bar, page content beginning after the rail, and a fixed/absolute `17.5rem` context drawer that overlays content while open. Mobile: one full-height navigation surface with primary topics first and page index second. Collapsed context drawer must contribute zero width.

- [ ] **Step 6: Run tests, delete them, and commit**

Run both focused test commands and expect PASS. Delete both local test files through `apply_patch`, confirm no test path is staged, run `git diff --check` and `git diff --cached --check`.

Commit: `feat: replace the secondary sidebar with a context drawer`

---

### Task 3: In-Page Paper Key-Points Reader

**Files:**
- Modify: `src/papers/site.py`
- Modify: `docs/assets/js/sidebar.js`
- Modify: `docs/assets/css/site.css`
- Test locally only: `tests/test_v8_paper_reader.py`
- Test locally only: `tests/v8_paper_reader.test.js`

**Interfaces:**
- Produces: `#paper-summary-panel`, `[data-summary-panel-home]`, `[data-summary-title]`, `[data-summary-content]`, `[data-summary-direct]`, and `openSummaryPanel(link: HTMLElement) -> Promise<void>`.
- Consumes: existing `data-summary-url` and `data-summary-id` attributes and the existing summary article HTML generated under `docs/notes/`.

- [ ] **Step 1: Write failing renderer and interaction tests**

The Python test must assert ready summary links use `aria-controls="paper-summary-panel"`, omit `aria-haspopup="dialog"`, and that the generated learning page contains one panel and no `#summary-dialog`.

The Node fixture must verify: clicking a ready link prevents navigation; loading state appears; the correct `#summary-<arxiv-id>` article is extracted; the selected row gets `.is-summary-active`; only one trigger has `aria-expanded="true"`; fetches are cached; HTTP errors show the fixed failure copy and preserve a direct summary link.

- [ ] **Step 2: Run tests and verify the dialog behavior fails them**

Run: `python -m unittest tests.test_v8_paper_reader -v`

Run: `node tests/v8_paper_reader.test.js`

Expected: FAIL because the current generator renders a dialog and `sidebar.js` calls `showModal()`.

- [ ] **Step 3: Render the learning workspace and summary panel**

Wrap the archive and reader as:

```html
<div class="learning-workspace">
  <div class="learning-archive">{render_content(categories, summary_catalog, candidate_statuses)}</div>
  <div data-summary-panel-home></div>
  <aside class="paper-summary-panel" id="paper-summary-panel" aria-live="polite">
    <header class="paper-summary-header"><h2 data-summary-title>论文要点</h2></header>
    <div data-summary-content><p>选择一篇已有摘要的论文查看要点。</p></div>
    <a data-summary-direct hidden>打开完整总结 →</a>
  </aside>
</div>
```

Keep the paper title as the primary row content. Rename visible link copy to `要点`, add `aria-controls` and `aria-expanded="false"`, and remove the trailing summary dialog from `generate_site`.

- [ ] **Step 4: Replace the dialog controller with the panel controller**

Retain `loadSummaryDocument` and its cache. `openSummaryPanel` updates title, loading/error state, direct link, active row, and trigger expanded state without stealing focus. Add a `matchMedia("(max-width: 900px)")` listener: on mobile create a single `<tr class="mobile-summary-row"><td colspan="4"></td></tr>` after the active paper and move the panel into the cell; on desktop move it back immediately after `[data-summary-panel-home]`.

When selection changes, remove the old mobile row before inserting the new one. The panel content is moved, never cloned, so IDs from the summary article remain unique.

- [ ] **Step 5: Implement reader layout and active states**

Desktop `.learning-workspace` uses `minmax(0, 1fr) minmax(18rem, 22rem)`; the reader is sticky below the utility bar and independently scrollable. Active rows use a blue inset rule plus a subtle cool tint. Mobile rows use one column and the inserted summary cell spans all table columns. Error text includes an actionable direct link.

- [ ] **Step 6: Run tests, delete them, and commit**

Run both focused suites and expect PASS. Delete the local tests through `apply_patch`, verify no `tests/` paths are staged, and run both diff checks.

Commit: `feat: show paper key points beside the archive`

---

### Task 4: Theme-Specific Model, Writing, and Journey Layouts

**Files:**
- Modify: `src/milestones/publisher.py`
- Modify: `src/writings/rendering.py`
- Modify: `src/shared/site_shell.py`
- Modify: `src/papers/site.py`
- Modify: `docs/assets/css/site.css`
- Test locally only: `tests/test_v8_theme_pages.py`

**Interfaces:**
- Produces: `render_model_specimen(family: dict[str, Any], notes: dict[str, Any]) -> str`, `render_journey_placeholder_page(*, output_file: Path, output_root: Path) -> str`, `.writing-source-rail`, `.milestone-overview`, and `.journey-map-placeholder`.
- Preserves: milestone release anchors, comparison table content, writing routes/tags, article TOC anchors, and journey route `journeys/index.html`.

- [ ] **Step 1: Write failing semantic page tests**

Assert the milestone family page has one `.milestone-overview` with timeline and model specimen, writing listing has an editorial stream plus public Notion/微信读书 source labels, article pages use LOKEN titles, and journey output contains a map placeholder with no invented city names, coordinates, pins, counts, or photos.

- [ ] **Step 2: Run the test and verify current markup fails**

Run: `python -m unittest tests.test_v8_theme_pages -v`

Expected: FAIL because the current pages use the old hero/workspace and generic empty-section layout.

- [ ] **Step 3: Build the milestone lineage overview**

Add `render_model_specimen(family, notes)` using the latest release in `family["releases"]` as the selected specimen. Render only data already present: name, release date, organization, status, and note availability. Wrap timeline plus specimen in `.milestone-overview`; keep the full comparison table immediately below and keep every existing release/deep-reading anchor.

- [ ] **Step 4: Build the editorial writing stream and source rail**

For non-empty listings, feature the first sorted article and render remaining entries in the existing chronological stream. Add a public source rail with static labels `Notion` and `微信读书` plus only public article counts; never render import paths, cache locations, private source references, or workbench actions. For empty listings, keep the same shell and render explicit forthcoming-content copy.

Keep article pages restrained: narrower body, visible type/date/tags, quiet context drawer TOC, and no source rail.

- [ ] **Step 5: Build the honest journey placeholder**

Add a dedicated `render_journey_placeholder_page` with an unlabeled world-grid silhouette, empty photo contact area, and copy stating that the city archive is not yet open. It must contain zero `.city-pin` elements and no fictional location values. Call it from `papers.site.generate_site` instead of `render_empty_section_page` for the journey route.

- [ ] **Step 6: Add theme CSS, run the tests, delete them, and commit**

Implement the model lineage/specimen, editorial writing/source rail, long-form article, and future map placeholder layouts. Run the focused suite and expect PASS. Delete `tests/test_v8_theme_pages.py`, verify no test path is staged, and run both diff checks.

Commit: `feat: give each LOKEN theme a distinct layout`

---

### Task 5: Full Build, Responsive Polish, and Generated Output

**Files:**
- Modify: `docs/assets/css/site.css`
- Modify as generated: `docs/index.html`
- Modify as generated: `docs/journeys/index.html`
- Modify as generated: `docs/milestone-models/*.html`
- Modify as generated: `docs/writings/**/*.html`
- Modify as generated when content changes: `docs/search-index.json`
- Modify as generated when content changes: `docs/writings/manifest.json`
- Test locally only: `tests/test_v8_generated_site.py`

**Interfaces:**
- Consumes all prior task DOM contracts.
- Produces the final public V8 static output with stable repeated builds.

- [ ] **Step 1: Write generated-output acceptance tests**

Assert built pages contain LOKEN visible branding and the expected active theme, contain no search or summary dialogs, preserve representative anchors such as `paper-<id>` and `milestone-<slug>`, and contain no page-level structures known to force horizontal overflow. Record `README.md` SHA-256 before build.

- [ ] **Step 2: Run the complete local test set before the final build**

Run: `python -m unittest discover -s tests -v`

Expected: PASS for all temporary V8 tests still present in this final verification workspace. If earlier task tests were already deleted as required, recreate only the acceptance assertions in `test_v8_generated_site.py`; do not resurrect or stage every earlier fixture.

- [ ] **Step 3: Build the full public site twice**

Run: `python -m writings.workbench build`

Capture `git diff -- docs` after the first build.

Run again: `python -m writings.workbench build`

Expected: the second build adds no new diff beyond the first build.

- [ ] **Step 4: Run syntax and repository validation**

Run:

```powershell
python -m compileall -q src
node --check docs/assets/js/site-shell.js
node --check docs/assets/js/search-core.js
node --check docs/assets/js/search.js
node --check docs/assets/js/sidebar.js
git diff --check
```

Verify the current README SHA-256 exactly matches the value recorded in Step 1.

- [ ] **Step 5: Perform visual QA at three viewports**

Serve `docs/` locally and inspect at `1440 × 1000`, `1024 × 768`, and `390 × 844`. Capture the four theme pages plus the learning page with an opened summary. Check: no page-level horizontal overflow; search is visible; focus rings are visible; context drawer overlays rather than squeezes content; the paper table alone scrolls; no decorative hero number remains; dark mode is legible; reduced-motion disables displacement.

If a visual defect is found, add a failing structural or JavaScript regression assertion before changing code, then rerun the relevant checks.

- [ ] **Step 6: Delete final local tests and inspect the exact commit**

Delete `tests/test_v8_generated_site.py` and all V8 fixtures through `apply_patch`. Confirm `git status --short` contains no test files, browser screenshots, local server output, or `.superpowers/` files.

Stage only source, public assets, font licenses, and generator-produced public files. Run `git diff --cached --check` and inspect `git diff --cached --stat`. Confirm `README.md` is absent.

- [ ] **Step 7: Commit the verified generated site**

Commit: `style: complete the LOKEN futuristic redesign`

---

### Task 6: Independent Review and Integration Readiness

**Files:**
- No planned source changes; review fixes, if any, are committed separately by concern.

**Interfaces:**
- Consumes the complete V8 branch and the design spec.
- Produces an independently reviewed, clean branch ready for ordinary merge into `main`.

- [ ] **Step 1: Request an independent code review**

Review against the spec with emphasis on search accessibility, summary-panel content safety, mobile table validity, visible branding boundaries, preserved deep links, generated-output determinism, and accidental README/test inclusion.

- [ ] **Step 2: Resolve only verified findings**

For every valid finding, reproduce it with a local failing test, implement the smallest fix, rerun the focused and full verification, delete the local test, and commit by concern. Do not accept review suggestions that rename repository/API compatibility identifiers or expand V8 into map/automation work.

- [ ] **Step 3: Run the final clean verification**

Run the full build twice, Python compilation, all four Node syntax checks, `git diff --check`, `git status --short --branch`, and compare the branch against `origin/main`. Confirm no local-only test or `.superpowers/` path is tracked.

- [ ] **Step 4: Finish the branch**

Use `superpowers:finishing-a-development-branch`. Per the user's standing preference, choose ordinary local merge into `main`, rerun the final verification on merged `main`, push `main`, and report exact commit SHAs and the local preview URL. Never force-push or discard unrelated work.
