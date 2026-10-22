# Testing localisation

Contents

1. [Static checks (CI)](#1-static-checks-ci)
2. [Pseudo-locale](#2-pseudo-locale)
3. [Switching language on a device](#3-switching-language-on-a-device)
4. [Automated tests](#4-automated-tests)
5. [Manual pass checklist](#5-manual-pass-checklist)

## 1. Static checks (CI)

Run the helper from this skill against every `composeResources` directory:

```bash
python3 scripts/l10n_check.py check feature/notes/src/commonMain/composeResources
python3 scripts/l10n_check.py check shared/src/commonMain/composeResources --strict   # warnings fail too
```

The JSON output has `errors`, `warnings` and a `findings` list (`severity`, `code`, `locale`, `key`,
`message`). Exit code 1 means errors (or warnings with `--strict`). Typical CI rule: fail on errors,
report warnings (untranslated keys) without failing until translations land.

| Code | Severity | Meaning |
|---|---|---|
| `missing-default` | error | Key exists in a translation but not in `values/`; lookups fail for other locales |
| `unsupported-placeholder` | error | `%s`, `%d`, `%.2f`, `%@`… would be shown literally |
| `placeholder-mismatch` | error | Translation uses different `%N$` indices from the default |
| `plural-missing-other` | error | A plural without `other` throws for quantities that need it |
| `duplicate-key` / `xml-parse-error` | error | Broken resource files |
| `missing-translation` | warning | Falls back to the default language |
| `array-size-mismatch` | warning | Index-based use of the array breaks in this language |

## 2. Pseudo-locale

```bash
python3 scripts/l10n_check.py pseudo shared/src/commonMain/composeResources --dry-run   # report only
python3 scripts/l10n_check.py pseudo shared/src/commonMain/composeResources             # writes values-en-rXA/strings.xml
```

`Notes` becomes `[Ñöţéš ··]`: accented (encoding and font problems show), padded about 40%
(truncation shows), bracketed (clipped edges and concatenated fragments show). Any text that stays
plain English is hard-coded.

Selecting it:

- **Android:** enable developer options, then choose "English (XA)" in the system language list.
  Android's own `isPseudoLocalesEnabled = true` build flag pseudo-localises Android `res/` strings;
  do not rely on it for `composeResources`, which is why the script generates the folder.
- **iOS:** launch with `-AppleLanguages "(en-XA)"` (section 3). Xcode's built-in double-length and
  right-to-left pseudolanguages act on the iOS string tables, not on Compose resources.

Keep the generated folder out of release builds (generate it in a debug-only task, or add it to
`.gitignore` and generate locally). Never list `en-XA` in `CFBundleLocalizations` or
`locale_config.xml`: it is a test locale, not a language.

## 3. Switching language on a device

Android:

```bash
# Per-app language (Android 13+): the system settings page, or inspect the shell command
adb shell cmd locale help
# Whole emulator (from the JetBrains localisation-testing guide; restarts the framework)
adb -e shell "setprop persist.sys.locale fr-FR; stop; sleep 5; start"
```

Developer options also offer "Force RTL layout direction" to check mirroring without translations.

iOS simulator / XCUITest:

```bash
xcrun simctl launch booted com.example.app -AppleLanguages "(fr)" -AppleLocale fr_FR
```

```swift
let app = XCUIApplication()
app.launchArguments = ["-AppleLanguages", "(ar)", "-AppleLocale", "ar_SA"]
app.launch()
```

In Xcode: scheme → Run → Options → App Language / App Region.

## 4. Automated tests

- **ViewModels** emit enums or resource references, so their tests need no locale at all.
- **Formatters:** construct them with an explicit locale (`AndroidLocaleFormatter(Locale.FRANCE)`,
  `IosLocaleFormatter(NSLocale(localeIdentifier = "fr_FR"))`) and run the tests on both platforms
  (`testAndroidHostTest` or `testDebugUnitTest`, and `iosSimulatorArm64Test`). Assert on parts or
  normalise ` `/` ` before comparing whole strings.
- **UI tests** locate nodes by test tag, never by visible text, so they keep passing in every language.
  Translation correctness is checked by the static check plus per-locale screenshots.
- **Fallback:** run once with a language the app does not support; every string must come from
  `values/`.

## 5. Manual pass checklist

Report each as PASS / FAIL / NOT RUN per platform:

1. Each supported language: the main flows show no English leftovers.
2. One RTL language: layout mirrors; back arrows and chevrons mirror; numbers, phone numbers and
   media controls do not.
3. Pseudo-locale: no truncation of buttons, tabs, titles; no plain-English text.
4. Largest system font size combined with the longest language: nothing clipped.
5. Plurals: 0, 1, 2, 5, 21 items in a language with complex rules (for example Polish or Arabic).
6. Dates and numbers: order, separators and month names match the language and region.
7. iOS: Settings → the app → Language lists the supported languages.
8. Android 13+: Settings → Apps → the app → Language lists the supported languages.
