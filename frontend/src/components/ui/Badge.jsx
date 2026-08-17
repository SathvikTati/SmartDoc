import { AlertCircle, Check, Clock, Loader2 } from 'lucide-react'

import { cn } from '@/lib/format'

const TONES = {
  neutral: 'bg-raised text-ink-muted border-line',
  accent: 'bg-accent-soft text-accent border-accent/20',
  ok: 'bg-ok-soft text-ok border-ok/20',
  warn: 'bg-warn-soft text-warn border-warn/20',
  danger: 'bg-danger-soft text-danger border-danger/20',
}

export function Badge({ tone = 'neutral', className, children }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded border px-1.5 py-0.5',
        'text-2xs font-medium leading-4 whitespace-nowrap',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

const STATUS = {
  READY: { tone: 'ok', label: 'Ready', icon: Check },
  PROCESSING: { tone: 'accent', label: 'Processing', icon: Loader2 },
  UPLOADED: { tone: 'neutral', label: 'Queued', icon: Clock },
  FAILED: { tone: 'danger', label: 'Failed', icon: AlertCircle },
}

export function StatusBadge({ status, className }) {
  const config = STATUS[status] ?? STATUS.UPLOADED
  const Icon = config.icon

  return (
    <Badge tone={config.tone} className={className}>
      <Icon
        className={cn('h-3 w-3', status === 'PROCESSING' && 'animate-spin')}
      />
      {config.label}
    </Badge>
  )
}

/** A status as a bare dot, for dense rows where a full badge is too loud. */
export function StatusDot({ status, className }) {
  const tone = {
    READY: 'bg-ok',
    PROCESSING: 'bg-accent animate-pulse',
    UPLOADED: 'bg-ink-subtle',
    FAILED: 'bg-danger',
  }[status]

  return (
    <span
      title={STATUS[status]?.label ?? status}
      className={cn('inline-block h-1.5 w-1.5 shrink-0 rounded-full', tone, className)}
    />
  )
}
