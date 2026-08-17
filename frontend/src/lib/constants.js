/**
 * Values the API defines, restated here so the UI can label and validate
 * without a round trip. Anything that changes in the backend has to change
 * here too — these are copies, not a contract.
 */

/** Document.status, from the ingestion pipeline. */
export const STATUS = {
  UPLOADED: 'UPLOADED',
  PROCESSING: 'PROCESSING',
  READY: 'READY',
  FAILED: 'FAILED',
}

/** Ingestion is still running for these. */
export const PENDING_STATUSES = [STATUS.UPLOADED, STATUS.PROCESSING]

/** The three answering pipelines exposed by GET /modes. */
export const RAG_MODES = ['naive', 'hybrid', 'agentic']

/** The retrievers POST /search can run on their own. */
export const SEARCH_MODES = ['semantic', 'keyword', 'hybrid']

// Mirrors upload.max_files / max_file_size_bytes in config.yaml.
export const MAX_FILES = 5
export const MAX_FILE_SIZE = 5 * 1024 * 1024

export const ACCEPTED_EXTENSIONS = ['pdf', 'docx', 'doc', 'txt', 'md', 'markdown']

/**
 * Browsers frequently report Markdown as text/plain or supply nothing at
 * all, and the API validates the declared type, so the extension decides.
 */
export const EXTENSION_MIME = {
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  doc: 'application/msword',
  txt: 'text/plain',
  md: 'text/markdown',
  markdown: 'text/markdown',
}
