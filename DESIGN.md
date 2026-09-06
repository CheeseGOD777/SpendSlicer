---
name: SpendSlicer
description: A terminus departure board for AWS spend — one authoritative figure, a queue beneath it, and a legend that defines every mark.
colors:
  board: "#E7EAEF"
  board-2: "#DCE0E7"
  panel: "#FFFFFF"
  panel-2: "#F4F6F9"
  panel-3: "#EAEDF2"
  rule: "#D3D9E1"
  rule-2: "#BAC2CD"
  rule-3: "#96A0AE"
  ink: "#0F1318"
  ink-2: "#262D36"
  ink-3: "#47505C"
  ink-4: "#606A78"
  ink-5: "#7C8794"
  ink-6: "#A9B2BE"
  signal: "#C42B10"
  signal-2: "#9C1F08"
  signal-soft: "#FBE4DF"
  signal-line: "#EFBCB1"
  signal-ink: "#7C1806"
  ontime: "#0B6E45"
  ontime-soft: "#DCEDE3"
  caution: "#945F0A"
  caution-soft: "#F7EBD1"
  caution-line: "#E4CE9A"
  caution-ink: "#5E3D02"
  line-1: "#1B4FC0"
  line-2: "#0B6E5F"
  line-3: "#6E35B8"
  line-4: "#B15400"
  line-5: "#00697F"
  line-6: "#9A1758"
  line-7: "#4C5A1E"
  line-8: "#5C6672"
typography:
  display:
    fontFamily: "Manrope Variable, Manrope, -apple-system, system-ui, sans-serif"
    fontSize: "clamp(46px, 5.6vw, 84px)"
    fontWeight: 600
    lineHeight: 0.9
    letterSpacing: "-0.022em"
    fontFeature: "tabular-nums"
  headline:
    fontFamily: "Manrope Variable, Manrope, -apple-system, system-ui, sans-serif"
    fontSize: "34px"
    fontWeight: 600
    lineHeight: 1.04
    letterSpacing: "-0.022em"
  title:
    fontFamily: "Manrope Variable, Manrope, -apple-system, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.012em"
  figure:
    fontFamily: "Manrope Variable, Manrope, -apple-system, system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.01em"
    fontFeature: "tabular-nums"
  body:
    fontFamily: "Manrope Variable, Manrope, -apple-system, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
    fontFeature: "tabular-nums"
  label:
    fontFamily: "Manrope Variable, Manrope, -apple-system, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.02em"
  identifier:
    fontFamily: "JetBrains Mono, ui-monospace, SF Mono, Menlo, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "-0.02em"
rounded:
  bar: "2px"
  mark: "3px"
  ctl: "8px"
  panel: "12px"
  pill: "999px"
spacing:
  xs: "6px"
  sm: "8px"
  md: "14px"
  lg: "22px"
  xl: "34px"
  page-x: "44px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel}"
    rounded: "{rounded.ctl}"
    padding: "0 17px"
    height: "38px"
    typography: "{typography.body}"
  button-primary-hover:
    backgroundColor: "{colors.ink-2}"
    textColor: "{colors.panel}"
  button-quiet:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.ctl}"
    padding: "0 17px"
    height: "38px"
  button-quiet-hover:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.ink-2}"
  control:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.ctl}"
    padding: "0 11px"
    height: "34px"
  chip:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-3}"
    rounded: "{rounded.ctl}"
    padding: "6px 13px"
  chip-on:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel}"
    rounded: "{rounded.ctl}"
    padding: "6px 13px"
  input-text:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.ctl}"
    padding: "0 13px"
    height: "40px"
  panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "20px 22px"
  rail-item:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
    rounded: "{rounded.ctl}"
    padding: "9px 10px"
  rail-item-on:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel}"
    rounded: "{rounded.ctl}"
    padding: "9px 10px"
  mark-exact:
    backgroundColor: "{colors.ontime-soft}"
    textColor: "{colors.ontime}"
    rounded: "{rounded.mark}"
    padding: "2px 7px"
    typography: "{typography.label}"
  mark-estimated:
    backgroundColor: "{colors.panel-3}"
    textColor: "{colors.ink-3}"
    rounded: "{rounded.mark}"
    padding: "2px 7px"
    typography: "{typography.label}"
  mark-drift:
    backgroundColor: "{colors.signal-soft}"
    textColor: "{colors.signal-ink}"
    rounded: "{rounded.mark}"
    padding: "2px 7px"
    typography: "{typography.label}"
