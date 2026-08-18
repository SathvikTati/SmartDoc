import { Breadcrumbs } from './Breadcrumbs'

/**
 * Deliberately thin: location on the left, at most one or two page actions
 * on the right. Page-level controls belong in the page's own toolbar.
 */
export function Header({ crumbs, actions }) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line bg-header px-5">
      <Breadcrumbs items={crumbs} />
      {actions && (
        <div className="flex shrink-0 items-center gap-1.5">{actions}</div>
      )}
    </header>
  )
}
