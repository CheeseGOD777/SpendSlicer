import { Component } from "react";

// Last-resort guard: an unexpected API shape must show a readable card,
// not a blank white page.
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ maxWidth: 560, margin: "80px auto", fontFamily: "system-ui, sans-serif" }}>
        <h1 style={{ fontSize: 20 }}>Something went wrong rendering the dashboard</h1>
        <pre style={{ background: "#f4f2ee", padding: 12, borderRadius: 6, overflowX: "auto", fontSize: 12 }}>
          {String(this.state.error?.message || this.state.error)}
        </pre>
        <button type="button" onClick={() => window.location.reload()} style={{ padding: "6px 14px", cursor: "pointer" }}>
          Reload
        </button>
        <p style={{ fontSize: 13, opacity: 0.7 }}>
          If this keeps happening, please open an issue with the message above.
        </p>
      </div>
    );
  }
}
