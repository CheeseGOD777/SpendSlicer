# SpendSlicer landing site

The marketing site. A small Vite + React app, separate from `frontend/`.

```bash
cd landing
npm install
npm run dev        # http://localhost:5174
npm run build      # -> landing/dist
npm run preview    # serve the build
```

## Why it is a separate Vite project

`frontend/vite.config.js` builds into `../spendslicer/web/static` with
`emptyOutDir: true`, and `pyproject.toml` ships `web/static/**/*` inside the
Python wheel. Adding the landing page as a second entry there would put a
marketing page inside every `pip install spendslicer`, so it lives here and
builds to its own `dist/`.

## One design system, not two

There is no separate stylesheet for the marketing site. `src/landing.css`
starts with:

```css
@import "@app/tokens.css";
```

where `@app` is a Vite alias for `../frontend/src`. The live demos import the
product's real modules:

| Imported from the app | Used for |
| --- | --- |
| `tokens.css` | the entire visual system |
| `components/Marks.jsx` | the Exact / Est. / Drift marks and the legend |
| `components/Flap.jsx` | the split-flap numerals in the hero |
| `charts.jsx` | `TrendBars`, `Donut`, `PALETTE` |
| `lib/icons.jsx` | the icon set and the brand mark |
| `lib/format.js` | `usd`, `pct`, `value` |

So when the product's design changes, the landing page changes with it.

**Rule for `landing.css`:** no bare element selectors. A rule like
`section { padding-block: 96px }` reaches into the live demos and restyles the
product, because the board's root element is a `<section>`. Marketing-only
classes that would collide with a product class take an `lp-` prefix
(`.lp-btn`, not `.btn`). Anything unprefixed and shared with the app is
deliberate reuse.

## The demos are live, and the data is fake

`src/demo/` renders the real Dashboard, Services and Resources surfaces
against a fixture in `src/demo/data.js`. Nothing calls the backend, and no
AWS credentials are involved.

`data.js` reconciles end to end, and it has to:

```
12 daily buckets       = $11,124.39   the Cost Explorer total
8 service rows         = $11,124.39
10 named resources     = $ 5,381.38   attributed
attributed + drift     = $11,124.39
EC2 usage-type buckets = $ 4,182.41   the EC2 service row
```

A cost tool whose landing page does not add up has argued against itself, so
`data.js` asserts these in development and logs to the console when a change
breaks one. If you edit a figure, edit the figures that depend on it and check
the console in `npm run dev`.

The page says the data is sample data in two places: under the hero board and
in the footer. Keep both.

## Light only, deliberately

`tokens.css` defines no dark mode, so the product has none. Because this page
embeds live product panels, a dark marketing shell would break at every demo
boundary. If dark mode is wanted, it starts in `tokens.css` and this page
follows.

## Deploying

`npm run build` emits a self-contained `dist/` with a relative `base`, so it
works at a domain root or a project subpath. `.github/workflows/pages.yml`
builds and publishes it to GitHub Pages on pushes to `main` that touch
`landing/` or `frontend/src/` (the second because the design system lives
there).

To enable it once: repository **Settings → Pages → Source → GitHub Actions**.
