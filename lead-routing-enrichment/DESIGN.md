---
name: Lead Routing Enrichment
description: Deterministic-first, AI-last lead enrichment console for Talon.One
colors:
  night-indigo: "#02043B"
  deep-indigo: "#0A0E45"
  mid-indigo: "#151B63"
  raised-indigo: "#1E2678"
  hairline: "#282F6B"
  hairline-hi: "#3A4488"
  instrument-white: "#F5F6FA"
  periwinkle-grey: "#AEB2E0"
  dim-indigo: "#7D82BE"
  signal-lime: "#CCF87D"
  deep-teal: "#00434C"
  caution-amber: "#FFC24B"
  alert-red: "#FF6B6B"
  resolved-blue: "#5B8DEF"
typography:
  display:
    fontFamily: "Syne, Outfit, system-ui, sans-serif"
    fontSize: "34px"
    fontWeight: 600
    lineHeight: 1.08
    letterSpacing: "normal"
  headline:
    fontFamily: "Outfit, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.2
  title:
    fontFamily: "Outfit, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.2
  body:
    fontFamily: "Outfit, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 500
    lineHeight: 1.5
  control:
    fontFamily: "Outfit, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 500
    lineHeight: 1.4
  data:
    fontFamily: "IBM Plex Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Outfit, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.08em"
  micro:
    fontFamily: "Outfit, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "10px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0.05em"
rounded:
  sm: "10px"
  md: "16px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.signal-lime}"
    textColor: "{colors.deep-teal}"
    rounded: "{rounded.pill}"
    padding: "10px 20px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.instrument-white}"
    borderColor: "{colors.hairline-hi}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
  button-tertiary:
    backgroundColor: "transparent"
    textColor: "{colors.dim-indigo}"
    borderColor: "transparent"
    rounded: "8px"
    padding: "8px 16px"
  badge:
    backgroundColor: "transparent"
    textColor: "{colors.dim-indigo}"
    rounded: "{rounded.pill}"
    padding: "4px 8px"
  badge-review:
    backgroundColor: "{colors.caution-amber}"
    textColor: "{colors.deep-teal}"
    rounded: "{rounded.pill}"
    padding: "1px 4px"
  input-reconciled:
    backgroundColor: "{colors.mid-indigo}"
    textColor: "{colors.signal-lime}"
    rounded: "{rounded.sm}"
    padding: "8px"
  card:
    backgroundColor: "{colors.deep-indigo}"
    rounded: "{rounded.md}"
---

# Design System: Lead Routing Enrichment

## 1. Overview

**Creative North Star: "The Audit Ledger"**

This is an instrument panel for governed AI, not a SaaS dashboard. Every surface reads like a ledger page: dense, precise, dark, built for someone cross-checking real data under time pressure, not browsing a marketing site. The night-indigo ground is the constant; nothing else on the page is allowed to fight it for attention except the one interactive signal.

Signal Lime is spent like a real signal, not a brand flourish: it appears only where the interface is telling you "this is the one thing to act on right now" — a primary CTA, a selected checkbox, an editable value the model reconciled. Everything else in the palette is quiet on purpose — periwinkle and dim-indigo text, hairline indigo borders, monospace data columns — so that when lime shows up, it means something. Caution amber and alert red are reserved the same way: amber only for "needs a human," red only for destructive or failed states. Nothing decorative borrows a functional color.

This system explicitly rejects the generic AI-tool look: no gradient hero cards, no badge sprawl with unexplained meaning, no pastel optimism-washing over what is, structurally, a cost-and-trust-governed pipeline. Every badge is a provenance stamp — it exists to answer "why should I trust this value," not to decorate a row.

**Key Characteristics:**
- Dark, high-contrast, indigo-grounded — reads like night-ops instrumentation, not a landing page
- One functional accent (lime) spent sparingly and consistently as "this is actionable"
- Monospace wherever a real extracted or computed value is shown; sans everywhere else
- Flat by default — hairline borders carry structure, shadow is reserved for the one thing that actually floats

## 2. Colors

A disciplined four-role palette (ground / ink / action / caution-and-error), never expanded casually — a fifth "just this once" color is a new system, not a variant.

