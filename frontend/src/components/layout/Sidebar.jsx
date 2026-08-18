import { Link, NavLink } from 'react-router-dom'
import { Columns3, FolderOpen, MessageSquareText, Search } from 'lucide-react'

import { cn, truncate } from '@/lib/format'
import { useInvestigations } from '@/state/InvestigationsContext'

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

const RECENT_SHOWN = 8

export function Sidebar({ documentCount, apiOnline }) {
  const { chats, total, open } = useInvestigations()

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex h-14 items-center gap-2 px-4">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-ink">
          <span className="text-[10px] font-bold leading-none text-surface">
            P6
          </span>
        </div>
        <span className="text-base font-semibold tracking-tight">PORT-6</span>
      </div>

      <nav className="space-y-0.5 px-2">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            title={item.hint}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm',
                'transition-colors duration-100',
                isActive
                  ? 'bg-accent-soft font-medium text-accent'
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
                <span className="flex-1">{item.label}</span>
                {item.to === '/files' && documentCount != null && (
                  <span className="tnum text-xs text-ink-subtle">
                    {documentCount}
                  </span>
                )}
                {item.to === '/ask' && total > 0 && (
                  <span className="tnum text-xs text-ink-subtle">{total}</span>
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Recent conversations, so returning to one is a click rather
          than a trip through the history list. */}
      {chats.length > 0 && (
        <div className="mt-6 min-h-0 flex-1 overflow-y-auto px-2">
          <div className="flex items-center justify-between px-2.5 pb-1">
            <p className="text-2xs font-medium uppercase tracking-wider text-ink-subtle">
              Recent
            </p>
            {total > RECENT_SHOWN && (
              <Link
                to="/history"
                className="rounded text-2xs text-ink-subtle transition-colors hover:text-ink"
              >
                View all
              </Link>
            )}
          </div>

          <ul>
            {chats.slice(0, RECENT_SHOWN).map((chat) => (
              <li key={chat.id}>
                <Link
                  to="/ask"
                  onClick={() => void open(chat.id)}
                  title={`${chat.title} (${chat.turn_count} questions)`}
                  className="flex items-baseline gap-1.5 rounded-lg px-2.5 py-1.5 text-sm leading-5 text-ink-muted transition-colors hover:bg-raised hover:text-ink"
                >
                  <span className="min-w-0 flex-1 truncate">
                    {truncate(chat.title, 42)}
                  </span>
                  {chat.turn_count > 1 && (
                    <span className="tnum shrink-0 text-2xs text-ink-subtle">
                      {chat.turn_count}
                    </span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className={cn('px-3 pb-3', chats.length === 0 && 'mt-auto')}>
        <div className="flex items-center gap-2.5 border-t border-line pt-3">
          <span
            className={cn(
              'h-1.5 w-1.5 shrink-0 rounded-full',
              apiOnline == null
                ? 'bg-ink-subtle'
                : apiOnline
                  ? 'bg-ok'
                  : 'bg-danger',
            )}
          />
          <span className="text-xs text-ink-muted">
            {apiOnline == null
              ? 'Connecting…'
              : apiOnline
                ? 'API connected'
                : 'API offline'}
          </span>
        </div>
      </div>
    </aside>
  )
}
