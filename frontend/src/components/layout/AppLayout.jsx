import { Outlet } from 'react-router-dom'

import { Sidebar } from './Sidebar'
import { useDocuments } from '@/state/DocumentsContext'

export function AppLayout() {
  const { documents, loading, apiOnline } = useDocuments()

  return (
    // `relative` makes this the containing block for anything positioned
    // inside it, so `overflow-hidden` here is authoritative: a positioned
    // descendant cannot resolve against the document, escape the clip and
    // give the page a second scrollbar behind the app's own.
    <div className="relative flex h-screen overflow-hidden bg-canvas">
      <Sidebar
        documentCount={loading ? null : documents.length}
        apiOnline={apiOnline}
      />

      {/* min-w-0 so wide tables scroll inside the column instead of
          pushing the whole page sideways. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <Outlet />
      </div>
    </div>
  )
}

/**
 * The scrolling region below a page's header, with the standard page gutter.
 * Files opts out of this — an explorer manages its own panes and scrolling.
 */
export function PageBody({ children, className = '' }) {
  return (
    <main className={`min-h-0 flex-1 overflow-y-auto ${className}`}>
      <div className="mx-auto w-full max-w-6xl px-5 py-5">{children}</div>
    </main>
  )
}
