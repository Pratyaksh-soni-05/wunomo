# Wunomo — Design Spec, Part 1: Foundations

Companion to the approved Platform Design Blueprint v2.
**This file is authoritative for every number.** The blueprint shows what it looks like; this says what it measures.

Rule for anyone building against it: if a value you need isn't here, ask — don't invent one. A colour, radius or font size that isn't in `tokens.css` is a bug, not a judgement call.

---

## 0. What "one to one" means in practice

The blueprint is a static mock. Three things in it will differ in the real build, and that's correct rather than a failure:

| In the mock | In the build | Why |
|---|---|---|
| Progress bars move on a script | They move when a `task_step` transitions in the DB | The mock's timings are illustrative, the real ones come from the stream |
| Chat messages appear on a timer | They stream token by token | The mock predates streaming existing |
| Fixed 1360×840 frame | Fluid from 1280px up, collapses below | The mock is a fixed artboard; the product is responsive |

Everything else — every colour, every spacing value, every piece of copy, every state, every empty state — is exact and should be matched.

---

## 1. Typography

Two families. Inter for everything human, IBM Plex Mono for code, SQL, IDs and column names only. **Mono is never used for labels, badges or UI chrome** — that reads as a template tell.

| Role | Size | Weight | Tracking | Notes |
|---|---|---|---|---|
| Metric | 42px | 700 | −0.035em | Dashboard numbers. Always `.num`. |
| Metric, small | 22–28px | 700 | −0.03em | In-card figures. Always `.num`. |
| Page title | 22px | 650 | −0.025em | |
| Screen heading | 19px | 650 | −0.025em | |
| Section heading | 16px | 600 | −0.015em | |
| Card title | 14.5px | 600 | — | |
| Body | 14px | 400 | −0.005em | Default. Line height 1.5. |
| Chat message | 13.8px | 400 | — | Line height 1.62 — looser than UI body, it's prose. |
| Secondary | 12.5px | 400 | — | `--text-secondary`. Metadata, timestamps, sub-lines. |
| Tertiary | 11.6px | 400 | — | `--text-muted`. Counts, hints. |
| Label | 10.5px | 600 | 0.07em | Uppercase. |
| Badge | 11px | 500 | — | Not uppercase — the shipped `Badge` component (`components/ui/Badge.tsx`) sets no `text-transform`/`letter-spacing`; sentence case, matching the copy rules below. |
| Code / SQL / IDs | 12.5px | 400 | — | `--font-mono`, usually `--accent-text`. |

**Reading width.** Chat column caps at 780px. Output blocks may break out to 1040px for tables. Nothing runs edge to edge.

---

## 2. Density

Spacing comes from the 4px scale only: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64.

| Context | Value |
|---|---|
| Dashboard card gaps | 12px |
| Chat message rhythm | 16px |
| Card padding | 15px 16px (standard), 12px 13px (compact), 18px 20px (feature) |
| Screen padding | 20px 24px |
| Sidebar nav item | 6.5px 15px |
| Gap between avatar and message body | 11px |

**Elevation is background difference, not shadow.** Shadows appear only on drawers and modals. The console must stay flat so status colour is the only thing that pops.

---

## 3. Components — exact anatomy

### Button

**This table describes the shipped four-tier system (`components.css`), not the sizing this section originally proposed** — the product moved to an accessibility-driven 44/52px touch-target floor since this spec's numbers were first written; the old 33/27px heights and 7px/6px radii never shipped. See "still open" at the end of this section for the one open question this leaves.

