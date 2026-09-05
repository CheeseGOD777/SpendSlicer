## What and why

<!-- What changes, and what problem it solves. For a fix, say what the wrong
     behaviour was. -->

## Checks

- [ ] `ruff check .` is clean
- [ ] `pytest -q` passes
- [ ] `cd frontend && npm test` passes
- [ ] If `frontend/src` changed: rebuilt with `npm run build` and committed `spendslicer/web/static/`

## Accuracy

<!-- Delete if this doesn't touch cost figures. -->

- [ ] Any new number is labelled as exact or estimated, matching what it is
- [ ] Provenance is populated for new cost paths

## Cost Explorer

<!-- Delete if this adds no CE calls. CE bills $0.01/request to the user. -->

- [ ] New CE calls go through `CostStore` / `cost_source` and are cached
- [ ] Change in CE calls per page load: <!-- e.g. "none" / "+1 on Resources" -->
