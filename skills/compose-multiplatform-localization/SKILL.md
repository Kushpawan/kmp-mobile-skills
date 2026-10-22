---
name: compose-multiplatform-localization
description: Use when localising a Compose Multiplatform app — composeResources strings.xml, values-fr / values-b+zh+Hans folders, plurals, string arrays, stringResource, pluralStringResource, getString, generated Res class, format arguments, iOS language not switching (CFBundleLocalizations), Android per-app language, in-app language picker, RTL layout, locale-aware dates and numbers, pseudo-locales, or "%s shows literally", missing translations, wrong plural.
license: Apache-2.0
compatibility: Kotlin Multiplatform project with Compose Multiplatform 1.8+ resources (org.jetbrains.compose.components:components-resources). iOS steps need macOS with Xcode. The helper script needs Python 3.9+.
metadata:
  category: ui
  platforms: android, ios
---

# Compose Multiplatform localization

All user-visible text lives in `commonMain/composeResources/values*/strings.xml` and is resolved in
the UI layer. ViewModels carry *what* to say (an enum, a resource reference), not the localised
string. Each platform must also be told which languages the app supports, and dates/numbers are
formatted with the platform's locale-aware formatters.

## When to use

- Adding the first translation, a new language, or new strings to a CMP app.
- Plurals, format arguments, string arrays, resources used outside composables.
- iOS shows the wrong language or system UI in a different language from the app; the Android
  per-app language setting is missing; building an in-app language picker.
- Right-to-left support; locale-aware date, time, number and currency formatting.
- Symptoms: `%s` or `%.2f` appears literally, a crash or blank text for one locale, "1 notes",
  English month names inside French text.

## When not to use

- Projects that localise with another library (moko-resources, Lyricist, native
  `Localizable.xcstrings` + Android `res/`): follow that library; the platform-declaration,
  RTL and formatting sections still apply.
- Strings inside a native SwiftUI UI → the iOS string catalog; see SwiftUI skills in Related.

## Step 0 — Read the project first

1. **Mechanism.** Search for `composeResources`, `Res.string.`, `stringResource(`, moko
   (`MR.strings`), or Android `R.string` in shared code. Keep the existing one.
2. **Resource config.** In the module's `build.gradle.kts`, the `compose.resources { }` block:
   `publicResClass`, `packageOfResClass`, `generateResClass`. Note which module owns which `Res`.
3. **Languages.** List the `values-*` folders and compare with iOS `CFBundleLocalizations`
   (`iosApp/iosApp/Info.plist`) and Android `android:localeConfig` / `res/xml/locale_config.xml`.
4. **How text leaves ViewModels.** Strings, resource ids, enums, a `UiText` type?
5. **Formatting.** Existing date/number helpers (`expect`/`actual`, kotlinx-datetime formats);
   Android `minSdk` (java.time needs core-library desugaring below API 26).
6. **Key naming convention** in existing `strings.xml`.

## Workflow

### 1. Dependency and configuration

```toml
# gradle/libs.versions.toml — use the Compose Multiplatform version
[libraries]
compose-components-resources = { module = "org.jetbrains.compose.components:components-resources", version.ref = "compose-multiplatform" }
```

```kotlin
kotlin {
    sourceSets {
        commonMain.dependencies { implementation(libs.compose.components.resources) }
    }
}
compose.resources {
    packageOfResClass = "com.example.app.resources"   // stable import path, independent of module renames
    // publicResClass = true                           // only if other modules must read this module's Res
}
```

The `compose.components.resources` accessor of the Compose Gradle plugin is deprecated from Compose
Multiplatform 1.10; use the catalog entry. With the Android KMP library plugin, also set
`androidResources.enable = true` in `kotlin { androidLibrary { } }` (AGP 8.8+).

Done when a build generates `Res` and `Res.string.<key>` resolves in the IDE.

### 2. Write the default strings

`commonMain/composeResources/values/strings.xml` holds **every** key, in the fallback language:

```xml
<resources>
    <string name="notes_list_title">Notes</string>
    <string name="notes_greeting">Hello, %1$s!</string>
    <string name="notes_synced_at">Last synced %1$s</string>
    <plurals name="notes_selected_count">
        <item quantity="one">%1$d note selected</item>
        <item quantity="other">%1$d notes selected</item>
    </plurals>
    <string-array name="notes_sort_options">
        <item>Newest first</item>
        <item>Oldest first</item>
    </string-array>
</resources>
```