| Tier | Class(es) | Min-height | Padding | Radius | Font | Weight | Background | Border |
|---|---|---|---|---|---|---|---|---|
| 1 — primary action | `.btn-primary` / `.btn-danger` / `.btn-success` | 52px (44px if `.btn-anchored`, e.g. inline with an input) | 0 20px | `--radius-sm` | 14px | 500 | `--accent-fill` / `--danger-fill` / `--success-fill`, text `--on-accent-fill` / `--on-dark` | none |
| 2/3 — secondary/tertiary | `.btn-secondary`, `.btn-ghost` (one shared treatment) | 44px | 0 20px | `--radius-sm` | 14px | 500 | transparent (hover `--surface-hover`), text `--text-secondary` (hover `--text-primary`) | transparent (hover 1px `--border-strong`) |
| 4 — text | `.btn-text` | auto, inline | 0 | none | 12.5px | 500 | transparent, text `--text-secondary` (hover `--text-primary`) | none |
| Small modifier | `.btn-sm` | inherits its tier | 0 14px | as above | 13px | as above | as above | as above |
| Large modifier | `.btn-lg` | inherits its tier | 0 26px | as above | 15px | as above | as above | as above |
| Icon only | `.btn-icon` (incl. `.btn-icon.btn-sm`) | 44×44 minimum, never smaller | 0 | as above | — | — | as above | as above |

Icon gap inside a button: 6px. Lucide, 16px, stroke 1.5, inherits colour. **No icon ever sits in a coloured circle.**

**Still open:** there is no shipped Danger *outline* variant matching this section's original "transparent background, coloured border" description — `.btn-danger` is a solid `--danger-fill` button, same shape as Primary. If a lower-emphasis danger action is still wanted, that's a real component gap, not a token-naming fix.

**Dense modifier** (`.btn-dense`, added 2026-09-20, not applied anywhere yet). This section's own original 33px/27px numbers, kept alive as an opt-in size rather than lost when the product moved to the 44/52px floor above. Composes with the existing tiers exactly like `.btn-sm`/`.btn-lg` do — same colours, hover, and focus, only the sizing changes:

| | Min-height | Padding | Font |
|---|---|---|---|
| `.btn-dense` | 33px | 0 13px | 13px |
| `.btn-dense.btn-sm` | 27px | 0 10px | 12px |
| `.btn-icon.btn-dense` | 33×33px | 0 | — |

Under `@media (pointer: coarse)` it reverts to the shipped 44/52px minimums regardless — the accessible touch-target floor always wins on a touch device; dense is a mouse/trackpad-density affordance, never a way to shrink a touch target.

**Reserved for stage 4's high-density surfaces only — live panels, table rows, toolbars, and inline card actions.** Not a general-purpose smaller button; every other surface keeps the 44/52px tiers above.

### Input

Padding 7px 12px, no fixed height (grows with its own line-height/font, not a forced box), radius `--radius-sm`, background `--surface`, border 1px `--border-strong`, font 13px. Placeholder `--text-muted`. Focus: border `--accent-border` plus a 3px ring, `box-shadow: 0 0 0 3px var(--accent-border-a15)` — a real glow, not the borderless-only treatment this line previously described.

### Card

Background `--surface` · border 1px `--border` · radius `--radius-lg` (12px) — matches the shipped `.card` rule exactly. Feature cards that carry the accent use `background: var(--accent-fill)`, `border-color: transparent`, `color: var(--accent-fg)`, and their label drops to `color-mix(in srgb, var(--accent-fg) 65%, transparent)` — no shipped component currently renders this variant; the token names are correct for whenever one does.

### Badge

Font 11px / 500 / — (no letter-spacing, not uppercase) · padding 2px 8px · radius `--radius-full` (a full pill — the shipped set never gained a discrete small badge radius) · inline-flex, gap 4px. Component: `Badge` (`components/ui/Badge.tsx`), variants `success` / `danger` / `warning` / `info` / `hold` / `gray` / `midnight`.

| State | Variant | Background | Text | Copy |
|---|---|---|---|---|
| Working | `info` | `--info-bg` | `--info` | `working` |
| Done | `success` | `--success-bg` | `--success` | `done` |
| Needs you | `hold` | `--hold-bg` | `--hold` | `needs you` |
| Degraded | `warning` | `--warning-bg` | `--warning` | `1 issue` |
| Failed | `danger` | `--danger-bg` | `--danger` | `failed` |
| Idle | `gray` | `--surface-hover` | `--text-secondary` | `idle` |

