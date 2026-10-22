---
name: kmp-koin-di
description: Use when setting up, extending or debugging Koin dependency injection in a Kotlin Multiplatform app — modules in commonMain, platform modules, startKoin in Application, initKoin called from Swift, koinViewModel in Compose Multiplatform, qualifiers, scopes, test overrides — or on NoDefinitionFoundException, InstanceCreationException, KoinApplicationAlreadyStartedException, "KoinApplication has not been started", or a launch crash only on iOS.
license: Apache-2.0
compatibility: Kotlin Multiplatform project (Android + iOS) using or adopting Koin 4.x. iOS steps need macOS with Xcode.
metadata:
  category: data
  platforms: android, ios
---

# Koin in Kotlin Multiplatform

Declare dependencies once in `commonMain`, add a small platform module for what only Android or iOS
can build, start Koin exactly once per process on each platform — in a fixed order — and prove the
graph resolves with a test instead of with a launch crash.

## When to use

- Adding Koin to a KMP project, or adding modules, ViewModels or platform bindings to an existing graph.
- Starting Koin from Swift, or getting a shared dependency into SwiftUI code.
- Errors: `NoDefinitionFoundException: No definition found for type ...`,
  `InstanceCreationException: Could not create instance for ...`,
  `KoinApplicationAlreadyStartedException: A Koin Application has already been started`,
  `IllegalStateException: KoinApplication has not been started`.
- Tests that leak Koin state between cases or fail only when run together.

## When not to use

- The project uses **Hilt** (Android-only), **kotlin-inject**, **Kodein** or manual constructor
  wiring — keep that framework; do not add Koin beside it. The ordering and verification ideas here
  still apply.
- Deciding what the dependencies are (client, repositories) — **kmp-data-layer**.
- `expect`/`actual` design beyond DI bindings — **kmp-expect-actual**.

## Step 0 — Read the project first

```bash
grep -nE "koin|hilt|kotlin-inject|kodein" gradle/libs.versions.toml
grep -rnE "startKoin|initKoin|koinApplication|KoinApplication\(" --include=*.kt --include=*.swift .
grep -rnE "^val [a-zA-Z]+Module = module|includes\(" --include=*.kt . | head -30
grep -rnE "@Module|@Single|@Factory|@KoinViewModel" --include=*.kt . | head    # Koin Annotations?
grep -rnE "named\(|qualifier" --include=*.kt . | head
```

| Finding | Then |
|---|---|
| Koin DSL modules (`module { }`) | Follow their layout and naming; add to the existing aggregator. |
| Koin Annotations (`@Module`, `@Single`) | Write annotated classes, not DSL — mixing styles confuses readers. |
| Existing `initKoin` | Extend it; never add a second `startKoin`. |
| Existing qualifiers | Reuse the exact names. A typo in `named("authenticated")` is a runtime failure. |
| Koin version | Koin 4.x APIs below. ViewModel DSL lives in `org.koin.core.module.dsl`; the old `org.koin.compose.viewmodel.dsl` imports are deprecated. |

## Workflow

### 1. Dependencies

```toml
# gradle/libs.versions.toml — keep the Koin version the catalog pins (or use its BOM)
[libraries]
koin-core = { module = "io.insert-koin:koin-core", version.ref = "koin" }
koin-android = { module = "io.insert-koin:koin-android", version.ref = "koin" }
koin-compose = { module = "io.insert-koin:koin-compose", version.ref = "koin" }
koin-compose-viewmodel = { module = "io.insert-koin:koin-compose-viewmodel", version.ref = "koin" }
koin-test = { module = "io.insert-koin:koin-test", version.ref = "koin" }
```

| Source set | Add |
|---|---|
| `commonMain` | `koin-core`; `koin-compose` + `koin-compose-viewmodel` only in modules with Compose UI |
| `androidMain` | `koin-android` |
| `commonTest` | `koin-test` |

A module that exports a framework consumed by SwiftUI (no Compose) needs only `koin-core`.

### 2. Lay out modules by layer, aggregate once

```kotlin
// commonMain — profile/di/ProfileModule.kt
val profileModule = module {
    single<ProfileApi> { KtorProfileApi(client = get(named("authenticated"))) }
    singleOf(::ProfileRepositoryImpl) bind ProfileRepository::class
    factoryOf(::GetProfileUseCase)
    viewModelOf(::ProfileViewModel)
}

// commonMain — di/AppModules.kt
fun appModules(): List<Module> = listOf(
    coreModule,          // logger bridge, dispatchers, Json
    networkModule,       // HttpClient instances, token refresher
    databaseModule,      // database and DAOs
    platformModule,      // expect/actual, step 3
    profileModule,       // features last
)
```

| Definition | Use for |
|---|---|
| `single` / `singleOf` | Stateful or expensive: `HttpClient`, database, repositories, session holders |
| `factory` / `factoryOf` | Stateless and cheap: use cases, mappers |
| `viewModel` / `viewModelOf` | `androidx.lifecycle.ViewModel` subclasses, resolved with `koinViewModel()` |
| `named("...")` | Two bindings of one type (`named("plain")` and `named("authenticated")` clients) |

