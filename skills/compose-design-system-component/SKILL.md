---
name: compose-design-system-component
description: Use when creating or changing a reusable Compose Multiplatform design-system component — button, text field, chip, card, badge, avatar, dialog — or theme tokens: variant and size enums, enabled/disabled/loading/error states, CompositionLocal theming, light/dark previews, accessibility semantics, testTag hooks, component gallery. Also for hardcoded colors or dp in components, or a component that ignores dark mode.
license: Apache-2.0
compatibility: Kotlin Multiplatform project with Compose Multiplatform 1.8+ (commonMain UI). Component UI tests need an iOS simulator or an Android device/emulator.
metadata:
  category: ui
  platforms: android, ios
---

# Compose Multiplatform design-system component

A design-system component takes **every** visual value from theme tokens, exposes a small fixed set
of variants and sizes, handles each interaction state explicitly, is accessible without extra work
at the call site, and is visible in previews and the component gallery before any screen uses it.

## When to use

- Adding a reusable UI primitive to the shared design-system module (or `ui/components` package).
- Adding a variant, size or state (loading, error) to an existing component.
- Adding or restructuring theme tokens (colours, typography, spacing, shapes) and the theme entry.
- Symptoms: hex colours or raw `dp` inside components, dark mode wrong in one component, a
  component unreadable at large font sizes, QA cannot locate an inner element.

## When not to use

- A layout used by one screen only → build it inside that screen (`compose-multiplatform-screen`).
- Implementing a Figma frame → `figma-to-mobile-ui` (it calls back here when a component is missing).
- SwiftUI components for a native iOS UI → SwiftUI skills in Related; the token rules still apply.

## Step 0 — Read the project first

1. **Where components live.** A design-system module (`:designsystem`, `:core:ui`, …) or a package in
   `:composeApp`/`:shared`. Write only there.
2. **Theme entry and tokens.** Find the theme composable (`AppTheme { }` or similar) and how tokens
   are read: `AppTheme.colors.*`, `MaterialTheme.colorScheme.*` plus extensions, plain `object`s.
   List the colour/typography/spacing/shape token names available. **Never invent token names.**
3. **Material 3 or custom.** Do components wrap Material 3 (`Button`, `OutlinedTextField`) or draw
   from foundation primitives? Match the existing ones.
4. **Existing components.** Search for the component and its synonyms (`Button`, `Cta`, `Action`).
   If one exists, extend it with a variant instead of adding a sibling.
5. **Conventions.** Name prefix (`App`, a brand prefix, none), parameter order, `Defaults`/`Colors`
   objects, preview import (`androidx.compose.ui.tooling.preview.Preview` on Compose
   Multiplatform 1.10+, `org.jetbrains.compose.ui.tooling.preview.Preview` before), gallery/showcase
   app and how entries are registered.
6. **Resources.** Is the component allowed to own strings (`composeResources` in the design-system
   module, with `publicResClass` if consumers need them)?

With no design system at all, create the theme first:
[references/theme-and-tokens.md](references/theme-and-tokens.md).

## Workflow

### 1. Decide the API before writing pixels

```kotlin
@Composable
fun AppButton(
    text: String,                                  // required content first
    onClick: () -> Unit,
    modifier: Modifier = Modifier,                 // first optional parameter
    variant: AppButtonVariant = AppButtonVariant.Primary,
    size: AppButtonSize = AppButtonSize.Medium,
    enabled: Boolean = true,
    loading: Boolean = false,
    leadingIcon: (@Composable () -> Unit)? = null, // slot, not an icon enum
    colors: AppButtonColors = AppButtonDefaults.colors(variant),
    interactionSource: MutableInteractionSource? = null,
)
```

- Variants and sizes are `enum`s with the values design actually uses — not booleans
  (`isPrimary`, `isLarge`) that multiply into invalid combinations.
- Content that varies in shape is a **slot** (`@Composable () -> Unit`); content that is just text
  is a `String`.
