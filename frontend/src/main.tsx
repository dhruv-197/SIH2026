import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'

// A tab keeps the page files of the build it first loaded; after the dashboard is rebuilt those files are gone. Reload
// once (at most once a minute, remembered in sessionStorage) so the tab picks up the new build instead of failing.
window.addEventListener('vite:preloadError', (event) => {
  try {
    if (Date.now() - Number(sessionStorage.getItem('geothermal-reload-at') ?? 0) < 60_000) return
    sessionStorage.setItem('geothermal-reload-at', String(Date.now()))
  } catch {
    return // no storage: leave it to the page's error message rather than risk a reload loop
  }
  event.preventDefault()
  window.location.reload()
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