---

# Design System: SpendSlicer

## Overview

**Creative North Star: "The Departure Board"**

This is a terminus board, not a dashboard. A Swiss railway departure board states
one authoritative figure at the top, queues the services beneath it in order of
consequence, and prints a legend that defines every mark it uses — so a traveller
can trust a number they did not watch being computed. SpendSlicer is built the
same way: the period total at board scale, service departures below it with track
badges and right-aligned costs, and an accuracy legend at the foot that defines
exact, estimated, and drift once for the whole application.

The material is cool enamel signage, never warm paper. Ground is a cool grey
board; panels are white plates set on it; every division between things is a 1px
hairline rule. Depth is not part of the vocabulary — nothing floats except two
elements that genuinely float, and state changes are made by swapping ink and
ground rather than by adding light. Numbers are set in a condensed board face
with tabular figures so a column of costs lines up as a column; monospace is
reserved for machine identifiers, where character-level literalness is the point.

Density is deliberately not uniform. The Dashboard is the calm overview and gets
air: a 96px figure, real voids between sections, generous row padding. Services
and Resources are the working surfaces and stay information-dense, because
scanning many rows is the job there — they get the same language, not fewer rows.
The application is light-only; there is no dark theme, and the document declares
`color-scheme: light`.

**Key Characteristics:**
- Hairline rules carry all structure; panels are flat and bordered, never shadowed.
- One signal red, owning exactly one meaning: overrun, drift, breach, error.
- Eight line liveries confined to data marks; chrome is ink, rules, and ground.
- Board-face condensed numerals with tabular figures at every scale.
- Magnitude reads as mass — a proportional row tint — before any number is read.
- States invert ink and ground; the active item is the darkest thing on screen.
- One authored motion: the split-flap numeral roll. Charts do not animate.

## Colors

A cool enamel signage palette: one grey board ground, white plates, a graded
near-black ink ramp, three service-state colors, and a bounded set of transit
line liveries that never leave a data mark.

### Primary
- **Board Ink** (`{colors.ink}`): The near-black the whole system speaks in. Headline figures, active navigation grounds, primary button grounds, the focus ring, selection highlight. Never pure black — it is cooled toward the board.
- **Signal Red** (`{colors.signal}`): The one accent. It means overrun, drift, breach, or error and it means nothing else. Budget bars over the line, the drift figure in the cross-check, the fault cue dot, the caret color of a text field. Its rarity is what makes it readable at a glance.

### Secondary
- **On-Time Green** (`{colors.ontime}`): Exact or on-budget. The exact accuracy mark, healthy budget fill, the nominal cue dot. Never used for "increase" or "good news" generally.
- **Caution Amber** (`{colors.caution}`): Approaching a limit or serving stale data. Budget bars in warning, the stale and working cue dots, the CE meter coin.

### Tertiary
- **Line Liveries** (`{colors.line-1}` through `{colors.line-8}`): One hue per series, in the manner of transit line liveries — a bounded set that keeps a stacked chart legible without inventing a hue per category. Mirrored in `charts.jsx` as the exported `PALETTE`; the two must stay identical. They appear only inside charts, dots, tags, bar segments, and row-mass tints.

### Neutral
- **Board** (`{colors.board}`): The page ground. Cool, slightly darker than its panels, so plates read as plates.
- **Panel / Panel-2 / Panel-3** (`{colors.panel}`, `{colors.panel-2}`, `{colors.panel-3}`): White plate; recessed strip for table headers, cross-check rows, cue strips, hover; and the inert track behind every progress bar.
- **Hairline Rule** (`{colors.rule}`): The default 1px division — panel borders, row separators, section rules. This single value draws most of the application's structure.
- **Rule-2 / Rule-3** (`{colors.rule-2}`, `{colors.rule-3}`): Control borders and table header underlines; and the emphasized or hovered border, dashed drift separators, scrollbar thumb.
- **Ink-2 / Ink-3** (`{colors.ink-2}`, `{colors.ink-3}`): Table body text and control labels; navigation items at rest and identifier text.
- **Secondary Ink** (`{colors.ink-4}`): The floor for text. Captions, field labels, legend prose, table headers, muted figures.
- **Graphical Grey** (`{colors.ink-5}`): Carets, list markers, small marks. Graphical use only.
- **Faint Ink** (`{colors.ink-6}`): The cross-check operators between reconciling cells, where the glyph is scaffolding rather than content.

