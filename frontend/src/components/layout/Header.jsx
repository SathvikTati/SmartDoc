import { useState } from 'react'
import { Settings2 } from 'lucide-react'

import { Breadcrumbs } from './Breadcrumbs'
import { DefaultsDialog } from '@/components/settings/DefaultsDialog'
import { useSettings } from '@/state/SettingsContext'

/**
 * Deliberately thin: location on the left, at most one or two page actions
 * on the right. Page-level controls belong in the page's own toolbar.
 *
 * Defaults are the exception. They apply to every new chat regardless of
 * which page you started it from, so they belong to the shell rather than
 * to any one page.
 */
export function Header({ crumbs, actions }) {
  const [settingsOpen, setSettingsOpen] = useState(false)

  const { defaults } = useSettings()

  return (
    <>
      <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line bg-header px-5">
        <Breadcrumbs items={crumbs} />

        <div className="flex shrink-0 items-center gap-1.5">
          {actions}

          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            title={`New chats use ${defaults.mode} retrieval, top ${defaults.topK}`}
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-ink-muted transition-colors hover:bg-raised hover:text-ink"
          >
            <Settings2 className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Defaults</span>
          </button>
        </div>
      </header>

      <DefaultsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </>
  )
}