- No domain types (`Note`, `Order`) and no ViewModels: the component must be usable from any feature.
- Colour sets resolved per variant live in an `@Immutable` `XColors` class, built by `XDefaults`.

Done when the signature reads well at three call sites you write down first.

### 2. Resolve every visual from tokens

| Must use | Must not use |
|---|---|
| `AppTheme.colors.<token>` (or the project's colour accessor) | `Color(0xFF…)`, `Color.Red`, `Color.White` |
| `AppTheme.spacing.<token>` | `8.dp`, `16.dp` padding/gaps |
| `AppTheme.shapes.<token>` | `RoundedCornerShape(12.dp)` inline |
| `AppTheme.typography.<style>` | `TextStyle(fontSize = 14.sp)`, `fontSize =` on `Text` |
| Size/height tokens in `XDefaults` (one place) | Magic numbers scattered in the body |
| Theme-provided indication (`LocalIndication.current`) | Hand-rolled press overlays |
| `commonMain` APIs only | `android.*`, `platform.UIKit.*`, Android `R` resources |

A token is missing? Add it to the token set (light **and** dark values) first, in its own commit —
never inline the value "for now".

### 3. Handle every state explicitly

| State | Visual | Behaviour | Semantics |
|---|---|---|---|
| Enabled | `colors.container` / `colors.content` | Clickable | role (`Role.Button`, `Role.Checkbox`, …) |
| Pressed | `colors.pressedContainer` from `collectIsPressedAsState()` | — | — |
| Disabled | `disabledContainer` / `disabledContent` | Not clickable (`enabled = false`) | Disabled (set by `clickable(enabled = false)`) |
| Loading | Content hidden but still measured (no width jump), progress indicator | Clicks ignored | `stateDescription` = localised "Loading" |
| Error (inputs) | Error colour + supporting text | Still editable | `Modifier.semantics { error(message) }` |
| Focused (inputs/TV) | Focus ring token | — | Handled by focusable/text field |

Done when the preview matrix shows every row of this table for every variant.

### 4. Make it accessible by default

- Interactive components meet a 48 dp minimum touch target (`Modifier.minimumInteractiveComponentSize()`
  with Material 3, or a size token) even when the visual is smaller.
- Use `heightIn(min = …)`, never a fixed `height`, around text: fixed heights clip at large font scales.
- Icon-only components take a **required** `contentDescription: String?` parameter; `null` only for
  decorative use.
- Use `Modifier.clickable(role = …, onClickLabel = …)` / `toggleable` / `selectable` so screen readers
  announce the right control type.
- Contrast comes from token pairs (`primary`/`onPrimary`); do not mix tokens from different pairs.

### 5. Test tags

- Callers tag the component through `modifier` (`Modifier.testTag(...)`). Apply the `modifier`
  parameter to the clickable root so the tag and the click land on the same semantics node.
- Do **not** add a `testTag: String` parameter by default. Add a named one
  (`clearButtonTestTag`, `actionTestTag`) only when QA must reach an **inner** element.
- Compose Multiplatform exposes `testTag` as the iOS `accessibilityIdentifier`.

### 6. Previews

- Preview the full matrix: variants × sizes × {enabled, disabled, loading, error}.
- Render it twice: `AppTheme(darkTheme = false)` and `AppTheme(darkTheme = true)`. Android `uiMode`
  constants are not available in `commonMain`, so switch the theme parameter instead.
- Always inside the app theme, never a bare `MaterialTheme`, so missing tokens fail loudly.

### 7. Gallery / showcase

Register the component in the project's gallery (catalog screen, showcase app, Storybook-like list)
using the same matrix composable as the preview. If no gallery exists, report where one would go;
do not invent one unasked.

### 8. Tests

Component behaviour worth pinning (clicks ignored while loading, disabled semantics, role) goes in a
common UI test with `runComposeUiTest`. Visual correctness is reviewed in previews/screenshots.
Full component, preview, gallery and test code:
[references/app-button-example.md](references/app-button-example.md).

## Quick reference

| Concern | Choice |
|---|---|
| Theme values that rarely change | `staticCompositionLocalOf { error("AppTheme not applied") }` |
| Values that change often (per item) | `compositionLocalOf` — or better, a parameter |
| Read a token | `AppTheme.colors.primary` (a `@Composable @ReadOnlyComposable` getter) |
| Per-variant colours | `@Immutable data class XColors` + `object XDefaults { @Composable fun colors(variant) }` |
| Press state | `interactionSource ?: remember { MutableInteractionSource() }` + `collectIsPressedAsState()` |
| Fonts from resources | `org.jetbrains.compose.resources.Font(Res.font.x)` — composable, so build typography inside the theme composable |
| Common UI test | `runComposeUiTest { }` with `@OptIn(ExperimentalTestApi::class)`, artifact `org.jetbrains.compose.ui:ui-test` |

## Verify

Report every check as **PASS**, **FAIL** or **NOT RUN (reason)**. Replace `:designsystem` with the
real module.

```bash
./gradlew :designsystem:compileKotlinMetadata          # compiles in common code
./gradlew :designsystem:iosSimulatorArm64Test           # common UI tests on iOS (macOS)
./gradlew :designsystem:connectedAndroidTest            # common UI tests on Android (device/emulator,
                                                        # after the instrumented-test setup in the reference)
./gradlew :composeApp:assembleDebug                     # gallery / app still builds
```

Common Compose UI tests do not run as Android host (local JVM) tests; report that row NOT RUN if no
device or emulator is available. Then check by search:

```bash
grep -nE "Color\(0x|Color\.(Red|White|Black|Gray)|[0-9]+\.dp|[0-9]+\.sp|TextStyle\(" <component file>
```

Every hit must be inside a token definition or `XDefaults`, not in the component body.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Hex colours or `Color.White` in the component | Breaks dark mode and rebrands | Token from the theme; add the token first |
| Raw `dp`/`sp` in the body | Drift from design spacing scale | Spacing/size tokens, centralised in `XDefaults` |
| Boolean flags for variants (`isPrimary`, `isOutlined`) | Invalid combinations, unreadable call sites | `enum class XVariant` |
| Loading replaces text with a spinner | Button width jumps; layout shifts | Keep text measured but invisible; overlay the indicator |
| Loading state still clickable | Double submissions | `clickable(enabled = enabled && !loading)` |
| Fixed `height(40.dp)` around text | Text clipped at 200% font scale | `heightIn(min = …)` |
| Icon-only button with no description | Screen readers say "button" only | Required `contentDescription` parameter |
| Theme local with a default value | Missing `AppTheme` goes unnoticed in previews and tests | `error(...)` default |
| `compositionLocalOf` for the whole theme | Every reader tracked; slower recomposition for no benefit | `staticCompositionLocalOf` for rarely-changing tokens |
| `testTag` parameter on every component | API noise; tags drift from callers | Tag through `modifier`; named inner-tag params only when needed |
| Preview in bare `MaterialTheme` | Shows wrong colours; hides missing tokens | Preview in `AppTheme`, light and dark |
| New component duplicating an existing one | Two buttons drift apart | Extend the existing component with a variant |
| Platform imports in `commonMain` component | iOS compile fails | Keep to Compose Multiplatform APIs; platform needs via `expect`/`actual` |

## Related skills

- `figma-to-mobile-ui` — mapping Figma variables to these tokens.
- `compose-multiplatform-screen` — using components inside screens.
- `compose-multiplatform-localization` — component strings (e.g. "Loading") and RTL mirroring.
- [chrisbanes/skills](https://github.com/chrisbanes/skills) — `compose-component-design` (slot APIs)
  and `compose-performance` (stability, recomposition).
- [android/skills — jetpack-compose](https://github.com/android/skills/tree/main/jetpack-compose) —
  Google's Compose theming/styles skills for Android-only apps.
