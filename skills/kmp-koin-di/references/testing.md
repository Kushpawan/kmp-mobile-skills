# Testing a Koin graph in Kotlin Multiplatform

Two different questions, two different tests:

- **Does the class behave?** Construct it with fakes. No Koin.
- **Does the graph resolve?** Verify the modules, or resolve the roots in an isolated Koin.

## Contents

1. [Unit tests without Koin](#1-unit-tests-without-koin)
2. [Static verification with verify()](#2-static-verification-with-verify)
3. [Resolving the real graph in an isolated Koin](#3-resolving-the-real-graph-in-an-isolated-koin)
4. [Overriding bindings with fakes](#4-overriding-bindings-with-fakes)
5. [Tests that need the global Koin](#5-tests-that-need-the-global-koin)
6. [Catching accidental overrides](#6-catching-accidental-overrides)

## 1. Unit tests without Koin

```kotlin
// commonTest — profile/ProfileViewModelTest.kt
class ProfileViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setUp() = Dispatchers.setMain(dispatcher)
    @AfterTest fun tearDown() = Dispatchers.resetMain()

    @Test
    fun should_showProfile_when_repositorySucceeds() = runTest(dispatcher) {
        val viewModel = ProfileViewModel(
            profileId = "p-1",
            getProfileUseCase = GetProfileUseCase(FakeProfileRepository(profile = sampleProfile)),
        )

        advanceUntilIdle()

        assertEquals(sampleProfile, viewModel.state.value.profile)
    }
}
```

Most tests in a healthy codebase look like this. A class that is hard to construct without Koin has
too many dependencies, or reaches into Koin itself (`KoinComponent` inside business logic) — fix the
class, not the test.

## 2. Static verification with verify()

`verify()` inspects each definition's constructor and reports parameter types no definition
provides. It lives in the JVM source set of `koin-test`, so the test goes in a JVM test source set
(`androidUnitTest`, `androidHostTest` with the KMP Android library plugin, or `jvmTest`).

```kotlin
// androidUnitTest — di/KoinModulesTest.kt
class KoinModulesTest {

    @Test
    fun should_resolveAllDefinitions_when_appModulesVerified() {
        // verify() checks one module plus its includes, so wrap the whole app graph in one module —
        // verifying feature modules one by one reports their cross-module dependencies as missing.
        val appGraph = module { includes(appModules()) }

        appGraph.verify(
            extraTypes = listOf(
                Context::class,              // supplied by androidContext(...) at start-up
                SavedStateHandle::class,     // supplied by the ViewModel's creation extras
            ),
            injections = injectedParameters(
                definition<ProfileViewModel>(String::class),   // profileId comes from parametersOf(...)
            ),
        )
    }
}
```

Imports: `org.koin.test.verify.verify`, `org.koin.test.verify.definition`,
`org.koin.test.verify.injectedParameters`. `checkModules()` is deprecated in favour of `verify()`.

`verify()` reads constructors; it does not run definition lambdas. A lambda that calls
`get(named("x"))` with a qualifier nobody declares passes `verify()` and fails at runtime — section 3
catches that.

## 3. Resolving the real graph in an isolated Koin

`koinApplication { }` builds a Koin instance without touching the global context, so it cannot
collide with other tests. It runs in `commonTest`, so it exercises the iOS bindings too.

```kotlin
// commonTest — di/KoinGraphTest.kt
class KoinGraphTest {

    @Test
    fun should_resolveRootDependencies_when_graphStarts() {
        val app = koinApplication {
            modules(appModules() + testPlatformOverrides)
        }
        try {
            app.koin.get<ProfileRepository>()
            app.koin.get<HttpClient>(named("authenticated"))
            app.koin.get<GetProfileUseCase>()
        } finally {
            app.close()
        }
    }
}

// Replace bindings that need a real device: Keychain, Android Context, file paths.
val testPlatformOverrides = module {
    single<SecureStore> { InMemorySecureStore() }
}
```

Resolve the roots — repositories, use cases, the authenticated client. Each `get()` builds the
transitive graph below it, so a handful of roots covers most definitions.

## 4. Overriding bindings with fakes

The last definition of a type + qualifier wins (overrides are allowed by default), so append
overrides after the real modules:

```kotlin
val app = koinApplication {
    modules(appModules() + module {
        single<ProfileApi> { FakeProfileApi(profile = sampleProfile) }
    })
}
```

Overriding a binding that has a qualifier needs the same qualifier:
`single<HttpClient>(named("authenticated")) { mockClient }`.

## 5. Tests that need the global Koin

Some code calls `KoinComponent.get()` or `koinViewModel()` and needs the global context. Start and
stop it around every test, never once per class or suite:

```kotlin
// commonTest — profile/ProfileDependenciesTest.kt
class ProfileDependenciesTest : KoinTest {

    @BeforeTest
    fun setUp() {
        startKoin { modules(appModules() + testPlatformOverrides) }
    }

    @AfterTest
    fun tearDown() {
        stopKoin()        // otherwise the next test throws KoinApplicationAlreadyStartedException
    }

    @Test
    fun should_returnUseCase_when_facadeAsked() {
        assertNotNull(ProfileDependencies().getProfileUseCase())
    }
}
```

`loadKoinModules(module)` and `unloadKoinModules(module)` add or remove modules on an already
started Koin — useful for one test that needs an extra binding.

## 6. Catching accidental overrides

Two modules defining the same type silently override each other in production. A test with
overrides disabled turns that into a failure:

```kotlin
@Test
fun should_haveNoDuplicateDefinitions_when_appModulesLoaded() {
    val app = koinApplication {
        allowOverride(false)                 // a duplicate throws DefinitionOverrideException
        modules(appModules())
    }
    app.close()
}
```

If the app overrides a library's default binding on purpose, exclude that pair or this test fails by
design — document the intended override next to it.