- `singleOf(::X)` resolves every constructor parameter by type. When one needs a qualifier or a
  value, write the lambda: `single { X(client = get(named("authenticated")), pageSize = 20) }`.
- `includes(otherModule)` lets a feature aggregator pull in its sub-modules.
- Never call `get()` at module level or inside a callback that runs later — only inside a definition
  lambda, where it resolves when the instance is built.

### 3. Platform modules

```kotlin
// commonMain — di/PlatformModule.kt
expect val platformModule: Module

// androidMain — di/PlatformModule.android.kt
actual val platformModule: Module = module {
    single<SecureStore> { AndroidSecureStore(context = androidContext()) }
    single { databaseBuilder(context = androidContext()) }
}

// iosMain — di/PlatformModule.ios.kt
actual val platformModule: Module = module {
    single<SecureStore> { KeychainSecureStore(service = "com.example.app.session") }
    single { databaseBuilder() }
}
```

Bind an interface from `commonMain` to a platform class here. `androidContext()` is only available
in Android code and only after `androidContext(...)` was passed to Koin. Shared code never sees
`Context` — it sees the interface.

### 4. Start Koin — once, in a fixed order

Koin resolves lazily, so module order rarely matters for plain lookups. The **start-up sequence**
does matter, and reordering it is a classic source of launch crashes:

1. **Initialise anything definitions read outside Koin** — a static platform-context holder used by
   `expect` factories, crash reporting, feature flags.
2. **Initialise the logger** (Kermit, Napier) — definitions that log while being built, and the HTTP
   logging bridge, otherwise log into a logger that does not exist yet, or bypass its redaction.
3. **`startKoin`** with infrastructure modules first and app modules last. Order inside `modules(...)`
   matters in two cases: an **override** (the last definition of a type + qualifier wins) and
   **`createdAtStart`** singletons, which are built at the end of `startKoin`.

```kotlin
// commonMain — di/InitKoin.kt
fun initKoin(config: KoinAppDeclaration? = null): KoinApplication = startKoin {
    config?.invoke(this)
    modules(appModules())
}
```

```kotlin
// androidMain (app module) — ExampleApplication.kt
class ExampleApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        AppLogging.init(isDebug = BuildConfig.DEBUG)          // 1 + 2: everything Koin definitions use
        initKoin {                                            // 3
            androidContext(this@ExampleApplication)
            androidLogger(if (BuildConfig.DEBUG) Level.ERROR else Level.NONE)
        }
    }
}
```

```kotlin
// iosMain — di/KoinIos.kt
@OptIn(ExperimentalNativeApi::class)              // kotlin.native.Platform
fun initKoinIos() {
    AppLogging.init(isDebug = Platform.isDebugBinary)
    initKoin()
}
```

```swift
// iosApp/iOSApp.swift
import Shared

@main
struct iOSApp: App {
    init() {
        KoinIosKt.doInitKoinIos()   // file KoinIos.kt → class KoinIosKt; "init…" gains a "do" prefix
    }
    var body: some Scene { WindowGroup { ContentView() } }
}
```

- The Swift name follows the Kotlin file name. Check the generated header (`Shared.framework/Headers`)
  if it does not compile; tools such as SKIE can change how top-level functions are exposed.
- Start Koin before the first Compose `MainViewController()` or any Swift call into Koin-backed code.
- `AppLogging` and `Platform.isDebugBinary` stand for whatever the project already has.

### 5. ViewModels in Compose Multiplatform

```kotlin
// commonMain — profile/ui/ProfileScreen.kt
@Composable
fun ProfileRoute(profileId: String, viewModel: ProfileViewModel = koinViewModel { parametersOf(profileId) }) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    ProfileScreen(state = state, onRetry = viewModel::retry)
}
```

- Import `org.koin.compose.viewmodel.koinViewModel`.
- `viewModelOf(::ProfileViewModel)` resolves a `String` constructor parameter from `parametersOf`;
  for several parameters of the same type use the lambda form
  `viewModel { (profileId: String) -> ProfileViewModel(profileId, get()) }`.
- Koin 4 resolves a `SavedStateHandle` constructor parameter from the ViewModel's creation extras.
- `koinViewModel()` scopes to the nearest `ViewModelStoreOwner` — inside a navigation destination
  that is the back-stack entry, so the ViewModel lives as long as the screen.

### 6. Dependencies in Swift

Swift cannot call Koin's reified `get<T>()`. Expose a small `KoinComponent` facade from `iosMain`:

```kotlin
// iosMain — di/ProfileDependencies.kt
class ProfileDependencies : KoinComponent {
    fun profileRepository(): ProfileRepository = get()
    fun getProfileUseCase(): GetProfileUseCase = get()
}
```

```swift
let getProfile = ProfileDependencies().getProfileUseCase()
```

