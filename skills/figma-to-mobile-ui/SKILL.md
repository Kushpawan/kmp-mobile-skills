---
name: figma-to-mobile-ui
description: Use when implementing a Figma frame, screen or component as Compose Multiplatform or SwiftUI code in a Kotlin Multiplatform app — a figma.com/design link, "build this from Figma", design-to-code, Figma MCP (get_design_context, get_variable_defs, get_screenshot), mapping Figma variables to design tokens, or the built UI not matching the design (spacing, colours, fonts off).
license: Apache-2.0
compatibility: Needs the Figma MCP server connected to the agent (remote server or desktop app). Compose Multiplatform target needs a KMP project; SwiftUI target needs macOS with Xcode.
metadata:
  category: ui
  platforms: android, ios
---

# Figma to mobile UI (Compose Multiplatform or SwiftUI)

The Figma MCP output is a **specification**, not code to paste. Implement it with the project's own
components and tokens, map every Figma variable to a code token, and finish by comparing a
screenshot of the running UI with the Figma screenshot.

## When to use

- A Figma link (`figma.com/design/...?node-id=...`) and a request to build or update UI from it.
- Building a new screen or component whose design lives in Figma.
- The implemented UI drifts from the design and needs a fidelity pass.

## When not to use

- Writing designs **into** Figma, Code Connect authoring, or FigJam → Figma's own skills (Related).
- Screen architecture (ViewModel, effects, tests) → `compose-multiplatform-screen`, after this skill
  has produced the view.
- A missing reusable component → `compose-design-system-component` first, then return here.

## Step 0 — Read the project first