- Name keys `feature_screen_element` (or the project's convention); never by content (`hello_text`).
- A key that exists only in a translation folder fails at runtime for every other locale.

### 3. Add translations

| Language | Folder |
|---|---|
| French | `values-fr/` |
| Portuguese (Brazil) | `values-pt-rBR/` (lowercase `r` before the region) |
| Chinese, Simplified / Traditional | `values-b+zh+Hans/`, `values-b+zh+Hant/` **plus** a script-less `values-zh/` |
| Arabic (RTL) | `values-ar/` |

Qualifiers are case-sensitive. Without the script-less folder, a device reporting `zh` without a
script finds no resource and falls back to the default.

### 4. Format arguments: positional `%N$s` / `%N$d` only

Compose Multiplatform substitutes only `%1$s`, `%2$d`, … (`$s` and `$d` behave the same). Anything
else — `%s`, `%d`, `%.2f`, `%1$.2f`, `%@` — is shown **literally**.

- Pre-format numbers, dates and currency in code (step 9) and pass the result as `%1$s`.
- Keep indices stable so translators can reorder: `"%2$s a %1$d notes"` is valid.
- Translations must use the same set of indices as the default (the script checks it). Passing
  fewer arguments than the highest index throws at runtime.

### 5. Plurals and arrays

```kotlin
Text(pluralStringResource(Res.plurals.notes_selected_count, count, count))  // quantity, then format arg
val options: List<String> = stringArrayResource(Res.array.notes_sort_options)
```

- Quantity is an `Int`. The plural rule (`zero`/`one`/`two`/`few`/`many`/`other`) is chosen from the
  current language; `other` is required in every language.
- Pass the number twice: once as the quantity, once as the format argument.
- Never build sentences by concatenating fragments; word order differs between languages.
- Translations of a string array must keep the same number of items.

### 6. Resolve text in the UI; carry intent from ViewModels

```kotlin
Text(stringResource(Res.string.notes_greeting, userName))
```

- `stringResource` follows the composition's locale and recomposes when it changes.
- ViewModels expose an enum / sealed type (`NoteEditorError.SaveFailed`) that the composable maps to a
  resource — the ViewModel stays testable without resources, and Compose-free logic modules (which
  cannot depend on the resources library) work the same way.
- Outside composition (notification text, share sheets) use `suspend fun getString(Res.string.x)`.
  It reads the **process** locale — Android `LocaleList.getAdjustedDefault()`, iOS
  `NSLocale.preferredLanguages` — not a Compose-level override.

### 7. Declare supported languages on each platform

- **iOS:** list every language in `Info.plist` → `CFBundleLocalizations` (and keep
  `CFBundleDevelopmentRegion` as the default). Compose resources do not live in `.lproj` folders, so
  without this key iOS treats the app as single-language: system-provided UI (alerts, pickers,
  permission prompts) can stay in the development language, the per-app Language option in
  Settings is typically not offered, and the App Store may list only one language.
- **Android:** add `res/xml/locale_config.xml` listing the languages and reference it with
  `android:localeConfig` on `<application>`. AGP's `generateLocaleConfig` derives the list from
  Android `res/values-*` folders, so it does not see `composeResources` strings — write the file by
  hand unless the module also has matching Android resources.

Code and details: [references/platform-language-setup.md](references/platform-language-setup.md).

### 8. In-app language picker

- **Android:** `AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags("fr"))`
  (activity must extend `AppCompatActivity`; add the `autoStoreLocales` service entry for API < 33).
  `stringResource` follows it through the activity configuration.
- **iOS:** there is no supported runtime API; the reliable path is opening the app's Settings page
  (`UIApplication.openSettingsURLString`), where the per-app language appears once step 7 is done.
- JetBrains documents a cross-platform workaround (a `LocalAppLocale` CompositionLocal that rewrites
  the platform locale); it changes process-wide state and JetBrains calls it temporary. See the
  reference before adopting it.

### 9. Dates, times, numbers, currency

kotlinx-datetime does **not** do locale-aware formatting (its README puts internationalisation out of
scope); its format DSL builds fixed patterns. Put a small formatter interface in `commonMain` and
implement it per platform with `java.time`/`java.text` (Android) and `NSDateFormatter`/
`NSNumberFormatter` (iOS). Code: [references/formatting-dates-numbers.md](references/formatting-dates-numbers.md).

### 10. Right-to-left

- Compose mirrors layouts automatically for RTL locales. Use `start`/`end`, never `left`/`right`.
- Directional icons (back arrows, chevrons) must mirror: `Icons.AutoMirrored.*` or
  `ImageVector.Builder(autoMirror = true)`. For vector drawables in `composeResources`, check on an
  RTL device that `android:autoMirrored="true"` is honoured by your Compose Multiplatform version.
- Keep inherently LTR content LTR (phone numbers, media controls, code) with
  `CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) { … }`.
- If Arabic text appears on iOS but the layout does not mirror, check the declared localizations
  (step 7) before debugging layout code.

### 11. Check, pseudo-localise, test

```bash
python3 scripts/l10n_check.py check shared/src/commonMain/composeResources          # JSON report
python3 scripts/l10n_check.py check shared/src/commonMain/composeResources --format table
python3 scripts/l10n_check.py pseudo shared/src/commonMain/composeResources --dry-run
```

`check` reports keys missing from `values/` (error), placeholder mismatches and unsupported
placeholders (error), plurals without `other` (error), missing translations and array-size
mismatches (warning). `pseudo` writes `values-en-rXA/strings.xml` with accented, padded, bracketed
text so truncation and hard-coded strings stand out. Locale-switching commands and test patterns:
[references/testing-localization.md](references/testing-localization.md).

## Quick reference

| Need | API / location |
|---|---|
| String in a composable | `stringResource(Res.string.key)` / `stringResource(Res.string.key, arg1, arg2)` |
| Plural | `pluralStringResource(Res.plurals.key, quantity, quantity)` |
| Array | `stringArrayResource(Res.array.key)` |
| Outside composition | `getString(...)`, `getPluralString(...)`, `getStringArray(...)` (suspend) |
| Placeholders | `%1$s`, `%2$d` only |
| Escapes | `\n`, `\t`, `\uXXXX`; `@` and `?` need no escaping |
| Language + region folder | `values-pt-rBR` |
| Script | `values-b+zh+Hans` + `values-zh` fallback |
| Force a direction | `CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr)` |
| iOS supported languages | `Info.plist` → `CFBundleLocalizations` |
| Android per-app languages | `res/xml/locale_config.xml` + `android:localeConfig` |

## Verify

Report each check as **PASS**, **FAIL** or **NOT RUN (reason)**.

```bash
python3 scripts/l10n_check.py check <module>/src/commonMain/composeResources    # exit 0 = no errors
python3 -m unittest discover -s scripts/tests                                   # helper's own tests (from the skill dir)
./gradlew :shared:compileKotlinMetadata                                         # Res accessors generate and compile
./gradlew :composeApp:assembleDebug
/usr/libexec/PlistBuddy -c "Print :CFBundleLocalizations" iosApp/iosApp/Info.plist   # macOS
```

Manual (report NOT RUN without a device/simulator): switch to each supported language on Android and
iOS; check one RTL language; run once with the pseudo-locale; set an unsupported language and
confirm the default strings appear.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| `%s`, `%d`, `%.2f` in strings | Shown literally; CMP only substitutes `%N$s`/`%N$d` | Positional placeholders; pre-format numbers |
| Key only in `values-xx/` | Lookup fails for every other locale | Every key in `values/` |
| `values-zh-Hans` folder name | Scripts are only recognised in the `b+` form | `values-b+zh+Hans` plus `values-zh` |
| No `CFBundleLocalizations` on iOS | System UI and formatters disagree with app text; no per-app language in Settings | Declare all languages |
| Relying on `generateLocaleConfig` | It reads Android `res/`, not `composeResources` | Hand-written `locale_config.xml` |
| Resolving strings in the ViewModel with `getString` | Ignores Compose-level locale changes; harder to test | Emit an enum/resource; resolve in UI |
| `"$count " + stringResource(...)` concatenation | Breaks word order and plural rules | One string with placeholders / plurals |
| Plural without `other`, or quantity passed but not the format arg | Runtime exception: a missing category falls back to `other`, and a missing `other` throws; a placeholder without a matching argument throws an index error | `other` always; pass the number twice |
| `Modifier.padding(left = …)` / non-mirrored back arrow | Wrong side in RTL | `start`/`end`; auto-mirrored icons |
| `LocalDate.toString()` shown to users | ISO format, not localised | Platform formatter via `expect`/`actual` |
| Exact-string assertions on formatted dates | CLDR data differs between JDK/Android/iOS versions (e.g. narrow no-break spaces) | Assert on parts or normalise whitespace |
| Expecting Android pseudo-locales to cover CMP strings | They are built from Android `res/` | Generate `values-en-rXA` with the script |

## Related skills

- `compose-multiplatform-screen` — where text is rendered and how errors travel from the ViewModel.
- `compose-design-system-component` — components that own strings (e.g. "Loading").
- `figma-to-mobile-ui` — moving design copy into resources.
- [AvdLee/SwiftUI-Agent-Skill](https://github.com/AvdLee/SwiftUI-Agent-Skill) and
  [twostraws/SwiftUI-Agent-Skill](https://github.com/twostraws/SwiftUI-Agent-Skill) — for a native
  SwiftUI UI with its own string catalog.
- [Meet-Miyani/compose-skill](https://github.com/Meet-Miyani/compose-skill) — broader Compose/CMP skill set.