`hold` was added to the shipped token set and to `Badge` on 2026-09-20, specifically for the "needs you" row — the approval flow's own state, distinct from `warning` ("degraded but running") and `info` ("in progress"). Before that addition this row had no real variant to render against.

**Status copy is human language, always.** Never `pending`, `in_progress`, `error`.

### Employee avatar and mention chip — **not yet built — stage 4**

No shipped component renders this yet (`.chat-avatar` today is a single fixed 28×28px AXIOM icon, not a per-employee-hue tile) — the eight identity hues below exist in `frontend/src/styles/tokens.css` as `.c-dataops` / `.c-finance` / `.c-hr` / `.c-analyst` / `.c-support` / `.c-growth` / `.c-compliance` / `.c-revops`, provisioned ahead of the roster they're for, same as this section's own anatomy. The one real correction: the shipped surface scale has no `--surface-2` — use `--surface-hover`.

Avatar tile: 22×22px, radius 6px, font 9.5px / 700 mono, two-letter initials.
Large variant: 30×30px, radius 8px, font 11px.
Extra large (profile): 52×52px, radius 13px, font 16px.

```css
background: color-mix(in srgb, var(--c) 22%, var(--surface-hover));
color: var(--c);
border: 1px solid color-mix(in srgb, var(--c) 34%, transparent);
```

Mention chip in a message: `background: color-mix(in srgb, var(--c) 18%, transparent)`, `color: var(--c)`, radius 5px, padding 1px 5px 1px 3px, weight 600, `white-space: nowrap`.

### Progress bar

Track: height 3px (inline) or 4px (card, matches the shipped `.progress-bar` exactly), radius `--radius-full`, background `--surface-hover`.
Fill: `--accent-fill`, or `--warning` when the task is degraded (matches the shipped `.progress-fill.warning` exactly). Transitions on width over `--dur-bar` (300ms) — the shipped `.progress-fill` now consumes this token directly rather than a hardcoded duration. **Never animates to a fake value to look busy.**

### Status dot

7px circle (matches the shipped `.status-dot` exactly), `flex-shrink: 0`, filled with the matching status token.

---

## 4. Copy rules

These are as binding as the colours.

1. **Active voice, sentence case.** "Hire employee", not "Employee Hiring". Never Title Case, never ALL CAPS outside labels and badges.
2. **A button's name survives the whole flow.** "Approve" produces "Approved". "Hire Axiom" produces "Axiom joined this project."
3. **Empty states are instructions, not apologies.** "No projects yet" is followed by what a project is and one button. Never "Nothing to see here."
4. **Errors say what happened and what to do.** Never a stack trace, never "Something went wrong."
5. **Employees speak as colleagues.** An acknowledgement states what it understood, what it will do, and an honest estimate. Never "Working on it…".
6. **Numbers carry their unit of work.** "3,412 of 5,500 rows", not "62%" alone. A spinner says nothing; a row count says the machine is honest.
7. **Admit assumptions.** If an output assumed something, the output says so.

---

## 5. Accessibility floor

Non-negotiable, and cheaper to build in than retrofit.

- Visible keyboard focus everywhere — `:focus-visible`, 2px `--focus-ring`, 2px offset (matches the shipped `.btn:focus-visible` rule exactly).
- Full keyboard path through the composer: `@` opens the picker, arrows navigate, Enter selects, Escape closes.
- Status is never colour alone — every status colour is paired with text.
- `prefers-reduced-motion` kills all three animations.
- Live regions on the chat feed and the live-work panel so streamed updates are announced.
- Contrast: body text ≥ 4.5:1, large text and UI borders ≥ 3:1, in both themes.

---

## 6. What is NOT in this product

Listing these because they're the defaults a component library will pull you toward.