### Primary
- **Signal Lime** (#CCF87D): the single action/selection accent. Primary buttons, selected checkboxes, the AI-reconciled method badge, editable reconciled-value text. If it isn't clickable or editable, it doesn't wear lime.

### Secondary
- **Deep Teal** (#00434C): ink used only on top of Signal Lime surfaces, so text stays readable without softening the accent itself.
- **Caution Amber** (#FFC24B): the review/needs-attention signal — low-confidence flags, the overwrite-opt-in control, skip notices. Never used for anything that isn't asking for human judgment.
- **Alert Red** (#FF6B6B): destructive/failed states only — reject, hard-fail.
- **Resolved Blue** (#5B8DEF): the one "already handled, first-party, no action needed" signal — kept-value badges, resolved-key pills.

### Neutral
- **Night Indigo** (#02043B): the page ground. The constant everything else sits on.
- **Deep Indigo** (#0A0E45): first raised surface — panels, cards, the toast.
- **Mid Indigo** (#151B63): second raised surface — hover states, inputs, the menu-item hover.
- **Raised Indigo** (#1E2678): third-tier surface, used sparingly for the most-elevated flat panels.
- **Instrument White** (#F5F6FA): primary reading color. Deliberately not pure #FFFFFF — softened just enough to avoid the harsh-white-on-deep-ground look while staying effectively at maximum contrast (measured ~18:1 against the ground).
- **Periwinkle Grey** (#AEB2E0): secondary text — descriptions, body copy that isn't the primary read.
- **Dim Indigo** (#7D82BE): tertiary/meta text — captions, field keys, table labels.
- **Hairline** (#282F6B) / **Hairline Hi** (#3A4488): the two border tones. Hairline for resting structure, Hairline Hi for interactive-element borders and hover states.

### Named Rules
**The One Signal Rule.** Signal Lime marks interaction and nothing else. If an element isn't clickable, editable, or the thing the user should act on next, it does not wear the accent — not for emphasis, not for decoration.

**The One Signal Rule, second half.** The rule above governs *whether* an element may wear lime. It does not govern *how many* may, and that gap is how the accent gets diluted. So: within any one region the user acts inside (a row, a card header, an action bar), lime marks the single thing to act on next. Two adjacent lime controls meaning different things defeat the signal even when both are individually interactive, which is exactly what a lime "selected" checkbox sitting 40px from a lime "commit now" button did. **The accent follows the load:** when a new commit path is added, lime moves to it and the old path steps down to secondary. An element's claim on the accent is not permanent, it lasts as long as it is the thing to act on next.

**The Provenance Rule.** Caution Amber, Alert Red, and Resolved Blue each mean exactly one thing across the entire app (needs review / destructive-or-failed / already trusted). A color is never reused for an unrelated state.

## 3. Typography

**Display Font:** Syne (with Outfit, system-ui fallback)
**Body Font:** Outfit (with system-ui, -apple-system, Segoe UI, Roboto fallback)
**Label/Mono Font:** IBM Plex Mono (with ui-monospace, SFMono-Regular, Menlo fallback)

**Character:** Syne is reserved for the single page title and appears nowhere else. Its letterforms only pay for themselves above ~28px; at 16-20px the same quirks read as distortion rather than as character, so every other heading is Outfit 600. A display face used once is a decision; used on every heading it is just the heading font. Outfit does all the reading work and disappears, which is correct; body text should never compete with data. Mono is reserved strictly for real values — anything extracted from a provider, computed, or user-editable renders in mono so it reads as data, not prose.

### Hierarchy
- **Display** (Syne 600, 34px, line-height 1.08, letter-spacing normal): the page H1 only. Appears once, and is the only Syne in the system.
- **Headline** (Outfit 600, 20px): step-panel titles, modal titles, overlay panel headers.
- **Title** (Outfit 600, 17px): per-account card headers — one tier down from Headline, since these repeat once per row.
- **Body** (500, 15px, line-height 1.5): prose. Descriptions, legends, notes, error text. Max measure 58-62ch.
- **Control** (500, 14px): buttons, inputs, selects, menu items, summary rows — anything you aim at rather than read.
- **Data** (400, 13px, mono-leaning): table cells, provider values, the reconciled-value input. The densest tier, because scanning a column wants more rows on screen, not larger glyphs.
- **Label** (600, 11px, letter-spacing 0.08em, uppercase): captions, field keys, table-header labels, stat-line labels, the stepper.
- **Micro** (600-700, 10px, uppercase): the badge/tag family specifically — method badges, status pills, the REVIEW flag. One size below Label on purpose; these are stamps, not reading text. Nothing in the system renders below this.

### Named Rules
**The Three Working Sizes Rule.** Text below the headings sits at exactly three sizes, each tied to a *mode of reading*: you **read** prose at 15px, you **aim at** controls at 14px, you **scan** tabular data at 13px. A fourth working size would have to name a fourth mode, and there isn't one.

This replaces an earlier One Working Size Rule (everything at 13px). One size turned out to produce flatness rather than restraint: prose was too small to read comfortably and controls were too small to feel like targets, so the interface read as a dense internal admin tool rather than as this product. Three sizes, each earning its place, is the sharpening of that rule and not its abandonment.

**The Ten Pixel Floor.** Nothing renders below 10px. The old 9px stamp tier was below comfortable reading on a dark ground, and was indistinguishable from 10px anyway, so it cost legibility and bought nothing.

## 4. Elevation

Flat by default. The system's only structural device is the hairline border — every panel, card, and input is defined by a 1px border in Hairline or Hairline Hi, not by a shadow. Shadow is reserved for the single element that is genuinely floating above the page rather than sitting flat within it: the account/admin dropdown menu.

### Shadow Vocabulary
- **Floating menu** (`box-shadow: 0 20px 50px rgba(0,0,0,.45)`): the account/admin dropdown only. Soft, wide, low enough contrast against the dark ground that it registers as depth, not decoration.
- **Flag stripe** (`box-shadow: inset 3px 0 0 var(--warn)`): not elevation — an inset colored edge used to flag a review-needed row without adding a second color role. Listed here because it's the only other box-shadow use in the system.

### Named Rules
**The Hairline Rule.** Structure is a border, not a shadow. A card, panel, or input floats only when it's genuinely temporary and layered above content (a dropdown, a modal) — never as a default treatment for "important" content.

## 5. Components

### Buttons
- **Shape carries hierarchy.** Pill (999px) is reserved for the primary action, 10px for secondary, 8px for tertiary. This is the one place the brand's hero CTA shape appears, which is what lets it read as *the* action; applied to every control it carried no information at all.
- **Primary:** Signal Lime background, Deep Teal text, pill, 15px type, 10px/20px padding. One per view. Where the primary action only becomes available part-way through a step, the button is promoted to Primary at that moment rather than sitting lime and inert beforehand.
- **Ghost (secondary) / ghost `.sm`:** transparent background, Instrument White text, Hairline Hi border, 10px radius; hover shifts border and text to Signal Lime.
- **Tertiary (the bare `button`):** transparent fill *and* transparent border, Dim Indigo text, 8px radius. Hover reveals the border and lifts the text to Instrument White — never to Signal Lime, which belongs to the two tiers above it. This is the default, so a button with no class is correctly quiet.
- **Danger:** tertiary by default, hover shifts to Alert Red. Destructive actions should be findable, not offered at the same weight as the action beside them.
- **Touch:** every button clears 44px minimum height under 760px.
- **States:** hover shifts border/text color (never the fill, except Primary which brightens 5%); active presses with `translateY(1px)` (Primary also dims via `brightness(.95)`); disabled drops to 50% opacity with `cursor: not-allowed`. No `outline: none` anywhere — focus-visible always gets a 2px Signal Lime ring.

### Chips / Badges
- **Style:** transparent fill, 1px Hairline Hi border, Dim Indigo text, uppercase, pill radius, 10px (Micro) type — this is the default `.badge` used for method labels (Deterministic / AI-reconciled / Kept).
- **Filled variant:** solid fill in the role color (Signal Lime for AI-reconciled, Resolved Blue border for Kept, Alert Red border for skipped) — border-only for neutral badges, filled only when the badge itself IS the signal (the REVIEW flag fills solid Caution Amber, since it must be readable at a glance without depending on surrounding context).
- **Provenance stamps** (`.def`, `.ov`): the tightest tier — 1px vertical padding, 4px horizontal, 10px type. These sit directly beside a field label, so they stay small enough to read as a suffix, not a sibling element.

### Cards / Containers
- **Corner Style:** 16px (`rounded.md`) for panels and account cards; 10px (`rounded.sm`) for nested elements (inputs, the "what do these mean" details block).
- **Background:** Deep Indigo on Night Indigo ground — one clear step up, never more than that for a resting card.
- **Shadow Strategy:** none. See Elevation — cards are flat, bordered in Hairline.
- **Border:** 1px Hairline.
- **Internal Padding:** 24px (`spacing.xl`) for top-level panels; 12-16px for nested rows.

### Inputs / Fields
- **Style:** Mid Indigo background, 1px Hairline Hi border, 10px (`rounded.sm`) radius. The reconciled-value input specifically renders its text in Signal Lime + mono, since it is simultaneously an input and a data value — the only input in the system that carries the accent color on its text rather than just its focus ring.
- **Focus:** 2px Signal Lime outline, offset inward on the CSV textarea, outward on standard inputs.
- **Checkboxes:** two distinct treatments by role. Standard field-selection checkboxes use the browser-native control tinted via `accent-color: Signal Lime`. The "also overwrite" opt-in checkbox is a custom `appearance: none` control with a hand-drawn checkmark and a Caution Amber border at rest — deliberately different from every other checkbox in the app, because unlike them it represents "spend money," not "select this."
- **Error / Disabled:** hard-fail rows show a `Search other sources` action in place of the value rather than a generic error state — the system prefers "here's what to do" over "here's what's wrong."

### Navigation
- **Stepper:** a progress rail, not a toolbar. Four steps at Label tier (11px uppercase) with a 6px radius and no border at rest, so colour alone carries state; the active step takes a Signal Lime border on an Accent Dim fill (not a solid lime fill, which would compete with the primary CTA); completed steps show a checkmark on a Raised Indigo chip. It is purely a progress display — the user cannot click ahead, only step back via explicit Back/Change-fields buttons — so it must not look like a row of secondary buttons, which is exactly what pill-shaped bordered chips at control size looked like.
- **Admin menu:** a right-aligned dropdown (the system's one shadow-elevated surface), Deep Indigo background, Hairline Hi border, 16px radius. Contains one entry point, "Admin panel" — it no longer holds individual admin screens directly.
- **Admin panel sidebar:** a persistent, always-on left nav (Activity log / Cost dashboard / Enrichment log / Danger zone) replacing the stepper for the duration of the admin view. Flat, bordered-by-selection rather than floating: the active item reuses the Flag Stripe device (`inset 3px 0 0 var(--accent)`) instead of a new color role, so "selected nav item" and "review-needed row" share one visual grammar. Collapses to a horizontal scrollable tab row under 760px, the same breakpoint the review table stacks at.

### Review Resolution (signature component)
**What a review flag is, and is not.** The flag is advisory: it says "look at this," not "this is unresolved." Accepting one is local, free and reversible. It clears the flag in the browser and nothing else: no request, no cost, no permanent effect. That is why the queue offers bulk selection (per field, per account, and all) with no confirmation step, and why every accept carries an Undo instead. A confirmation dialog in front of a free, reversible action is ceremony, and ceremony that appears every time is ceremony nobody reads.

**Two resolution paths, and which one wears the accent.** A flagged row can be resolved from the queue (tick its checkbox, commit from the selection bar) or in place (expand the provenance, then use "Accept this value"). Both stay: the checkbox is queue management, deferred and batched, while the inline action is a judgement made at the moment of reading the evidence. Only one of them carries the accent. The selection bar is the commit surface and wears the lime border; the inline action is secondary, reached only by expanding a row, and is styled as the escape hatch it is. When the inline action was the *only* resolution path it correctly wore the accent; it lost it when the bar arrived, per the second half of the One Signal Rule.

**Where the commitment actually happens.** Writing to CRM is the operator vouching for the whole record, so every changed mapping in scope is promoted to canonical, whether or not it ever carried a review flag. Accepting flags does not change what gets promoted, and neither does leaving them. This is deliberate: the unit being vouched for is the record, not the individual cell. Keep the two ideas separate in any future UI work, because collapsing them (treating accept as the commit) is the easy mistake, and it invites a false safeguard on the harmless action while leaving the consequential one undisclosed.

The REVIEW badge is the system's most load-bearing UI element: solid Caution Amber fill, Deep Teal text, always paired with a tooltip and a legend entry using identical wording ("confidence under 75% — click the row to see why, then accept or fix the reconciled value"). Every flagged row has two real resolution paths, not just a warning: an explicit "Accept this value" action inside the expanded provenance row, or editing the reconciled-value input directly (which resolves the flag on change). A flag that cannot be resolved into a clean state is treated as a defect in this system, not an acceptable end state.

## 6. Do's and Don'ts

### Do:
- **Do** keep Signal Lime to interactive/actionable elements only — selection, primary action, editable values.
- **Do** render every real extracted or computed value in mono; reserve Outfit sans for prose, labels, and chrome.
- **Do** give every low-confidence flag a real resolution path (accept or edit), never a dead-end warning.
- **Do** show provenance on every reconciled value — source, confidence, and (when applicable) the AI mapping confidence, kept as two distinct numbers, never collapsed into one.
- **Do** use hairline borders as the default structural device; reach for shadow only on genuinely floating elements.

### Don't:
- **Don't** use a gradient anywhere — hero, button, card, or text. Flat, deliberate color only.
- **Don't** add a badge or pill whose meaning isn't explained in the legend and, for anything review-relevant, in a per-element tooltip too.
- **Don't** let a confidence number imply progression (no "before → after" arrow between provider match and AI confidence — they are two independent signals, always shown side by side).
- **Don't** state a fact the user isn't asking about as reassurance ("this action has no cost" when nothing suggested it would) — copy answers real uncertainty or it doesn't ship.
- **Don't** use `border-left` as a decorative accent stripe outside the one functional exception (the REVIEW row flag and the overwrite-checkbox row, both of which use it as a genuine state signal, not decoration).
- **Don't** uppercase a full sentence. Uppercase is for stamps of one to three words; past that it stops being a label and becomes shouting nobody reads. The same goes for machine values — a domain or an ID renders as it actually is, in mono.
- **Don't** give every control the same shape. If primary, secondary and tertiary share a radius, shape carries no information and the user has to read every button to find the action.
- **Don't** introduce a fifth color role. Ground / ink / action / caution-and-error is the whole system.
