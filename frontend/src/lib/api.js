import axios from 'axios'

import { EXTENSION_MIME } from './constants'

/**
 * In development this is `/api`, which Vite proxies to FastAPI. A production
 * build points straight at the API origin via VITE_API_URL, which is why the
 * backend also sends CORS headers.
 */
const BASE_URL = import.meta.env.VITE_API_URL ?? '/api'

// Answering runs a local model. The first call after a cold start can take
// minutes, so this deliberately outlasts any sensible default.
const ASK_TIMEOUT = 600_000
const DEFAULT_TIMEOUT = 30_000
const UPLOAD_TIMEOUT = 120_000

const client = axios.create({
  baseURL: BASE_URL,
  timeout: DEFAULT_TIMEOUT,
})

/** An API failure with a message worth putting in front of a user. */
export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function describe(error) {
  if (!axios.isAxiosError(error)) {
    return new ApiError(error?.message ?? 'Unexpected error')
  }

  if (error.code === 'ECONNABORTED') {
    return new ApiError('The API did not respond in time.')
  }

  if (!error.response) {
    return new ApiError(
      'Could not reach the PORT-6 API. Is the FastAPI service running?',
    )
  }

  const { status, data } = error.response
  const detail = data?.detail

  // FastAPI validation errors arrive as a list of per-field objects.
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && item.msg ? String(item.msg) : String(item)))
      .join('; ')

    return new ApiError(messages || `Request failed (${status})`, status)
  }

  if (typeof detail === 'string') {
    return new ApiError(detail, status)
  }

  return new ApiError(`Request failed with status ${status}`, status)
}

async function call(run) {
  try {
    const response = await run()
    return response.data
  } catch (error) {
    throw describe(error)
  }
}

// --- Health ---------------------------------------------------------

export async function checkHealth() {
  try {
    await client.get('/health', { timeout: 5_000 })
    return true
  } catch {
    return false
  }
}

// --- Documents ------------------------------------------------------

export function listDocuments() {
  return call(() => client.get('/documents'))
}

export function getDocument(id) {
  return call(() => client.get(`/documents/${id}`))
}

export function getDocumentContent(id) {
  return call(() => client.get(`/documents/${id}/content`))
}

export function getDocumentStructure(id) {
  return call(() => client.get(`/documents/${id}/structure`))
}

export function deleteDocument(id) {
  return call(() => client.delete(`/documents/${id}`))
}

/** Documents that failed, or that indexed without a summary. */
export function listDocumentsNeedingAttention() {
  return call(() => client.get('/documents/attention'))
}

/** Run a document through ingestion again. The file was never deleted. */
export function reprocessDocument(id) {
  return call(() => client.post(`/documents/${id}/reprocess`))
}

export function resolveMimeType(file) {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  return EXTENSION_MIME[extension] ?? file.type ?? 'application/octet-stream'
}

export function uploadDocuments(files, onProgress) {
  const form = new FormData()

  for (const file of files) {
    // Re-wrap so the declared MIME type is one the API accepts.
    form.append(
      'files',
      new File([file], file.name, { type: resolveMimeType(file) }),
    )
  }

  return call(() =>
    client.post('/upload', form, {
      timeout: UPLOAD_TIMEOUT,
      onUploadProgress: (event) => {
        if (!onProgress || !event.total) return
        onProgress(Math.round((event.loaded / event.total) * 100))
      },
    }),
  )
}

// --- Retrieval ------------------------------------------------------

export function listModes() {
  return call(() => client.get('/modes'))
}

/**
 * `documentIds` is a hard scope: retrieval cannot reach outside it in any
 * mode. Omit or pass an empty list to search the whole library.
 */
/**
 * `chatId` continues a conversation, so a follow-up like "what about sick
 * leave?" is resolved against the turns before it. Omit it to start a new
 * one — the id comes back in `metadata.chat_id` either way.
 */
/** What a pipeline can be built from: retrievers, tools, presets. */
export function listRetrievalOptions() {
  return call(() => client.get('/pipelines'))
}

/**
 * `pipeline` names the exact strategy. Passing null for both it and
 * `topK` lets the server apply the configured defaults, which is what a
 * new chat should do — the settings are stored server-side so they hold
 * across browsers.
 */
export function ask(
  question,
  { mode, retrievers, agent, tools, topK, documentIds, chatId, signal } = {},
) {
  return call(() =>
    client.post(
      '/ask',
      {
        question,
        mode: mode ?? null,
        retrievers: retrievers?.length ? retrievers : null,
        agent: agent ?? false,
        tools: tools?.length ? tools : null,
        top_k: topK ?? null,
        document_ids: documentIds?.length ? documentIds : null,
        chat_id: chatId ?? null,
      },
      { timeout: ASK_TIMEOUT, signal },
    ),
  )
}

/**
 * Runs sequentially on the server, so the timeout scales with how many
 * were asked for rather than assuming three.
 */
export function compare(
  question,
  { modes, configurations, topK, documentIds, signal } = {},
) {
  const count = configurations?.length || modes?.length || 3

  return call(() =>
    client.post(
      '/ask/compare',
      {
        question,
        modes: modes ?? undefined,
        configurations: configurations?.length ? configurations : null,
        top_k: topK,
        document_ids: documentIds?.length ? documentIds : null,
      },
      { timeout: ASK_TIMEOUT * count, signal },
    ),
  )
}

export function search(query, mode, topK, signal) {
  return call(() =>
    client.post(
      '/search',
      { query, mode, top_k: topK },
      { timeout: ASK_TIMEOUT, signal },
    ),
  )
}

// --- Query history ---------------------------------------------------
//
// History lives on the server, so a question asked yesterday can still be
// reopened with the citations and trace it originally produced.

export function listHistory({ limit = 50, offset = 0, mode, answered } = {}) {
  return call(() =>
    client.get('/history', {
      params: { limit, offset, mode, answered },
    }),
  )
}

export function getHistoryRun(id) {
  return call(() => client.get(`/history/${id}`))
}

export function deleteHistoryRun(id) {
  return call(() => client.delete(`/history/${id}`))
}

export function clearHistory() {
  return call(() => client.delete('/history'))
}

// --- Conversations ----------------------------------------------------

export function listChats({ limit = 50, offset = 0 } = {}) {
  return call(() => client.get('/chats', { params: { limit, offset } }))
}

export function getChat(id) {
  return call(() => client.get(`/chats/${id}`))
}

export function deleteChat(id) {
  return call(() => client.delete(`/chats/${id}`))
}

// --- Settings and prompts --------------------------------------------

export function listSettings() {
  return call(() => client.get('/settings'))
}

export function updateSetting(key, value) {
  return call(() => client.put(`/settings/${key}`, { value }))
}

export function listPrompts() {
  return call(() => client.get('/prompts'))
}
