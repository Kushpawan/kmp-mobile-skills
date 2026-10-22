# Worked example — `AppButton`

A complete token-driven button: three variants, three sizes, pressed/disabled/loading states,
accessibility semantics, a preview matrix in light and dark, a gallery entry and common UI tests.
`AppTheme` is the theme from `theme-and-tokens.md`; rename to the project's own.

Contents

1. [Variants, sizes, colours, defaults](#1-variants-sizes-colours-defaults)
2. [The component](#2-the-component)
3. [Preview matrix](#3-preview-matrix)
4. [Gallery entry](#4-gallery-entry)
5. [Common UI tests](#5-common-ui-tests)
6. [Self-review checklist](#6-self-review-checklist)

## 1. Variants, sizes, colours, defaults

```kotlin
package com.example.app.designsystem.components

enum class AppButtonVariant { Primary, Secondary, Destructive }
enum class AppButtonSize { Small, Medium, Large }

@Immutable
data class AppButtonColors(
    val container: Color,
    val content: Color,
    val pressedContainer: Color,
    val disabledContainer: Color,
    val disabledContent: Color,
)

object AppButtonDefaults {

    @Composable
    fun colors(variant: AppButtonVariant): AppButtonColors = when (variant) {
        AppButtonVariant.Primary -> AppButtonColors(
            container = AppTheme.colors.primary,
            content = AppTheme.colors.onPrimary,
            pressedContainer = AppTheme.colors.primaryPressed,
            disabledContainer = AppTheme.colors.disabledContainer,
            disabledContent = AppTheme.colors.disabledContent,
        )
        AppButtonVariant.Secondary -> AppButtonColors(
            container = AppTheme.colors.secondaryContainer,
            content = AppTheme.colors.onSecondaryContainer,
            pressedContainer = AppTheme.colors.outline,
            disabledContainer = AppTheme.colors.disabledContainer,
            disabledContent = AppTheme.colors.disabledContent,
        )
        AppButtonVariant.Destructive -> AppButtonColors(
            container = AppTheme.colors.error,
            content = AppTheme.colors.onError,
            pressedContainer = AppTheme.colors.error.copy(alpha = 0.85f),
            disabledContainer = AppTheme.colors.disabledContainer,
            disabledContent = AppTheme.colors.disabledContent,
        )
    }

    // Size tokens live here, in one place, not in the composable body.
    fun minHeight(size: AppButtonSize): Dp = when (size) {
        AppButtonSize.Small -> 32.dp
        AppButtonSize.Medium -> 40.dp
        AppButtonSize.Large -> 48.dp
    }

    val IndicatorStrokeWidth: Dp = 2.dp

    fun indicatorSize(size: AppButtonSize): Dp = when (size) {
        AppButtonSize.Small -> 14.dp
        AppButtonSize.Medium -> 18.dp
        AppButtonSize.Large -> 20.dp
    }

    @Composable
    fun contentPadding(size: AppButtonSize): PaddingValues = when (size) {
        AppButtonSize.Small -> PaddingValues(horizontal = AppTheme.spacing.sm, vertical = AppTheme.spacing.xxs)
        AppButtonSize.Medium -> PaddingValues(horizontal = AppTheme.spacing.md, vertical = AppTheme.spacing.xs)
        AppButtonSize.Large -> PaddingValues(horizontal = AppTheme.spacing.lg, vertical = AppTheme.spacing.sm)
    }

    @Composable
    fun textStyle(size: AppButtonSize): TextStyle = when (size) {
        AppButtonSize.Small -> AppTheme.typography.labelMedium
        AppButtonSize.Medium, AppButtonSize.Large -> AppTheme.typography.labelLarge
    }
}
```

`pressedContainer` for `Destructive` derives from a token with `copy(alpha = …)`; if the design has
a dedicated pressed token, use it instead.

## 2. The component

```kotlin
@Composable
fun AppButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    variant: AppButtonVariant = AppButtonVariant.Primary,
    size: AppButtonSize = AppButtonSize.Medium,
    enabled: Boolean = true,
    loading: Boolean = false,
    leadingIcon: (@Composable () -> Unit)? = null,
    colors: AppButtonColors = AppButtonDefaults.colors(variant),
    interactionSource: MutableInteractionSource? = null,
) {
    val source = interactionSource ?: remember { MutableInteractionSource() }
    val isPressed by source.collectIsPressedAsState()
    val containerColor = when {
        !enabled -> colors.disabledContainer
        isPressed -> colors.pressedContainer
        else -> colors.container
    }
    val contentColor = if (enabled) colors.content else colors.disabledContent
    val loadingDescription = stringResource(Res.string.ds_loading)

    Box(
        modifier = modifier                                   // caller's testTag lands on this node
            .minimumInteractiveComponentSize()                // 48dp touch target, visual may be smaller
            .heightIn(min = AppButtonDefaults.minHeight(size)) // min, not fixed: survives large fonts
            .clip(AppTheme.shapes.medium)                     // clip before background + ripple
            .background(containerColor)
            .clickable(
                interactionSource = source,
                indication = LocalIndication.current,
                enabled = enabled && !loading,                // no double submit while loading
                role = Role.Button,
                onClick = onClick,
            )
            .semantics { if (loading) stateDescription = loadingDescription }
            .padding(AppButtonDefaults.contentPadding(size)),
        contentAlignment = Alignment.Center,
    ) {
        // Keep the label measured while loading so the button does not change width.
        Row(
            modifier = Modifier.alpha(if (loading) 0f else 1f),
            horizontalArrangement = Arrangement.spacedBy(AppTheme.spacing.xs),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (leadingIcon != null) {
                CompositionLocalProvider(LocalContentColor provides contentColor) { leadingIcon() }
            }
            Text(
                text = text,
                style = AppButtonDefaults.textStyle(size),
                color = contentColor,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (loading) {
            CircularProgressIndicator(
                modifier = Modifier.size(AppButtonDefaults.indicatorSize(size)),
                color = contentColor,
                strokeWidth = AppButtonDefaults.IndicatorStrokeWidth,
            )
        }
    }
}
```

Notes:

- `Res.string.ds_loading` lives in the design-system module's `composeResources/values/strings.xml`
  (translated like any other string).
- `LocalContentColor` and `CircularProgressIndicator` come from Material 3; with a non-Material
  design system, use the project's own progress component and content-colour local.
- `clickable(enabled = false)` already marks the node disabled for accessibility services.
- To reuse Material 3's `Button` instead, map `AppButtonColors` to `ButtonDefaults.buttonColors(...)`;
  keep the loading and size rules above.

## 3. Preview matrix

```kotlin
import androidx.compose.ui.tooling.preview.Preview   // Compose Multiplatform 1.10+

@Composable
internal fun AppButtonMatrix() {
    Column(
        modifier = Modifier.background(AppTheme.colors.surface).padding(AppTheme.spacing.md),
        verticalArrangement = Arrangement.spacedBy(AppTheme.spacing.sm),
    ) {
        AppButtonVariant.entries.forEach { variant ->
            AppButtonSize.entries.forEach { size ->
                Row(horizontalArrangement = Arrangement.spacedBy(AppTheme.spacing.sm)) {
                    AppButton(text = "Save", onClick = {}, variant = variant, size = size)
                    AppButton(text = "Save", onClick = {}, variant = variant, size = size, enabled = false)
                    AppButton(text = "Save", onClick = {}, variant = variant, size = size, loading = true)
                }
            }
        }
    }
}

@Preview
@Composable
private fun AppButtonLightPreview() {
    AppTheme(darkTheme = false) { AppButtonMatrix() }
}

@Preview
@Composable
private fun AppButtonDarkPreview() {
    AppTheme(darkTheme = true) { AppButtonMatrix() }
}
```

Literal labels are fine in previews; production call sites pass localised strings.

## 4. Gallery entry

Reuse the matrix in the project's component gallery. A typical shape:

```kotlin
val componentGallery: List<GalleryEntry> = listOf(
    // …existing entries…
    GalleryEntry(name = "Button", content = { AppButtonMatrix() }),
)
```

Find the real registry first (`grep -rn "GalleryEntry\|Showcase\|Catalog" --include=*.kt`). Add the
entry in the same order/grouping as its neighbours.

## 5. Common UI tests

Dependency: `org.jetbrains.compose.ui:ui-test` in `commonTest` (catalog entry with the Compose
Multiplatform version). Recent releases expose `runComposeUiTest` from
`androidx.compose.ui.test.v2`; older ones from `androidx.compose.ui.test`. Use the import your
version offers. Running on Android needs the instrumented-test setup from the JetBrains testing
guide (device test source set, `AndroidJUnitRunner`, `ui-test-manifest`).

```kotlin
@OptIn(ExperimentalTestApi::class)
class AppButtonTest {

    @Test
    fun should_invokeOnClick_when_enabled() = runComposeUiTest {
        var clicks = 0
        setContent { AppTheme { AppButton(text = "Save", onClick = { clicks++ }, modifier = Modifier.testTag(TAG)) } }

        onNodeWithTag(TAG).performClick()

        assertEquals(1, clicks)
    }

    @Test
    fun should_ignoreClicks_when_loading() = runComposeUiTest {
        var clicks = 0
        setContent { AppTheme { AppButton(text = "Save", onClick = { clicks++ }, loading = true, modifier = Modifier.testTag(TAG)) } }

        onNodeWithTag(TAG).performClick()

        assertEquals(0, clicks)
    }

    @Test
    fun should_exposeDisabledButton_when_disabled() = runComposeUiTest {
        setContent { AppTheme { AppButton(text = "Save", onClick = {}, enabled = false, modifier = Modifier.testTag(TAG)) } }

        onNodeWithTag(TAG)
            .assertIsNotEnabled()
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Button))
    }

    private companion object {
        const val TAG = "app_button_under_test"
    }
}
```

## 6. Self-review checklist

- [ ] No colour, `dp` or `sp` literal outside `AppButtonDefaults` and token files.
- [ ] Every variant × size × state appears in the preview, in light and dark.
- [ ] Loading: width stable, clicks ignored, state announced.
- [ ] Disabled: disabled colours, not clickable, announced as disabled.
- [ ] Touch target ≥ 48 dp; text not clipped at large font scale (check with the system font size at maximum).
- [ ] `modifier` applied to the clickable root; no `testTag` parameter unless an inner element needs one.
- [ ] Only `commonMain` APIs; compiles for iOS.
- [ ] Gallery entry added, or the missing gallery reported.
