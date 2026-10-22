# Data-layer, DI and UI tests in KMP

- [Ktor client with MockEngine](#ktor-client-with-mockengine)
- [Repository with a fake API and an in-memory store](#repository-with-a-fake-api-and-an-in-memory-store)
- [Koin: wiring tests and overrides](#koin-wiring-tests-and-overrides)
- [Mokkery, when the project uses mocks](#mokkery-when-the-project-uses-mocks)
- [Compose Multiplatform UI tests](#compose-multiplatform-ui-tests)
- [Dependencies](#dependencies)

## Ktor client with MockEngine

Test the API layer against `MockEngine`. Build the client **with the same factory production uses**:
same plugins, same JSON settings, same `expectSuccess`, same default request. Only the engine
changes. A test client assembled by hand checks a different client.

```kotlin
// commonMain - the production factory takes an engine
fun createHttpClient(engine: HttpClientEngine, json: Json = defaultJson): HttpClient = HttpClient(engine) {
    expectSuccess = false
    install(ContentNegotiation) { json(json) }
    defaultRequest { url("https://api.example.com/") }
}
```

```kotlin
// commonTest
class KtorNotesApiTest {

    private fun jsonResponse(body: String, status: HttpStatusCode = HttpStatusCode.OK) = MockEngine { _ ->
        respond(
            content = ByteReadChannel(body),
            status = status,
            headers = headersOf(HttpHeaders.ContentType, "application/json"),
        )
    }

    @Test
    fun should_returnNotes_when_serverAnswers200() = runTest {
        val engine = jsonResponse("""[{"id":"1","title":"Milk","extra":"ignored"}]""")
        val api = KtorNotesApi(createHttpClient(engine))

        val result = api.fetchNotes()

        assertEquals(ApiResult.Success(listOf(NoteDto(id = "1", title = "Milk"))), result)
        val request = engine.requestHistory.single()
        assertEquals(HttpMethod.Get, request.method)
        assertEquals("/v1/notes", request.url.encodedPath)
    }

    @Test
    fun should_returnFailure_when_serverAnswers503() = runTest {
        val api = KtorNotesApi(createHttpClient(jsonResponse("""{"error":"down"}""", HttpStatusCode.ServiceUnavailable)))

        assertEquals(ApiResult.Failure(code = 503), api.fetchNotes())
    }
}
```

- Inspect `engine.requestHistory` after the call, rather than asserting inside the handler. An
  assertion that throws inside the handler fails the request, and the test then reports a network
  error instead of the real mismatch.
- Cover the non-2xx paths and malformed JSON. With `expectSuccess = true`, a non-2xx response throws
  `ClientRequestException` / `ServerResponseException`, so the repository's `catch` is the code under
  test.
- For authentication or refresh flows, give the handler a counter and return 401 on the first call
  and 200 afterwards. Then assert how many requests were made.

## Repository with a fake API and an in-memory store

```kotlin
class NotesRepositoryImplTest {
    private val api = FakeNotesApi()
    private val store = InMemoryNotesStore()            // or a hand-written FakeNotesDao
    private val repository = NotesRepositoryImpl(notesApi = api, notesStore = store)

    @Test
    fun should_cacheNotes_when_refreshSucceeds() = runTest {
        api.nextResult = ApiResult.Success(listOf(NoteDto(id = "1", title = "Milk")))

        repository.refresh()

        assertEquals(listOf(Note(id = "1", title = "Milk")), store.observeAll().first())
    }

    @Test
    fun should_dropInvalidRows_when_dtoHasNoId() = runTest {
        api.nextResult = ApiResult.Success(listOf(NoteDto(id = null, title = "orphan"), NoteDto(id = "2", title = "ok")))

        repository.refresh()

        assertEquals(listOf("2"), store.observeAll().first().map { it.id })
    }
}
```

- A real Room in-memory database needs a per-platform builder (the Android one needs a `Context`), so
  `commonTest` usually uses a fake DAO or a production in-memory implementation. Keep one Room test
  per DAO in a device or JVM test set for the SQL itself.
- Read the store back to assert side effects. A return value says nothing about what was written.

## Koin: wiring tests and overrides

Construct classes directly in unit tests: pass the fakes to the constructor. Use Koin in a test only
to prove the **wiring** resolves.

```kotlin
class AppModuleTest : KoinTest {

    @AfterTest
    fun tearDown() = stopKoin()          // a running container makes the next startKoin fail

    @Test
    fun should_resolveNotesViewModel_when_dataLayerIsFaked() {
        startKoin {
            modules(
                appModule,
                module { single<NotesRepository> { FakeNotesRepository() } },   // loaded last: it wins
            )
        }

        assertNotNull(get<NotesViewModel>())
    }
}
```

- The module loaded **last** wins. If the app calls `allowOverride(false)`, a duplicate definition
  throws. Follow the Koin docs for marking test overrides, or start Koin with only the modules under
  test.
- `KoinTest` uses the global context. Always `stopKoin()` in `@AfterTest`, or one test leaks
  definitions into the next.
- Koin's module `verify()` API inspects constructors by reflection. Keep it in a JVM test set
  (`androidHostTest`, `androidUnitTest`, `jvmTest`), not in `commonTest`.

## Mokkery, when the project uses mocks

Hand-written fakes are the default: they run on every target with no plugin. When a team wants mocks
in `commonTest`, [Mokkery](https://mokkery.dev) is a Kotlin compiler plugin that works on JVM,
Android and all Kotlin/Native targets.

```kotlin
// plugins { alias(libs.plugins.mokkery) }      plugin id "dev.mokkery"
val notesRepository = mock<NotesRepository> {
    everySuspend { loadNotes() } returns NotesResult.Success(emptyList())
}
// ... act ...
verifySuspend { notesRepository.loadNotes() }
```

Mokkery mocks interfaces, function types, and abstract or open classes that have a public
constructor. Final classes need the all-open plugin. It cannot mock objects, sealed types, top-level
functions, or final classes from compiled libraries. MockK and Mockito run only on the JVM. Adding
them to `commonTest` breaks iOS test compilation.

## Compose Multiplatform UI tests

Unit-test the state holder first. Write Compose UI tests only for real UI behaviour: what renders for
a given state, and which action a click sends.

```kotlin
@OptIn(ExperimentalTestApi::class)
class NotesListUiTest {
    @Test
    fun should_sendOpen_when_rowClicked() = runComposeUiTest {
        val actions = mutableListOf<NotesAction>()
        setContent {
            NotesList(state = NotesUiState(notes = listOf(note("7"))), onAction = { actions += it })
        }

        onNodeWithTag(NotesTestTags.row("7")).performClick()

        assertEquals(listOf<NotesAction>(NotesAction.Open(id = "7")), actions)
    }
}
```

- Dependency: `org.jetbrains.compose.ui:ui-test` in `commonTest`. Newer Compose Multiplatform
  versions also ship `androidx.compose.ui.test.v2.runComposeUiTest`. Use the import that the
  project's version documents.
- These tests run on the iOS simulator (`iosSimulatorArm64Test`), on desktop JVM (`jvmTest`) and as
  Android **device** tests (`connectedAndroidTest`). The official docs say common Compose tests cannot
  run as Android local (host) tests.
- Find nodes by `testTag`, never by display text. See the `mobile-accessibility-test-ids` skill.

## Dependencies

Version-catalog entries (versions live in `[versions]`; never inline them in `build.gradle.kts`):

```toml
[libraries]
kotlinx-coroutines-test = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-test", version.ref = "kotlinx-coroutines" }
turbine = { module = "app.cash.turbine:turbine", version.ref = "turbine" }
ktor-client-mock = { module = "io.ktor:ktor-client-mock", version.ref = "ktor" }
koin-test = { module = "io.insert-koin:koin-test", version.ref = "koin" }

[plugins]
mokkery = { id = "dev.mokkery", version.ref = "mokkery" }
```

```kotlin
kotlin {
    sourceSets {
        commonTest.dependencies {
            implementation(kotlin("test"))
            implementation(libs.kotlinx.coroutines.test)
            implementation(libs.turbine)            // only if the project uses Turbine
            implementation(libs.ktor.client.mock)   // only for API-layer tests
        }
    }
}
```
