# Changelog

Notable changes to SpendSlicer. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[semver](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-09-07

First public release.

Numbered 1.0.0 rather than 0.x deliberately. The surface people actually
depend on — the CLI, the environment variables and the HTTP endpoints — is
settled, and the accuracy work still ahead makes estimates *better* rather
than breaking anyone's integration. A 0.x label would have understated how
usable this is while buying no real freedom.

### Added

- **Native desktop builds** for macOS (`.dmg`, Apple Silicon and Intel) and
  Windows (`.zip`). The app binds an OS-assigned loopback port, runs the server
  in-process, and renders the dashboard in the platform webview — WebKit on
  macOS, WebView2 on Windows — falling back to the default browser when no
  webview backend exists. Builds are currently unsigned; see
  [docs/DESKTOP.md](docs/DESKTOP.md).
- **Per-launch auth token in the desktop builds.** Each run mints a random
  `SPENDSLICER_AUTH_TOKEN` and passes it to the webview. A loopback bind alone was
  not enough: the CSRF check only covers state-changing methods, so any page in
  the user's browser could fire cross-origin `GET`s at the port and spend real
  Cost Explorer money.
- **Documentation**: architecture, configuration reference, least-privilege IAM
  policy, CUR setup, desktop install/build, contributing guide, security policy.
- **CI** on Python 3.10–3.13 plus frontend tests, and a PyInstaller smoke build
  on macOS and Windows so packaging breakage surfaces on PRs. A gate fails the
  build when the committed dashboard bundle is stale relative to `frontend/src`.

### Fixed

- **The dashboard 404'd outside a git checkout.** The React bundle was resolved
  relative to the repo root, so an installed wheel looked for it inside
  site-packages and a frozen build failed outright. Vite now builds into
  `spendslicer/web/static` and a resolver handles all three layouts.
- **Startup blocked on AWS.** Profile resolution ran inline in the lifespan,
  holding the port closed for ~15s with five profiles — far longer with an
  expired SSO session or a downed VPN. It now warms in the background: 15s → 1.1s.
- **`serve()` defaulted to `reload=True`**, which both run scripts used. Reload
  re-execs via a watcher and breaks frozen builds. Now opt-in via
  `SPENDSLICER_RELOAD=1`.
- **CUR ingest could hang shutdown**, sitting in `time.sleep` for up to 6 hours
  with no shutdown hook. It now waits on an event the lifespan sets.
- The Pricing API cache measured TTL with `datetime.utcnow().timestamp()`, which
  reads a naive UTC value as local time. The skew cancelled out, so the TTL
  worked by luck; it now uses a monotonic clock.
- Removed every deprecated `datetime.utcnow()` call and migrated the three
  `@app.on_event` handlers to a lifespan context manager. Test-suite warnings
  went from 19 to 2, both from Starlette itself.

### Changed

- **Renamed to SpendSlicer.** The project previously carried three names at once:
  the `aws_cost_ultra` package, the `aws-cost-dashboard` repo, and a
  "Cloud Ledger" brand rendered in the UI, PDF reports, and export filenames.
  Environment variables moved from `ACU_*` to `SPENDSLICER_*` and the auth header
  from `X-ACU-Token` to `X-SpendSlicer-Token`. No back-compat aliases — there were
  no released users.
- **Minimum Python is now 3.10** (3.9 is end-of-life).
- Dropped `reportlab`, declared as a dependency but imported nowhere.
- Removed `requirements.txt`; it duplicated `pyproject.toml` and had drifted,
  pinning `pytest` as a runtime dependency while missing real ones.
- Lint clean: 196 ruff findings → 0.
- Stripped ~30 `FINDING NN` markers referencing a private audit tracker, plus
  `Phase 1/2/3` planning notes, keeping the reasoning they annotated.
- Corrected the README's accuracy claim. It advertised exact per-instance EC2
  cost via Cost Explorer `RESOURCE_ID`; that path had been removed because
  `GetCostAndUsageWithResources` bills $0.00001 per usage record and dominated
  running cost. Per-resource figures are estimates unless the CUR warehouse is
  enabled, and the docs now say so.

### Known limitations

- PDF export renders through Puppeteer and therefore needs Node.js. It does not
  work in the desktop builds or a bare `pip install`. CSV and JSON work
  everywhere.
- The Pricing API fallback table only carries `ap-south-1` rates.
- Desktop builds are unsigned, so macOS Gatekeeper and Windows SmartScreen warn
  on first launch.

[1.0.0]: https://github.com/CheeseGOD777/SpendSlicer/releases/tag/v1.0.0
