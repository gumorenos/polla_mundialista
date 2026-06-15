import { useEffect, useState } from 'react'

export type Theme = 'dark' | 'light' | 'black'

const STORAGE_KEY = 'oraculo-theme'
const DEFAULT_THEME: Theme = 'dark'

function applyTheme(theme: Theme) {
  const html = document.documentElement
  html.classList.remove('theme-light', 'theme-dark', 'theme-black')
  html.classList.add(`theme-${theme}`)
}

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'black') return stored
  } catch {
    // localStorage not available (SSR / private mode)
  }
  return DEFAULT_THEME
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(getStoredTheme)

  useEffect(() => {
    applyTheme(theme)
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      // ignore
    }
  }, [theme])

  // Apply on first mount (before any effect fires)
  useEffect(() => {
    applyTheme(getStoredTheme())
  }, [])

  return { theme, setTheme }
}
