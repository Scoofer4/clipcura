# Clipsana design system

The living reference is the page `/_kitchen-sink` (`ui/src/screens/KitchenSink.tsx`). It renders every
building block with sample data and works without the backend. Screenshots for review are in
`docs/screenshots/m3a/` and are regenerated with `npm run screenshots` in `ui/`.

## Principles

1. **One main action per screen.** Drop a folder, see the state, fix in one click. Everything else is
   secondary and visually quieter.
2. **Plain words first, numbers on demand.** A finding says what it means for the edit ("Variable frame
   rate") and carries the measured value next to it in mono (`60 → 58.26`).
3. **Live system.** Scans, jobs and AI requests update in place through the event stream. Nothing needs a
   refresh.
4. **Status is never colour alone.** Every status pairs a hue with an icon and a word (WCAG 1.4.1).

## Motion and 3D

Clipsana comes from a company that works in spatial visualisation, so depth is part of the identity. It
has to stay timeless, though, which sets the rules:

- **One motif: the film frame.** Every 3D visual uses the same object, the frame (`ui/src/visuals/Frame.tsx`).
  No unrelated particles, grids or blobs.
- **Motion explains a cause or a state, never decorates.** Loose frames that line up mean "this folder will
  be put in order". Frames that arrive unevenly, pass the viewfinder gate and leave evenly spaced show what
  converting variable to constant frame rate does.
- **Visuals are instruments.** The drop zone's frames are part of the drop target and open the folder
  picker. The cadence view recomputes for the chosen target rate and states the consequence ("leaves out
  26 frames each second"). During a job the frames advance with the real processed-frame count.
- **Physically plausible.** Damped springs and inertia, soft light, matte-to-satin materials, a contact
  shadow. Depth comes from light and parallax, not from effects.
- **The still frame must work on its own.** With animations off (in-app switch or the Windows setting), or
  while a 3D view is off screen, every scene draws a single meaningful pose.
- **The GPU belongs to the transcode.** Scenes request the low-power GPU (the integrated one on hybrid
  laptops) and stop continuous rendering while a job runs. Job-driven visuals redraw only when progress
  arrives.
- **Short UI motion.** 150–250 ms with an ease-out curve, for things that answer the user: open, expand,
  confirm, reorder. One ambient motion at most per screen (the drop zone's scan line).

## Tokens

All colours are CSS variables in `ui/src/design-system/tokens.css`, so a brand change is a one-file edit.

| Group | Dark | Light | Notes |
|---|---|---|---|
| Page | `#12151a` → `#0c0e12` | `#f3f5f8` → `#e6eaf0` | graphite with a soft light falloff and film-grain noise |
| Panels | white at 3.5–6 % + blur | white at 72–92 % | "glass", thin light border |
| Text | `#e8eaed` / `#a3aab4` / `#7d8590` | `#14171c` / `#4b5563` / `#5f6875` | all ≥ 4.5:1 on page and panels |
| Ready | `#3ddc97` | `#0b7f51` | |
| Fixable | `#f5b841` | `#8a5d00` | |
| Needs you | `#ff8a3d` | `#b04a07` | |
| Error | `#ff5470` | `#c41d47` | pinker than the brand crimson, so "Fix" and "Error" never look alike |

Accents (switch `data-accent`):

- **Brand** comes from the Metaverse Media logo, measured from its pixels: `#bf1b2c` (shaded face),
  `#e52c3f` (lit face), plus the site's secondary `#fe6c61`.
- **Aurora** is the violet → cyan of the original brief: `#7c4dff` → `#22d3ee`.

Buttons use only the darker part of each gradient (`--accent-solid`), because white text on coral or cyan
would fall below WCAG AA. The accent colour itself is never used as text: at 4.0–4.4:1 on the page it is
reserved for fills, focus rings and glows.

## Type

- **Inter** (variable, bundled locally) for all interface text. Scale: 12, 13, 14, 15, 20, 28, 40 px.
  Headings use negative tracking (−0.02 to −0.035 em).
- **JetBrains Mono** (variable, bundled) only for technical values: frame rates, codecs, sizes, paths,
  timecode, commands. Tabular figures so numbers do not jump while they update.

## Shape

Three radii carry the hierarchy: panels 16 px, controls 10 px, chips fully round.

## Keyboard

Tab moves between rows, Space selects, Enter opens the detail, F fixes the selection. The command palette
(Ctrl+K) arrives with the screens in M3b. Focus is always visible as an accent outline.

## Logo

**Monogram** (owner's choice, 2026-11-02): a "C" left open on the right, where playback starts. The arc
carries the accent gradient and the play triangle uses the text colour, so the mark works on both themes.
It stays legible at 16 px (tray icon). Source: `ui/src/design-system/Logo.tsx`, favicon `ui/public/favicon.svg`.
The wordmark is lowercase "clipsana" in Inter Semibold with −0.035 em tracking.

The viewfinder corners remain the drop zone's motif. They are not part of the logo.

## Decisions

- 2026-11-02: visual style approved by the owner; Brand accent (Metaverse Media crimson) is the default and
  Aurora stays as an option in settings; logo is the Monogram.
