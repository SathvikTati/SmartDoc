import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ArrowLeft, MessageSquareText } from 'lucide-react'

import { Button } from '@/components/ui/Button'

export function NotFoundPage() {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-6">
      <div className="w-full max-w-md">
        <p className="tnum text-sm font-medium text-ink-subtle">404</p>

        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink">
          Page not found
        </h1>

        <p className="mt-2 text-sm leading-6 text-ink-muted">
          The page you're looking for doesn't exist or may have been moved.
        </p>

        <p className="mt-3 break-all rounded border border-line bg-raised px-2.5 py-1.5 font-mono text-xs text-ink-subtle">
          {location.pathname}
        </p>

        <div className="mt-6 flex gap-2">
          {/* Router navigation, not a reload: the app shell and any
              in-session investigations stay alive. */}
          <Button variant="primary" onClick={() => navigate('/ask')}>
            <MessageSquareText className="h-3.5 w-3.5" />
            Go to Ask
          </Button>

          <Button onClick={() => navigate(-1)}>
            <ArrowLeft className="h-3.5 w-3.5" />
            Go back
          </Button>
        </div>

        <nav className="mt-8 border-t border-line pt-4">
          <p className="mb-2 text-2xs font-medium uppercase tracking-wide text-ink-subtle">
            Elsewhere
          </p>
          <ul className="space-y-1">
            {[
              { to: '/ask', label: 'Ask — cited answers' },
              { to: '/files', label: 'Files — the document library' },
              { to: '/search', label: 'Search — raw chunk retrieval' },
              { to: '/compare', label: 'Compare — modes side by side' },
            ].map((item) => (
              <li key={item.to}>
                <Link
                  to={item.to}
                  className="rounded text-sm text-accent hover:underline"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </div>
  )
}
