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

export function ask(question, mode, topK, signal) {
  return call(() =>
    client.post(
      '/ask',
      { question, mode, top_k: topK },
      { timeout: ASK_TIMEOUT, signal },
    ),
  )
}

export function compare(question, modes, topK, signal) {
  return call(() =>
    client.post(
      '/ask/compare',
      { question, modes, top_k: topK },
      // Three pipelines run back to back against the same local model.
      { timeout: ASK_TIMEOUT * 3, signal },
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
