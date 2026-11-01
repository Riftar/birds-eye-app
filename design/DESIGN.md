---
version: alpha
name: Birds Eye Console
description: A dark, quiet console for watching AI agents make a post, where amber always means a person decides and blue always means a model ran.
colors:
  ground: "oklch(17% 0.008 250)"
  panel: "oklch(21% 0.009 250)"
  well: "oklch(13.5% 0.007 250)"
  ink: "oklch(95% 0.005 250)"
  ink-2: "oklch(83% 0.008 250)"
  muted: "oklch(71% 0.01 250)"
  rule: "oklch(31% 0.01 250)"
  rule-2: "oklch(42% 0.012 250)"
  person: "oklch(82% 0.15 80)"
  person-ink: "oklch(18% 0.04 75)"
  person-soft: "oklch(29% 0.05 80)"
  person-hover: "oklch(87% 0.13 80)"
  person-press: "oklch(76% 0.15 78)"
  model: "oklch(77% 0.12 245)"
  model-soft: "oklch(29% 0.05 245)"
  ok: "oklch(76% 0.15 150)"
  ok-soft: "oklch(24.5% 0.03 150)"
  bad: "oklch(70% 0.17 25)"
  bad-soft: "oklch(24.5% 0.035 25)"
typography:
  heading-page:
    fontFamily: Host Grotesk
    fontSize: 1.728rem
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  heading-section:
    fontFamily: Host Grotesk
    fontSize: 1.44rem
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: "-0.03em"
  title:
    fontFamily: Host Grotesk
    fontSize: 1.2rem
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-0.03em"
  body:
    fontFamily: Host Grotesk
    fontSize: 1rem
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: Host Grotesk
    fontSize: 0.875rem
    fontWeight: 500
    lineHeight: 1.4
  measured:
    fontFamily: Atkinson Hyperlegible Mono
    fontSize: 0.875rem
    fontWeight: 400
    lineHeight: 1.6
    fontFeature: "tnum, zero"
rounded:
  chip: 4px
  control: 6px
  panel: 10px
spacing:
  3xs: 2px
  2xs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 40px
  2xl: 64px
components:
  button-primary:
    backgroundColor: "{colors.person}"
    textColor: "{colors.person-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: 8px 16px
    height: 40px
  button-primary-hover:
    backgroundColor: "{colors.person-hover}"
    textColor: "{colors.person-ink}"
  button-primary-active:
    backgroundColor: "{colors.person-press}"
    textColor: "{colors.person-ink}"
  button-primary-disabled:
    backgroundColor: "{colors.person-soft}"
    textColor: "{colors.muted}"
  button-primary-loading:
    backgroundColor: "{colors.person-soft}"
    textColor: "{colors.ink}"
  button-primary-error:
    backgroundColor: "{colors.bad-soft}"
    textColor: "{colors.bad}"
  button-primary-success:
    backgroundColor: "{colors.ok-soft}"
    textColor: "{colors.ok}"
  button-secondary:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: 8px 16px
    height: 40px
  button-secondary-hover:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
  button-secondary-disabled:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.muted}"
  input-brief:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: 12px
  chip-waiting:
    backgroundColor: "{colors.well}"
    textColor: "{colors.muted}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
  chip-running:
    backgroundColor: "{colors.model-soft}"
    textColor: "{colors.model}"
    rounded: "{rounded.chip}"
  chip-backup:
    backgroundColor: "{colors.well}"
    textColor: "{colors.model}"
    rounded: "{rounded.chip}"
  chip-done:
    backgroundColor: "{colors.ok-soft}"
    textColor: "{colors.ok}"
    rounded: "{rounded.chip}"
  chip-failed:
    backgroundColor: "{colors.bad-soft}"
    textColor: "{colors.bad}"
    rounded: "{rounded.chip}"
  chip-cutoff:
    backgroundColor: "{colors.well}"
    textColor: "{colors.person}"
    rounded: "{rounded.chip}"
  chip-gate:
    backgroundColor: "{colors.person-soft}"
    textColor: "{colors.person}"
    rounded: "{rounded.chip}"
  panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: 24px
  output-well:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink-2}"
    typography: "{typography.measured}"
    rounded: "{rounded.control}"
    padding: 16px
  alert-error:
    backgroundColor: "{colors.bad-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: 16px
  trail-time:
    textColor: "{colors.model}"
    typography: "{typography.measured}"
  trail-person:
    textColor: "{colors.person}"
    typography: "{typography.label}"
