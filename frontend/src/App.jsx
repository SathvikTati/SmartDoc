import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { ErrorBoundary } from '@/components/ErrorBoundary'
import { AppLayout } from '@/components/layout/AppLayout'
import { AskPage } from '@/pages/AskPage'
import { ComparePage } from '@/pages/ComparePage'
import { DocumentDetailPage } from '@/pages/DocumentDetailPage'
import { FilesPage } from '@/pages/FilesPage'
import { HistoryPage } from '@/pages/HistoryPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { SearchPage } from '@/pages/SearchPage'
import { DocumentsProvider } from '@/state/DocumentsContext'
import { InvestigationsProvider } from '@/state/InvestigationsContext'

export default function App() {
  return (
    // Outside the router so a crash in the shell itself is caught too, not
    // only one inside a route.
    <ErrorBoundary>
      <BrowserRouter>
        <DocumentsProvider>
          <InvestigationsProvider>
            <Routes>
              {/* Ask is the home page: asking questions is what the
                  product is for, and the library is one click away. */}
              <Route path="/" element={<Navigate to="/ask" replace />} />

              <Route element={<AppLayout />}>
                <Route path="/ask" element={<AskPage />} />
                <Route path="/history" element={<HistoryPage />} />
                <Route path="/files" element={<FilesPage />} />
                <Route
                  path="/files/:documentId"
                  element={<DocumentDetailPage />}
                />
                <Route path="/search" element={<SearchPage />} />
                <Route path="/compare" element={<ComparePage />} />
              </Route>

              {/* Outside the shell: a 404 has no breadcrumb trail. */}
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </InvestigationsProvider>
        </DocumentsProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
