import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api')

import * as api from '@/lib/api'

import { PipelinesPage } from './PipelinesPage'
import { OPTIONS, SETTINGS, renderPage } from '@/test/render'

beforeEach(() => {
  api.listRetrievalOptions.mockResolvedValue(OPTIONS)
  api.listSettings.mockResolvedValue(SETTINGS)
  api.listDocuments.mockResolvedValue([])
  api.listChats.mockResolvedValue({ total: 0, chats: [] })
})

describe('PipelinesPage', () => {
  it('renders once the options load', async () => {
    renderPage(<PipelinesPage />, { route: '/pipelines' })

    expect(
      await screen.findByPlaceholderText(/Ask the same question/),
    ).toBeInTheDocument()
  })

  it('starts with two pipelines to compare', async () => {
    renderPage(<PipelinesPage />, { route: '/pipelines' })

    expect(await screen.findByText('Pipeline 1')).toBeInTheDocument()
    expect(await screen.findByText('Pipeline 2')).toBeInTheDocument()
  })

  it('offers every retriever in each builder', async () => {
    renderPage(<PipelinesPage />, { route: '/pipelines' })

    for (const one of OPTIONS.retrievers) {
      // One per builder.
      expect(await screen.findAllByText(one.label)).toHaveLength(2)
    }
  })

  it('hides the tool picker until an agent is added', async () => {
    /* Tools are meaningless without an agent to use them. */
    renderPage(<PipelinesPage />, { route: '/pipelines' })

    await screen.findByText('Pipeline 1')

    expect(screen.queryByText('Extra tools')).not.toBeInTheDocument()
  })

  it('offers the presets as shortcuts', async () => {
    renderPage(<PipelinesPage />, { route: '/pipelines' })

    expect(await screen.findByText('Start from')).toBeInTheDocument()
    expect(await screen.findByText('Semantic only')).toBeInTheDocument()
    expect(await screen.findByText('Hybrid')).toBeInTheDocument()
  })

  it('renders the Top K select with its options', async () => {
    renderPage(<PipelinesPage />, { route: '/pipelines' })

    const select = await screen.findByRole('combobox')

    expect(select.querySelectorAll('option').length).toBeGreaterThan(0)
  })

  it('surfaces a failure to load the options instead of blanking', async () => {
    api.listRetrievalOptions.mockRejectedValue(new Error('API is down'))

    renderPage(<PipelinesPage />, { route: '/pipelines' })

    await waitFor(() =>
      expect(screen.getByText(/API is down/)).toBeInTheDocument(),
    )
  })
})