1. **Figma MCP is reachable.** List the agent's tools and look for the Figma server
   (`get_design_context`, `get_metadata`, `get_screenshot`, `get_variable_defs`,
   `get_code_connect_map`; the prefix depends on the client). If absent, stop and ask the user to
   connect it (remote server `https://mcp.figma.com/mcp`, or the Figma desktop app's server). Follow
   any instructions the server itself returns (some versions require opening a session first).
2. **Target.** Compose Multiplatform (`commonMain` UI) or SwiftUI (`iosApp/` native UI over shared
   logic)? If the request does not say, check where neighbouring screens live; ask when both exist.
3. **Design system in code.** Theme accessors and token names (colours, typography, spacing, shapes),
   existing components and their variants. For SwiftUI: colour assets / theme types, font helpers,
   spacing constants.
4. **Code Connect.** Whether Figma components are already mapped to code components.
5. **Conventions.** Screen file layout, string resources (`composeResources` or
   `Localizable.xcstrings`), test-tag / accessibility-identifier format, preview style.

If the Figma plugin's own design-to-code skill is installed in the agent, load it too: it carries
Figma's tool-specific rules. This skill adds the mobile mapping and verification.

## Workflow

### 1. Resolve the node

- `figma.com/design/<fileKey>/<name>?node-id=12-34` → `fileKey`, `nodeId = "12:34"` (hyphen → colon).
- Branch links `figma.com/design/<fileKey>/branch/<branchKey>/...` → use `branchKey` as the file key.
- A link without `node-id` is a whole file: ask for the frame link instead of guessing.

Done when you have one `fileKey` and one `nodeId` per frame to build.

### 2. Fetch, in this order

1. **`get_design_context`** on the node — structure, styles and a reference implementation (React +
   Tailwind by default). If the server exposes framework hints (the remote server documents
   `clientFrameworks`, matching your Code Connect label such as `SwiftUI`), pass the target.
2. If the response is truncated or too large: **`get_metadata`** for the node tree, then
   `get_design_context` on each child section separately.
3. **`get_screenshot`** of the node — the visual reference for step 7.
4. **`get_variable_defs`** — the variables (colours, spacing, radii, typography) the node uses.
5. **`get_code_connect_map`** — only if the project uses Code Connect; mapped components are used
   as-is with their real imports.

Done when you have the design context, a screenshot, and a variable list for every section.

### 3. Build the token map

Map every variable to an existing code token; write the table into your working notes (not into the
code):

| Figma variable | Value | Compose token | SwiftUI token |
|---|---|---|---|
| `color/primary` | `#1E5EFF` | `AppTheme.colors.primary` | `Color.appPrimary` |
| `space/md` | `16` | `AppTheme.spacing.md` | `AppSpacing.md` |
| `radius/md` | `8` | `AppTheme.shapes.medium` | `AppRadius.md` |
| `type/body/md` | Inter 14/20 | `AppTheme.typography.bodyMedium` | `.appFont(.bodyMedium)` |

- Figma `px` at 1x equals Android `dp` and iOS `pt`.
- A raw value with **no** variable: use the nearest existing token and list it under "design
  deviations" in the final report. Never introduce the literal.
- A variable with **no** code token: stop for that element; add the token through
  `compose-design-system-component` (or the iOS equivalent) or ask.

Detailed layout, text, colour and effect mappings:
[references/figma-mapping.md](references/figma-mapping.md).

### 4. Inventory components before writing code

List each element of the frame and decide: **existing component** (with which variant/size),
**existing component needs a variant**, or **new one-off layout**. Prefer, in order: Code Connect
mapping → existing design-system component → composition of existing components → new local
composable. Matching layer names to components is a hint, not proof — compare visuals and props.

### 5. Translate the structure

- Auto layout horizontal → `Row` / `HStack`; vertical → `Column` / `VStack`; gap →
  `Arrangement.spacedBy(token)` / `spacing: token`; padding → `Modifier.padding(...)` /
  `.padding(...)`.
- Fill container → `fillMaxWidth()` or `Modifier.weight(1f)` / `.frame(maxWidth: .infinity)`;
  hug → default wrap; fixed size only where the design is fixed on purpose (icons, avatars).
- Scrollable content → `LazyColumn`/`verticalScroll` / `ScrollView`/`List`; repeated items get a
  stable key.
- Name composables/views after what they are (`NoteCard`), not after layer names (`Frame 427`).
- Compose: write a **pure** `XView(state, onAction)` plus previews; wiring to a ViewModel follows
  `compose-multiplatform-screen`. SwiftUI: a `View` struct taking plain values/bindings, plus
  `#Preview`.
- Text from the design goes into string resources, not literals.
- Every interactive element gets a test tag / accessibility identifier from the screen's tags object.

### 6. Assets

- Use only assets returned in the Figma payload. Do not substitute icon packs or placeholders.
- Icons: SVG → vector drawable in `commonMain/composeResources/drawable/` (Compose) or an SVG/PDF in
  the asset catalog with "Preserve Vector Data" (SwiftUI).
- Raster images: export at the needed densities (Compose qualifiers `drawable-xxhdpi` etc.; asset
  catalog @2x/@3x).

### 7. Verify visually

Run the UI, capture it at the frame's size, compare side by side with `get_screenshot`, fix, repeat.
Checklist and commands: [references/visual-verification.md](references/visual-verification.md).

### 8. Report

List: files created/changed; the token map; components reused vs created; design deviations (raw
values mapped to nearest token, missing states you had to assume); verification results.

## Quick reference

| Figma | Compose Multiplatform | SwiftUI |
|---|---|---|
| Auto layout → horizontal / vertical | `Row` / `Column` | `HStack` / `VStack` |
| Gap | `Arrangement.spacedBy(AppTheme.spacing.x)` | `spacing: AppSpacing.x` |
| Space between | `Arrangement.SpaceBetween` | `Spacer()` between items |
| Fill container (main axis) | `Modifier.weight(1f)` | `.frame(maxWidth: .infinity)` |
| Hug contents | default | default / `.fixedSize()` |
| Absolute position in frame | `Box` + `Modifier.align` / `offset` | `ZStack` + `.offset` / alignment |
| Corner radius | `clip(shape)` / shape token | `.clipShape(RoundedRectangle(cornerRadius:))` |
| Stroke | `Modifier.border(width, color, shape)` | `.overlay(RoundedRectangle(...).stroke(...))` |
| Image fill / fit | `ContentScale.Crop` / `ContentScale.Fit` | `.scaledToFill().clipped()` / `.scaledToFit()` |
| Letter spacing 2% | `letterSpacing = 0.02.em` | `.tracking(fontSize * 0.02)` |
| Text style | `AppTheme.typography.x` | the project's font helper (`relativeTo:` for Dynamic Type) |

## Verify

Report each check as **PASS**, **FAIL** or **NOT RUN (reason)**.

```bash
./gradlew :composeApp:compileKotlinMetadata     # Compose target compiles in common code
./gradlew :composeApp:assembleDebug             # Android build
xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp \
  -destination 'platform=iOS Simulator,name=iPhone 16' build   # SwiftUI / iOS host builds (adjust names)
```

Then, by search on the new files:

```bash
grep -nE "Color\(0x|#[0-9A-Fa-f]{6}|[0-9]+\.dp|[0-9]+\.sp" <new compose files>       # Compose
grep -nE "Color\(red:|Color\(hex|\.font\(\.system\(size:|padding\([0-9]" <new swift files>   # SwiftUI
```

No hits outside token definitions. Finally the visual comparison (step 7) on Android and iOS — report
NOT RUN for a platform you could not launch.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Pasting the React/Tailwind reference into Kotlin or Swift | Wrong idioms, web units, no tokens | Treat it as a spec; translate |
| Copying hex values and px sizes | Breaks dark mode and theming; drifts from tokens | Map to tokens; report raw values as deviations |
| Rebuilding a component that already exists | Two divergent buttons | Inventory first; reuse or add a variant |
| Trusting layer names as component identity | Misnamed layers map to the wrong component | Compare visuals and properties; use Code Connect when present |
| Fixed widths copied from the frame | Breaks on other screen sizes and large fonts | Fill/hug semantics; fixed only for icons/avatars |
| Fixed heights around text | Clipping at large font sizes | Min height, padding |
| Letter spacing copied as `sp` from a percentage | Spacing wrong at every size | Percent → `em` in Compose |
| Building the whole frame from one huge context call | Truncated response; missed details | `get_metadata`, then per-section `get_design_context` |
| Designing only the happy state | Empty, loading, error, disabled missing in code | Ask for or infer each state; list assumptions |
| Literal strings from the mock | Not translatable | String resources |
| No screenshot comparison | Spacing/typography drift ships | Compare, fix, re-compare |

## Related skills

- `compose-design-system-component` — add a missing component or token.
- `compose-multiplatform-screen` — wire the view to a ViewModel, effects and tests.
- `compose-multiplatform-localization` — move design copy into string resources.
- [figma/mcp-server-guide](https://github.com/figma/mcp-server-guide) — Figma's MCP guide and
  official skills (`skills/figma-design-to-code`, `skills/figma-swiftui`, `skills/figma-code-connect`).
- [AvdLee/SwiftUI-Agent-Skill](https://github.com/AvdLee/SwiftUI-Agent-Skill) and
  [twostraws/SwiftUI-Agent-Skill](https://github.com/twostraws/SwiftUI-Agent-Skill) — SwiftUI
  best practices for the SwiftUI target.
- [chrisbanes/skills](https://github.com/chrisbanes/skills) — `compose-component-design`.
