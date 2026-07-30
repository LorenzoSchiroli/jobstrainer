# Fixed, Collapsible Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the app sidebar a classic pinned/fixed panel that never scrolls out of view, scrolls its own content independently of the main page, and slides in/out smoothly when toggled.

**Architecture:** `Sidebar.tsx`'s `<aside>` switches from a normal flex child to `position: fixed`, pinned to the viewport, with its own `overflow-y: auto` and a `transform: translateX(...)` slide animation driven by an `open` prop. `AppLayout.tsx` always mounts `Sidebar` (instead of conditionally swapping it for a bare button) and pushes `<main>` via an animated `margin-left` that mirrors the sidebar's open/closed state.

**Tech Stack:** React 18 + TypeScript, inline style objects (no CSS framework in this codebase), Vite.

## Global Constraints

- Sidebar width stays fixed at 240px — no drag-resize (per spec).
- No behavior change across viewport widths — no separate mobile/overlay mode (per spec).
- `useSidebarOpen` (`frontend/src/hooks/useSidebarOpen.ts`) is unchanged — its `localStorage`-backed, cross-tab-synced `open`/`toggle` API is reused as-is.
- No new dependencies, no new files — only `Sidebar.tsx` and `AppLayout.tsx` change (per spec's Scope section).
- Slide/push transition timing: `200ms ease` (per spec).
- Sidebar `z-index: 30`; closed-state corner hamburger `z-index: 20` (must stay below the sidebar so the sliding panel covers it during the closing animation, per spec).

---

### Task 1: Pin the sidebar, add slide animation, and push main content

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx:8` (function signature), `frontend/src/components/Sidebar.tsx:71-74` (aside style)
- Modify: `frontend/src/components/AppLayout.tsx` (whole file)

**Interfaces:**
- Consumes: `useSidebarOpen()` from `frontend/src/hooks/useSidebarOpen.ts` → `{ open: boolean, toggle: () => void }` (unchanged, already exists).
- Produces: `Sidebar` component now takes `{ open: boolean; onToggle: () => void }` (previously just `{ onToggle: () => void }`) — this is a breaking prop-signature change, so its one caller (`AppLayout.tsx`) must be updated in this same task.

- [ ] **Step 1: Update `Sidebar.tsx`'s function signature to accept `open`**

In `frontend/src/components/Sidebar.tsx`, change line 8 from:

```tsx
export default function Sidebar({ onToggle }: { onToggle: () => void }) {
```

to:

```tsx
export default function Sidebar({ open, onToggle }: { open: boolean; onToggle: () => void }) {
```

- [ ] **Step 2: Pin the `<aside>` to the viewport with its own scroll and slide transform**

In `frontend/src/components/Sidebar.tsx`, change the `<aside>` opening style block (currently lines 71-74):

```tsx
    <aside style={{
      width: 240, minWidth: 240, height: '100vh', borderRight: '1px solid #2a2a2a',
      padding: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem', background: '#0f0f0f',
    }}>
```

to:

```tsx
    <aside style={{
      position: 'fixed', top: 0, left: 0, zIndex: 30,
      width: 240, minWidth: 240, height: '100vh', borderRight: '1px solid #2a2a2a',
      padding: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem', background: '#0f0f0f',
      overflowY: 'auto',
      transform: open ? 'translateX(0)' : 'translateX(-100%)',
      transition: 'transform 200ms ease',
    }}>
```

Leave the rest of `Sidebar.tsx` (the collapse button, nav links, CV section, preferences, logout) untouched.

- [ ] **Step 3: Always mount `Sidebar` and push `<main>` in `AppLayout.tsx`**

Replace the full contents of `frontend/src/components/AppLayout.tsx` with:

```tsx
import Sidebar from './Sidebar'
import { useSidebarOpen } from '../hooks/useSidebarOpen'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { open, toggle } = useSidebarOpen()
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar open={open} onToggle={toggle} />
      {!open && (
        <button onClick={toggle} aria-label="Open sidebar"
                style={{ position: 'fixed', top: 12, left: 12, zIndex: 20, background: '#1f1f1f', color: '#fff', border: '1px solid #2a2a2a', borderRadius: 6, padding: '0.35rem 0.6rem', cursor: 'pointer' }}>
          ☰
        </button>
      )}
      <main style={{
        flex: 1, minWidth: 0,
        marginLeft: open ? 240 : 0,
        transition: 'margin-left 200ms ease',
      }}>{children}</main>
    </div>
  )
}
```

- [ ] **Step 4: Type-check and build**

Run:

```bash
cd frontend && npm run build
```

Expected: exits 0, no TypeScript errors (in particular, no complaint about `Sidebar`'s new `open` prop — `AppLayout.tsx` now passes it).

- [ ] **Step 5: Manual browser verification**

This is a pure layout/CSS change; the spec calls for manual verification instead of new automated tests (no new logic branches were introduced — `useSidebarOpen` is unchanged). Start the full stack per this repo's `AGENTS.md` (`docker compose up -d postgres opensearch`, `cd backend && uv run uvicorn backend.main:app --reload`, `cd frontend && npm run dev`), log in with a valid user, go to `/search`, and confirm:

1. **Pinned during scroll:** run a search that returns enough results to make the page taller than the viewport (or shrink the browser window). Scroll down. The sidebar must stay fixed in place — it must not scroll away — and its "☰ Collapse sidebar" button must stay clickable at all times.
2. **Independent internal scroll:** shrink the browser window height until the sidebar's own content (CV section with "View CV" expanded + preferences textarea) overflows. Confirm the sidebar scrolls internally (via its own scrollbar) without moving the main page.
3. **Slide + push animation:** click the sidebar's collapse button. Confirm the panel slides out to the left over ~200ms while `<main>` simultaneously animates to full width (no jump cut, no lag between the two). Click the corner "☰ Open sidebar" button that appears — confirm the reverse animation, and that the button disappears/gets covered rather than flashing next to an already-open sidebar.
4. **Persistence:** reload the page after collapsing the sidebar. Confirm it stays collapsed (existing `localStorage` behavior, unchanged).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Sidebar.tsx frontend/src/components/AppLayout.tsx
git commit -m "$(cat <<'EOF'
fix(frontend): pin sidebar to viewport with own scroll and slide animation

EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** fixed/pinned positioning ✓ (Step 2), own scroll ✓ (Step 2, `overflowY: 'auto'`), slide animation ✓ (Step 2 transform/transition), push (not overlay) main content ✓ (Step 3 marginLeft), collapsed-state hamburger stays reachable and doesn't flash ✓ (Step 3 z-index ordering + conditional render), fixed 240px width (no resize) ✓ (unchanged), no mobile-specific behavior ✓ (none added), `useSidebarOpen` untouched ✓ (only consumed, not modified).
- **Placeholder scan:** no TBD/TODO; every step shows full literal code to write.
- **Type consistency:** `Sidebar`'s new prop type (`{ open: boolean; onToggle: () => void }`) matches exactly how `AppLayout.tsx` calls it (`<Sidebar open={open} onToggle={toggle} />`); `useSidebarOpen()`'s returned shape (`{ open, toggle }`) matches its existing (unmodified) implementation.
