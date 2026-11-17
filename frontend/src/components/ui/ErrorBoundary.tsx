import { Component, createRef, type ReactNode } from 'react'

// Never render/log exception text: it may contain server or identity details.
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  private heading = createRef<HTMLHeadingElement>()
  static getDerivedStateFromError() { return { failed: true } }
  componentDidMount() { if (this.state.failed) this.heading.current?.focus() }
  componentDidUpdate() { if (this.state.failed) this.heading.current?.focus() }
  render() {
    if (this.state.failed) return <section className="feedback-state error-state" role="alert">
      <h2 ref={this.heading} tabIndex={-1}>Unable to display this page</h2>
      <p>Reload PowerFlow to retrieve the current application files. If the problem continues, try again later.</p>
      <button className="secondary-button" onClick={() => window.location.reload()}>Reload PowerFlow</button>
    </section>
    return this.props.children
  }
}
