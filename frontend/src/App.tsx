import { ListChecks, Moon, Network, Sun } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Route, Routes } from 'react-router'
import ResultPage from './pages/Result'
import RunDetailPage from './pages/RunDetail'
import RunsPage from './pages/Runs'
import { TracePage, TracesPage } from './pages/Traces'

const NAV = [
  { to: '/', label: 'Runs', icon: ListChecks, end: true },
  { to: '/traces', label: 'Traces', icon: Network },
]

function ThemeToggle() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? 'dark')
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      aria-label={`switch to ${next} theme`}
      className="rounded-md p-2 text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
      onClick={() => {
        document.documentElement.dataset.theme = next
        try { localStorage.setItem('tj-theme', next) } catch { /* private mode */ }
        setTheme(next)
      }}
    >
      {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  )
}

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--page)]/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] items-center gap-1 overflow-x-auto px-4 py-2">
          <NavLink to="/" className="mr-4 flex shrink-0 items-center gap-2 font-semibold tracking-tight">
            <img src="/favicon.svg" alt="" className="h-6 w-6" />
            tracejudge
          </NavLink>
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition ${
                  isActive ? 'bg-[var(--surface-3)] text-[var(--ink)]' : 'text-[var(--ink-2)] hover:bg-[var(--surface-2)]'
                }`
              }
            >
              <Icon size={15} />
              {label}
            </NavLink>
          ))}
          <div className="ml-auto shrink-0"><ThemeToggle /></div>
        </div>
      </header>
      <main className="mx-auto max-w-[1400px] px-4 py-6">
        <Routes>
          <Route path="/" element={<RunsPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/results/:id" element={<ResultPage />} />
          <Route path="/traces" element={<TracesPage />} />
          <Route path="/traces/:id" element={<TracePage />} />
          <Route path="*" element={<div className="text-[var(--ink-2)]">Not found.</div>} />
        </Routes>
      </main>
    </div>
  )
}
