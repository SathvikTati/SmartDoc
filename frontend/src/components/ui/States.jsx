import { AlertTriangle, RefreshCw } from 'lucide-react'

import { Button } from './Button'
import { cn } from '@/lib/format'

/**
 * Empty states are text and one action, deliberately. No illustrations:
 * they take vertical space and say nothing the sentence does not.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center px-6 py-14 text-center',
        className,
      )}
    >
      {Icon && (
        <Icon className="mb-3 h-5 w-5 text-ink-subtle" aria-hidden="true" />
      )}
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && (
        <p className="mt-1 max-w-sm text-sm text-ink-muted">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
  className,
}) {
  return (
    <div
      role="alert"
      className={cn(
        'flex items-start gap-3 rounded-md border border-danger/25 bg-danger-soft px-3 py-2.5',
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink">{title}</p>
        <p className="mt-0.5 break-words text-sm text-ink-muted">{message}</p>
      </div>
      {onRetry && (
        <Button size="sm" onClick={onRetry} className="shrink-0">
          <RefreshCw className="h-3.5 w-3.5" />
          Retry
        </Button>
      )}
    </div>
  )
}

export function Skeleton({ className }) {
  return <div className={cn('skeleton', className)} />
}

/** Table placeholder that keeps the row rhythm while data loads. */
export function SkeletonRows({ rows = 6, columns }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <tr key={rowIndex} className="border-t border-line">
          {columns.map((width, columnIndex) => (
            <td key={columnIndex} className="px-3 py-2">
              <Skeleton className={cn('h-3.5', width)} />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

export function SkeletonBlock({ lines = 3 }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton
          key={index}
          className={cn('h-3.5', index === lines - 1 ? 'w-2/3' : 'w-full')}
        />
      ))}
    </div>
  )
}
