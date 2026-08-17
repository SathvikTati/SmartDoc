/**
 * Join class names, dropping anything falsy. Takes anything so the common
 * `condition && 'class'` guard works whatever type `condition` happens to be.
 */
export function cn(...values) {
  return values
    .filter((value) => typeof value === 'string' && value !== '')
    .join(' ')
}

export function formatBytes(bytes) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`

  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(kb < 10 ? 1 : 0)} KB`

  return `${(kb / 1024).toFixed(1)} MB`
}

export function formatLatency(ms) {
  if (ms == null) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

export function formatCount(value, noun) {
  return `${value} ${noun}${value === 1 ? '' : 's'}`
}

export function formatDate(iso) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'

  return date.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

export function formatDateTime(iso) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'

  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatRelative(iso) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'

  const seconds = Math.round((Date.now() - date.getTime()) / 1000)

  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`

  return formatDate(iso)
}

const TYPE_LABELS = {
  pdf: 'PDF',
  docx: 'DOCX',
  doc: 'DOC',
  txt: 'Text',
  md: 'Markdown',
  markdown: 'Markdown',
}

export function extensionOf(filename) {
  return filename?.split('.').pop()?.toLowerCase() ?? ''
}

/** The `file_type` column holds a MIME type; show the extension instead. */
export function fileKindLabel(document) {
  const extension = extensionOf(document.filename)
  return TYPE_LABELS[extension] ?? extension.toUpperCase() ?? 'File'
}

/** Strip the `[n]` markers, e.g. to measure how much prose an answer has. */
export function stripCitations(text) {
  return text.replace(/\[\d+\]/g, '').trim()
}

export function truncate(text, limit) {
  if (!text || text.length <= limit) return text
  return `${text.slice(0, limit).trimEnd()}…`
}

/**
 * A Chroma distance and a BM25 score both arrive in `score`, and they mean
 * opposite things, so the label has to come from which retriever found it.
 */
export function scoreLabel(sources) {
  if (sources?.length === 1 && sources[0] === 'keyword') return 'BM25'
  return 'distance'
}
