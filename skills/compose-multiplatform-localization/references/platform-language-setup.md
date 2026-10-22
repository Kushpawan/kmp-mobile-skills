# Declaring languages and switching them per platform

Contents

1. [How each platform picks the language for Compose resources](#1-how-each-platform-picks-the-language-for-compose-resources)
2. [iOS: declare localizations](#2-ios-declare-localizations)
3. [Android: per-app language preferences](#3-android-per-app-language-preferences)
4. [A shared language-controller interface](#4-a-shared-language-controller-interface)
5. [JetBrains' runtime-override workaround](#5-jetbrains-runtime-override-workaround)

## 1. How each platform picks the language for Compose resources

| Path | Android | iOS |
|---|---|---|
| `stringResource` (composable) | `LocalConfiguration.current.locales` — follows the activity configuration, including a per-app locale | `NSLocale.preferredLanguages` |
| `getString` (suspend, non-composable) | `LocaleList.getAdjustedDefault()` (process default) | `NSLocale.preferredLanguages` |

Compose resources pick the first preferred language they have resources for, then fall back to
`values/`. The platform itself (system dialogs, Foundation/`java.text` formatters, iOS Settings,
App Store) knows nothing about `composeResources`, which is why the languages must also be declared.

## 2. iOS: declare localizations

`iosApp/iosApp/Info.plist`:

```xml
<key>CFBundleDevelopmentRegion</key>
<string>en</string>
<key>CFBundleLocalizations</key>
<array>
    <string>en</string>
    <string>fr</string>
    <string>pt-BR</string>
    <string>zh-Hans</string>
    <string>ar</string>
</array>
```

- Use the same languages as the `values-*` folders (iOS identifiers use hyphens: `pt-BR`,
  `zh-Hans`).
- Apple describes `CFBundleLocalizations` as the list of localizations an app handles itself rather
  than through `.lproj` folders — the situation of Compose resources.
- Adding the languages in Xcode (Project → Info → Localizations) creates `.lproj` folders for the
  project's own files; either way, check the built bundle declares every language.
- If the app has an `InfoPlist.strings` / `InfoPlist.xcstrings` (localised permission prompts, app
  name), translate it for the same languages.

Verify:

```bash
/usr/libexec/PlistBuddy -c "Print :CFBundleLocalizations" iosApp/iosApp/Info.plist
```

Offering a language switch on iOS: open the app's page in Settings, where the per-app Language
option appears for multi-language apps.

```swift
if let url = URL(string: UIApplication.openSettingsURLString) {
    UIApplication.shared.open(url)
}
```

## 3. Android: per-app language preferences

`androidApp/src/main/res/xml/locale_config.xml` (write it by hand: AGP's `generateLocaleConfig`
reads Android `res/values-*` folders, not `composeResources`, and fails the build if a manual file
also exists):

```xml
<?xml version="1.0" encoding="utf-8"?>
<locale-config xmlns:android="http://schemas.android.com/apk/res/android">
    <locale android:name="en" />
    <locale android:name="fr" />
    <locale android:name="pt-BR" />
    <locale android:name="zh-Hans" />
    <locale android:name="ar" />
</locale-config>
```

`AndroidManifest.xml`:

```xml
<application
    android:localeConfig="@xml/locale_config"
    ...>
    <!-- Android 12 (API 32) and lower: let AppCompat persist the chosen locale -->
    <service
        android:name="androidx.appcompat.app.AppLocalesMetadataHolderService"
        android:enabled="false"
        android:exported="false">
        <meta-data android:name="autoStoreLocales" android:value="true" />
    </service>
</application>
```

Change the language from code (main thread):

```kotlin
AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags("fr"))   // "" or empty list = system
val current: LocaleListCompat = AppCompatDelegate.getApplicationLocales()
```

Requirements and side effects:

- The activity must extend `AppCompatActivity` (with an AppCompat-compatible theme) for this to work
  with Compose; `ComponentActivity` alone does not apply it.
- The call recreates the activity unless it handles locale configuration changes itself.
- `autoStoreLocales` performs a blocking read on the main thread at startup (StrictMode may flag it).
- On Android 13+, users can also set the language in system settings; open that page directly with
  `Intent(Settings.ACTION_APP_LOCALE_SETTINGS, Uri.fromParts("package", packageName, null))`.

## 4. A shared language-controller interface

Keep the picker UI in common code and the mechanics per platform:

```kotlin
// commonMain
interface AppLanguageController {
    /** False where the OS owns the choice (iOS): show a "Change in Settings" button instead. */
    val canChangeInApp: Boolean
    /** BCP 47 tag of the app-specific language, or null when following the system. */
    fun currentLanguageTag(): String?
    fun setLanguage(languageTag: String?)
    fun openSystemLanguageSettings()
}
```

```kotlin
// androidMain
class AndroidAppLanguageController(private val context: Context) : AppLanguageController {
    override val canChangeInApp = true
    override fun currentLanguageTag(): String? =
        AppCompatDelegate.getApplicationLocales().takeUnless { it.isEmpty }?.toLanguageTags()
    override fun setLanguage(languageTag: String?) =
        AppCompatDelegate.setApplicationLocales(
            if (languageTag == null) LocaleListCompat.getEmptyLocaleList() else LocaleListCompat.forLanguageTags(languageTag),
        )
    override fun openSystemLanguageSettings() {
        val intent = if (Build.VERSION.SDK_INT >= 33) {
            Intent(Settings.ACTION_APP_LOCALE_SETTINGS, Uri.fromParts("package", context.packageName, null))
        } else {
            Intent(Settings.ACTION_LOCALE_SETTINGS)
        }
        context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
```

```kotlin
// iosMain
class IosAppLanguageController(private val openSettings: () -> Unit) : AppLanguageController {
    override val canChangeInApp = false
    override fun currentLanguageTag(): String? = null
    override fun setLanguage(languageTag: String?) = Unit
    override fun openSystemLanguageSettings() = openSettings()   // Swift passes the snippet from section 2
}
```

Bind each implementation in the platform DI module (Koin: `single<AppLanguageController> { … }`).

## 5. JetBrains' runtime-override workaround

The Compose Multiplatform docs ("Manage local resource environment") show an `expect object
LocalAppLocale` with a `provides` infix and an `AppEnvironment` wrapper that re-keys the content when
a `customAppLocale` state changes. The platform `actual`s:

- Android: call `Locale.setDefault(...)` and update the `Configuration` passed through
  `LocalConfiguration`.
- iOS: write the `AppleLanguages` array to `NSUserDefaults` and provide the new value through a
  CompositionLocal.

Before adopting it, weigh:

- JetBrains labels it a temporary workaround until a common API exists.
- Both actuals change **process-wide** state; Android's uses deprecated configuration APIs.
- On iOS, `AppleLanguages` is persisted and also affects system-provided UI, but typically only after
  the next launch; Compose text switches immediately, so the two can disagree until restart.
- Non-composable `getString` reads the process locale, so text resolved in ViewModels may lag.

On Android prefer the AppCompat per-app API above; on iOS prefer Settings. Read the current docs page
for the exact code rather than copying an old snapshot.
