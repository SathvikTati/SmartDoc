import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api')

import * as api from '@/lib/api'

import { AskPage } from './AskPage'
import { ComparePage } from './ComparePage'
import { HistoryPage } from './HistoryPage'
import { NotFoundPage } from './NotFoundPage'
import { SearchPage } from './SearchPage'
import { OPTIONS, SETTINGS, renderPage } from '@/test/render'

/**
 * Does each page render at all.
 *
 * Not a substitute for using the app, but the build compiles JSX without
 * ever executing it — a component handed children when it expected an
 * `options` array type-checks fine and throws on first paint. These catch
 * that class of thing.
 */
beforeEach(() => {
  api.listRetrievalOptions.mockResolvedValue(OPTIONS)
  api.listSettings.mockResolvedValue(SETTINGS)
  api.listDocuments.mockResolvedValue([])
  api.listChats.mockResolvedValue({ total: 0, chats: [] })
  api.listHistory.mockResolvedValue({ total: 0, runs: [] })
  api.listModes.mockResolvedValue([])
})

describe('page smoke tests', () => {
  it('renders Ask', async () => {
    renderPage(<AskPage />, { route: '/ask' })

    expect(
      await screen.findByText('What do you need to know?'),
    ).toBeInTheDocument()
  })

  it('renders Ask with the mode pill showing the configured default', async () => {
    renderPage(<AskPage />, { route: '/ask' })

    expect(await screen.findByText('hybrid')).toBeInTheDocument()
  })

  it('renders Compare', async () => {
    renderPage(<ComparePage />, { route: '/compare' })

    expect(await screen.findAllByText(/Compare/i)).not.toHaveLength(0)
  })

  it('renders Search', async () => {
    renderPage(<SearchPage />, { route: '/search' })

    expect(await screen.findAllByText(/Search/i)).not.toHaveLength(0)
  })

  it('renders History', async () => {
    renderPage(<HistoryPage />, { route: '/history' })

    expect(await screen.findAllByText(/History/i)).not.toHaveLength(0)
  })

  it('renders the 404', () => {
    renderPage(<NotFoundPage />, { route: '/nonsense' })

    expect(screen.getAllByText(/404|not found/i).length).toBeGreaterThan(0)
  })
})
