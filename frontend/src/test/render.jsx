import { MemoryRouter } from 'react-router-dom'
import { render } from '@testing-library/react'

import { DocumentsProvider } from '@/state/DocumentsContext'
import { InvestigationsProvider } from '@/state/InvestigationsContext'
import { SettingsProvider } from '@/state/SettingsContext'

/** What GET /pipelines returns, shaped like the real thing. */
/** What GET /pipelines returns, shaped like the real thing. */
export const OPTIONS = {
  retrievers: [
    { id: 'semantic', label: 'Semantic', description: 'Embedding similarity.' },
    { id: 'keyword', label: 'Keyword', description: 'BM25 over the chunks.' },
    {
      id: 'hierarchical',
      label: 'Hierarchical',
      description: 'Document, then section, then chunk.',
    },
  ],
  tools: [
    {
      id: 'document_lookup',
      label: 'Document lookup',
      description: 'Lists the library.',
      enabled: true,
    },
    {
      id: 'calculate',
      label: 'Calculator',
      description: 'Arithmetic the answer depends on.',
      enabled: true,
    },
    {
      id: 'web_search',
      label: 'Web search',
      description: 'The public internet.',
      enabled: false,
    },
  ],
  presets: [
    {
      name: 'semantic',
      label: 'Semantic only',
      id: 'semantic',
      retrievers: ['semantic'],
      agent: false,
      planner: true,
      extra_tools: [],
      allowed_tools: ['semantic_search', 'aggregate_search'],
      family: 'naive',
      method: 'semantic vector search (top-k)',
    },
    {
      name: 'hybrid',
      label: 'Hybrid',
      id: 'semantic+keyword+hierarchical',
      retrievers: ['semantic', 'keyword', 'hierarchical'],
      agent: false,
      planner: true,
      extra_tools: [],
      allowed_tools: ['semantic_search', 'keyword_search'],
      family: 'hybrid',
      method: 'semantic + keyword + hierarchical, RRF fused',
    },
  ],
  default_mode: 'hybrid',
}

export const SETTINGS = [
  { key: 'defaults.mode', value: 'hybrid' },
  { key: 'defaults.top_k', value: 5 },
]

/**
 * Renders inside the providers a page actually runs in.
 *
 * Every page reads at least one context, so rendering one bare only ever
 * tests the error path.
 */
export function renderPage(ui, { route = '/' } = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <SettingsProvider>
        <DocumentsProvider>
          <InvestigationsProvider>{ui}</InvestigationsProvider>
        </DocumentsProvider>
      </SettingsProvider>
    </MemoryRouter>,
  )
}
