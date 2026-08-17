import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, CircleDashed, Loader2, Upload, UploadCloud, X } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { StatusBadge } from '@/components/ui/Badge'
import { ErrorState } from '@/components/ui/States'
import { FileIcon } from '@/components/FileIcon'
import * as api from '@/lib/api'
import {
  ACCEPTED_EXTENSIONS,
  MAX_FILES,
  MAX_FILE_SIZE,
} from '@/lib/constants'
import { cn, extensionOf, formatBytes } from '@/lib/format'

/** Checked here only to fail fast; the API is still the authority. */
function inspect(file, existing) {
  const extension = extensionOf(file.name)

  if (!ACCEPTED_EXTENSIONS.includes(extension)) {
    return { file, problem: `.${extension || '?'} is not a supported format` }
  }

  if (file.size > MAX_FILE_SIZE) {
    return { file, problem: `${formatBytes(file.size)} exceeds the 5 MB limit` }
  }

  if (file.size === 0) {
    return { file, problem: 'File is empty' }
  }

  if (existing.some((staged) => staged.file.name === file.name)) {
    return { file, problem: 'Already selected' }
  }

  return { file, problem: null }
}

/**
 * The gates the API runs *before* it responds. A 200 means every one of
 * them passed, so they are shown complete on a successful upload rather
 * than animated as if they were being polled.
 */
const ACCEPTANCE_GATES = [
  'File count and size',
  'Declared MIME type',
  'Magic-byte signature',
  'Duplicate detection',
  'Content extraction',
]

/**
 * What ingestion does after the response. The API reports these as one
 * PROCESSING state, so they are shown as a group rather than ticked off
 * individually — inventing per-stage progress would be a lie.
 */
const INGESTION_STAGES = [
  'Section-aware chunking',
  'Embedding and indexing',
  'Summarisation',
]

function StageRow({ label, state }) {
  const Icon =
    state === 'done'
      ? Check
      : state === 'active'
        ? Loader2
        : state === 'failed'
          ? X
          : CircleDashed

  return (
    <li className="flex items-center gap-2 text-xs">
      <Icon
        className={cn(
          'h-3.5 w-3.5 shrink-0',
          state === 'done' && 'text-ok',
          state === 'active' && 'animate-spin text-accent',
          state === 'failed' && 'text-danger',
          state === 'pending' && 'text-ink-subtle/60',
        )}
      />
      <span className={cn(state === 'pending' ? 'text-ink-subtle' : 'text-ink-muted')}>
        {label}
      </span>
    </li>
  )
}

function IngestionCard({ filename, status, errorMessage }) {
  const ready = status === 'READY'
  const failed = status === 'FAILED'

  return (
    <div className="rounded border border-line px-3 py-2.5">
      <div className="mb-2 flex items-center gap-2">
        <FileIcon filename={filename} />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {filename}
        </span>
        <StatusBadge status={status} />
      </div>

      <ul className="grid gap-1 sm:grid-cols-2">
        {ACCEPTANCE_GATES.map((gate) => (
          <StageRow key={gate} label={gate} state="done" />
        ))}
        {INGESTION_STAGES.map((stage) => (
          <StageRow
            key={stage}
            label={stage}
            state={
              ready
                ? 'done'
                : failed
                  ? 'failed'
                  : status === 'PROCESSING'
                    ? 'active'
                    : 'pending'
            }
          />
        ))}
      </ul>

      {failed && errorMessage && (
        <p className="mt-2 break-words text-xs text-danger">{errorMessage}</p>
      )}
    </div>
  )
}

