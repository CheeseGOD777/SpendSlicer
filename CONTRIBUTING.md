# Contributing

Thanks for looking. SpendSlicer is a small, focused tool and contributions are
genuinely welcome — particularly on accuracy, which is where the remaining work
matters most.

## Setup

```bash
git clone https://github.com/CheeseGOD777/spendslicer.git
cd spendslicer

python3 -m venv venv && source venv/bin/activate
pip install -e ".[web,cur,exporters,dev]"

cd frontend && npm install && cd ..
```

Python 3.10+ and Node 20+.

## Running it

```bash
# Backend, with autoreload
SPENDSLICER_RELOAD=1 python -m spendslicer.web.app

# Frontend dev server on :5173, proxying /api to :8080
cd frontend && npm run dev
```

For frontend work use the Vite dev server — it has hot reload. `./run.sh`
serves the committed production bundle instead, which will not reflect your
edits until you rebuild.

## Before you open a PR

```bash
ruff check .                   # must be clean
pytest -q                      # must be green
cd frontend && npm test        # must be green
```

**If you changed anything under `frontend/src`, rebuild the bundle and commit
the result:**

```bash
cd frontend && npm run build   # writes spendslicer/web/static/
```

That directory is committed on purpose, so `pip install spendslicer` and
`./run.sh` work without a Node toolchain. CI fails the build if it is stale.

## What we care about in review

**Accuracy claims must be true.** This is the whole premise of the tool. If a
number is an estimate, the code should say so and the UI should show it. If you
add an attribution path, be explicit about its error bounds. Do not let a
rescaled estimate get presented as a billed figure.

**Cost Explorer calls cost money.** $0.01 per request, on the user's bill. New
code paths that call CE need a cache key and should reuse
`CostStore`/`cost_source` rather than calling the client directly. If a change
increases the number of CE calls a page makes, say so in the PR.

**Keep the layers separate.** `core/` must not import AWS or FastAPI; `aws/`
must not import the web layer. This is what keeps the attribution math testable
without mocking HTTP, and it is easy to break by accident.

**Comments should say why, not what.** The existing code leans this way
deliberately — most non-obvious lines carry the reason they are that way,
usually a bug that made them necessary. Please match it.

## Tests

`moto` and `unittest.mock` for AWS; nothing touches a real account.

New attribution logic needs tests covering the boundaries, not just the happy
path — a stopped instance, a resource created mid-window, a multi-AZ RDS, an
empty Cost Explorer response. Those are where this class of tool goes quietly
wrong, and where most of the existing 190 tests live.

```bash
pytest -q                                   # everything
pytest tests/test_attribution_math_fixes.py # one file
pytest -k rescale -v                        # by name
pytest --cov=spendslicer --cov-report=term-missing
```

## Especially wanted

- **CUR-based attribution.** The highest-value work in the project. Exact
  per-resource costs from a local warehouse remove the estimation entirely.
  See [docs/CUR.md](docs/CUR.md).
- **More service enumerators.** ECS, EKS, CloudFront, NAT Gateway, Route 53.
  Follow the shape of `spendslicer/resources/rds.py` — it is the clearest example.
- **Regional pricing.** The fallback rate table in `core/pricing.py` only
  carries `ap-south-1`. Any additional region is a useful contribution.
- **Windows and Linux testing.** Development happens on macOS; reports from
  elsewhere are valuable.

## Commit messages

Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).

Explain *why* in the body, and for a bug fix say what the wrong behaviour was.
"Fixed the cache" tells a future reader nothing; "cache eviction raced with
init, so a cold start could serve another profile's numbers" tells them
everything.

## Reporting bugs

Open an issue with your OS, Python version, install method (desktop build /
pip / source), what you expected, and what happened. Include relevant output
from `SPENDSLICER_LOG_LEVEL=debug`.

**Never paste real account IDs, ARNs, or cost figures.** Redact them. There is
no sanitiser in the loop here — what you paste is what gets published.

For security issues, do not open a public issue. See [SECURITY.md](SECURITY.md).

## License

Contributions are accepted under the MIT license, matching the project.
