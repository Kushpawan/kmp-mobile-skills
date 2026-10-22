# Library swap guide: Android-only → Kotlin Multiplatform

Status checked October 2026 against each project's documentation. Re-check the linked docs before
committing to a version — KMP support moves quickly.

Contents:

1. How to audit dependencies
2. Swap table
3. Notes per swap
4. When there is no KMP replacement

## 1. How to audit dependencies

```bash
./gradlew :app:dependencies --configuration releaseRuntimeClasspath \
  | grep -oE '[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[0-9][^ ]*' | cut -d: -f1,2 | sort -u
```

Search a library on [klibs.io](https://klibs.io) to see which KMP targets it publishes. A library
is usable from `commonMain` only if it publishes every target the module declares (for example
`android`, `iosArm64`, `iosSimulatorArm64`, and `iosX64` if declared).

## 2. Swap table

| Android library | KMP replacement | Migration effort | Keep on Android meanwhile? |
|---|---|---|---|
| Retrofit + OkHttp | Ktor client (OkHttp engine on Android, Darwin engine on iOS) | Medium | Yes — behind a repository interface |
| Gson / Moshi | kotlinx.serialization | Low–medium | Only during the swap of one model set |
| Room (Android) | Room KMP (same library, KMP artifacts) | Medium | No — upgrade in place |
| Hilt / Dagger | Koin (or kotlin-inject / Metro); or keep Hilt in the Android app module only | Medium–high | Yes — Hilt can provide shared classes |
| `java.time`, ThreeTenABP | kotlinx-datetime + `kotlin.time` | Low | No |
| RxJava 2/3 | kotlinx.coroutines + Flow | High | Yes — bridge with `kotlinx-coroutines-rx3` |
| LiveData | `StateFlow` / `Flow` | Low–medium | Bridge with `asLiveData()` on Android |
| androidx ViewModel | androidx lifecycle-viewmodel (KMP artifacts) | Low | No — same API |
| Glide / Picasso | Coil 3 (`coil-compose` + `coil-network-ktor3`) | Low (in Compose) | Yes, for View-based screens |
| SharedPreferences | DataStore Preferences (KMP) or multiplatform-settings | Low–medium | Migrate data once with `SharedPreferencesMigration` |
| EncryptedSharedPreferences | Keystore-backed storage on Android + Keychain on iOS, behind an interface | Medium | Yes |
| Timber / `Log` | Kermit or Napier | Low | No |
| Fragment navigation / Navigation (XML) | Navigation Compose (KMP) or Navigation 3 | High (tied to UI) | Yes, until the UI moves |
| Paging 3 | Paging (KMP artifacts) | Low–medium | No |
| Android resources (`R.string`) | Compose Multiplatform resources (`Res.string`) or per-platform strings | Medium | Yes |
| WorkManager | none — keep in `androidMain`; iOS uses `BGTaskScheduler` | n/a | Yes |
| Firebase Android SDKs | keep native SDKs behind an interface (community KMP wrappers exist) | Low per interface | Yes |
| `Parcelable` / `@Parcelize` | `@Serializable` for navigation arguments and state | Low | Keep only in Android UI code |

## 3. Notes per swap

**Retrofit → Ktor.** Add `ktor-client-core`, `ktor-client-content-negotiation`,
`ktor-serialization-kotlinx-json` in `commonMain`, `ktor-client-okhttp` in `androidMain` and
`ktor-client-darwin` in `iosMain`. OkHttp interceptors can be reused on Android through the
OkHttp engine's configuration, but anything that must also run on iOS belongs in a Ktor plugin.
If the team wants Retrofit-style annotated interfaces, Ktorfit generates them on top of Ktor.
Wrap results in the project's result type (`Result`, a sealed `NetworkResult`, …).

**Gson/Moshi → kotlinx.serialization.** Reflection-free and compile-time checked. Map
`@SerializedName`/`@Json(name=)` to `@SerialName`. Configure `Json { ignoreUnknownKeys = true }`
if the old adapter tolerated unknown fields — Gson does by default and kotlinx.serialization does
not. Default values: a property with a default is optional in JSON; Gson silently produced `null`
for missing non-null fields, which kotlinx.serialization rejects. Run the model tests against real
captured payloads.

**Room → Room KMP.** Room has KMP artifacts (2.7 and later; a Room 3 line under new
`androidx.room3` coordinates is in development — check the docs for which to target). Steps: move
entities, DAOs and the database class to `commonMain`; make every DAO function `suspend` or return
`Flow` (blocking DAO functions are allowed only in `androidMain`); add
`@ConstructedBy(AppDatabaseConstructor::class)` plus an `expect object AppDatabaseConstructor :
RoomDatabaseConstructor<AppDatabase>`; apply KSP for **every** target (`kspAndroid`,
`kspIosArm64`, `kspIosSimulatorArm64`, `kspIosX64` if declared); build the database per platform
with a driver. `BundledSQLiteDriver` ships its own SQLite and is the documented default.
`NativeSQLiteDriver` uses the system SQLite and needs `-lsqlite3` in the framework's linker
options. Pick one per framework: one team found that adding `-lsqlite3` alongside the bundled
driver let the release link resolve SQLite symbols to the system library instead of the bundled
one, which failed at runtime on a newer iOS. Keep existing Android migrations; schema export
continues to work.

**Hilt → Koin, or keep Hilt.** Hilt and Dagger run on the JVM/Android only and cannot appear in
`commonMain`. Two valid paths:

- *Keep Hilt in the Android app.* Shared classes take plain constructor parameters (no `@Inject`).
  An Android Hilt module `@Provides` them. iOS builds the same graph with Koin or a small manual
  factory. Lowest risk for a large Hilt codebase.
- *Move to Koin* (or a compile-time KMP DI such as kotlin-inject or Metro) for the shared graph,
  and bridge into Android components with the DI library's Android integration.

**java.time → kotlinx-datetime.** `LocalDate`, `LocalDateTime`, `TimeZone`, `DateTimePeriod` map
directly. Since kotlinx-datetime 0.7, `Instant` and `Clock` are the standard library's
`kotlin.time.Instant` / `kotlin.time.Clock`. Formatting: use the library's format builders, or
format in platform code if the UI needs locale-aware output.

**RxJava → coroutines.** Migrate leaves first (repositories return `Flow`/`suspend`), bridge at the
seam with `kotlinx-coroutines-rx3` (`asFlow()`, `asObservable()`, `rxSingle { }`), and delete the
bridge when the last subscriber moves. Schedulers become injected dispatchers. On Kotlin/Native,
`Dispatchers.IO` is available via `import kotlinx.coroutines.IO`.

**ViewModel.** `androidx.lifecycle:lifecycle-viewmodel` publishes KMP artifacts, so a ViewModel
with `viewModelScope` can live in `commonMain`. `viewModelScope` uses `Dispatchers.Main`; tests
need `Dispatchers.setMain`. Compose Multiplatform screens use the JetBrains
`lifecycle-viewmodel-compose` artifact. SwiftUI hosts need a small owner/wrapper on the Swift side
(see `kmp-swiftui-interop`).

**Glide → Coil 3.** Coil 3 is multiplatform for Compose. Network loading is a separate artifact
(`coil-network-ktor3` or `coil-network-okhttp`), and the Ktor variant needs a Ktor engine per
platform. View-based Android screens can keep Glide until they move to Compose.

**SharedPreferences → DataStore.** DataStore Preferences publishes KMP artifacts; create it with
`PreferenceDataStoreFactory.createWithPath(produceFile = { path })` and supply the path per
platform (`Context.filesDir` on Android, the app's documents or application-support directory on
iOS). Migrate existing values once on Android with `SharedPreferencesMigration` (Android-only
API, so it lives in `androidMain`). For simple synchronous key-value needs, multiplatform-settings
wraps `SharedPreferences` and `NSUserDefaults`.

**EncryptedSharedPreferences.** Deprecated by AndroidX. Do not port it; put secrets behind a
`SecureStore` interface with an Android Keystore implementation and an iOS Keychain implementation
(see `kmp-secure-storage`).

**Timber → Kermit / Napier.** Both are KMP loggers with Android Logcat and Apple `os_log`/`NSLog`
sinks. If the project already wraps logging in its own facade, keep the facade and swap the
backend.

## 4. When there is no KMP replacement

Define an interface in `commonMain`, implement it in `androidMain` with the Android library, and
implement it on iOS — either in `iosMain` with Apple frameworks through Kotlin/Native interop, or in
Swift and injected into the Kotlin DI graph at app start. This is the normal pattern for payments,
analytics SDKs, maps, push and background work. Do not block the migration on finding a KMP
library.
