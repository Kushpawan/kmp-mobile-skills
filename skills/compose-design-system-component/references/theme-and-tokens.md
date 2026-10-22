# Theme and tokens for a Compose Multiplatform design system

Use this when the project has no theme layer yet, or to check an existing one. If the project
already reads tokens another way (Material 3 `colorScheme` plus extensions, a brand object), keep it.

Contents

1. [Token groups](#1-token-groups)
2. [Theme entry with CompositionLocals](#2-theme-entry-with-compositionlocals)
3. [Light and dark palettes](#3-light-and-dark-palettes)
4. [Typography with resource fonts](#4-typography-with-resource-fonts)
5. [Bridging to Material 3](#5-bridging-to-material-3)
6. [Rules for adding a token](#6-rules-for-adding-a-token)

## 1. Token groups

Name tokens by **role**, not by value: `primary`, `onPrimary`, `surface`, `outline`, `error` — not
`blue500` at the call site. A raw palette (`Blue500`) may exist, but only the theme references it.

```kotlin
package com.example.app.designsystem.theme

@Immutable
data class AppColors(
    val primary: Color,
    val onPrimary: Color,
    val primaryPressed: Color,
    val secondaryContainer: Color,
    val onSecondaryContainer: Color,
    val surface: Color,
    val onSurface: Color,
    val onSurfaceVariant: Color,
    val outline: Color,
    val error: Color,
    val onError: Color,
    val disabledContainer: Color,
    val disabledContent: Color,
    val isDark: Boolean,
)

@Immutable
data class AppSpacing(
    val xxs: Dp = 2.dp,
    val xs: Dp = 4.dp,
    val sm: Dp = 8.dp,
    val md: Dp = 16.dp,
    val lg: Dp = 24.dp,
    val xl: Dp = 32.dp,
)

@Immutable
data class AppShapes(
    val small: Shape = RoundedCornerShape(4.dp),
    val medium: Shape = RoundedCornerShape(8.dp),
    val large: Shape = RoundedCornerShape(16.dp),
    val full: Shape = RoundedCornerShape(percent = 50),
)

@Immutable
data class AppTypography(
    val titleLarge: TextStyle,
    val titleMedium: TextStyle,
    val bodyLarge: TextStyle,
    val bodyMedium: TextStyle,
    val labelLarge: TextStyle,
    val labelMedium: TextStyle,
)
```

Token files are the **only** place literal `dp`, `sp` and colour values appear.

## 2. Theme entry with CompositionLocals

```kotlin
private val LocalAppColors = staticCompositionLocalOf<AppColors> { error("AppTheme is not applied") }
private val LocalAppSpacing = staticCompositionLocalOf<AppSpacing> { error("AppTheme is not applied") }
private val LocalAppShapes = staticCompositionLocalOf<AppShapes> { error("AppTheme is not applied") }
private val LocalAppTypography = staticCompositionLocalOf<AppTypography> { error("AppTheme is not applied") }

/** Read tokens as AppTheme.colors.primary, AppTheme.spacing.md, … */
object AppTheme {
    val colors: AppColors
        @Composable @ReadOnlyComposable get() = LocalAppColors.current
    val spacing: AppSpacing
        @Composable @ReadOnlyComposable get() = LocalAppSpacing.current
    val shapes: AppShapes
        @Composable @ReadOnlyComposable get() = LocalAppShapes.current
    val typography: AppTypography
        @Composable @ReadOnlyComposable get() = LocalAppTypography.current
}

@Composable
fun AppTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colors = if (darkTheme) DarkAppColors else LightAppColors
    val typography = appTypography()
    CompositionLocalProvider(
        LocalAppColors provides colors,
        LocalAppSpacing provides AppSpacing(),
        LocalAppShapes provides AppShapes(),
        LocalAppTypography provides typography,
    ) {
        MaterialTheme(
            colorScheme = colors.toMaterialColorScheme(),
            typography = typography.toMaterialTypography(),
            content = content,
        )
    }
}
```

Why these choices:

- `staticCompositionLocalOf`: theme values change rarely (dark-mode switch). Changing one
  recomposes the subtree, which is fine at that frequency, and reads are cheaper than with
  `compositionLocalOf`, which tracks every reader.
- `error(...)` as the default: a preview or test that forgot `AppTheme { }` fails immediately instead
  of silently rendering fallback colours.
- The object and the composable share the name `AppTheme`, the same way `MaterialTheme` does: call
  sites read `AppTheme { }` to apply and `AppTheme.colors` to read.

## 3. Light and dark palettes

```kotlin
private object Palette {
    val Blue600 = Color(0xFF1E5EFF)
    val Blue700 = Color(0xFF1748C7)
    val Blue300 = Color(0xFF8DAEFF)
    val Grey50 = Color(0xFFF7F8FA)
    val Grey400 = Color(0xFF9AA1AD)
    val Grey900 = Color(0xFF14171C)
    val Red600 = Color(0xFFD92D20)
    val Red300 = Color(0xFFFF8A80)
    val White = Color(0xFFFFFFFF)
}

internal val LightAppColors = AppColors(
    primary = Palette.Blue600, onPrimary = Palette.White, primaryPressed = Palette.Blue700,
    secondaryContainer = Palette.Grey50, onSecondaryContainer = Palette.Grey900,
    surface = Palette.White, onSurface = Palette.Grey900, onSurfaceVariant = Palette.Grey400,
    outline = Palette.Grey400, error = Palette.Red600, onError = Palette.White,
    disabledContainer = Palette.Grey50, disabledContent = Palette.Grey400, isDark = false,
)

internal val DarkAppColors = AppColors(
    primary = Palette.Blue300, onPrimary = Palette.Grey900, primaryPressed = Palette.Blue600,
    secondaryContainer = Palette.Grey900, onSecondaryContainer = Palette.Grey50,
    surface = Palette.Grey900, onSurface = Palette.Grey50, onSurfaceVariant = Palette.Grey400,
    outline = Palette.Grey400, error = Palette.Red300, onError = Palette.Grey900,
    disabledContainer = Palette.Grey900, disabledContent = Palette.Grey400, isDark = true,
)
```

The values are placeholders; take real ones from the design source (Figma variables, brand guide).
Check each `x`/`onX` pair for contrast (WCAG AA: 4.5:1 for body text) in both palettes.

## 4. Typography with resource fonts

`org.jetbrains.compose.resources.Font(...)` is a composable function, so build the typography
inside composition:

```kotlin
@Composable
internal fun appTypography(): AppTypography {
    val brand = FontFamily(
        Font(Res.font.brand_regular, FontWeight.Normal),
        Font(Res.font.brand_medium, FontWeight.Medium),
        Font(Res.font.brand_semibold, FontWeight.SemiBold),
    )
    return remember(brand) {
        AppTypography(
            titleLarge = TextStyle(fontFamily = brand, fontWeight = FontWeight.SemiBold, fontSize = 22.sp, lineHeight = 28.sp),
            titleMedium = TextStyle(fontFamily = brand, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 24.sp),
            bodyLarge = TextStyle(fontFamily = brand, fontWeight = FontWeight.Normal, fontSize = 16.sp, lineHeight = 24.sp),
            bodyMedium = TextStyle(fontFamily = brand, fontWeight = FontWeight.Normal, fontSize = 14.sp, lineHeight = 20.sp),
            labelLarge = TextStyle(fontFamily = brand, fontWeight = FontWeight.Medium, fontSize = 14.sp, lineHeight = 20.sp),
            labelMedium = TextStyle(fontFamily = brand, fontWeight = FontWeight.Medium, fontSize = 12.sp, lineHeight = 16.sp),
        )
    }
}
```

Fonts go in `commonMain/composeResources/font/`. Use `sp` (scales with the user's font size), never
`dp`, for text.

## 5. Bridging to Material 3

Material 3 components used inside the app (dialogs, date pickers, text selection handles) read
`MaterialTheme`. Map the app tokens once so they match:

```kotlin
internal fun AppColors.toMaterialColorScheme(): ColorScheme {
    val base = if (isDark) darkColorScheme() else lightColorScheme()
    return base.copy(
        primary = primary, onPrimary = onPrimary,
        secondaryContainer = secondaryContainer, onSecondaryContainer = onSecondaryContainer,
        surface = surface, onSurface = onSurface, onSurfaceVariant = onSurfaceVariant,
        outline = outline, error = error, onError = onError,
    )
}

internal fun AppTypography.toMaterialTypography(): Typography = Typography(
    titleLarge = titleLarge, titleMedium = titleMedium,
    bodyLarge = bodyLarge, bodyMedium = bodyMedium,
    labelLarge = labelLarge, labelMedium = labelMedium,
)
```

## 6. Rules for adding a token

1. Search the existing tokens for the role first; reuse beats a near-duplicate.
2. Name it by role (`warningContainer`), add **both** light and dark values.
3. Add it to the Material bridge if a Material component should pick it up.
4. If the design tool has variables, keep the token name traceable to the variable
   (`color/warning/container` → `warningContainer`).
5. Land the token in its own commit so the review of the component stays about the component.