### Named Rules

**The One Signal Rule.** `{colors.signal}` owns overrun, drift, breach, and error, and appears nowhere else. It is never used for emphasis, for branding, for a hover state, or for "this number is big."

**The Neutral Delta Rule.** Change indicators carry no color. Up, down, and flat deltas all sit on `{colors.panel-3}`; direction is carried by the arrow glyph and by ink weight (up is full `{colors.ink}` at 600, down is `{colors.ink-3}` at 500, flat is `{colors.ink-4}` at 500). Red and green are spoken for by the accuracy legend, and a delta that borrowed them would make "spend rose" look like "figure is wrong."

**The Livery Containment Rule.** The eight line colors may tint a chart series, a legend dot, a usage-type tag, or a row's mass. They may never color a border, a button, a heading, an icon, a background, or any other chrome.

**The Text Floor Rule.** `{colors.ink-4}` is the lightest ink permitted on text; it clears 4.5:1 on every ground it lands on, including `{colors.board}`. `{colors.ink-5}` is verified at 3:1 for graphical use only and must never carry a word.

## Typography

**Interface Font:** Manrope Variable (with Manrope, then system sans)
**Identifier Font:** JetBrains Mono (with `ui-monospace`, SF Mono, Menlo, Consolas)

**Character:** One variable face carries the entire system — figures, headings,
labels and prose alike. There is no condensed cut and no second family: hierarchy
comes from weight and size, never from a change of width, because a change of
width is the thing that reads as utilitarian. Manrope's geometric, lightly
rounded forms keep large currency figures open and legible rather than packed.
Tabular figures are set globally on `body`, so every column of numbers aligns
without per-component effort.

### Hierarchy
- **Display** (800, `clamp(46px, 5.6vw, 84px)`, line-height 0.9, -0.035em): The period total and the audit recoverable figure, and nothing else. Fluid rather than stepped, so a seven-figure bill cannot overrun its row at any width.
- **Headline** (800, 32px, -0.032em): Page titles. 27px below 900px.
- **Title** (700-800, 16-19px): Panel headings (16px), brand wordmark (19px at 800), board bar title (17px).
- **Figure** (700, 14-24px): Every number that is not a display figure — board aside values (24px), cross-check values (22px), departure costs (19px), strong table numbers (15.5px), notice costs (17px), track badges (14px).
- **Body** (400, 14px, line-height 1.5): Table cells, control text, running prose. Descriptive paragraphs cap at 74ch; legend items at 52ch; the cross-check note at 40ch.
- **Label** (600, 11.5-13px): Field labels, table headers, the caption above the board total, cross-check keys, accuracy marks, cue titles. Sentence case, not uppercase.
- **Identifier** (JetBrains Mono 400, 12px, -0.02em): Resource IDs, ARNs, usage types, inline code.

### Named Rules

**The One Width Rule.** Hierarchy is carried by weight and size only. There is no condensed, expanded, or second family anywhere in the system; if a figure does not fit, the fluid display clamp shrinks it rather than narrowing it.

**The Tabular Figure Rule.** Every number is set with tabular figures, which are enabled globally on `body`. A column of costs that does not align on the decimal is a bug.

**The Mono Reservation Rule.** JetBrains Mono (`.id`) is reserved strictly for machine identifiers — resource IDs, usage types, ARNs, inline shell snippets. It is never used for money, for percentages, for timestamps, for labels, or for emphasis. Monospace in this system means "this string is literal and you may need to copy it exactly."

**The Reel Width Rule.** Split-flap digit cells are sized in `ch`, not `em`, so the reel tracks whatever face is loaded instead of a value hand-tuned to one family.

**The Sentence Case Rule.** Labels are sentence case at weight 600. Uppercase tracking-out is not part of this world's label voice.

## Layout