- No gradient backgrounds, blobs or washes
- No coloured icon circles
- No card hover lifts or page transitions
- No drop shadows outside drawers and modals
- No centred-everything layouts
- No spinner without a unit of work next to it
- No colour used decoratively — the five status hues and the eight employee hues are the complete palette of meaningful colour
- No `localStorage` for anything that belongs in the database

---

## 7. The Project Workspace

Visual reference: `docs/design/wunomo-blueprint.html` §07 — open it in a browser, **do not read it into context**.

This is written against what actually shipped in stages 1 and 2, not against the mock. Where the mock and this file disagree, **this file wins**.

### 7.0 What this screen is

`/projects/[id]/chat`. The one screen where work happens. Everything else in the product watches, approves or retrieves — this is the only place a user performs.

The governing rule: **if a user has to leave this screen to do something, that's a bug.** Uploading a file, connecting a source, hiring an employee, approving an action, scheduling recurring work — all of it happens by talking.

### 7.1 Layout

Two panes inside the existing app shell.

| Region | Width | Notes |
|---|---|---|
| App sidebar | `--sidebar-w` (212px) | Existing, unchanged |
| Project header | full, 12px 20px | Below the app topbar, above both panes |
| Thread | fluid, min 0 | Message column capped at `--chat-max` (780px), centred |
| Live work panel | `--livepanel-w` (352px) | Right, `border-left: 1px solid var(--border)`, `background: var(--surface)` |

**Responsive.** Below 1180px the live panel collapses to a toggle in the header showing a count badge of active tasks. Below 820px it becomes a bottom sheet. The thread never collapses — it's the product.

**Scroll.** Thread and live panel scroll independently. The composer is fixed at the bottom of the thread pane, never scrolls away.

### 7.2 Project header

Left: project name (16.5px/650/−0.025em) with a status badge beside it; below, a sub-line at 12.3px `--text-secondary` reading `{n} of {m} tasks done · {project description}`.

Then the hired employees as an overlapping avatar stack (−6px margin), followed by a **dense** `+ Hire` button.

Right: a 120px progress track (3px, `--radius-full`, `--surface-hover`) with `--accent-fill` fill, then an overflow `⋯` menu.

Header status badge maps from live state:

| Condition | Badge | Copy |
|---|---|---|
| Any task running | `info` | `working` |
| Any approval pending | `hold` | `needs you` |
| Any task failed or blocked | `warning` | `1 issue` (pluralise) |
| Nothing active | `success` | `all clear` |

Precedence top to bottom — `needs you` outranks `working`.

### 7.3 Message shapes

Nine shapes. Every one of them is one of these — if something doesn't fit, ask before inventing a tenth.

#### A. User message

Right-aligned, `max-width: 600px`. Card with `border-color: color-mix(in srgb, var(--accent-fill) 45%, transparent)` and `background: color-mix(in srgb, var(--accent-fill) 8%, var(--surface))`. Body 13.8px, line-height 1.62. Mentions render as chips (§7.3.J). Attachments as badges below the body. Meta line bottom-right: `You · HH:MM`.

#### B. Employee acknowledgement

Left, avatar + body. Header row: name (13.4px/600), status badge, timestamp (11.4px `--text-muted`). Body states **what it understood, what it will do, and an honest estimate.** Never "Working on it…".

The avatar carries `.is-working` while the task is active — the pulse animation from `tokens.css`.

#### C. Streaming assistant message

Same as B, but the body fills from `token` deltas. Tool calls render inline as `ToolCallBlock` (already shipped) in `running` state, resolving to `completed` or `failed` on `tool_end`.

A caret or block cursor at the end of the streaming text is the only permitted "thinking" indicator. **No spinner, ever** — D6.

#### D. Employee result

Header as B with a `success` badge. Body leads with **the answer in one or two sentences**, then the output card, then affordances. Never lead with a table.

