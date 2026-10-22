# HttpClient factory for Kotlin Multiplatform

One factory in `commonMain` builds every client the app uses. Platform code only chooses the engine.
APIs below are Ktor client 3.x and kotlinx.serialization 1.7+.

## Contents

1. [Dependencies](#1-dependencies)
2. [One shared Json](#2-one-shared-json)
3. [Engines per platform](#3-engines-per-platform)
4. [The factory](#4-the-factory)
5. [Bearer auth and token refresh](#5-bearer-auth-and-token-refresh)
6. [Timeouts](#6-timeouts)
7. [Logging without leaking secrets](#7-logging-without-leaking-secrets)
8. [Two clients in DI](#8-two-clients-in-di)
9. [Certificate pinning](#9-certificate-pinning)
10. [Testing with MockEngine](#testing-with-mockengine)

## 1. Dependencies

`gradle/libs.versions.toml` — keep the Ktor 3.x version the catalog already pins:

```toml
[libraries]
ktor-client-core = { module = "io.ktor:ktor-client-core", version.ref = "ktor" }
ktor-client-content-negotiation = { module = "io.ktor:ktor-client-content-negotiation", version.ref = "ktor" }
ktor-serialization-kotlinx-json = { module = "io.ktor:ktor-serialization-kotlinx-json", version.ref = "ktor" }
ktor-client-logging = { module = "io.ktor:ktor-client-logging", version.ref = "ktor" }
ktor-client-auth = { module = "io.ktor:ktor-client-auth", version.ref = "ktor" }
ktor-client-okhttp = { module = "io.ktor:ktor-client-okhttp", version.ref = "ktor" }
ktor-client-darwin = { module = "io.ktor:ktor-client-darwin", version.ref = "ktor" }
ktor-client-mock = { module = "io.ktor:ktor-client-mock", version.ref = "ktor" }

[plugins]
kotlinSerialization = { id = "org.jetbrains.kotlin.plugin.serialization", version.ref = "kotlin" }
```

`shared/build.gradle.kts`:

```kotlin
plugins {
    alias(libs.plugins.kotlinSerialization)
}

kotlin {
    sourceSets {
        commonMain.dependencies {
            implementation(libs.ktor.client.core)
            implementation(libs.ktor.client.content.negotiation)
            implementation(libs.ktor.serialization.kotlinx.json)
            implementation(libs.ktor.client.logging)
            implementation(libs.ktor.client.auth)
        }
        androidMain.dependencies { implementation(libs.ktor.client.okhttp) }
        iosMain.dependencies { implementation(libs.ktor.client.darwin) }
        commonTest.dependencies { implementation(libs.ktor.client.mock) }
    }
}
```

## 2. One shared Json

```kotlin
// commonMain — core/network/AppJson.kt
val AppJson: Json = Json {
    ignoreUnknownKeys = true   // a field added server-side must not break installed apps
    explicitNulls = false      // encode: omit null properties; decode: absent nullable property is null
    // isLenient stays false: accepting malformed JSON hides server bugs
    // coerceInputValues = true would turn null / unknown enum values into the property default
}
```

Use `AppJson` in the client and in every serialization test. A test with its own `Json` proves nothing
about production.

## 3. Engines per platform

```kotlin
// commonMain — core/network/PlatformHttpEngine.kt
expect fun platformHttpEngine(): HttpClientEngine

// androidMain — core/network/PlatformHttpEngine.android.kt
actual fun platformHttpEngine(): HttpClientEngine = OkHttp.create()

// iosMain — core/network/PlatformHttpEngine.ios.kt
actual fun platformHttpEngine(): HttpClientEngine = Darwin.create()
```

Engine-specific tuning goes in the `create { }` block, for example
`OkHttp.create { config { retryOnConnectionFailure(true) } }`. Two clients may share one engine
instance; a client does not close an engine it was given.

## 4. The factory

```kotlin
// commonMain — core/network/HttpClientFactory.kt
import io.ktor.client.HttpClient
import io.ktor.client.HttpClientConfig
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.defaultRequest
import io.ktor.client.plugins.logging.LogLevel
import io.ktor.client.plugins.logging.Logger
import io.ktor.client.plugins.logging.Logging
import io.ktor.client.request.header
import io.ktor.http.HttpHeaders
import io.ktor.serialization.kotlinx.json.json

data class NetworkConfig(
    val baseUrl: String,       // must end with "/" — e.g. "https://api.example.com/v1/"
    val isDebug: Boolean,
    val userAgent: String,
)

/** Bridges Ktor's logging to the project's logger (Kermit, Napier, …), never to println. */
fun interface HttpLogger {
    fun log(message: String)
}

private val SensitiveHeaders = listOf(HttpHeaders.Authorization, HttpHeaders.Cookie, HttpHeaders.SetCookie)

fun createHttpClient(
    engine: HttpClientEngine,
    config: NetworkConfig,
    httpLogger: HttpLogger,
    configureAuth: (HttpClientConfig<*>.() -> Unit)? = null,
): HttpClient = HttpClient(engine) {
    // Non-2xx throws ResponseException (ClientRequestException for 4xx, ServerResponseException for 5xx)
    // instead of trying to parse an error body as the success type.
    expectSuccess = true

    install(ContentNegotiation) { json(AppJson) }

    install(HttpTimeout) {
        requestTimeoutMillis = 30_000
        socketTimeoutMillis = 30_000
        connectTimeoutMillis = 15_000                // the Darwin engine ignores this one
    }

    install(Logging) {
        logger = object : Logger {
            override fun log(message: String) = httpLogger.log(message)
        }
        level = if (config.isDebug) LogLevel.HEADERS else LogLevel.NONE
        sanitizeHeader { name -> SensitiveHeaders.any { it.equals(name, ignoreCase = true) } }
    }

    configureAuth?.invoke(this)

    defaultRequest {
        url(config.baseUrl)
        header(HttpHeaders.UserAgent, config.userAgent)
    }
}
```

The client is a long-lived singleton. Do not create or `close()` one per request.

## 5. Bearer auth and token refresh

Keep Ktor types out of your session interfaces so they stay testable and usable from Swift:

```kotlin
// commonMain — core/session/SessionContracts.kt
data class SessionTokens(val accessToken: String, val refreshToken: String) {
    override fun toString(): String = "SessionTokens(***)"   // the generated toString would print both tokens
}

interface SessionTokenStore {           // backed by secure storage — see kmp-secure-storage
    suspend fun read(): SessionTokens?
    suspend fun write(tokens: SessionTokens)
    suspend fun clear()
}

fun interface TokenRefresher {
    /** Returns null when the server rejects the refresh token. Throws on transport failure. */
    suspend fun refresh(refreshToken: String): SessionTokens?
}
```

```kotlin
// commonMain — core/network/BearerAuth.kt
fun HttpClientConfig<*>.installBearerAuth(
    apiHost: String,
    tokenStore: SessionTokenStore,
    tokenRefresher: TokenRefresher,
    onSessionExpired: () -> Unit,
) {
    install(Auth) {
        bearer {
            loadTokens {
                tokenStore.read()?.let { BearerTokens(it.accessToken, it.refreshToken) }
            }
            refreshTokens {
                val stored = tokenStore.read() ?: return@refreshTokens null
                if (stored.accessToken != oldTokens?.accessToken) {
                    // Someone refreshed while this request was in flight: reuse, don't rotate twice.
                    return@refreshTokens BearerTokens(stored.accessToken, stored.refreshToken)
                }
                // Throws on a transport failure: the caller gets a network error and stays signed in.
                val fresh = tokenRefresher.refresh(stored.refreshToken)
                if (fresh == null) {                       // the server rejected the refresh token
                    tokenStore.clear()
                    onSessionExpired()
                    return@refreshTokens null              // the original 401 reaches the caller
                }
                tokenStore.write(fresh)
                BearerTokens(fresh.accessToken, fresh.refreshToken)
            }
            // The bearer provider attaches the token to every request by default.
            // Limit it to your API so tokens never reach CDNs or pre-signed upload URLs.
            sendWithoutRequest { request -> request.url.host == apiHost }
        }
    }
}
```

The refresher calls the refresh endpoint with the **plain** client, so the refresh request cannot
trigger another refresh:

```kotlin
// commonMain — core/session/KtorTokenRefresher.kt
@Serializable
private data class RefreshRequestDto(@SerialName("refresh_token") val refreshToken: String)

@Serializable
private data class RefreshResponseDto(
    @SerialName("access_token") val accessToken: String? = null,
    @SerialName("refresh_token") val refreshToken: String? = null,
)

class KtorTokenRefresher(private val plainClient: HttpClient) : TokenRefresher {
    override suspend fun refresh(refreshToken: String): SessionTokens? = try {
        val dto: RefreshResponseDto = plainClient.post("auth/refresh") {
            contentType(ContentType.Application.Json)
            setBody(RefreshRequestDto(refreshToken))
        }.body()
        dto.accessToken?.let { access ->
            SessionTokens(accessToken = access, refreshToken = dto.refreshToken ?: refreshToken)
        }
    } catch (e: ClientRequestException) {
        // 400/401 from the refresh endpoint is a definitive "session over". Anything else propagates.
        if (e.response.status == HttpStatusCode.Unauthorized || e.response.status == HttpStatusCode.BadRequest) null
        else throw e
    }
}
```

Alternative with one client: inside `refreshTokens { }` call
`client.post("auth/refresh") { markAsRefreshTokenRequest(); setBody(...) }`. The marker excludes that
request from the auth retry mechanism.

Rules that prevent the classic bugs:

- **Sign out only on a definitive rejection.** A timeout or offline error during refresh must not
  clear the session.
- **Token cache and logout.** With the default `cacheTokens = true` the provider keeps the loaded
  tokens in memory. On logout, after clearing the store, call
  `authenticatedClient.authProvider<BearerAuthProvider>()?.clearToken()` (recent Ktor 3 releases
  also offer `client.clearAuthTokens()`), or the old token keeps being sent. `cacheTokens = false`
  reads the store on every request instead — simpler, but a secure-store read per request.
- **Concurrent 401s.** Within one client Ktor serialises refreshes. The stale-token check above also
  covers several authenticated clients sharing one store; with more than one client, also guard
  `TokenRefresher.refresh` with a `Mutex` so a rotating refresh token is never spent twice.
- **Backends that signal expiry with another status** (for example 403): recent Ktor 3 releases
  offer `reAuthorizeOnResponse { response -> ... }` inside `install(Auth) { }`. Check that your
  Ktor version has it before relying on it.

## 6. Timeouts

- Per request: `client.post("uploads") { timeout { requestTimeoutMillis = 120_000 } }`.
- `HttpRequestTimeoutException`, `ConnectTimeoutException` and `SocketTimeoutException` all extend
  `kotlinx.io.IOException`, as does the Darwin engine's `DarwinHttpRequestException`. Map them
  in one place — the repository's error boundary — and check the timeout types before `IOException`.
- The Darwin engine supports request and socket timeouts but not connect timeouts.
- Budgets that are too tight on cellular networks produce fast-looking failures that sync retry
  loops then amplify. Choose values from measured latency on real devices, not from Wi-Fi.

## 7. Logging without leaking secrets

- `LogLevel.NONE`, `INFO`, `HEADERS`, `BODY`, `ALL`. `sanitizeHeader { }` replaces matching header
  values with `***`. **Bodies are never sanitised** — login and refresh responses carry tokens in
  the body. Keep `BODY`/`ALL` out of release builds.
- In debug, `filter { request -> !request.url.encodedPath.startsWith("/v1/auth") }` keeps auth
  traffic out of the log while other calls log at a higher level (`encodedPath` on the request's
  `URLBuilder` needs `import io.ktor.http.encodedPath`).
- Bind `HttpLogger` to the project's logger. Kermit: `HttpLogger { Logger.withTag("HTTP").d { it } }`.
  Napier: `HttpLogger { Napier.d(it, tag = "HTTP") }`. `println` and `NSLog` bypass any redaction the
  logger does.
- On-device network inspectors belong in debug-only dependencies, compiled out of release — not
  hidden behind a runtime flag.

## 8. Two clients in DI

```kotlin
// commonMain — core/network/NetworkModule.kt (Koin)
val networkModule = module {
    single(named("plain")) {
        createHttpClient(engine = platformHttpEngine(), config = get(), httpLogger = get())
    }
    single<TokenRefresher> { KtorTokenRefresher(plainClient = get(named("plain"))) }
    single(named("authenticated")) {
        val config: NetworkConfig = get()
        val tokenStore: SessionTokenStore = get()
        val tokenRefresher: TokenRefresher = get()
        val sessionEvents: SessionEvents = get()       // resolve now, not inside a later callback
        createHttpClient(engine = platformHttpEngine(), config = config, httpLogger = get()) {
            installBearerAuth(
                apiHost = Url(config.baseUrl).host,
                tokenStore = tokenStore,
                tokenRefresher = tokenRefresher,
                onSessionExpired = sessionEvents::onSessionExpired,
            )
        }
    }
}
```

`NetworkConfig`, `HttpLogger` and `SessionEvents` (whatever the app uses to route to sign-in) are
provided by the app module. Feature code asks for `get(named("authenticated"))`.

## 9. Certificate pinning

Only pin when your threat model needs it, and pin at least two keys (current and backup) or a
certificate rotation bricks every installed app.

```kotlin
// androidMain
OkHttp.create {
    config {
        certificatePinner(
            CertificatePinner.Builder()
                .add("api.example.com", "sha256/<current-key-hash>", "sha256/<backup-key-hash>")
                .build()
        )
    }
}

// iosMain — io.ktor.client.engine.darwin.certificates.CertificatePinner
Darwin.create {
    handleChallenge(
        CertificatePinner.Builder()
            .add("api.example.com", "sha256/<current-key-hash>", "sha256/<backup-key-hash>")
            .build()
    )
}
```

## Testing with MockEngine

Run the **real** factory with a `MockEngine`, so the test covers content negotiation, base URL,
`expectSuccess` and auth exactly as production configures them.

```kotlin
// commonTest — notes/data/remote/KtorNotesApiTest.kt
private val jsonHeaders = headersOf(HttpHeaders.ContentType, ContentType.Application.Json.toString())
private val testConfig = NetworkConfig(baseUrl = "https://api.example.com/v1/", isDebug = false, userAgent = "test")

private fun testClient(handler: MockRequestHandler): HttpClient =
    createHttpClient(engine = MockEngine(handler), config = testConfig, httpLogger = {})

class KtorNotesApiTest {

    @Test
    fun should_sendCursorAndParsePage_when_cursorGiven() = runTest {
        var captured: HttpRequestData? = null
        val api = KtorNotesApi(testClient { request ->
            captured = request
            respond("""{"items":[{"id":"n1","title":"A","unknown":1}],"next_cursor":null}""", headers = jsonHeaders)
        })

        val page = api.getNotes(cursor = "c2")

        assertEquals("/v1/notes", captured?.url?.encodedPath)
        assertEquals("c2", captured?.url?.parameters?.get("cursor"))
        assertEquals("n1", page.items?.single()?.id)
    }

    @Test
    fun should_throwClientRequestException_when_serverReturns404() = runTest {
        val api = KtorNotesApi(testClient { respondError(HttpStatusCode.NotFound) })

        assertFailsWith<ClientRequestException> { api.getNotes(cursor = null) }
    }
}
```

Refresh-and-retry, with hand-written fakes:

```kotlin
// commonTest — core/network/BearerAuthTest.kt
class InMemorySessionTokenStore(private var tokens: SessionTokens?) : SessionTokenStore {
    override suspend fun read() = tokens
    override suspend fun write(tokens: SessionTokens) { this.tokens = tokens }
    override suspend fun clear() { tokens = null }
}

class BearerAuthTest {

    @Test
    fun should_refreshOnceAndRetry_when_accessTokenExpired() = runTest {
        val store = InMemorySessionTokenStore(SessionTokens("old", "r1"))
        var refreshCalls = 0
        val refresher = TokenRefresher { refreshCalls++; SessionTokens("new", "r2") }
        val client = createHttpClient(
            engine = MockEngine { request ->
                if (request.headers[HttpHeaders.Authorization] == "Bearer new") {
                    respond("""{"items":[]}""", headers = jsonHeaders)
                } else {
                    respondError(HttpStatusCode.Unauthorized)
                }
            },
            config = testConfig,
            httpLogger = {},
        ) {
            installBearerAuth("api.example.com", store, refresher, onSessionExpired = {})
        }

        KtorNotesApi(client).getNotes(cursor = null)

        assertEquals(1, refreshCalls)
        assertEquals("new", store.read()?.accessToken)
    }

    @Test
    fun should_clearSessionAndNotify_when_refreshRejected() = runTest {
        val store = InMemorySessionTokenStore(SessionTokens("old", "r1"))
        var expired = false
        val client = createHttpClient(
            engine = MockEngine { respondError(HttpStatusCode.Unauthorized) },
            config = testConfig,
            httpLogger = {},
        ) {
            installBearerAuth("api.example.com", store, { null }, onSessionExpired = { expired = true })
        }

        assertFailsWith<ClientRequestException> { KtorNotesApi(client).getNotes(cursor = null) }
        assertTrue(expired)
        assertNull(store.read())
    }
}
```

With a single auth provider, Ktor refreshes on a 401 even when the response has no
`WWW-Authenticate` header. With several providers it needs the header to choose one.
