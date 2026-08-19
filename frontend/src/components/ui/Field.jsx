import { forwardRef } from 'react'
import { ChevronDown } from 'lucide-react'

import { cn } from '@/lib/format'

const CONTROL =
  'w-full rounded border border-line bg-surface text-sm text-ink ' +
  'placeholder:text-ink-subtle transition-colors ' +
  'hover:border-line-strong focus:border-accent ' +
  'disabled:opacity-60 disabled:pointer-events-none'

export function Label({ htmlFor, children, className }) {
  return (
    <label
      htmlFor={htmlFor}
      className={cn(
        'block text-2xs font-medium uppercase tracking-wide text-ink-subtle',
        className,
      )}
    >
      {children}
    </label>
  )
}

export const Input = forwardRef(function Input(
  { icon, trailing, className, ...props },
  ref,
) {
  return (
    <div className="relative flex items-center">
      {icon && (
        <span className="pointer-events-none absolute left-2.5 flex text-ink-subtle">
          {icon}
        </span>
      )}
      <input
        ref={ref}
        className={cn(
          CONTROL,
          'h-8 px-2.5',
          icon && 'pl-8',
          trailing && 'pr-8',
          className,
        )}
        {...props}
      />
      {trailing && (
        <span className="absolute right-2.5 flex text-ink-subtle">
          {trailing}
        </span>
      )}
    </div>
  )
})

export const Textarea = forwardRef(function Textarea(
  { className, ...props },
  ref,
) {
  return (
    <textarea
      ref={ref}
      className={cn(CONTROL, 'resize-y px-2.5 py-2 leading-6', className)}
      {...props}
    />
  )
})

/**
 * Takes either a flat `options` list or children.
 *
 * `options` covers the common case in one prop. Children exist because a
 * flat list cannot express `<optgroup>`, and the pipeline selectors group
 * by family — passing children used to render an empty select and then
 * crash on `options.map`.
 */
export const Select = forwardRef(function Select(
  { options, className, children, ...props },
  ref,
) {
  return (
    <div className="relative flex items-center">
      <select
        ref={ref}
        className={cn(CONTROL, 'h-8 appearance-none pl-2.5 pr-7', className)}
        {...props}
      >
        {options
          ? options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))
          : children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 h-3.5 w-3.5 text-ink-subtle" />
    </div>
  )
})

/**
 * Radio group styled as a segmented control. Kept as real radios so arrow
 * keys move between options and screen readers announce the group.
 */
export function SegmentedControl({ name, value, options, onChange, className }) {
  return (
    <div
      role="radiogroup"
      aria-label={name}
      className={cn(
        'inline-flex rounded border border-line bg-raised p-0.5',
        className,
      )}
    >
      {options.map((option) => {
        const selected = option.value === value

        return (
          <label
            key={option.value}
            title={option.hint}
            className={cn(
              // `relative` is load-bearing, not cosmetic. The input below
              // is `sr-only`, which is `position: absolute` with no offsets
              // — so without a positioned parent its containing block is
              // the document, and `overflow: hidden` on the app shell does
              // not clip a descendant whose containing block is an ancestor
              // of the clipping element. The inputs escaped the shell,
              // landed at their static position in document coordinates and
              // made the whole page scrollable; scrolling a new turn into
              // view then dragged the entire app down. Anchoring them to the
              // label keeps them inside the scroll container they belong to.
              'relative cursor-pointer rounded px-2.5 py-1 text-xs font-medium',
              'transition-colors select-none',
              selected
                ? 'bg-surface text-ink shadow-panel'
                : 'text-ink-muted hover:text-ink',
            )}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={selected}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            {option.label}
          </label>
        )
      })}
    </div>
  )
}
