# Parity dimensions

What can diverge between Android and iOS, where each side keeps it, and the minimum severity when it
does. Use the rows that match the change; a whole-feature audit walks all of them.

**Columns.** *Lens* — stable name, becomes the key `parity/<lensName>`. *Diverges when* — the
defect. *Android side* / *iOS side* — where to read. *Floor* — minimum severity. *Mech?* — `yes`: a
script can compare the two sides; `partial`: a grep lists candidates; `no`: needs reading both.

A difference the operating system forces is not a defect when it is **documented** (see the skill's
"Intentional divergence" section). An undocumented difference is a finding even when it is
defensible.

## Contents

1. [Shared code boundaries](#1-shared-code-boundaries)
2. [Rules the user can observe](#2-rules-the-user-can-observe)
3. [Screens and copy](#3-screens-and-copy)
4. [Permissions and system dialogs](#4-permissions-and-system-dialogs)
5. [Lifecycle, background and offline](#5-lifecycle-background-and-offline)
6. [Formatting: dates, numbers, time zones](#6-formatting-dates-numbers-time-zones)
7. [Navigation, deep links and input](#7-navigation-deep-links-and-input)
8. [Analytics, flags and accessibility](#8-analytics-flags-and-accessibility)
9. [Security controls](#9-security-controls)

## 1. Shared code boundaries

| Lens | Diverges when | Android side | iOS side | Floor | Mech? |
|---|---|---|---|---|---|
| Semantic actual divergence | Two `actual`s of one `expect` agree on the signature but not the behaviour: a different timeout, error type or message, ordering, null-vs-empty result, cancellation behaviour, or the dispatcher/thread the result arrives on. **Critical** on auth, payment and data-integrity paths | `androidMain` / `jvmMain` actual | `iosMain` / `appleMain` / `nativeMain` actual | High | no |
| Unit mismatch at the boundary | A duration or timestamp crossing into platform APIs in different units — Kotlin milliseconds vs `TimeInterval` seconds, epoch seconds vs milliseconds | the actual's platform call | the actual's platform call, Swift call sites | High | partial |
| Platform constant hardcoded | A timeout, retry count, threshold or permission string written separately in each `actual` instead of named once in `commonMain` and passed in | `androidMain` | `iosMain`, Swift | High | partial |
| Platform library semantics | The actuals wrap platform libraries whose defaults differ (HTTP engine timeouts and redirects, regex flavour, `HashMap` iteration order, locale-sensitive string functions) and code relies on the default | engine/library config | engine/library config | Medium | no |

## 2. Rules the user can observe

| Lens | Diverges when | Android side | iOS side | Floor | Mech? |
|---|---|---|---|---|---|
| Duplicated user-observable rule | A gate, threshold, validation or eligibility check written once in Kotlin and again in Swift (or in two Compose and SwiftUI screens). **High** if the two copies already differ; Medium while they still match — it is debt with a delay fuse | Compose screen, Android ViewModel | SwiftUI view, Swift view model | Medium | no |
| Validation rules | Input rules differ: regex, length limits, trimming, case folding, allowed characters, Unicode handling, or *when* validation runs (on change, on blur, on submit) | field state, validators | field bindings, validators | High | partial |
| Single-platform fix | A behavioural bug fixed on one platform while the other keeps the bug, with no follow-up issue named in the change | the fixed or unfixed side | the fixed or unfixed side | High | no |

## 3. Screens and copy

| Lens | Diverges when | Android side | iOS side | Floor | Mech? |
|---|---|---|---|---|---|
| Error, empty and loading states | Errors map to different messages, one side offers retry and the other does not, an empty state exists on one side only, or one side blocks the UI while the other shows content | `UiState` mapping, screen | view model state, view | High | no |
| Copy and string keys | A string key present on one side only, different text for the same key, plurals handled on one side (`plurals` vs `.stringsdict` / string catalog), placeholders that differ (`%1$s` vs `%@`) | `res/values*/strings.xml`, `composeResources/values*/strings.xml` | `Localizable.strings`, `.xcstrings`, `.stringsdict` | Medium | yes — compare key sets |
| Localization coverage | A language shipped on one platform and missing or partial on the other | `values-<lang>/` folders | `.lproj` folders, string catalog languages | Medium | yes |

## 4. Permissions and system dialogs

| Lens | Diverges when | Android side | iOS side | Floor | Mech? |
|---|---|---|---|---|---|
| Permission flow | Request order, priming copy, or the denied and permanently-denied branches differ beyond what each OS forces. Android can re-ask after a denial (`shouldShowRequestPermissionRationale`); iOS asks once, then only Settings can change it — the user-visible outcome (explanation, a path to Settings, a degraded mode) must match | permission launcher, rationale UI | `requestAuthorization` calls, `Info.plist` usage strings | High | no |
| Background location | Android requires a separate, later request for background location (API 30+); iOS offers "Allow Once" and upgrades from when-in-use to always in a separate prompt. Both need the feature to work, explain, or degrade the same way | location permission flow | `CLLocationManager` authorization flow | High | no |
| Precise vs approximate | Android 12+ lets the user grant coarse only; iOS 14+ lets the user turn off precise location. One side handles reduced accuracy, the other assumes precise | accuracy checks | `accuracyAuthorization` handling | High | no |
| Notification permission | Android 13+ needs the runtime `POST_NOTIFICATIONS` permission; iOS needs authorization (optionally provisional). One side asks at launch, the other in context; one side handles refusal, the other assumes delivery | notification permission request | `UNUserNotificationCenter.requestAuthorization` | Medium | no |

## 5. Lifecycle, background and offline

| Lens | Diverges when | Android side | iOS side | Floor | Mech? |
|---|---|---|---|---|---|
| State restoration | Android restores after process death (`SavedStateHandle`, `rememberSaveable`) while iOS restarts from scratch after termination, or the reverse — a half-filled form survives on one platform only | saved state | scene storage, state restoration | Medium | no |
| Background work | Work that runs reliably on one side and opportunistically on the other — `WorkManager` constraints vs `BGTaskScheduler` timing that iOS does not guarantee — with a UI that promises the same | `WorkManager`, foreground services | `BGTaskScheduler`, background modes | High | no |
| Timers and suspension | A countdown, poll or timeout that keeps running in the background on Android and is suspended on iOS (or killed on Android) — the value is wrong when the app returns | timers, `delay` loops | timers, `Task.sleep` | High | no |
| Offline behaviour | One side queues the action offline and the other fails it; different cache-first vs network-first choices; connectivity detected with different semantics (validated internet vs a satisfied path) | connectivity monitor, queue | `NWPathMonitor`, queue | High | no |
| Foreground resume | Work triggered on returning to the foreground (refresh, re-auth, lock screen) runs on one platform only, or at a different point in the lifecycle | `ON_START` / `ON_RESUME` | `scenePhase`, `willEnterForeground` | Medium | no |

## 6. Formatting: dates, numbers, time zones

| Lens | Diverges when | Android side | iOS side | Floor | Mech? |
|---|---|---|---|---|---|
| Time zone source | One side formats or computes in the device zone, the other in UTC or a fixed zone; one parses ISO timestamps without an offset as local, the other as UTC | `TimeZone.currentSystemDefault()`, `ZoneId` | `TimeZone.current`, `ISO8601DateFormatter` | High | partial |
| Date and time formatting | Hand-built patterns on one side, locale templates on the other; the device 12/24-hour setting honoured on one side only; first day of week, relative dates ("yesterday") computed differently | `DateTimeFormatter`, `DateFormat.is24HourFormat` | `DateFormatter.dateFormat(fromTemplate:…)`, `.formatted()` | Medium | partial |
| Number and currency formatting | Decimal and grouping separators, currency symbol position, rounding mode or fraction digits differ — usually because one side formats in shared code and the other with a platform formatter | `NumberFormat` | `NumberFormatter`, `.formatted(.currency…)` | High on money, else Medium | partial |
| DST and day boundaries | "Today", "this week" or a duration computed by adding 24 hours on one side and by calendar arithmetic on the other — wrong across DST changes | date arithmetic | `Calendar` arithmetic | High | no |

## 7. Navigation, deep links and input

| Lens | Diverges when | Android side | iOS side | Floor | Mech? |
|---|---|---|---|---|---|
| Deep link coverage | A path handled on one platform only, the same link landing on different screens, parameters validated differently, or different behaviour when the user is signed out (dropped vs resumed after login) or the app is cold-started | intent filters, `assetlinks.json`, router | associated domains, `apple-app-site-association`, `onOpenURL` | High | partial |
| Back and dismiss | System back / predictive back on Android and swipe-back on iOS lead to different places, a dialog dismisses on outside tap on one side only, or unsaved-changes confirmation exists on one side | `BackHandler`, nav graph | navigation stack, `interactiveDismissDisabled` | Medium | no |
| Keyboard and input | IME actions (Next, Done), keyboard type, autofill hints vs `textContentType`, secure entry, or keyboard avoidance differ for the same field | `KeyboardOptions`, autofill semantics | `keyboardType`, `textContentType`, `SecureField` | Medium | partial |

## 8. Analytics, flags and accessibility

| Lens | Diverges when | Android side | iOS side | Floor | Mech? |
|---|---|---|---|---|---|
| Analytics divergence | An event fired on one platform only, the same event with different property keys or value types, a different firing point (on tap vs on success), automatic screen tracking on one side and manual on the other, or the user id not reset on logout on one side | analytics wrapper calls | analytics wrapper calls | High | yes — compare event names |
| Feature flag evaluation | The same flag read under a different key, a different default when the fetch fails, or evaluated at a different time (cached at launch vs fresh) | remote config / flag client | remote config / flag client | High | partial |
| Accessibility coverage | A control with a test identifier or spoken label on one platform and none on the other — the shared QA suite breaks for that element. Identifier *strings* may follow different conventions; *coverage* must match | `testTag`, `contentDescription`, semantics | `.accessibilityIdentifier`, `.accessibilityLabel` | Medium | partial |
| Text scaling and touch targets | One side scales text with the user's font setting and the other uses fixed sizes; touch targets below the platform minimum (48 dp, 44 pt) on one side | `sp` units, `minimumInteractiveComponentSize` | Dynamic Type, frame sizes | Medium | partial |

## 9. Security controls

Report these here *and* run `mobile-security-review` when they appear.

| Lens | Diverges when | Android side | iOS side | Floor | Mech? |
|---|---|---|---|---|---|
| Security control on one side | Pinning, screenshot protection (`FLAG_SECURE` vs an app-switcher cover), clipboard expiry, backup exclusion or biometric gating present on one platform only | network config, window flags, backup rules | `Info.plist`, scene phase handling, Keychain | High | partial |
| Logout wipe divergence | One platform clears a store the other leaves behind — a database, Keychain item, cookie store, cache or scheduled notification | logout path, platform cleanup | logout path, platform cleanup | Critical | no |
