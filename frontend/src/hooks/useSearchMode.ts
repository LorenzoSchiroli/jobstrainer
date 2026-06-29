import { useState } from 'react'

export type SearchMode = 'basic' | 'advanced'

export function useSearchMode() {
  const [mode, setModeState] = useState<SearchMode>(
    () => (localStorage.getItem('search_mode') as SearchMode) || 'basic',
  )
  const setMode = (m: SearchMode) => {
    localStorage.setItem('search_mode', m)
    setModeState(m)
  }
  return { mode, setMode }
}