Output card: bordered, radius `--radius-lg`, no shadow. Header row = filename (13.4px/600) + sub-line (11.6px `--text-muted`) + trust badge + dense Download button. Optional preview body. Footer row (border-top, 11.9px) carries `Show work` and `How this was made` as `--accent-fill` text links, plus any caveat.

**Caveats are mandatory when they exist.** "Assumed 20% overhead as you specified — not verified against your actuals" is required copy, not decoration.

#### E. Approval card — inline, blocking

Rendered on `approval_required`. Uses the real `risk_level` and `reason` from the event.

- Container: `border-color: color-mix(in srgb, var(--hold) 50%, transparent)`
- Header strip: `background: color-mix(in srgb, var(--hold) 9%, transparent)`, 7px status dot in `--hold`, title 13px/600, right-aligned risk badge
- Detail rows: label column 74px `--text-muted`, value `--text-secondary`, 12.7px
- Action row: border-top, dense buttons. Primary approve, secondary scoped-approve, danger reject. Right-aligned 11.4px: `Task is paused`

Where a dependent task is held behind this one, the card **must say so**: "Approving this also unblocks Ravi's costing." Users have to see the full consequence of one click.

#### F. Handoff card

Rendered from the `Handoff` row. Not a message from anyone — a system event.

Single row, 12.8px: `{from avatar+name}` · `handed over to` (in `--text-muted`) · `{to avatar+name}` · right-aligned `HH:MM · logged`. Below, 12.6px `--text-secondary`: `payload_summary`.

If `withheld` is non-empty, a second line states it plainly: "Ravi did not receive names or contact details — he doesn't need them." **This is a privacy feature. Render it whenever present.**

#### G. Clarification — inline, non-blocking

New. The supervisor's `needs_clarification` outcome. **Does not block the composer** — the user can ignore it and rephrase instead.

Container: `border-color: var(--border-strong)`, `background: var(--surface)`. No status-colour tint — this is the system being unsure, not something consequential pending. Do **not** reuse the `--hold` treatment; that vocabulary belongs to approvals.

- Body: the planner's `question`, naming both agents
- Action row: one dense button per entry in `options` (e.g. `Wait for Nova` / `Run independently`)
- Right-aligned 11.4px `--text-muted`: `Nothing has started yet`

**Supersession.** If the user sends any new message before answering, the card greys to `opacity: 0.5`, buttons become non-interactive, and the footer changes to `Superseded by your next message`. Never leave a dangling unanswered question with live buttons.

#### H. Refusal

The supervisor's hard `error` outcome — cycle, fan-in, or DAG ceiling. Zero tasks were created.

The user's message above it goes to `opacity: 0.55` with a `not run` badge appended. Below, a card with `border-left: 3px solid var(--warning)` stating **specifically** what was wrong:

- Cycle: "Nova would be waiting on Ravi and Ravi on Nova. Tell me which goes first."
- Fan-in: "Ravi's task depends on two others. I can only chain one dependency at a time — split this into two messages."
- Ceiling: "That's {n} tasks from one message, above the limit of {max}."

**The raw text is restored to the composer**, exactly as typed, `@mention` syntax intact, cursor at the end. Do not re-render it through the mention parser — round-tripping mangles it. Do not auto-fix, do not pre-select.

#### I. System line

Centred, 12.4px `--text-muted`, flanked by 1px `--border` rules. Used for: hires, approvals granted, inferred-edge notices, date separators.

Inferred edges use this shape: "Running Ravi after Priya — he needs the shortlist." Sourced from `inferred_edge_notices`. **Every inferred edge produces one of these. Never silent.**

#### J. Mention chip

Inline in message bodies. `background: color-mix(in srgb, var(--c) 18%, transparent)`, `color: var(--c)`, radius `--radius-full`, padding `1px 5px 1px 3px`, weight 600, `white-space: nowrap`.

### 7.4 Employee avatar — build this first

