import { Fragment } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'

/** `items` are `{ label, to? }`; the last one is always the current page. */
export function Breadcrumbs({ items }) {
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center text-sm">
      {items.map((item, index) => {
        const last = index === items.length - 1

        return (
          <Fragment key={`${item.label}-${index}`}>
            {index > 0 && (
              <ChevronRight
                className="mx-1 h-3.5 w-3.5 shrink-0 text-ink-subtle"
                aria-hidden="true"
              />
            )}
            {item.to && !last ? (
              <Link
                to={item.to}
                className="shrink-0 rounded text-ink-muted transition-colors hover:text-ink"
              >
                {item.label}
              </Link>
            ) : (
              <span
                aria-current={last ? 'page' : undefined}
                className="truncate font-medium text-ink"
              >
                {item.label}
              </span>
            )}
          </Fragment>
        )
      })}
    </nav>
  )
}
