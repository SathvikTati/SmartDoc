import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api')

import * as api from '@/lib/api'

import { DefaultsDialog } from './DefaultsDialog'
import { OPTIONS, SETTINGS, renderPage } from '@/test/render'

beforeEach(() => {
  api.listRetrievalOptions.mockResolvedValue(OPTIONS)
  api.listSettings.mockResolvedValue(SETTINGS)
  api.listDocuments.mockResolvedValue([])
  api.listChats.mockResolvedValue({ total: 0, chats: [] })
})

describe('DefaultsDialog', () => {
  it('renders nothing when closed', () => {
    const { container } = renderPage(
      <DefaultsDialog open={false} onClose={() => {}} />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('renders the mode control and the chunk count', async () => {
    renderPage(<DefaultsDialog open onClose={() => {}} />)

    expect(await screen.findByText('Retrieval mode')).toBeInTheDocument()
    expect(await screen.findByLabelText('Chunks to retrieve')).toBeInTheDocument()
  })

  it('offers the three modes and nothing more', async () => {
    /* A chat picks a family. Choosing between the strategies inside one
       is what the Pipelines page is for. */
    renderPage(<DefaultsDialog open onClose={() => {}} />)

    const modes = await screen.findAllByRole('radio')

    expect(modes).toHaveLength(3)
  })

  it('preselects the configured default mode', async () => {
    renderPage(<DefaultsDialog open onClose={() => {}} />)

    const hybrid = await screen.findByRole('radio', { name: /hybrid/i })

    expect(hybrid).toBeChecked()
  })

  it('points at the Pipelines page for the finer choice', async () => {
    renderPage(<DefaultsDialog open onClose={() => {}} />)

    expect(await screen.findByRole('link', { name: 'Pipelines' })).toHaveAttribute(
      'href',
      '/pipelines',
    )
  })

  it('disables save until something changes', async () => {
    renderPage(<DefaultsDialog open onClose={() => {}} />)

    expect(await screen.findByText('Save defaults')).toBeDisabled()
  })
})