A two-column application shell: a fixed 236px navigation rail (68px collapsed)
beside a scrolling main column with a fixed 58px board bar at its top and a cue
strip at its foot. The page content centers at 1560px maximum, or 1760px on the
dense pages, with 34px vertical and 44px horizontal padding.

Vertical rhythm is built from a small set of steps: 6px inside a label group, 8px
between a caption and its figure, 14px between related blocks, 22px between
panels in a stack or across a split grid, and 34px for the void between major
sections. Sections are separated by real empty space (`.void-lg`, `.void-md`),
not by ruled dividers — the rule is for rows and edges, the void is for sections.
Panels in a split grid align to the top and size to their content; a panel
stretched to match its neighbor reads as an unfinished column.

Density is split by page and it is binding: the Dashboard runs at 16px row
padding with air between sections, while Services and Resources run at 12px cell
padding and keep every row rather than paginating into calm.

Breakpoints, and what each one changes:
- **1400px** — page and board padding tighten to 32px/26px.
- **1180px** — split grids collapse to one column; the display figure drops to 76px.
- **900px** — the rail is replaced by a slide-in navigation sheet; board bar controls take their own full-width row; the cross-check reconciles vertically with its operators left-aligned rather than orphaned mid-air; departure rows regrid to name/cost over track/badge; dense tables drop the service column (already answered by the chip filter above) and move the resource identifier under its name rather than off screen. Cost is never the column that gets dropped.

### Named Rules

**The Void Rule.** Sections are separated by measured empty space, never by a
horizontal rule. Rules divide rows and bound edges; they do not chunk a page.

**The Cost Stays Rule.** When a table sheds columns on a narrow screen, the money
column stays. Anything already answered by a filter above the table goes first.

## Elevation & Depth

This system is flat. Structure comes from 1px hairline rules and from tonal
separation between the board ground and its white plates — never from shadow. A
panel, board, table wrapper, or legend carries a 1px `{colors.rule}` border and no
shadow at any state, including hover. Depth cues that other systems spend shadow
on are spent here on borders, ground shifts to `{colors.panel-2}`, and ink
inversion.

Two shadow tokens exist, and they are confined to elements that genuinely float
above the page rather than sit in it.

### Shadow Vocabulary
- **Lift 1** (`box-shadow: 0 1px 2px rgba(15,19,24,0.06), 0 4px 10px -4px rgba(15,19,24,0.10)`): The rail collapse toggle, which straddles the rail's own edge, and the fixed CE meter pill in the bottom-right corner.
- **Lift 2** (`box-shadow: 0 2px 4px rgba(15,19,24,0.05), 0 18px 34px -14px rgba(15,19,24,0.20)`): The mobile navigation sheet over its scrim, the chart tooltip, and the CE meter on hover.

### Named Rules

**The Hairline Rule.** If two things need to be distinguished, draw a 1px rule or
change the ground. A shadow is not an available answer for structure.

**The Inversion Raise.** State is expressed by swapping ink and ground, never by
adding shadow or glow. The active rail item, the selected chip, and the primary
button are all `{colors.ink}` ground with `{colors.panel}` ink; the primary button
in particular is inversion rather than color, because the accent is spoken for.

**The Float Test.** A shadow is permitted only on an element that is positioned
outside the normal flow and overlaps content it does not belong to. Everything
else is flat.

## Shapes

Panels soften; data stays square. Containers — boards, panels, table wrappers,
the legend, banners — take a 12px radius. Interactive controls, buttons, chips,
inputs, and rail items take 8px. Small marks, badges, tags, and skeleton blocks
take 3px. Progress tracks and bar segments take 2px, and the 7px square inside an
accuracy mark takes 1px, so a data mark reads as a printed square rather than a
pill. Fully round (999px / 50%) is reserved for genuinely circular objects: the
CE meter pill, the scrollbar thumb, avatar and cue dots.

Borders are always 1px and always solid, with one deliberate exception: the drift
row in a resource table is separated by a 1px dashed `{colors.rule-3}` because it
is not a resource and should not read as one more row in the list. Icons are a
single authored family — 1.5px stroke on a 20px box, rendered in `currentColor`,
round caps and joins — with no icon dependency, no icon font, and no emoji.

## Components

