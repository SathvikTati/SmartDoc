import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { cn } from '@/lib/format'

/**
 * Right-click menu, positioned at the pointer and nudged back on screen if
 * it would overflow. Closes on Escape, on any outside click, and on scroll —
 * the same rules a desktop file manager uses.
 *
 * `items` are `{ label, icon, onSelect, danger, disabled }`, or
 * `{ separator: true }`.
 */
export function ContextMenu({ x, y, items, onClose }) {
  const ref = useRef(null)
  const [position, setPosition] = useState({ left: x, top: y })

  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return

    const { width, height } = element.getBoundingClientRect()

    setPosition({
      left: Math.min(x, window.innerWidth - width - 8),
      top: Math.min(y, window.innerHeight - height - 8),
    })
  }, [x, y])

  useEffect(() => {
    const close = () => onClose()

    /**
     * Close on a press *outside* the menu.
     *
     * This must ignore presses inside it. Closing on every mousedown
     * unmounted the menu between the press and the release, so the click
     * never reached the item and none of the actions could be used at all.
     */
    const onPointerDown = (event) => {
      if (ref.current?.contains(event.target)) return
      onClose()
    }

    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose()
    }

    // `capture` so a press that also lands on a row closes the menu before
    // the row handles it.
    document.addEventListener('mousedown', onPointerDown, true)
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)

    return () => {
      document.removeEventListener('mousedown', onPointerDown, true)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [onClose])

  return (
    <div
      ref={ref}
      role="menu"
      style={position}
      onContextMenu={(event) => event.preventDefault()}
      className="fixed z-50 min-w-[190px] rounded-md border border-line bg-surface py-1 shadow-pop animate-fade-in"
    >
      {items.map((item, index) =>
        item.separator ? (
          <div key={`sep-${index}`} className="my-1 h-px bg-line" />
        ) : (
          <button
            key={item.label}
            type="button"
            role="menuitem"
            disabled={item.disabled}
            onClick={() => {
              onClose()
              item.onSelect?.()
            }}
            className={cn(
              'flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-sm',
              'transition-colors disabled:opacity-40 disabled:pointer-events-none',
              item.danger
                ? 'text-danger hover:bg-danger-soft'
                : 'text-ink hover:bg-raised',
            )}
          >
            {item.icon && <item.icon className="h-3.5 w-3.5 shrink-0" />}
            <span className="flex-1">{item.label}</span>
            {item.shortcut && (
              <span className="text-2xs text-ink-subtle">{item.shortcut}</span>
            )}
          </button>
        ),
      )}
    </div>
  )
}

/** Tracks right-click position and the entry the menu was opened on. */
export function useContextMenu() {
  const [menu, setMenu] = useState(null)

  return {
    menu,
    close: () => setMenu(null),
    openAt: (event, target) => {
      event.preventDefault()
      event.stopPropagation()
      setMenu({ x: event.clientX, y: event.clientY, target })
    },
  }
}
