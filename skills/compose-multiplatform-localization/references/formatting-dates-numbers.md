# Locale-aware dates, numbers and currency in shared code

Contents

1. [What kotlinx-datetime does and does not do](#1-what-kotlinx-datetime-does-and-does-not-do)
2. [Common interface](#2-common-interface)
3. [Android implementation](#3-android-implementation)
4. [iOS implementation](#4-ios-implementation)
5. [Using it from Compose](#5-using-it-from-compose)
6. [Pitfalls](#6-pitfalls)

## 1. What kotlinx-datetime does and does not do

| Need | kotlinx-datetime | Use instead |
|---|---|---|
| Dates, times, time zones, arithmetic | Yes | — |
| Fixed machine formats (ISO, `yyyy-MM-dd`-like via `LocalDate.Format { }`) | Yes | — |
| Localised month/day names, locale-dependent order (`12/1/20` vs `01/12/2020`) | No — internationalisation is out of scope per its README | Platform formatters |
| Number grouping/decimal separators, currency | No | Platform formatters |

Its format DSL can print month/day names from a list you supply (English lists are built in); that
is not localisation. Since 0.7.0, `Instant` and `Clock` come from `kotlin.time`.

On Android below API 26, `java.time` (used by kotlinx-datetime on the JVM and by the formatter below)
needs core-library desugaring: `compileOptions { isCoreLibraryDesugaringEnabled = true }` plus the
`com.android.tools:desugar_jdk_libs` dependency via the version catalog.

## 2. Common interface

```kotlin
// commonMain
enum class DateStyle { Short, Medium, Long }

/** Display formatting in the user's locale. Keep money as minor units in the domain; convert at the edge. */
interface LocaleFormatter {
    fun date(date: LocalDate, style: DateStyle = DateStyle.Medium): String
    fun decimal(value: Double, maxFractionDigits: Int = 2): String
    fun currency(amount: Double, currencyCode: String): String
}
```

Bind one implementation per platform in DI, or expose `expect fun createLocaleFormatter(): LocaleFormatter`
if the project prefers `expect`/`actual` factories.

## 3. Android implementation

```kotlin
// androidMain
class AndroidLocaleFormatter(private val locale: Locale = Locale.getDefault()) : LocaleFormatter {

    // DateTimeFormatter is immutable and thread-safe: cache it.
    private val dateFormatters = DateStyle.entries.associateWith { style ->
        DateTimeFormatter.ofLocalizedDate(style.toFormatStyle()).withLocale(locale)
    }

    override fun date(date: LocalDate, style: DateStyle): String =
        dateFormatters.getValue(style).format(date.toJavaLocalDate())

    // java.text.NumberFormat is NOT thread-safe: create per call (cheap enough for UI use).
    override fun decimal(value: Double, maxFractionDigits: Int): String =
        NumberFormat.getNumberInstance(locale).apply { maximumFractionDigits = maxFractionDigits }.format(value)

    override fun currency(amount: Double, currencyCode: String): String =
        NumberFormat.getCurrencyInstance(locale).apply { currency = Currency.getInstance(currencyCode) }.format(amount)

    private fun DateStyle.toFormatStyle(): FormatStyle = when (this) {
        DateStyle.Short -> FormatStyle.SHORT
        DateStyle.Medium -> FormatStyle.MEDIUM
        DateStyle.Long -> FormatStyle.LONG
    }
}
```

Imports: `java.time.format.DateTimeFormatter`, `java.time.format.FormatStyle`, `java.text.NumberFormat`,
`java.util.Currency`, `java.util.Locale`, `kotlinx.datetime.LocalDate`, `kotlinx.datetime.toJavaLocalDate`.

## 4. iOS implementation

```kotlin
// iosMain
class IosLocaleFormatter(private val locale: NSLocale = NSLocale.currentLocale) : LocaleFormatter {

    // LocalDate is ISO (Gregorian). Build the NSDate with a Gregorian calendar, or users whose
    // system calendar is Buddhist/Japanese/... get a date in the wrong year.
    private val gregorian = NSCalendar(calendarIdentifier = NSCalendarIdentifierGregorian)

    // NSDateFormatter is expensive to create: cache per style.
    private val dateFormatters = DateStyle.entries.associateWith { style ->
        NSDateFormatter().apply {
            locale = this@IosLocaleFormatter.locale
            dateStyle = style.toNsStyle()
            timeStyle = NSDateFormatterNoStyle
        }
    }

    override fun date(date: LocalDate, style: DateStyle): String {
        val components = NSDateComponents().apply {
            year = date.year.toLong()
            month = date.month.number.toLong()
            day = date.day.toLong()          // `dayOfMonth` before kotlinx-datetime 0.7
        }
        val nsDate = gregorian.dateFromComponents(components) ?: return date.toString()
        return dateFormatters.getValue(style).stringFromDate(nsDate)
    }

    override fun decimal(value: Double, maxFractionDigits: Int): String =
        NSNumberFormatter().apply {
            locale = this@IosLocaleFormatter.locale
            numberStyle = NSNumberFormatterDecimalStyle
            maximumFractionDigits = maxFractionDigits.toULong()
        }.stringFromNumber(NSNumber(double = value)) ?: value.toString()

    override fun currency(amount: Double, currencyCode: String): String =
        NSNumberFormatter().apply {
            locale = this@IosLocaleFormatter.locale
            numberStyle = NSNumberFormatterCurrencyStyle
            this.currencyCode = currencyCode
        }.stringFromNumber(NSNumber(double = amount)) ?: amount.toString()

    private fun DateStyle.toNsStyle() = when (this) {
        DateStyle.Short -> NSDateFormatterShortStyle
        DateStyle.Medium -> NSDateFormatterMediumStyle
        DateStyle.Long -> NSDateFormatterLongStyle
    }
}
```

Imports: `platform.Foundation.*` (`NSCalendar`, `NSCalendarIdentifierGregorian`, `NSDateComponents`,
`NSDateFormatter`, `NSDateFormatter*Style`, `NSLocale`, `currentLocale`, `NSNumber`,
`NSNumberFormatter`, `NSNumberFormatterDecimalStyle`, `NSNumberFormatterCurrencyStyle`),
`kotlinx.datetime.LocalDate`, `kotlinx.datetime.number`. Let the IDE confirm the exact Kotlin/Native
signatures for your Kotlin version.

Which locale: Compose resources pick their language from `NSLocale.preferredLanguages`, while
`NSLocale.currentLocale` carries the user's region settings (date order, separators). When the app
declares its languages (`CFBundleLocalizations`), the two normally agree; if text is French and
months are English, check that declaration first.

## 5. Using it from Compose

```kotlin
// commonMain; bind per platform: single<LocaleFormatterFactory> { LocaleFormatterFactory { AndroidLocaleFormatter() } }
fun interface LocaleFormatterFactory {
    fun create(): LocaleFormatter
}

@Composable
fun rememberLocaleFormatter(): LocaleFormatter {
    val languageTag = Locale.current.toLanguageTag()      // androidx.compose.ui.text.intl.Locale
    val factory = koinInject<LocaleFormatterFactory>()    // or the project's DI / expect fun
    return remember(languageTag) { factory.create() }     // rebuild when the locale changes
}
```

Pre-format values and pass them as `%1$s` arguments:

```kotlin
val formatter = rememberLocaleFormatter()
Text(stringResource(Res.string.notes_synced_at, formatter.date(state.lastSyncedDate)))
```

Relative times ("5 minutes ago") need their own platform API: `DateUtils.getRelativeTimeSpanString`
on Android, `NSRelativeDateTimeFormatter` on iOS.

## 6. Pitfalls

- **Exact-string tests on formatted output are fragile.** CLDR data differs between JDK, Android and
  iOS versions — for example, newer CLDR uses a narrow no-break space (U+202F) before AM/PM and
  U+00A0 as a grouping separator in some locales. Assert on components, or normalise
  ` `/` ` to spaces before comparing.
- **`LocalDate.toString()` in the UI** prints ISO `2026-10-22`, not a localised date.
- **Formatting money as `Double` arithmetic.** Compute in minor units (`Long`) or a decimal type;
  convert to `Double` only for display.
- **Caching a formatter forever.** A formatter built with the old locale keeps formatting in it after
  a language change; key the cache on the language tag.
- **Time zones.** A `LocalDate` has none; an `Instant` needs one (`TimeZone.currentSystemDefault()`)
  before it becomes a calendar date. Do the conversion once, in one place.
