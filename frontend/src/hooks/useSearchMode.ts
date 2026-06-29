import { useSyncExternalStore } from 'react'

export type SearchMode = 'basic' | 'advanced'

const KEY = 'search_mode'
const listeners = new Set<() => void>()

function getSnapshot(): SearchMode {
  return (localStorage.getItem(KEY) as SearchMode) || 'basic'
}

function subscribe(cb: () => void) {
  listeners.add(cb)
  window.addEventListener('storage', cb)
  return () => {
    listeners.delete(cb)
    window.removeEventListener('storage', cb)
  }
}

function setSearchMode(m: SearchMode) {
  localStorage.setItem(KEY, m)
  listeners.forEach((l) => l())
}

export function useSearchMode() {
  const mode = useSyncExternalStore(subscribe, getSnapshot)
  return { mode, setMode: setSearchMode }
}
