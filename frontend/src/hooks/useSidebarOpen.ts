import { useSyncExternalStore } from 'react'

const KEY = 'sidebar_open'
const listeners = new Set<() => void>()

function getSnapshot(): boolean {
  return localStorage.getItem(KEY) !== 'false' // default open
}

function subscribe(cb: () => void) {
  listeners.add(cb)
  window.addEventListener('storage', cb)
  return () => {
    listeners.delete(cb)
    window.removeEventListener('storage', cb)
  }
}

function setOpen(v: boolean) {
  localStorage.setItem(KEY, String(v))
  listeners.forEach((l) => l())
}

export function useSidebarOpen() {
  const open = useSyncExternalStore(subscribe, getSnapshot)
  return { open, toggle: () => setOpen(!open) }
}
