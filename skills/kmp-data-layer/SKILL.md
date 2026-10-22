---
name: kmp-data-layer
description: Use when designing, adding or refactoring the data layer of a Kotlin Multiplatform app in commonMain — Ktor HttpClient setup, DTOs and kotlinx.serialization, repositories and mappers, a typed result/error wrapper, bearer token refresh, offline-first caching with Room or SQLDelight — or when debugging MissingFieldException, JsonConvertException, 401 refresh loops, random logouts, tokens in logs, or iOS-only network timeouts.
license: Apache-2.0
compatibility: Kotlin Multiplatform project (Android + iOS) using or adopting Ktor client 3.x and kotlinx.serialization 1.7+. iOS compile checks need macOS with Xcode.
metadata:
  category: data
  platforms: android, ios
---

# KMP data layer

The wire is untrusted; the domain is not. Parse responses into nullable DTOs, validate and map them in
the data layer, and expose only non-null domain models and a typed result. One configured `HttpClient`
is the only door to the network. When a screen must work offline, the UI observes the database, not
the network response.

## When to use

- Designing the remote and local data layer of a new KMP app or module.
- Adding a repository, mapper, error type, cache or sync path to existing shared code.
- Reviewing data-layer code against the failure modes in **Common mistakes**.
- Debugging: one malformed item empties or crashes a whole list; 401 loops or users logged out at
  random; tokens visible in Logcat or the Xcode console; requests that time out differently on iOS.

## When not to use

