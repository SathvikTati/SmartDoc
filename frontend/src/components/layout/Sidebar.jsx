import { NavLink } from 'react-router-dom'
import { Columns3, FolderOpen, MessageSquareText, Search } from 'lucide-react'

import { cn } from '@/lib/format'

/**
 * Ask leads: it is the home route and what most sessions start with. Files
 * is second because it is where the library is managed, and the two
 * inspection tools follow.
 */
const NAV = [
  { to: '/ask', label: 'Ask', icon: MessageSquareText, hint: 'Cited answers' },
  { to: '/files', label: 'Files', icon: FolderOpen, hint: 'Document library' },
  { to: '/search', label: 'Search', icon: Search, hint: 'Raw chunk retrieval' },
  { to: '/compare', label: 'Compare', icon: Columns3, hint: 'Modes side by side' },
]

export function Sidebar({ documentCount, apiOnline }) {
  return (
    <aside className="flex h-full w-52 shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex h-12 items-center gap-2 border-b border-line px-4">
        <div className="flex h-5 w-5 items-center justify-center rounded-sm bg-ink">
          <span className="text-[10px] font-bold leading-none text-surface">
            P6
          </span>
        </div>
        <span className="text-sm font-semibold tracking-tight">PORT-6</span>
      </div>

      <nav className="flex-1 space-y-0.5 p-2">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            title={item.hint}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded px-2.5 py-1.5 text-sm',
                'transition-colors duration-100',
                isActive
                  ? 'bg-raised font-medium text-ink'
                  : 'text-ink-muted hover:bg-raised hover:text-ink',
              )
            }
          >
            {({ isActive }) => (
              <>
                <item.icon
                  className={cn(
                    'h-4 w-4 shrink-0',
                    isActive ? 'text-accent' : 'text-ink-subtle',
                  )}
                />
                {item.label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="space-y-1.5 border-t border-line px-3 py-2.5 text-2xs text-ink-subtle">
        <div className="flex items-center justify-between">
          <span>Library</span>
          <span className="tnum text-ink-muted">
            {documentCount == null ? '—' : documentCount}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>API</span>
          <span className="flex items-center gap-1.5">
            <span
              className={cn(
                'h-1.5 w-1.5 rounded-full',
                apiOnline == null
                  ? 'bg-ink-subtle'
                  : apiOnline
                    ? 'bg-ok'
                    : 'bg-danger',
              )}
            />
            <span className="text-ink-muted">
              {apiOnline == null
                ? 'checking'
                : apiOnline
                  ? 'connected'
                  : 'offline'}
            </span>
          </span>
        </div>
      </div>
    </aside>
  )
}