### Buttons
- **Shape:** Softly squared (8px radius), 38px tall, 17px horizontal padding, 14px semi-bold label with an optional 18px icon at 8px gap.
- **Primary:** Ink ground, panel-white text. No border, no shadow. It is the darkest element in its region and that is its emphasis.
- **Hover / Active:** Primary lifts to `{colors.ink-2}`; all buttons translate down 1px on `:active`. Transitions run at 130ms. Disabled drops to 50% opacity and loses the press.
- **Quiet:** White ground, `{colors.rule-2}` border, `{colors.ink-2}` text; hover shifts the ground to `{colors.panel-2}` and darkens the border to `{colors.rule-3}`.
- **Link button:** No ground; semi-condensed 600 at 13px, underlined with a 3px offset in `{colors.rule-3}` that darkens to full ink on hover.

### Controls (period and profile selects)
- **Style:** 34px tall, 11px padding, white ground, `{colors.rule-2}` border, 8px radius, 13.5px medium label. Selects use an inline SVG chevron at 10px from the right; the native arrow is suppressed.
- **Hover:** Border darkens to `{colors.rule-3}`, ground to `{colors.panel-2}`.

### Chips
- **Style:** Semi-condensed 13.5px on white with a `{colors.rule-2}` border, 8px radius, 6px/13px padding, arranged in a horizontally scrolling row.
- **State:** Selected inverts to ink ground with panel text and a matching ink border. There is no third state and no accent tint.

### Panels / Boards
- **Corner Style:** 12px radius, `overflow: hidden` so tables and rows clip cleanly to the corner.
- **Background:** White plate on the board ground. Headers and recessed strips use `{colors.panel-2}`.
- **Shadow Strategy:** None, at any state. See Elevation & Depth.
- **Border:** 1px `{colors.rule}` all round; the panel header is divided from the body by the same rule.
- **Internal Padding:** 18px/22px header, 20px/22px body, reduced to 15px/18px and 16px/18px below 900px. `panel-body-flush` drops padding entirely where a table or row list should meet the panel edge.

### Inputs / Fields
- **Style:** 40px tall, 13px padding, white ground, `{colors.rule-2}` border, 8px radius, label above in semi-condensed 600 at 13px, optional note below in 12.5px `{colors.ink-4}`.
- **Focus:** The border goes to full `{colors.ink}` with a 3px `rgba(15,19,24,0.09)` ring — a widened stroke, not a glow. Global `:focus-visible` is a 2px `{colors.ink}` outline at 2px offset.

### Navigation
- **Style:** A white rail with a right hairline border, grouped items separated by a 1px section rule. Items are 14px medium in `{colors.ink-3}` with a 18px stroke icon at 72% opacity.
- **States:** Hover shifts the ground to `{colors.panel-2}` and brings the icon to full opacity; active inverts entirely to ink ground with panel text. Collapsed (68px) hides all labels and centers the icons.
- **Mobile:** Below 900px the rail is replaced by a left-anchored sheet (min(292px, 84vw)) over a `rgba(15,19,24,0.42)` scrim, opened from a control in the board bar. Navigation is never simply hidden.

### Departure Rows (signature)
The dashboard's queue. A three-column grid — service name, track badge, cost —
divided by hairline rules, with the cost right-aligned in the board face at 21px.
The track badge is a boxed field, the way a board sets a platform number: a 62px
minimum box with a `{colors.rule-2}` border and a 3px radius carrying the share of
period spend. Behind everything, a proportional tint (`--mass`, 11% opacity,
scaled horizontally from the left edge) states magnitude before any number is
read. The same mass language repeats in dense tables as a left-anchored gradient
on the row, so one page has one language for magnitude.

### Accuracy Marks and the Legend (signature)
Three marks and nothing else: **Exact** (on-time green on its soft tint, filled
square), **Est.** (recessed grey with a `{colors.rule-2}` border and a hollow
outlined square), **Drift** (signal red ink on its soft tint, filled square).
Marks and their definitions are single-sourced from one module, and the legend
renders from that same source, so a mark can never appear without the definition
behind it. The legend is a bordered `{colors.panel-2}` strip at the foot of the
board titled "How to read this board."