Keep the facade narrow — one per feature, returning interfaces. A shared `ViewModel` handed to Swift
needs an owner that clears it when the view goes away, or its `viewModelScope` never cancels; see
**kmp-swiftui-interop**.

### 7. Scopes — for state that must die before the process

A logged-in user's caches must not survive logout. Either reset `single` holders explicitly on logout,
or use a Koin scope and close it:

```kotlin
val sessionModule = module {
    scope(named("session")) {
        scoped { ProfileCache() }
    }
}

// on sign-in
val sessionScope = getKoin().getOrCreateScope(scopeId = "session", qualifier = named("session"))
val cache: ProfileCache = sessionScope.get()

// on sign-out
sessionScope.close()          // every scoped instance is released
```

Anything that outlives the scope must not hold a reference to a scoped instance.

### 8. Verify the graph and test with fakes

Verification and override patterns: [references/testing.md](references/testing.md). In short:

- A **JVM test** (`androidUnitTest`/`androidHostTest` or `jvmTest`) calls `module.verify(extraTypes = ...)`
  for each module — `verify()` lives in `koin-test`'s JVM source set. `checkModules()` is deprecated.
- Tests that start Koin call `stopKoin()` in `@AfterTest`. Prefer constructing the class under test
  with fakes directly; start Koin only to test wiring.

## Quick reference

| Task | API |
|---|---|
| Bind interface | `singleOf(::Impl) bind Repo::class` or `single<Repo> { Impl(get()) }` |
| Qualified dependency | `single(named("authenticated")) { ... }` + `get(named("authenticated"))` |
| Use case | `factoryOf(::GetProfileUseCase)` |
| ViewModel | `viewModelOf(::ProfileViewModel)` + `koinViewModel()` |
| ViewModel parameter | `koinViewModel { parametersOf(id) }` |
| Platform binding | `expect val platformModule: Module` + `actual val` per platform |
| Android start | `initKoin { androidContext(this@App) }` in `Application.onCreate` |
| iOS start | `KoinIosKt.doInitKoinIos()` in the SwiftUI `App.init` |
| Swift access | `KoinComponent` facade in `iosMain` |
| Already started? | `KoinPlatform.getKoinOrNull() != null` |
| Test cleanup | `stopKoin()` in `@AfterTest` |

## Verify

Report each check as `PASS`, `FAIL` or `NOT RUN` (with the reason). A graph that compiles can still
fail at the first `get()`.

```bash
./gradlew :shared:testDebugUnitTest --tests "*KoinModulesTest*"   # verify() test (or testAndroidHostTest / jvmTest)
./gradlew :shared:allTests
./gradlew :composeApp:assembleDebug
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64              # Swift-visible facades compile into the framework
grep -rn "startKoin" --include=*.kt . | grep -v Test               # exactly one production call site
```

Then launch the app on Android and on the iOS simulator and open one screen per feature you wired —
resolution errors surface on first use, not at start.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| `startKoin` in both `Application` and a shared helper, or in every test | `KoinApplicationAlreadyStartedException` | One `initKoin`; `stopKoin()` after each test |
| Logger or platform holder initialised after `startKoin` | Eager or early-built instances crash or log unredacted | Fixed order: platform init → logger → Koin |
| Swift calls shared code before `doInitKoinIos()` | `KoinApplication has not been started`, iOS only | Start in `App.init` / `didFinishLaunching` |
| Qualifier string typo | `NoDefinitionFoundException` on first use only | Constants for qualifier names; `verify()` test |
| `singleOf(::X)` when `X` needs a qualified dependency | Resolves the unqualified binding — or fails | Lambda definition with `get(named(...))` |
| Repository declared with `factory` | A new instance per injection; caches and in-flight refreshes are not shared | `single` |
| Two modules both define the same type, unintentionally | Silent override: the last one loaded wins | Search before adding; `allowOverride(false)` in a test to catch it |
| `get()` captured inside a lambda that runs later | Resolves against whatever graph exists then, or crashes after `stopKoin` | Resolve in the definition, pass the instance |
| `Context` or `UIViewController` injected into `commonMain` classes | Breaks the shared build | Interface in common, platform binding in `platformModule` |
| Old `org.koin.compose.viewmodel.dsl.viewModelOf` import | Deprecated in Koin 4 | `org.koin.core.module.dsl.viewModelOf` |
| Tests share a started Koin | Order-dependent failures | Fakes via constructors; `stopKoin()` in `@AfterTest` |

## Related skills

- **kmp-data-layer** — what the network and repository modules provide.
- **kmp-room-database** and **kmp-secure-storage** — platform bindings for the database and secure store.
- **kmp-expect-actual** — designing platform abstractions behind the bindings.
- **kmp-swiftui-interop** — exposing shared code and ViewModels to SwiftUI.
- Koin KMP setup: <https://insert-koin.io/docs/reference/koin-core/kmp-setup>
- Koin multiplatform reference: <https://insert-koin.io/docs/reference/koin-mp/kmp/>
- Koin module verification: <https://insert-koin.io/docs/reference/koin-test/verify>
