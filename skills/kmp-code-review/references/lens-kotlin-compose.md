# Lens — Kotlin, coroutines, KMP and Compose

Tier 2 rows: each one names a defect class that has shipped in real Kotlin Multiplatform apps. A hit
is a proposal the author can reject with a reason; a project rule that says otherwise wins.

**Columns.** *Lens* — stable name, becomes the key `kotlin/<lensName>`. *What a hit looks like* —
the violation in code; *Applies when* states a condition the row depends on. *Floor* — minimum
severity. *Mech?* — `yes`: a compiler, lint or detekt rule can catch it (skip the row only if that
check runs in the project's CI); `partial`: a grep finds candidates, judgement confirms; `no`: needs
reading.

## Contents

1. [Coroutines and Flow](#1-coroutines-and-flow)
2. [Kotlin language](#2-kotlin-language)
3. [KMP structure and the Swift-facing API](#3-kmp-structure-and-the-swift-facing-api)
4. [Networking and serialization](#4-networking-and-serialization)
5. [Persistence](#5-persistence)
6. [Compose](#6-compose)
7. [UI state and accessibility](#7-ui-state-and-accessibility)
8. [Cross-cutting state and side effects](#8-cross-cutting-state-and-side-effects)
9. [Design tokens](#9-design-tokens)

## 1. Coroutines and Flow

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Swallowed cancellation | `catch (e: Exception)`, `catch (e: Throwable)` or `runCatching { }` around a suspend call that also swallows `CancellationException`. The coroutine keeps running after its scope is cancelled. Rethrow `CancellationException` or catch narrower types | High | partial — detekt `TooGenericExceptionCaught` finds candidates |
| `GlobalScope` | `GlobalScope.launch` / `async` — work that outlives its owner and cannot be cancelled or tested. *Applies unless* the project documents an app-lifetime scope it prefers | High | yes — detekt `GlobalCoroutineUsage` |
| Scope outliving consumer | Work launched in a scope wider than the thing that consumes it: a repository-owned scope writing UI state, a `viewModelScope` job handed to a singleton | High | no |
| `runBlocking` on a UI path | `runBlocking` reachable from a Composable, a ViewModel `init`, a main-thread callback or Swift on the main thread — an ANR on Android, a frozen UI on iOS | Critical | yes |
| Blocking I/O off-dispatcher | File, database, crypto or bitmap work in a `suspend` function with no `withContext(Dispatchers.IO)` (or the project's injected dispatcher) | High | no |
| Hardcoded dispatcher | `Dispatchers.IO` / `Default` hardcoded in a class the project's rules say must take an injected dispatcher — tests cannot control timing. *Applies when* the project injects dispatchers | Medium | yes — detekt `InjectDispatcher` |
| `withContext` inside `flow { }` | `withContext(...) { emit(x) }` inside a `flow { }` builder violates context preservation and throws `IllegalStateException` at runtime. Use `flowOn` | High | partial |
| Lost `SharedFlow` emission | A `SharedFlow` with `replay = 0` whose only collector subscribes after the emitter fires — one-shot events (navigate, toast) silently dropped | High | no |
| `StateFlow` equality trap | A `StateFlow` holding a type without value equality (a mutable class, an array, a lambda), or a mutated-in-place collection re-set into it — equal by identity suppresses the update | High | no |
| Public mutable state | `MutableStateFlow`, `MutableSharedFlow` or a mutable collection exposed as public API instead of `asStateFlow()` / `asSharedFlow()` / a read-only type | High | yes |
| Callback bridge | `suspendCancellableCoroutine` or `callbackFlow` over a platform callback that can resume twice, resumes on a non-terminal callback, may never resume, or has no `invokeOnCancellation` / `awaitClose` teardown — the delegate leaks or the caller hangs | High | no |
| Shared mutable state race | A `var`, collection or cache mutated from more than one coroutine with no `Mutex`, single-threaded confinement or atomic | Critical | no |
| Timeout around committed work | `withTimeout` / cancellation wrapped around work that keeps running or has already committed (a POST in flight, a DB write) — the caller reports failure for something that happened | High | no |

## 2. Kotlin language

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Empty catch | `catch (…) { }` with no logging, rethrow or state change — a silent failure | High | yes — detekt `SwallowedException`, `EmptyCatchBlock` |
| Force unwrap | `!!` on a value that is not provably non-null at that point (network data, platform callbacks, map lookups) | High | yes — detekt `UnsafeCallOnNullableType` |
| `lateinit` on a nullable path | A `lateinit var` read on a branch that can run before it is initialised | High | no |
| Unclosed resource | A `Closeable`, stream, cursor or file handle acquired without `use { }` | High | partial |
| Money in floating point | A currency amount, rate or balance held as `Float` / `Double`. Use integer minor units or a decimal type | Critical | partial |
| Local time where UTC is required | A timestamp persisted or sent in device-local time, or a local date derived without an explicit zone — records become ambiguous across time zones and DST | Critical | no |
| Unbounded growth | A list, cache, map or log buffer that grows with no eviction, cap or paging | High | no |
| Pagination boundary | Off-by-one in offset/limit, a last-page condition that can loop forever, or the first page treated as the whole list | High | no |
| Over-wide visibility | A new declaration left `public` when `internal` or `private` states the intent. In an iOS-exported module every `public` declaration also becomes Swift API | Medium | partial |
| Nullable where sealed is clearer | A function returning `T?` to signal several distinct outcomes (not found, forbidden, offline) that a sealed result would name | Medium | no |
| Magic number | An unexplained literal on a behavioural path — a timeout, retry count, threshold, page size — with no named constant | Medium | partial |

## 3. KMP structure and the Swift-facing API

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Platform import in common code | `android.*`, `java.*`, `platform.*` or `UIKit` imported in `commonMain`. Many `androidx.*` libraries are multiplatform (lifecycle, Room, DataStore, navigation, collection) — those are fine | High | yes — `compileCommonMainKotlinMetadata` fails |
| Business logic in a platform source set | A decision, validation or mapping implemented in `androidMain` / `iosMain` beyond what the `actual` must do — it now has to be kept in sync by hand | High | no |
| Missing or partial `actual` | An `expect` changed without every `actual` following. *Note:* CI that builds only Android on Linux never compiles the iOS `actual` | High | yes — compile every target |
| DI binding not updated | A constructor gained or changed a parameter but its Koin `module { }` / manual factory did not. *Applies when* DI resolves at runtime (Koin, Kodein, service locators) — the app crashes on first resolution. Koin's `verify()` / `checkModules()` test catches it | Critical | partial — a module verification test |
| Activity context held too long | An `Activity` or `View` context stored in a singleton, a Koin `single`, a companion object or a ViewModel — leaks the whole screen. Use `applicationContext` | High | partial — Android Lint `StaticFieldLeak` |
| Kotlin exception crosses into Swift | A Kotlin function called from Swift can throw but has no `@Throws(...)`. An exception reaching Swift without it terminates the app; `suspend` functions without `@Throws` propagate only `CancellationException` | Critical | no |
| Swift-breaking API change | A public declaration in an iOS-exported module renamed, removed or re-typed, a parameter reordered, or a default argument relied on — Swift sees no default arguments through the Objective-C export unless the project uses a bridging tool that adds them. Grep the Swift sources | High | partial — build the iOS app |
| Sealed hierarchy grows | A new subclass of a sealed class or a new enum entry consumed in Swift `switch` statements that use `default:` — the new case silently takes the default branch | Medium | partial |
| Hardcoded container path | A file path built from a literal instead of the platform API (`Context.filesDir`, `NSFileManager` URLs). The iOS app container path changes between installs | Medium | partial |

## 4. Networking and serialization

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Client per call | `HttpClient(...)` created per request or per repository and never closed — connection pools and threads leak, and shared configuration (auth, logging, timeouts) is lost. Reuse one client | High | partial |
| Plugin installed outside the shared client | A feature installs its own Ktor plugins or builds its own client. *Applies when* the project provides one configured client | Medium | partial |
| Engine missing for a target | `HttpClient()` without an explicit engine on a target whose source set has no engine dependency — fails at runtime on that target only | High | partial |
| Non-2xx treated as success | Ktor's `expectSuccess` is off by default: a 4xx/5xx body is decoded as the success type or the status never checked. Check `status`, or enable `expectSuccess` and map `ResponseException` | High | no |
| Missing field crashes decode | A new non-nullable DTO property with no default — any response that omits it throws `MissingFieldException` | High | partial |
| Unknown keys crash decode | `Json { }` without `ignoreUnknownKeys = true` decoding a server that adds fields independently of app releases | High | yes |
| Unknown enum value crashes decode | A serialized enum with no fallback for values the server adds later. Use a nullable/defaulted property with `coerceInputValues = true`, or a custom serializer with an `UNKNOWN` entry | High | partial |
| New field default disables behaviour | A new or moved wire field whose default (`false`, `null`, empty) switches a feature off for cached, older or partial payloads | High | no |
| Refresh race | Several requests receive 401 at once and each starts its own token refresh; with rotating refresh tokens the second refresh invalidates the first and the user is logged out. *Applies to* custom refresh logic — serialise refreshes behind one `Mutex` | High | no |
| No timeout on a blocking request | A request behind a spinner with no request/socket timeout, inheriting an engine default (often 60 s on iOS) | Medium | partial |
| Logger bypassed | `println`, `print`, `Log.*` or `NSLog` instead of the project's logger. *Applies when* the project has a logger — direct calls skip its redaction and release filtering | Medium | yes — grep |

## 5. Persistence

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Destructive migration | `fallbackToDestructiveMigration()` (Room) or a drop-and-recreate path shipped with a schema change — users lose data on upgrade | Critical | yes |
| Missing migration | A Room `@Entity` or SQLDelight `.sq` schema changed without a version bump and a `Migration` / `.sqm` file | Critical | partial — Room schema export, SQLDelight `verifyMigrations` |
| Non-atomic multi-write | Related writes outside one `@Transaction` / `transaction { }` — a crash between them leaves half-written state | High | partial |
| Two DataStores, one file | More than one `DataStore` instance for the same file (created per call or per screen) — DataStore throws when two are active | High | partial |
| Missing index | A column used in `WHERE` / `ORDER BY` on a table that grows without bound, with no index | Medium | no |
| Destroyed before replaced | A partial, paged or empty payload written with replace semantics; a cache cleared or a legacy copy purged before the new write is verified; a reset triggered by a transient failure | High | no |

## 6. Compose

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| `mutableStateOf` without `remember` | State created in composition without `remember` — the value resets on every recomposition | High | yes — Compose lint `UnrememberedMutableState` |
| Side effect in composition | I/O, navigation, analytics or a ViewModel call in the composable body instead of `LaunchedEffect`, `SideEffect`, `DisposableEffect` or an event handler — runs on every recomposition | High | partial — Compose lint `CoroutineCreationDuringComposition` |
| Effect keyed on the wrong input | `LaunchedEffect(Unit)` / `remember { }` capturing a parameter that can change — the effect never re-runs for the new value | High | partial |
| Not lifecycle-aware collection | `collectAsState()` where the project uses `collectAsStateWithLifecycle()` — collection continues while the UI is stopped | High | yes |
| Missing `key` in a lazy list | `items(list)` without a stable `key` — item state, animations and scroll position attach to the wrong rows after insert or delete | High | yes |
| Unsaveable `rememberSaveable` | `rememberSaveable` of a type the platform cannot save (not primitive, `Parcelable` or covered by a `Saver`) — crashes when Android saves instance state | High | partial |
| Insets not handled | A screen root that ignores window insets (`Scaffold` padding dropped, no `safeDrawingPadding()` / `windowInsetsPadding`) — content draws under the system bars (Android 15 enforces edge-to-edge for apps targeting SDK 35+) and under the iOS notch and home indicator | Medium | no |
| `Modifier` contract | A public Composable whose `modifier: Modifier = Modifier` parameter is missing, not the first optional parameter, or not applied to the root | Medium | yes — Compose lint `ModifierParameter` |
| Unstable parameter | A lambda allocated per composition or an unstable collection type passed to a child, defeating skipping on a hot path | Medium | no |
| Missing `derivedStateOf` | A value derived from a high-frequency state read (scroll offset, text input) recomputed on every frame | Medium | no |
| Eager state read | State read at the call site where a lambda modifier (`Modifier.offset { }`) would defer it to layout or draw | Medium | no |
| State hoisting violated | A Composable owns state its caller needs to control or observe | Medium | no |

## 7. UI state and accessibility

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Unknown treated as known | A timeout, missing field, not-yet-loaded value or failed lookup read as a definite answer — empty, success, `false` — or a `Loading` branch that falls through to the success UI | High | no |
| No loading or error state | An async image, list or content slot with no loading, empty or error fallback — it renders blank | Medium | no |
| Missing test identifier | An interactive control (button, input, list-row tap target, dialog action, retry) with no `testTag`. *Applies when* the project's UI tests locate elements by tag | Medium | no |
| `testTag` invisible to external runners | Tags set but `testTagsAsResourceId` not enabled at the root — Appium, UI Automator and Maestro cannot see them. *Applies when* such tools are used | Medium | partial |
| Accessibility label mismatch | A `contentDescription` / semantics label that contradicts what the element does, is set on only one branch of a conditional, or reuses a test identifier as spoken text | Medium | no |

## 8. Cross-cutting state and side effects

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Silent failure | An error path that neither surfaces to the user, logs, nor changes state — the feature appears to work and does nothing | High | no |
| Sibling path missed | A fix or guard added to one of several paths that reach the same outcome (online/offline, cold/warm start, each entry point, each platform) while the others keep the old behaviour. Fix it at the shared chokepoint | High | no |
| Marker before success | A done-flag, stored marker, success event or notification written before — or in a `finally` around — the step that can fail | High | no |
| Stuck flag | A busy, pending or one-shot flag set on entry and cleared only on the success path — an error, cancel or early return leaves the feature locked | High | no |
| Stale completion clobbers newer state | A late callback or code after an `await` writes shared state without checking it still belongs to the current attempt (no generation token; the superseded job not cancelled) | High | no |
| Restore raced by a live event | At cold start a live path (foreground event, location update, push) reads or clears persisted recovery state before the restore that owns it finishes | High | no |
| Result read from shared state | A caller learns its own operation's outcome by watching a shared `StateFlow` or a `replay = 0` event instead of the call's return value — a concurrent call answers for it | High | no |
| Scheduled work not reconciled | A notification, alarm, `WorkManager` job or timer not cancelled or rescheduled on every path that invalidates it — completion, logout, edit, restart after a kill | High | no |
| Not exactly-once | A non-idempotent action that can run twice: no in-flight guard against a double tap, retry or second trigger, or two paths that both emit it with no dedupe key | High | no |
| Gesture blocked on unrelated work | A tap handler that awaits a whole queue drain, a full sync or an uncapped location/network call before updating the UI. Await only the caller's own result, with a bounded timeout | High | no |
| Guard fails open | A validation that cannot reject: missing on one entry path, comparing a value with itself, only logging, or passing when its input is missing | High | no |
| Behaviour dropped in a refactor | A move, rename or comment-out that removes behaviour with no replacement — a handler no longer called, a value plumbed partway and dropped | High | no |
| Cache key missing a dimension | A cache or lookup key without a dimension its value depends on — user, account, locale, date range, a second id | High | no |
| Dev setting committed | A fake repository, fixture, developer toggle (`useFakeRepository = true`, `SKIP_LOGIN`) or machine-specific path committed in its developer position and reachable from release | High | partial |
| No-op callback | A button, navigation or completion callback wired to `{}`, or a statement that compiles but does nothing (a lambda never invoked, a string template missing `$`) | Medium | partial |
| Duplicated logic | The same non-trivial branch or calculation implemented twice in this change | Medium | no |
| Dead code introduced | A function, parameter or branch added with no caller | Medium | yes — detekt `UnusedPrivateMember` and similar |
| Test that cannot fail | An assertion that holds whatever the code does, or a fake that contradicts production semantics | Medium | no |
| Untested new behaviour | A new ViewModel, use case, mapper or repository with no test. Floor is **High** when the project's rules require tests | Medium | partial — coverage report |
| Doc contradicts code | A name, KDoc, comment or README that promises behaviour the code in the same change does not implement | Low | no |

## 9. Design tokens

*Applies when* the project has a design system with colour, typography and spacing tokens.

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Hardcoded style value | `Color(0xFF…)`, a `.dp` / `.sp` literal or a `TextStyle(...)` that duplicates an existing token | Medium | partial — grep |
| Static palette in a themed component | A light-theme-only colour constant in a component that must follow light and dark theme, where a theme-aware token exists | Medium | no |
| Token breaks its siblings' pattern | A new token mapped to a different primitive than its siblings (a `*Medium` style with regular weight), or the wrong token role chosen at the call site | Medium | no |
| Token pair contrast | A foreground/background token pair that loses contrast in one theme | Medium | no |