### Cross-Check Strip
A `{colors.panel-2}` band across the foot of the board where each cell owns one
truth and the operators between them (`+`, `=`) are the proof rather than
decoration. Operators are set in the board face at 21px in `{colors.ink-6}`. On
narrow screens the strip becomes a vertical equation with left-aligned operators.

### Cue Strip
A single 38px live-region line at the foot of the shell: a 7px status dot
(on-time / caution / signal), a semi-condensed 600 event name, optional detail,
and a right-aligned timestamp. It exists so the board announces what changed
rather than repainting silently.

### Split-Flap Numerals (signature motion)
The one authored moment. Digits in a changed figure roll to their new value on a
520ms cubic-bezier, staggered 34ms per digit; separators, currency marks, and
letters stay fixed. A 1px 50%-opacity seam across each cell is the split in
split-flap. The full value is exposed to assistive technology as one string so it
is never read out digit by digit. Under `prefers-reduced-motion` the transition
and the seam are both dropped.

### Banners

- **Character:** a stated fault, not a decoration. Used for backend errors, partial-data caveats, and stale-cache warnings, so that a page never renders `$0.000` as though it were a real figure.
- **Shape:** 8px radius (`{rounded.ctl}`), 1px border, a 17px alert glyph held at the top-left.
- **Warning:** `{colors.caution-soft}` ground, `{colors.caution-line}` border, `{colors.caution-ink}` text.
- **Error:** `{colors.signal-soft}` ground, `{colors.signal-line}` border, `{colors.signal-ink}` text; renders with `role="alert"` where the warning uses `role="status"`.
- **Retry:** an inline action on a translucent ink wash, never a second colored button.

## Do's and Don'ts

### Do:
- **Do** draw structure with 1px `{colors.rule}` hairlines and ground shifts to `{colors.panel-2}`; panels carry a border and no shadow.
- **Do** reserve `{colors.signal}` for overrun, drift, breach, and error, and `{colors.ontime}` for exact or on-budget.
- **Do** set every number in the interface face with tabular figures, and keep `.id` monospace strictly for machine identifiers.
- **Do** express selected and active states by inverting ink and ground.
- **Do** state magnitude as proportional row mass, and normalize it against whatever the row's printed figure refers to: the departure rows print a share of the period, so their mass is normalized to the period total and field and figure agree; a table that prints no share figure (Top resources) normalizes to the largest row in that table, which answers "largest of these" rather than "share of everything". Never normalize to the leader while printing a share figure — the field would overstate the leader and be contradicted by its own badge.
- **Do** define any accuracy mark you use through the shared marks module, and render its definition in the legend.
- **Do** separate sections with the void steps (34px / 22px) and honor the page's density ruling: air on Dashboard, density on Services and Resources.
- **Do** honor `prefers-reduced-motion` on every animation, and keep the split-flap as the only authored motion.
- **Do** hold secondary text at `{colors.ink-4}` or darker.

### Don't:
- **Don't** add a shadow to a panel, card, table, board, or row; `--lift-1` and `--lift-2` belong only to elements that overlap content they don't sit in.
- **Don't** color a delta or a trend indicator red or green; direction is the arrow and the ink weight.
- **Don't** let a line livery touch chrome — no colored borders, headings, icons, buttons, or backgrounds.
- **Don't** set money, percentages, timestamps, or labels in monospace.
- **Don't** borrow the accuracy-mark shape vocabulary for anything that is not an accuracy mark; a notice row that reused it was a review regression.
- **Don't** use `{colors.ink-5}` or `{colors.ink-6}` for text.
- **Don't** animate charts, or add motion beyond the split-flap and the cue pulse.
- **Don't** add a dark theme; the application declares `color-scheme: light` and its grounds are enamel signage, not paper.
- **Don't** ship a raw hex value in a component; every color comes from the token set. Two carve-outs, both deliberate: `charts.jsx` mirrors `{colors.line-1}`–`{colors.line-8}` as the exported `PALETTE` because Recharts needs literal values, and the mirror must stay byte-identical to the tokens; and `ErrorBoundary.jsx` writes each token as `var(--x, #literal)` because it is the one component that must still render if the stylesheet itself failed to load.
- **Don't** exceed 96px in the type scale — the board total is the ceiling, and nothing else in the system may reach it.
