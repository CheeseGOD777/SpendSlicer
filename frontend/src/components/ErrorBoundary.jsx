import { Component } from "react";

// Last-resort guard: an unexpected API shape must show a readable card,
// not a blank white page. This is the one screen a user sees when the app
// has broken, so it is built in the board's own language rather than left
// as unstyled browser defaults. Tokens are loaded before App mounts, but
// every var() carries a literal fallback in case the stylesheet is the
// thing that failed.
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
      <div
        style={{
          minHeight: "100vh",
          background: "var(--board, #E7EAEF)",
          padding: "80px 24px",
          fontFamily: "var(--face, Manrope, system-ui, sans-serif)",
          color: "var(--ink, #0F1318)",
        }}
      >
        <div
          style={{
            maxWidth: 620,
            margin: "0 auto",
            background: "var(--panel, #FFFFFF)",
            border: "1px solid var(--rule, #D3D9E1)",
            borderRadius: "var(--r-panel, 12px)",
            overflow: "hidden",
          }}
        >
          <div style={{ padding: "20px 24px 16px", borderBottom: "1px solid var(--rule, #D3D9E1)" }}>
            <h1
              style={{
                margin: 0,
                fontFamily: "var(--face-col, Manrope, system-ui, sans-serif)",
                fontSize: 22,
                fontWeight: 600,
                letterSpacing: "-0.012em",
              }}
            >
              The dashboard stopped rendering
            </h1>
            <p style={{ margin: "8px 0 0", fontSize: 13.5, color: "var(--ink-4, #606A78)", lineHeight: 1.5 }}>
              No cost data was lost and nothing was sent anywhere. This is a display
              fault in the page itself.
            </p>
          </div>

          <div style={{ padding: "18px 24px" }}>
            <pre
              style={{
                margin: 0,
                background: "var(--panel-2, #F4F6F9)",
                border: "1px solid var(--rule, #D3D9E1)",
                borderRadius: "var(--r-mark, 3px)",
                padding: 12,
                overflowX: "auto",
                fontFamily: "var(--face-id, ui-monospace, Menlo, monospace)",
                fontSize: 12,
                color: "var(--ink-2, #262D36)",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {String(this.state.error?.message || this.state.error)}
            </pre>

            <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 18, flexWrap: "wrap" }}>
              <button
                type="button"
                onClick={() => window.location.reload()}
                style={{
                  height: 38,
                  padding: "0 17px",
                  border: "1px solid transparent",
                  borderRadius: "var(--r-ctl, 8px)",
                  background: "var(--ink, #0F1318)",
                  color: "var(--panel, #FFFFFF)",
                  fontFamily: "inherit",
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Reload the board
              </button>
              <span style={{ fontSize: 13, color: "var(--ink-4, #606A78)" }}>
                If this keeps happening, please open an issue with the message above.
              </span>
            </div>
          </div>
        </div>
      </div>
    );
  }
}
