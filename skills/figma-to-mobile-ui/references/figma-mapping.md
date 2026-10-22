# Figma → Compose Multiplatform / SwiftUI mapping

Contents

1. [Units](#1-units)
2. [Auto layout](#2-auto-layout)
3. [Sizing and constraints](#3-sizing-and-constraints)
4. [Text](#4-text)
5. [Colour and variables](#5-colour-and-variables)
6. [Shape, stroke, effects](#6-shape-stroke-effects)
7. [Images and icons](#7-images-and-icons)
8. [Components, variants and properties](#8-components-variants-and-properties)
9. [States the design may not show](#9-states-the-design-may-not-show)
10. [Worked translation](#10-worked-translation)

## 1. Units

| Figma | Android (Compose) | iOS (SwiftUI) |
|---|---|---|
| 1 px (at 1x) | 1 `dp` | 1 `pt` |
| Font size px | `sp` (scales with user font size) | `pt`, via a font helper that supports Dynamic Type |
| Letter spacing % | `em` = % / 100 (`0.02.em` for 2%) | `.tracking(fontSize × % / 100)` in pt |
| Letter spacing px | `sp` | `.tracking(px)` |
| Line height px | `lineHeight = x.sp` | No direct modifier; approximate with `.lineSpacing(lineHeight − font line height)` and check visually |
| Line height % | `lineHeight = (% / 100).em` | as above |

## 2. Auto layout

| Figma auto layout | Compose | SwiftUI |
|---|---|---|
| Direction horizontal | `Row` | `HStack` |
| Direction vertical | `Column` | `VStack` |
| Wrap | `FlowRow` / `FlowColumn` (foundation layout) | a custom `Layout` (iOS 16+) or the project's flow helper |
| Gap N | `Arrangement.spacedBy(token)` | `HStack(spacing: token)` |
| Gap "Auto" (space between) | `Arrangement.SpaceBetween` | `Spacer()` between children |
| Padding T/R/B/L | `Modifier.padding(start=, top=, end=, bottom=)` | `.padding(EdgeInsets(top:leading:bottom:trailing:))` |
| Alignment (cross axis) | `verticalAlignment` (Row) / `horizontalAlignment` (Column) | `HStack(alignment:)` / `VStack(alignment:)` |
| Absolute-positioned child | `Box { … Modifier.align(...).offset(...) }` | `ZStack(alignment:)` + `.offset` |
| Layer order (z) | Later children draw on top; `Modifier.zIndex` | Later children on top; `.zIndex` |

Use `start`/`end` (Compose) and `leading`/`trailing` (SwiftUI), never left/right, so RTL layouts
mirror correctly.

## 3. Sizing and constraints

| Figma | Compose | SwiftUI |
|---|---|---|
| Fill container (main axis in a row/column) | `Modifier.weight(1f)` | `.frame(maxWidth: .infinity)` (HStack) / `maxHeight` (VStack) |
| Fill container (cross axis) | `fillMaxWidth()` / `fillMaxHeight()` | `.frame(maxWidth: .infinity)` |
| Hug contents | default (wrap content) | default; `.fixedSize()` to prevent truncation |
| Fixed W×H | `Modifier.size(...)` — only for icons, avatars, illustrations | `.frame(width:height:)` |
| Min / max width | `widthIn(min =, max =)` | `.frame(minWidth:maxWidth:)` |
| Frame width (e.g. 390) | Not a width: the screen. Use `fillMaxSize()` | Not a width: the screen |
| Constraints Left & Right / Scale | Fill width with padding | Fill width with padding |

Mobile frames are drawn at one device size. Build for every width: never copy the frame width or
absolute x/y positions of flowing content.

## 4. Text

- Map the text style to a typography token (`AppTheme.typography.bodyMedium`), not to its parts.
  When the style has no token, use the nearest and list it as a deviation.
- Text colour → colour token for the role (`onSurface`, `onSurfaceVariant`), even when the hex
  matches another token.
- "Truncate text" with N lines → `maxLines = N, overflow = TextOverflow.Ellipsis` / `.lineLimit(N)`.
- "Auto height" → no height at all. "Fixed size" text boxes → still avoid fixed heights; allow growth
  for large font sizes.
- Copy goes into string resources; placeholder text in the mock (`Lorem ipsum`, sample names) belongs
  in previews only.

## 5. Colour and variables

`get_variable_defs` returns the variables bound to the node. Typical naming → token:

| Variable naming | Token |
|---|---|
| `color/primary`, `Primary/Default` | `AppTheme.colors.primary` |
| `color/on-primary`, `Text/On Primary` | `AppTheme.colors.onPrimary` |
| `surface/default` | `AppTheme.colors.surface` |
| `border/subtle` | `AppTheme.colors.outline` |
| `space/4`, `spacing-md` | `AppTheme.spacing.<matching step>` |
| `radius/md` | `AppTheme.shapes.medium` |

Rules:

- Variables with light/dark modes map to one role token whose light/dark values come from the theme.
  Never branch on dark mode in the screen.
- A colour with an opacity in Figma: prefer a dedicated token; use `token.copy(alpha = …)` only if the
  design system already does that.
- A hex value with no variable bound: map to the nearest role token **by role**, not by closest hex,
  and report it.

## 6. Shape, stroke, effects

| Figma | Compose | SwiftUI |
|---|---|---|
| Corner radius | shape token: `clip(AppTheme.shapes.medium)` / `background(color, shape)` | `.clipShape(RoundedRectangle(cornerRadius: token))` |
| Individual corners | `RoundedCornerShape(topStart=, topEnd=, …)` from tokens | `UnevenRoundedRectangle` (check its minimum iOS version against the deployment target) |
| Stroke inside/center | `Modifier.border(width, color, shape)` | `.overlay(RoundedRectangle(...).strokeBorder(color, lineWidth:))` |
| Drop shadow | `Modifier.shadow(elevation, shape)` — an approximation; Figma blur/spread/offset do not map 1:1 | `.shadow(color:radius:x:y:)` — radius is roughly half the Figma blur; check visually |
| Layer blur / background blur | `Modifier.blur(...)` (content blur only) | `.blur(radius:)`, `.background(.ultraThinMaterial)` |
| Opacity | `Modifier.alpha(...)` | `.opacity(...)` |

Prefer the design system's elevation/shadow tokens when they exist; the platform shadow models
differ and per-screen tuning drifts.

## 7. Images and icons

- Use only assets the Figma payload provides. Do not swap in an icon library or placeholder images.
- Icons → vector: Compose `composeResources/drawable/ic_name.xml` (Android vector XML) read with
  `painterResource(Res.drawable.ic_name)`; SwiftUI asset catalog SVG/PDF with "Preserve Vector Data",
  rendered as template images so they take the foreground colour.
- Icon tint → colour token (`Icon(tint = AppTheme.colors.onSurface)` / `.foregroundStyle(...)`).
- Decorative images: `contentDescription = null` / `.accessibilityHidden(true)`. Meaningful images:
  a localised description.
- Image fill → `ContentScale.Crop` / `.scaledToFill().clipped()`; fit → `ContentScale.Fit` /
  `.scaledToFit()`.

## 8. Components, variants and properties

| Figma | Code |
|---|---|
| Component instance | Existing component (Code Connect map first) |
| Variant property (`Type=Primary`, `Size=Large`) | Enum parameters (`variant = AppButtonVariant.Primary`, `size = AppButtonSize.Large`) |
| Boolean property (`Show icon`) | Optional slot (`leadingIcon = { … }`) or nullable parameter |
| Instance swap property | Slot parameter |
| Text property | `String` parameter (from resources at the call site) |
| Detached instance | Treat as the original component plus overrides; ask if the override is intentional |

## 9. States the design may not show

Before finishing, decide each of these for every interactive element and list what you assumed:
pressed, disabled, loading, error/validation, empty list, offline, long text / large font, RTL.

## 10. Worked translation

Design: a note card — vertical auto layout, padding 16, gap 8, radius `radius/md`, fill `surface`,
stroke 1 `border/subtle`; title `type/title/md`, body `type/body/md` truncated to 2 lines, a
horizontal row of tag chips with gap 4.

Compose:

```kotlin
@Composable
fun NoteCard(
    title: String,
    preview: String,
    tags: List<NoteTag>,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(AppTheme.shapes.medium)
            .background(AppTheme.colors.surface)
            .border(width = AppTheme.borders.thin, color = AppTheme.colors.outline, shape = AppTheme.shapes.medium)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(AppTheme.spacing.md),
        verticalArrangement = Arrangement.spacedBy(AppTheme.spacing.sm),
    ) {
        Text(text = title, style = AppTheme.typography.titleMedium, color = AppTheme.colors.onSurface)
        Text(
            text = preview,
            style = AppTheme.typography.bodyMedium,
            color = AppTheme.colors.onSurfaceVariant,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        FlowRow(horizontalArrangement = Arrangement.spacedBy(AppTheme.spacing.xs)) {
            tags.forEach { tag -> AppTagChip(label = tag.label, modifier = Modifier.testTag(NotesTestTags.tagChip(tag.id))) }
        }
    }
}
```

SwiftUI:

```swift
struct NoteCard: View {
    let title: String
    let preview: String
    let tags: [NoteTag]
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: AppSpacing.sm) {
                Text(title).appFont(.titleMedium).foregroundStyle(Color.appOnSurface)
                Text(preview).appFont(.bodyMedium).foregroundStyle(Color.appOnSurfaceVariant).lineLimit(2)
                HStack(spacing: AppSpacing.xs) {
                    ForEach(tags) { tag in
                        AppTagChip(label: tag.label).accessibilityIdentifier("notes.tagChip.\(tag.id)")
                    }
                }
            }
            .padding(AppSpacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.appSurface)
            .clipShape(RoundedRectangle(cornerRadius: AppRadius.md))
            .overlay(RoundedRectangle(cornerRadius: AppRadius.md).strokeBorder(Color.appOutline, lineWidth: AppBorder.thin))
        }
        .buttonStyle(.plain)
    }
}
```

`AppTheme.borders`, `AppSpacing`, `AppRadius`, `appFont`, `Color.app*` and `AppTagChip` stand for
the project's real tokens and components. The SwiftUI tag row uses `HStack`; if tags must wrap,
use the project's flow layout. `NoteTag` must be `Identifiable` for `ForEach`.