---

## Overview

Birds Eye is a console for watching three agents (Planner, Writer, Reviewer) turn a creator brief into a post, and for the two moments a person has to decide. It should feel like an instrument kept by careful people: a graphite ground, hairline panels, nothing glowing. It is not a neon terminal or a glass dashboard.

The one rule that carries the whole system: amber is a person, blue is a model. The approval buttons, the gate panels and the audit rows a person wrote are amber. Provider names, model names, running steps and timestamps are blue. Nothing else gets either colour, so a judge can tell at a glance who did what.

Built on Hallmark's Console theme (graphite colourway, app scope). The live reference is `component-sheet.html` beside this file; `tokens.css` and `components.css` are what the app imports.

## Colors

- **Ground, panel, well:** three steps of graphite. The page sits on ground, every component on panel, and model output and inputs in the deeper well.
- **Ink, ink-2, muted:** primary text, secondary text, and helper text. Muted passes AA on every surface.
- **Person (amber):** the primary action and the two human gates only. Dark person-ink sits on it.
- **Model (blue):** provider and model names, running and backup steps, and audit timestamps.
- **Ok and bad:** Done and Failed, and error alerts. Never used as decoration.

## Typography

Host Grotesk at weight 400 and 500 for everything a person reads. Atkinson Hyperlegible Mono for what the system wrote: provider and model ids, error codes, timestamps, post ids and raw model output, always with tabular figures. Mono is never used for a label, a heading or a button. All labels are sentence case and untracked. The scale is fixed (ratio 1.2), with no fluid headings.

## Layout

A top bar with the wordmark and the mock data chip, no sidebar. On desktop the run view is two columns: the brief form at 22rem on the left, the step cards on the right. Below 60rem everything stacks into one column. Controls are 40px tall with a 44px hit target. Spacing comes only from the spacing tokens. Checked at 375, 768, 1024 and 1440px with no sideways scroll.

## Elevation & Depth

No shadows anywhere. Depth comes from the three graphite steps and 1px rules. A panel is panel colour inside a 1px rule; panels that sit together share one surface split by 1px seams.

## Shapes

Three radii only: 4px for chips, 6px for controls, inputs, wells and alerts, 10px for panels.

## Components

- **Brief input:** label "Creator brief", the helper line, the example placeholder, and the "Run pipeline" button, with the MOCK data notice under it. Empty submit shows a red edge and a short error line.
- **Step card:** the step name, one step badge, and one row per provider attempt (provider, concrete model, error code or attempt number, badge). A failed attempt row sits on the bad tint. When a backup took over, the blue fallback note sits under the attempts. Model output goes in a mono well. While running, a three-line skeleton stands in for the output.
- **Step badges:** Waiting, Running, On backup (dashed blue edge), Done, Failed, Cut off.
- **Lifecycle:** seven chips in order. The current stage is lifted; Approved and Scheduled carry an amber edge because only a person can move a post there.
- **Post card:** title, lifecycle chip, platform chip, post id in mono, one line of summary.
- **Gate panel:** amber edge, the gate chip and current stage, an amber approve button and an outlined reject button. Approve opens an inline confirm, never a modal. Reject opens an inline reason field.
- **Error alert:** plain title, plain reason, and the code on the right in mono so QA can match it to the log. Codes in use: HUMAN_ONLY, CLAIM_LOST, INVALID_TRANSITION, PROVIDERS_EXHAUSTED, and the truncated flag for cut off output.
- **Audit log:** one spine, newest at the bottom, time in blue mono, the agent name in ink, the model in blue, and a person's rows in amber.
- **Empty states:** a dashed panel with a title and one line saying what fills it.

Every button ships eight states: default, hover, focus, pressed, disabled, loading (spinner plus the same label, so the width never changes), error and success. Focus is a 2px amber outline. Transitions only touch colour, over 220ms, and stop under reduced motion.

## Do's and Don'ts

- Do use Peggy's copy from `ui-copy-v1.md` word for word.
- Do show the provider and concrete model on every step; QA checks them.
- Don't use amber for anything a model did, or blue for anything a person did.
- Don't add shadows, gradients, glows, emoji icons or decorative status dots.
- Don't use em or en dashes, tracked caps labels or eyebrow text.
- Don't invent figures. Latency and cost show only when the run returns them.
- Don't open a modal for a gate decision; confirm inline.