export function UploadDialog({ open, onClose, documents, onUploaded }) {
  const [staged, setStaged] = useState([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [submittedIds, setSubmittedIds] = useState(null)

  const inputRef = useRef(null)
  const dialogRef = useRef(null)

  const close = useCallback(() => {
    setStaged([])
    setError(null)
    setUploading(false)
    setSubmittedIds(null)
    setDragging(false)
    onClose()
  }, [onClose])

  useEffect(() => {
    if (!open) return

    const onKeyDown = (event) => {
      if (event.key === 'Escape' && !uploading) close()
    }

    document.addEventListener('keydown', onKeyDown)
    dialogRef.current?.focus()

    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, uploading, close])

  const addFiles = useCallback((incoming) => {
    setError(null)
    setStaged((current) => {
      const next = [...current]

      for (const file of Array.from(incoming)) {
        if (next.length >= MAX_FILES) {
          setError(`At most ${MAX_FILES} files can be uploaded at a time.`)
          break
        }
        next.push(inspect(file, next))
      }

      return next
    })
  }, [])

  const valid = staged.filter((item) => !item.problem)

  async function submit() {
    if (!valid.length) return

    setUploading(true)
    setError(null)

    try {
      const created = await api.uploadDocuments(valid.map((item) => item.file))
      setSubmittedIds(created.map((item) => item.id))
      // The explorer behind the dialog should start polling immediately.
      onUploaded()
    } catch (caught) {
      setError(caught?.message ?? 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  if (!open) return null

  // Once submitted, follow the real documents so status comes from the API
  // rather than from anything this component assumed.
  const tracked = submittedIds
    ? submittedIds
        .map((id) => documents.find((document) => document.id === id))
        .filter(Boolean)
    : []

  const allSettled =
    tracked.length > 0 &&
    tracked.every(
      (document) => document.status === 'READY' || document.status === 'FAILED',
    )

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/20 p-4 pt-[8vh] animate-fade-in"
      onClick={(event) => {
        if (event.target === event.currentTarget && !uploading) close()
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Upload documents"
        tabIndex={-1}
        className="flex max-h-[80vh] w-full max-w-xl flex-col rounded-lg border border-line bg-surface shadow-pop animate-slide-up"
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-sm font-medium">
            {submittedIds ? 'Ingesting documents' : 'Upload documents'}
          </h2>
          <button
            type="button"
            onClick={close}
            disabled={uploading}
            aria-label="Close"
            className="rounded p-1 text-ink-subtle transition-colors hover:bg-raised hover:text-ink disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
          {error && <ErrorState title="Upload failed" message={error} />}

          {submittedIds ? (
            <>
              {tracked.map((document) => (
                <IngestionCard
                  key={document.id}
                  filename={document.filename}
                  status={document.status}
                  errorMessage={document.error_message}
                />
              ))}
              <p className="text-xs text-ink-subtle">
                The three background stages are reported by the API as a
                single processing state, so they advance together rather than
                one at a time.
              </p>
            </>
          ) : (
            <>
              <div
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragging(false)
                  addFiles(event.dataTransfer.files)
                }}
                className={cn(
                  'rounded-md border border-dashed px-4 py-8 text-center transition-colors',
                  dragging
                    ? 'border-accent bg-accent-soft'
                    : 'border-line-strong bg-raised/50',
                )}
              >
                <UploadCloud className="mx-auto mb-2 h-5 w-5 text-ink-subtle" />
                <p className="text-sm text-ink">
                  Drag files here, or{' '}
                  <button
                    type="button"
                    onClick={() => inputRef.current?.click()}
                    className="rounded font-medium text-accent underline-offset-2 hover:underline"
                  >
                    browse
                  </button>
                </p>
                <p className="mt-1 text-xs text-ink-subtle">
                  PDF, DOCX, DOC, TXT, Markdown · up to {MAX_FILES} files · 5 MB
                  each
                </p>
                <input
                  ref={inputRef}
                  type="file"
                  multiple
                  accept=".pdf,.docx,.doc,.txt,.md,.markdown"
                  className="hidden"
                  onChange={(event) => {
                    if (event.target.files) addFiles(event.target.files)
                    event.target.value = ''
                  }}
                />
              </div>

              {staged.length > 0 && (
                <ul className="divide-y divide-line rounded border border-line">
                  {staged.map((item, index) => (
                    <li
                      key={`${item.file.name}-${index}`}
                      className="flex items-center gap-2.5 px-3 py-2"
                    >
                      <FileIcon filename={item.file.name} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm">{item.file.name}</p>
                        <p
                          className={cn(
                            'text-xs',
                            item.problem ? 'text-danger' : 'text-ink-subtle',
                          )}
                        >
                          {item.problem ?? formatBytes(item.file.size)}
                        </p>
                      </div>
                      <button
                        type="button"
                        aria-label={`Remove ${item.file.name}`}
                        onClick={() =>
                          setStaged((current) =>
                            current.filter((_, position) => position !== index),
                          )
                        }
                        className="rounded p-1 text-ink-subtle transition-colors hover:bg-raised hover:text-ink"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-3">
          <span className="text-xs text-ink-subtle">
            {submittedIds
              ? allSettled
                ? 'Ingestion complete.'
                : 'Ingesting — this stays live if you close the dialog.'
              : `${valid.length} of ${staged.length} ready to upload`}
          </span>

          <div className="flex gap-2">
            <Button onClick={close} disabled={uploading}>
              {submittedIds ? 'Done' : 'Cancel'}
            </Button>
            {!submittedIds && (
              <Button
                variant="primary"
                onClick={() => void submit()}
                loading={uploading}
                disabled={!valid.length}
              >
                {!uploading && <Upload className="h-3.5 w-3.5" />}
                Upload {valid.length || ''}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