- Adding one concrete REST endpoint end to end — use **kmp-api-endpoint** (it follows this skill's rules).
- Room setup, DAOs, migrations, iOS SQLite linking — use **kmp-room-database**.
- Koin modules, qualifiers, bootstrap order — use **kmp-koin-di**.
- Where tokens and secrets are stored, logout wipe — use **kmp-secure-storage**.

## Step 0 — Read the project first

Real projects already chose a shape. Detect it before writing anything, then follow it.

```bash
grep -rn "HttpClient(" --include=*.kt .                                                    # 1 client
grep -rnE "sealed (class|interface) [A-Za-z]*(Result|Outcome|Either)" --include=*.kt .    # 2 wrapper
grep -rnE "DispatcherProvider|CoroutineDispatchers|Dispatchers\.IO" --include=*.kt .      # 3 dispatchers
grep -nE "ktor|serialization|room|sqldelight|realm|datastore|koin|kotlin-inject|hilt|kermit|napier" gradle/libs.versions.toml  # 4 stack
find . -path "*commonTest*" -name "*.kt" | head -20                                       # 5 tests
```

| Finding | Then |
|---|---|
| A client factory or DI-provided `HttpClient` | Inject it. Do not build a second client. |
| A result / error wrapper (custom sealed type, `Either`, `kotlin.Result`) | Use it. Never add a second wrapper. |
| A dispatcher provider | Use that type. |
| SQLDelight, Realm or DataStore instead of Room | Follow that library; Room specifics are in **kmp-room-database**. |
| Koin, kotlin-inject, Hilt or manual DI | Wire in that framework's idiom. |
| Kermit or Napier | Route HTTP logs through it. |
| An existing feature | Copy its layout: where DTOs live, `toDomain()` or mapper classes, use cases or not. |
| Ktor, serialization and Kotlin versions | Use only APIs those versions have. |
| `Fake*` classes, `MockEngine`, Turbine | Write tests the same way. |

Defaults below apply only when the project has no precedent.

## Workflow

### 1. Lay out the layers

```
shared/src/commonMain/kotlin/com/example/app/
├── core/network/        HttpClient factory, AppJson, ApiResult, DataError, safeApiCall
├── core/coroutines/     DispatcherProvider
└── notes/
    ├── data/
    │   ├── remote/      NotesApi + KtorNotesApi, dto/NoteDto.kt
    │   ├── local/       NoteEntity, NotesDao            (only when cached)
    │   ├── NoteMappers.kt
    │   └── NotesRepositoryImpl.kt
    └── domain/
        ├── Note.kt                    non-null, no annotations
        └── NotesRepository.kt         interface
```

Dependencies point inward: `data` knows `domain`; `domain` imports nothing from Ktor,
kotlinx.serialization or Room. In a feature-modularised app each feature owns its own API, DTOs and
repository; shared modules hold only infrastructure (client, result type, database shell). Two
features that call the same endpoint may each declare a DTO — duplication is cheaper than coupling.

Done when this prints nothing:

```bash
grep -rnE "import (io\.ktor|kotlinx\.serialization|androidx\.room)" --include=*.kt $(find . -type d -name domain -path "*commonMain*")
```

### 2. One HttpClient, configured once

- Build it in one place (the app's core/network module) and provide it as a DI singleton. Features
  inject it. Never call `HttpClient()` in a repository, per request, or per feature, and never
  `install(...)` a plugin from feature code — a second client silently loses the auth, timeouts,
  default headers and log redaction of the first, and opens its own connection pool.
- The factory takes the `HttpClientEngine` as a parameter: OkHttp on Android, Darwin on iOS,
  `MockEngine` in tests.
- It installs: `ContentNegotiation` with one shared `Json`, `HttpTimeout`, `Logging` with header
  sanitising, `Auth` bearer (authenticated client only), `defaultRequest` with the base URL, and
  sets `expectSuccess = true`.
- Use two clients only when you need them: a plain client for login and token refresh, and an
  authenticated client, distinguished in DI by `named("authenticated")`.

The full factory, token refresh, timeouts and pinning: [references/http-client.md](references/http-client.md).

Done when exactly one production construction site exists (step **Verify**).

### 3. Treat DTOs as untrusted input

```kotlin
// commonMain — notes/data/remote/dto/NoteDto.kt
@Serializable
data class NoteDto(
    @SerialName("id") val id: String? = null,
    @SerialName("title") val title: String? = null,
    @SerialName("body") val body: String? = null,
    @SerialName("updated_at") val updatedAt: Long? = null,
    @SerialName("tags") val tags: List<String>? = null,
    @SerialName("visibility") val visibility: String? = null,   // enum as String: new values must not crash old apps
)

@Serializable
data class NotesPageDto(
    @SerialName("items") val items: List<NoteDto>? = null,
    @SerialName("next_cursor") val nextCursor: String? = null,
)
```

- **Every response field nullable, defaulting to `null`, with an explicit `@SerialName`.** A
  non-null field the server omits for one item throws `MissingFieldException` (Ktor wraps it in
  `JsonConvertException`) and fails the whole page, not just that item.
- Explicit `@SerialName` keeps the wire contract greppable and lets you rename Kotlin properties freely.
- Decode server enums as `String?` and map them, or a value added server-side crashes every old install.
- Request bodies you send may be non-null — you control them.

### 4. Keep domain models non-null

```kotlin
// commonMain — notes/domain/Note.kt
data class Note(
    val id: String,
    val title: String,
    val body: String,
    val updatedAtEpochMillis: Long,
    val tags: List<String>,
    val visibility: NoteVisibility,
)

enum class NoteVisibility { Private, Shared, Unknown }
```

No serialization annotations. Nullable only where absence means something to the domain.

### 5. Map and validate in the data layer

```kotlin
// commonMain — notes/data/NoteMappers.kt
internal fun NoteDto.toDomainOrNull(): Note? {
    val id = id?.takeIf { it.isNotBlank() } ?: return null   // no identity: row is unusable, drop it
    return Note(
        id = id,
        title = title?.trim().orEmpty(),                       // cosmetic: safe fallback
        body = body.orEmpty(),
        updatedAtEpochMillis = updatedAt ?: 0L,
        tags = tags.orEmpty().filter { it.isNotBlank() },
        visibility = when (visibility?.lowercase()) {
            "private" -> NoteVisibility.Private
            "shared" -> NoteVisibility.Shared
            else -> NoteVisibility.Unknown
        },
    )
}

internal fun List<NoteDto>?.toDomainNotes(): List<Note> = orEmpty().mapNotNull { it.toDomainOrNull() }
```

Decide per field: **drop** the row when a field it cannot exist without is missing (identity,
foreign key, amount on a payment); **fall back** when the field is cosmetic. Write one test per
rule. If you log dropped rows, log the count, never the values. Nullability never leaks past the mapper.

### 6. Keep the API service thin

```kotlin
// commonMain — notes/data/remote/NotesApi.kt
interface NotesApi {
    suspend fun getNotes(cursor: String?): NotesPageDto
    suspend fun createNote(request: CreateNoteRequest): NoteDto
}

internal class KtorNotesApi(private val client: HttpClient) : NotesApi {
    override suspend fun getNotes(cursor: String?): NotesPageDto =
        client.get("notes") { cursor?.let { parameter("cursor", it) } }.body()

    override suspend fun createNote(request: CreateNoteRequest): NoteDto =
        client.post("notes") {
            contentType(ContentType.Application.Json)
            setBody(request)
        }.body()
}
```

No `try`/`catch` here, no mapping, no base URL. Paths are relative to the `defaultRequest` base
URL, which must end with `/`; a path with a leading `/` replaces the base path (`/v1/` is lost).

### 7. Make the repository the error boundary

```kotlin
// commonMain — notes/data/NotesRepositoryImpl.kt
class NotesRepositoryImpl(
    private val notesApi: NotesApi,
    private val dispatchers: DispatcherProvider,
) : NotesRepository {

    override suspend fun getNotes(cursor: String?): ApiResult<NotesPage> =
        safeApiCall(dispatchers.default) {
            val page = notesApi.getNotes(cursor)
            NotesPage(notes = page.items.toDomainNotes(), nextCursor = page.nextCursor)
        }
}
```

`safeApiCall` turns every exception into a typed `DataError` and **rethrows
`CancellationException`**. Ktor is main-safe, but body deserialization and mapping run on the
caller's dispatcher, so large payloads move off `Main`. `ApiResult`, `DataError` and
`safeApiCall`: [references/api-result.md](references/api-result.md). If the project already has a
wrapper, map into that instead. ViewModels see only domain types and the result type, never DTOs or
Ktor exceptions.

### 8. Inject dispatchers

```kotlin
// commonMain — core/coroutines/DispatcherProvider.kt
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.IO   // Dispatchers.IO is an extension property outside the JVM

interface DispatcherProvider {
    val main: CoroutineDispatcher
    val io: CoroutineDispatcher
    val default: CoroutineDispatcher
}

object DefaultDispatcherProvider : DispatcherProvider {
    override val main: CoroutineDispatcher get() = Dispatchers.Main
    override val io: CoroutineDispatcher get() = Dispatchers.IO
    override val default: CoroutineDispatcher get() = Dispatchers.Default
}
```

Tests pass one `StandardTestDispatcher(testScheduler)` for all three, so `runTest` controls every
coroutine and no test waits on real time.

### 9. Go offline-first when the screen must work without network

- **Read:** the DAO returns `Flow<List<Entity>>`; the repository maps it to domain models; the UI
  observes only this. A read never throws and is not wrapped in the result type.
- **Refresh:** a `suspend` call fetches, maps, writes to the database in one transaction and
  returns `ApiResult<Unit>`. Its result drives only the spinner and error UI — the database write
  is what updates the screen.
- **Writes made offline:** insert a pending row first, then trigger a sync worker. The worker posts,
  marks the row synced, or retries with backoff (network errors, 429 and 5xx); any other 4xx marks
  the row as failed so it stops retrying.
- **Never make a user gesture await the whole outbox.** Draining every pending row, each with a
  network timeout, pins the loader on unrelated backlog. Trigger the sync and wait a bounded time
  (a few seconds) for the gesture's own row; returning "pending" is a valid success.
- Store a last-synced timestamp per cache key so the UI can tell "never loaded" from "loaded, empty".

```kotlin
// commonMain — notes/data/OfflineNotesRepository.kt
class OfflineNotesRepository(
    private val notesApi: NotesApi,
    private val notesDao: NotesDao,
    private val dispatchers: DispatcherProvider,
) {
    fun observeNotes(): Flow<List<Note>> =
        notesDao.observeAll().map { rows -> rows.map { it.toDomain() } }

    suspend fun refresh(): ApiResult<Unit> = safeApiCall(dispatchers.default) {
        val notes = notesApi.getNotes(cursor = null).items.toDomainNotes()
        notesDao.replaceAll(notes.map { it.toEntity() })   // @Transaction DAO method
    }
}
```

DAO, transactions and migrations: **kmp-room-database**. Clearing cached tables on logout: **kmp-secure-storage**.

### 10. Wire it

With Koin (the default when nothing else exists):

```kotlin
// commonMain — notes/di/NotesDataModule.kt
val notesDataModule = module {
    single<NotesApi> { KtorNotesApi(client = get(named("authenticated"))) }
    singleOf(::NotesRepositoryImpl) bind NotesRepository::class
}
```

`singleOf(::X)` cannot pass a qualifier to a constructor parameter; use a lambda when a dependency
is qualified. Module layout and start-up order: **kmp-koin-di**.

### 11. Test at the seams

| Unit | Test with | Assert |
|---|---|---|
| Mapper | plain `commonTest` | each drop rule and each fallback |
| API + client config | `MockEngine` through the real factory | path, query, headers, body; 401 → refresh → retry |
| Repository | hand-written `FakeNotesApi` | success, every `DataError`, cancellation propagates |
| ViewModel | fake repository + test dispatcher | state and one-shot events |

Use the production `AppJson` in tests, or serialization tests prove nothing. MockEngine recipes:
[references/http-client.md](references/http-client.md#testing-with-mockengine).

## Quick reference

| Concern | Default | Rule |
|---|---|---|
| Engine | OkHttp (Android), Darwin (iOS) | factory takes `HttpClientEngine` |
| JSON | one `Json { ignoreUnknownKeys = true; explicitNulls = false }` | shared by client and tests |
| DTO field | `@SerialName("x") val x: T? = null` | every response field |
| Domain model | plain non-null `data class` | no annotations |
| Mapping | `Dto.toDomainOrNull()` in `data/` | drop unusable rows, fall back on cosmetic fields |
| Errors | `ApiResult<T>` + `DataError` | mapped in the repository; `CancellationException` rethrown |
| Non-2xx | `expectSuccess = true` | status becomes a typed error, not a parse failure |
| Timeouts | `HttpTimeout` request + socket | Darwin ignores `connectTimeoutMillis` |
| Logging | `HEADERS` in debug, `NONE` in release | `sanitizeHeader` for `Authorization`, `Cookie` |
| Auth | `Auth { bearer { loadTokens; refreshTokens } }` | refresh request marked; tokens only to your host |
| Dispatchers | injected `DispatcherProvider` | never hard-code in classes under test |
| Offline | DAO `Flow` is the source of truth | network calls write to the DB |

## Verify

Run what applies; report each line as `PASS`, `FAIL` or `NOT RUN` (with the reason). Never report
a check as passed that you did not run. Module and task names vary — read `settings.gradle.kts`
and run `./gradlew :shared:tasks --all | grep -i test` when unsure.

```bash
./gradlew :shared:allTests                         # common, Android host and iOS simulator tests
./gradlew :shared:compileKotlinIosSimulatorArm64   # commonMain compiles for iOS
./gradlew :composeApp:assembleDebug                # Android app still builds
```

Static checks (each should print nothing, or only lines you have reviewed):

```bash
# More than one production construction site means a second client
grep -rn "HttpClient(" --include=*.kt . | grep -viE "test|mock"
# Non-null fields in response DTOs (request DTOs may legitimately be non-null)
grep -rnE "val [A-Za-z0-9_]+: [^?=]+(,|$)" --include=*Dto.kt .
# Raw printing bypasses log redaction
grep -rnE "println\(|NSLog\(|Log\.[dviwe]\(" --include=*.kt . | grep -v Test
# Plugins installed outside the network module
grep -rn "install(" --include=*.kt . | grep -v "core/network" | grep -viE "test"
```

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Non-null DTO field without default | One item missing it fails the whole response with `MissingFieldException` / `JsonConvertException` | Nullable, `= null`, map in the repository |
| `catch (e: Exception)` or `runCatching` around a suspend call | Swallows `CancellationException`; cancelled screens keep working and leak | Catch `CancellationException` first and rethrow (see `safeApiCall`) |
| `expectSuccess = false` then `.body<T>()` | A 404 or 500 error envelope is parsed as `T` and surfaces as a misleading parse error | `expectSuccess = true`; map `ResponseException` by status |
| `HttpClient()` inside a feature or per call | Loses auth, timeouts, redaction; new connection pool each time | Inject the shared client |
| `LogLevel.ALL` / `BODY` in release | Bodies with passwords and tokens reach device logs; `sanitizeHeader` does not touch bodies | `HEADERS` in debug only, `NONE` in release |
| Refresh request goes through the `Auth` plugin | 401 on refresh triggers another refresh: loop | `markAsRefreshTokenRequest()` or a plain client |
| Bearer token sent to every host | Bearer sends proactively by default; tokens leak to CDNs and break pre-signed upload URLs | `sendWithoutRequest { it.url.host == apiHost }` |
| Signing out when refresh fails offline | A transport error is not an invalid session | Sign out only when the server rejects the refresh token |
| Base URL without trailing `/`, or path with leading `/` | `/v1` is dropped and requests hit the wrong path | `https://api.example.com/v1/` + `get("notes")` |
| Relying on `connectTimeoutMillis` on iOS | Darwin does not support it | Set request and socket timeouts |
| `explicitNulls = false` with PATCH | Null fields are omitted, so "clear this field" never reaches the server | Send an explicit request DTO or a `JsonObject` for clears |
| `Dispatchers.IO` hard-coded in a repository | Tests race real threads and flake | Inject `DispatcherProvider` |
| UI binds to the network response in an offline app | Data disappears offline and after process death | Observe the DAO `Flow`; network writes into it |
| Gesture awaits the full sync drain | Spinner waits on unrelated backlog and timeouts | Trigger sync, bounded wait on the gesture's own row |

## Related skills

- **kmp-api-endpoint** — concrete recipe for one endpoint using these rules.
- **kmp-room-database** — Room KMP setup, DAOs, migrations, iOS linking.
- **kmp-koin-di** — modules, qualifiers, bootstrap order.
- **kmp-secure-storage** — token storage and logout wipe.
- Ktor multiplatform client: <https://ktor.io/docs/client-create-multiplatform-application.html>
- Ktor bearer auth: <https://ktor.io/docs/client-bearer-auth.html>
- Compose-side state and ViewModels: <https://github.com/Meet-Miyani/compose-skill>
- Android-only data patterns: <https://github.com/rcosteira79/android-skills>