**Does not exist yet.** `.chat-avatar` is currently one fixed 28px AXIOM icon — a CSS-level artefact of the old single-agent assumption. Replace it.

| Size | Dimensions | Radius | Font |
|---|---|---|---|
| Small (inline, chips) | 22×22 | 6px | 9.5px/700 mono |
| Default (messages, rows) | 30×30 | 8px | 11px/700 mono |
| Large (profile) | 52×52 | 13px | 16px/700 mono |

```css
background: color-mix(in srgb, var(--c) 22%, var(--surface-hover));
color: var(--c);
border: 1px solid color-mix(in srgb, var(--c) 34%, transparent);
```

`--c` comes from the employee-identity classes in `tokens.css`, resolved from `agent_instances.employee_type`. Content is two-letter initials from the instance name.

**`--c` is used only on the avatar tile and the mention chip.** Never on backgrounds, buttons, borders or text blocks.

### 7.5 Composer

Card, radius `--radius-lg`, `border-color: var(--border-strong)`. Three rows: attachments (hidden when empty), text input, toolbar.

Input follows shipped anatomy — `7px 12px`, no fixed height, auto-grows to 6 lines then scrolls. 3px focus ring.

Toolbar left: attach, `@ Tag`, `/ Command` — all dense. Right: 11.6px `--text-muted` hint `Everyone tagged runs in parallel`, then a send button on the 33px dense icon tier (`.btn-icon.btn-dense`) — 30px has no shipped equivalent and sits below even that tier's own floor.

Below, centred 11.4px `--text-muted`: `Drop any file here — CSV, PDF, Excel, a proposal doc. It attaches to this project automatically.`

#### Mention picker

Opens on `@`. Anchored above the composer, 330px, radius `--radius-lg`, `--shadow-lg`.

Two groups with 10.5px labels: **On this project** (hired instances, showing name, employee_type, operation_mode, live status) and **Not hired yet — tag to hire** (available types, badge `+ hire`), plus an `everyone` broadcast row.

**Live status does not exist.** `AgentInstance.status` is only `ACTIVE`/`OFFBOARDED` — a lifecycle flag, not a live "is this agent doing something right now" signal — and nothing else in this codebase tracks that. The "On this project" row omits it rather than fabricate one. **"Tag to hire" does not hire in one click either**: there is no zero-input hire flow anywhere in this app — hiring always requires a name. Tagging an unhired type opens the real hire modal (pre-filled) instead; the system line (§7.3.I) fires once that modal's real hire actually succeeds, not on the tag itself.

Full keyboard path: `@` opens, arrows navigate, Enter selects, Escape closes. Selected row uses `--surface-3`.

**Tagging an unhired type opens the hire modal**, confirmed with a system line (§7.3.I) once the hire actually succeeds.

### 7.6 Live work panel

Tabs: `Live work` · `Team` · `Files` · `Data`. Live work is default.

#### Task card

Built from `Task` + `task_steps`.

Row 1: small avatar · title (12.7px/550) · status badge.
Row 2: 11.5px `--text-muted` — the step line.

**No progress track.** `Task`/`TaskStep` carry no numeric progress field anywhere — nothing a bar could honestly animate to. A card is always exactly two rows, never three. **The step line always names the step** — `Step 1: Profiling sales_orders` — never a bare percentage, never a spinner (D6). This is the only real branch: with no progress field to check, there is no separate "count known" case to render differently.

