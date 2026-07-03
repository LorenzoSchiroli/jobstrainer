# Fixed, Collapsible Sidebar

**Date:** 2026-07-03
**Status:** Approved (design)

## Goal

The sidebar (`Sidebar.tsx`) already has a collapse/expand mechanism
(`useSidebarOpen` hook, hamburger toggle), but it renders as a normal flex
child with `height: 100vh`. Since it isn't pinned to the viewport, once page
content (job results) grows taller than one screen, the sidebar scrolls away
with the rest of the page — including its own collapse button, so it becomes
unreachable until the user scrolls back to the top.

Fix: make the sidebar a classic fixed/pinned panel that never scrolls out of
view, has its own internal scroll independent of the main content, and slides
in/out smoothly when toggled.

## Scope

- `frontend/src/components/Sidebar.tsx`
- `frontend/src/components/AppLayout.tsx`

No other files change. `useSidebarOpen` (localStorage-backed, cross-tab
synced via the `storage` event) is already correct and is not touched.

## Design

### Sidebar (`Sidebar.tsx`)

- `<aside>` becomes `position: fixed; top: 0; left: 0; height: 100vh; width:
  240px; z-index: 30`, pinning it to the viewport regardless of page scroll
  position.
- Add `overflow-y: auto` on the aside so its own contents (nav, CV section,
  preferences textarea, logout) scroll independently of the main content,
  when taller than the viewport.
- The aside stays mounted at all times (no more conditional mount/unmount in
  the parent). Slide animation is driven by `transform: translateX(0)` when
  open / `translateX(-100%)` when closed, with `transition: transform 200ms
  ease`.
- The existing internal "☰ Collapse sidebar" button (top-right of the aside)
  is unchanged — it now stays reachable at all times since the panel can't
  scroll away.
- Width stays fixed at 240px (no drag-resize).

### Layout (`AppLayout.tsx`)

- `Sidebar` is now always rendered (previously conditionally rendered vs. a
  standalone hamburger button) so its slide transform can animate.
- The `<main>` wrapper gets `margin-left: 240px` when open / `0` when
  closed, with a matching `transition: margin-left 200ms ease`, so content is
  pushed in sync with the sidebar's slide (not overlaid).
- The closed-state "☰ Open sidebar" button (already `position: fixed; top:
  12; left: 12`) is only rendered when the sidebar is closed, at `z-index:
  20` — below the sidebar's `z-index: 30`. This means during the closing
  animation the sliding panel visually covers the corner button until it's
  fully off-screen, avoiding a jarring double-hamburger flash.
- Behavior is unchanged across viewport widths — no separate mobile/overlay
  mode.

## Testing

This is a pure frontend layout/CSS change with no new logic branches beyond
what already exists in `useSidebarOpen` — no new unit tests needed. Verify
manually in the browser:

- Long job-results list: scroll the page and confirm the sidebar stays
  pinned in place (does not scroll away) and its collapse button stays
  reachable.
- Sidebar content taller than the viewport (e.g. CV view expanded +
  preferences box): confirm it scrolls independently without moving the main
  page.
- Toggle open → closed → open: confirm the slide + content-push animate in
  sync, and state persists across a page reload (existing `localStorage`
  behavior).

## Out of scope

- Resizable sidebar width.
- Mobile-specific overlay behavior.
- Any change to sidebar contents (CV section, preferences, nav) or to
  `useSidebarOpen`.
