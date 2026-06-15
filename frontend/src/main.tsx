import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

// Apply saved theme before first render to avoid flash of unstyled content
;(function () {
  try {
    const t = localStorage.getItem('oraculo-theme')
    const theme = t === 'light' || t === 'dark' || t === 'black' ? t : 'dark'
    document.documentElement.classList.add(`theme-${theme}`)
  } catch {
    document.documentElement.classList.add('theme-dark')
  }
})()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 2,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