| Task status | Badge | Step line |
|---|---|---|
| `SUPERVISOR_QUEUED` | `gray` `queued` | Its current step, named (`Step 1: {description}`), or `Waiting to start` if it has none yet |
| `SUPERVISOR_RUNNING` | `info` `running` | Its current step, named — never a percentage; no field on `Task`/`TaskStep` could honestly produce one |
| `BLOCKED_ON_DEPENDENCY` | `warning` `blocked` | The task's own `pause_reason` (falling back to `action_text`, then `Waiting to start`) — **not** `{upstream agent}'s {task}`. That richer copy needs the upstream task's identity, which `ActiveTaskRailItem` (the endpoint this card is built from) doesn't carry today; building it means adding that field first, not a template change here. |
| Awaiting approval | `hold` `needs you` | `Paused — waiting for your approval` |
| Failed | `danger` `failed` | The reason, in one line, from the same `pause_reason`/`action_text` fallback above |

#### Empty state

Centred, 50px 18px: **Nothing running** (13.4px/550 `--text-secondary`) + "Tag an employee in the chat and their work will appear here as it happens." (12.4px)

Shown whenever nothing is active. The live panel has **no archive** — finished tasks leave it.

#### Footer

Border-top, 11px 14px. Two rows, 12.2px: `This project so far` / `₹{cost}` and `Hours saved` / `{n}`, values 600 weight, `.num`.

### 7.7 Stream events → UI

| Event | Payload | UI |
|---|---|---|
| `token` | `{delta}` | Append to the streaming body. Caret at the end. |
| `tool_start` | `{name, args_summary}` | `ToolCallBlock` in `running`, `info` badge |
| `tool_end` | `{name, result_summary, ok}` | Resolve to `completed` / `failed` |
| `approval_required` | `{approval_request_id, risk_level, reason}` | Render §7.3.E using the real risk and reason. Set the owning task to `hold`. |
| `error` | `{message}` | §7.3.H shape without the refusal copy. Say what happened and what to do. Never a stack trace. |
| `done` | `{message_id, session_id, provider, used_fallback, usage}` | Finalise. Adopt `session_id` if the session was new. Stop the avatar pulse. |

`used_fallback: true` shows nothing to the user. It's telemetry, not a status.

**Disconnect.** The backend's detached task keeps working. On reconnect, refetch history — the row will be complete. Show a quiet 12.4px line: `Reconnecting…` then `Caught up.` Never claim work was lost; it wasn't.

### 7.8 Supervisor outcomes → UI

| Outcome | Tasks created | UI |
|---|---|---|
| Dispatched, no inference | N | Acknowledgements (B), task cards appear |
| Dispatched, inferred edge | N | As above, plus a system line (I) per entry in `inferred_edge_notices` |
| `needs_clarification` | 0 or partial | Clarification card (G). Any fast-path-dispatched tasks still appear normally — partial dispatch is visible, not hidden. |
| `error` | 0 | Refusal (H). Message greyed with `not run`. Text restored to composer. |

Partial dispatch is the subtle one. When the planner fails but fast-path edges survived, some tasks run while others wait on a clarification. **Both must be visible simultaneously** — running task cards in the panel, clarification card in the thread. Do not hide one behind the other.

### 7.9 Build order

1. Employee avatar component (§7.4) — everything else depends on it
2. Message shape components A, B, C, I — the existing thread refactored to a shape-dispatched renderer
3. Live work panel with task cards and empty state
4. Composer with mention picker
5. Shapes D, E, F — output, approval, handoff
6. Shapes G, H — clarification and refusal
7. Responsive collapse

### 7.10 Acceptance checklist

Done when all of these hold:

- [ ] Two employees tagged in one message produce two acknowledgements and two task cards
- [ ] A dependent task shows `queued` naming its upstream, not a false progress bar
- [ ] An inferred edge always produces a visible system line
- [ ] The handoff card renders `payload_summary`, and `withheld` when present
- [ ] The approval card shows real `risk_level` and `reason`, and names any dependent it unblocks
- [ ] A clarification does not block the composer, and supersedes on the next message
- [ ] A refusal restores the raw text, mentions intact, unmangled
- [ ] Closing the tab mid-stream and reopening shows the complete message
- [ ] No spinner anywhere. Every progress indicator carries a unit of work.
- [ ] No colour, radius or font size outside `tokens.css`
- [ ] Full keyboard path through the composer and mention picker
- [ ] Renders correctly in both themes and under `prefers-reduced-motion`
