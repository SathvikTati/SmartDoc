import { Component } from 'react'
import { AlertTriangle, RefreshCw, RotateCcw } from 'lucide-react'

import { Button } from '@/components/ui/Button'

/**
 * Catches a render crash so one broken page does not blank the whole app.
 *
 * Class component because React has no hook equivalent: `componentDidCatch`
 * and `getDerivedStateFromError` only exist on classes.
 *
 * Two recovery paths, deliberately. "Try again" clears the error and
 * re-renders in place, which is enough when the cause was one odd response.
 * "Reload" is the escape hatch when state itself is the problem.
 */
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null, info: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // Nothing collects these yet, so the console is where they land.
    console.error('Unhandled error in PORT-6 UI:', error, info)
    this.setState({ info })
  }

  reset = () => {
    this.setState({ error: null, info: null })
  }

  render() {
    const { error, info } = this.state

    if (!error) return this.props.children

    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-6">
        <div className="w-full max-w-lg">
          <div className="mb-3 flex items-center gap-2 text-danger">
            <AlertTriangle className="h-4 w-4" />
            <span className="text-sm font-medium">Something broke</span>
          </div>

          <h1 className="text-xl font-semibold tracking-tight text-ink">
            This page failed to render
          </h1>

          <p className="mt-2 text-sm leading-6 text-ink-muted">
            The error is below. Your documents and history are unaffected —
            this is a display problem, not a data one.
          </p>

          <pre className="mt-4 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded border border-line bg-raised p-3 font-mono text-xs leading-5 text-ink-muted">
            {String(error?.stack || error)}
            {info?.componentStack ? `\n${info.componentStack}` : ''}
          </pre>

          <div className="mt-5 flex gap-2">
            <Button variant="primary" onClick={this.reset}>
              <RotateCcw className="h-3.5 w-3.5" />
              Try again
            </Button>
            <Button onClick={() => window.location.reload()}>
              <RefreshCw className="h-3.5 w-3.5" />
              Reload the app
            </Button>
          </div>
        </div>
      </div>
    )
  }
}
