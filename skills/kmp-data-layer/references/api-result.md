# ApiResult and DataError

A typed outcome for every data-layer call that can fail. Use it only when the project has no wrapper
of its own — if it already has one (`Result`, `Either`, `Outcome`, a custom sealed type), map into
that and skip the type definitions here; the exception mapping and the cancellation rule still apply.

## Contents

1. [The types](#1-the-types)
2. [safeApiCall](#2-safeapicall)
3. [Exception and status mapping](#3-exception-and-status-mapping)
4. [Operators](#4-operators)
5. [Using kotlin.Result instead](#5-using-kotlinresult-instead)
6. [Design rules](#6-design-rules)
7. [Tests](#7-tests)

## 1. The types

```kotlin
// commonMain — core/network/ApiResult.kt
sealed interface ApiResult<out T> {
    data class Success<out T>(val value: T) : ApiResult<T>
    data class Failure(val error: DataError) : ApiResult<Nothing>
}

sealed interface DataError {
    data object NoConnection : DataError                         // offline, DNS, refused, TLS
    data object Timeout : DataError
    data object Unauthorized : DataError                         // 401 after refresh failed: session over
    data object Forbidden : DataError                            // 403
    data object NotFound : DataError                             // 404
    data class Validation(val serverMessage: String?) : DataError // 400, 422
    data object RateLimited : DataError                          // 429
    data class Server(val status: Int) : DataError               // 5xx
    data class Http(val status: Int) : DataError                 // any other non-2xx
    data object Serialization : DataError                        // body did not match the DTO
    data class Unknown(val cause: Throwable) : DataError
}

val DataError.isRetryable: Boolean
    get() = this is DataError.NoConnection || this is DataError.Timeout ||
        this is DataError.RateLimited || this is DataError.Server
```

`ApiResult` lives in a core module that both `domain` and `data` can import — repository interfaces
return it.

## 2. safeApiCall

```kotlin
// commonMain — core/network/SafeApiCall.kt
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import io.ktor.client.plugins.ResponseException

suspend fun <T> safeApiCall(
    dispatcher: CoroutineDispatcher,
    block: suspend () -> T,
): ApiResult<T> = withContext(dispatcher) {
    try {
        ApiResult.Success(block())
    } catch (e: CancellationException) {
        throw e                                   // cancellation is not a failure: never swallow it
    } catch (e: ResponseException) {
        ApiResult.Failure(e.response.status.value.toDataError(serverMessage = e.serverMessageOrNull()))
    } catch (e: Exception) {
        ApiResult.Failure(e.toDataError())
    }
}
```

Why the order matters: `CancellationException` first, or a cancelled screen's coroutine keeps
running and reports a bogus failure. Catch `Exception`, not `Throwable` — an `OutOfMemoryError` is
not a network outcome.

## 3. Exception and status mapping

```kotlin
// commonMain — core/network/ErrorMapping.kt
import io.ktor.client.network.sockets.ConnectTimeoutException
import io.ktor.client.network.sockets.SocketTimeoutException
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.serialization.ContentConvertException
import kotlinx.io.IOException
import kotlinx.serialization.SerializationException

fun Exception.toDataError(): DataError = when (this) {
    // Timeouts first: all three extend IOException.
    is HttpRequestTimeoutException, is ConnectTimeoutException, is SocketTimeoutException -> DataError.Timeout
    is IOException -> DataError.NoConnection            // OkHttp IOExceptions, Darwin's DarwinHttpRequestException
    is ContentConvertException, is SerializationException -> DataError.Serialization
    else -> DataError.Unknown(this)
}

fun Int.toDataError(serverMessage: String?): DataError = when (this) {
    401 -> DataError.Unauthorized
    403 -> DataError.Forbidden
    404 -> DataError.NotFound
    400, 422 -> DataError.Validation(serverMessage)
    429 -> DataError.RateLimited
    in 500..599 -> DataError.Server(this)
    else -> DataError.Http(this)
}
```

Reading the server's error message (adapt the envelope to your API):

```kotlin
// commonMain — core/network/ErrorEnvelope.kt
@Serializable
private data class ErrorEnvelopeDto(@SerialName("message") val message: String? = null)

suspend fun ResponseException.serverMessageOrNull(): String? = try {
    AppJson.decodeFromString<ErrorEnvelopeDto>(response.bodyAsText()).message
} catch (e: CancellationException) {
    throw e
} catch (e: Exception) {
    null                                         // error bodies are untrusted too
}
```

Ktor 3 keeps the response body readable after `expectSuccess` throws, so `bodyAsText()` works here.
Treat `serverMessage` as diagnostic or as text the backend explicitly designs for users — never
show raw server text without that agreement.

A `JsonConvertException` (a `ContentConvertException`) is what Ktor throws when the body does not
match the DTO, wrapping kotlinx.serialization's `MissingFieldException` or
`JsonDecodingException`. A spike of `DataError.Serialization` almost always means a DTO field that
should be nullable.

## 4. Operators

```kotlin
// commonMain — core/network/ApiResultOps.kt
inline fun <T, R> ApiResult<T>.map(transform: (T) -> R): ApiResult<R> = when (this) {
    is ApiResult.Success -> ApiResult.Success(transform(value))
    is ApiResult.Failure -> this
}

inline fun <T> ApiResult<T>.onSuccess(action: (T) -> Unit): ApiResult<T> {
    if (this is ApiResult.Success) action(value)
    return this
}

inline fun <T> ApiResult<T>.onFailure(action: (DataError) -> Unit): ApiResult<T> {
    if (this is ApiResult.Failure) action(error)
    return this
}

inline fun <T, R> ApiResult<T>.fold(onSuccess: (T) -> R, onFailure: (DataError) -> R): R = when (this) {
    is ApiResult.Success -> onSuccess(value)
    is ApiResult.Failure -> onFailure(error)
}

fun <T> ApiResult<T>.getOrNull(): T? = (this as? ApiResult.Success)?.value
```

ViewModel use:

```kotlin
viewModelScope.launch {
    _state.update { it.copy(isLoading = true) }
    getNotesUseCase(cursor = null)
        .onSuccess { page -> _state.update { it.copy(isLoading = false, notes = page.notes) } }
        .onFailure { error -> _state.update { it.copy(isLoading = false, error = error.toUiMessage()) } }
}
```

`toUiMessage()` lives in the presentation layer — the data layer never decides wording.

## 5. Using kotlin.Result instead

`kotlin.Result` is fine when the project already uses it, with two caveats:

- `runCatching { }` catches `CancellationException`. Use a suspend-aware variant:

  ```kotlin
  suspend inline fun <T> runSuspendCatching(block: () -> T): Result<T> = try {
      Result.success(block())
  } catch (e: CancellationException) {
      throw e
  } catch (e: Exception) {
      Result.failure(e)
  }
  ```

- The failure is an untyped `Throwable`. Map it with `toDataError()` at the presentation boundary
  so every screen handles the same cases.

## 6. Design rules

- **No `Loading` case.** A result is an outcome of a finished call. Loading belongs in UI state.
- **Unauthorized means the session is over.** The bearer `Auth` plugin already tried a refresh; the
  app reacts once (sign-in screen), not per screen.
- **Map once.** Only `safeApiCall` turns exceptions into `DataError`. Repositories never `try`/`catch`
  Ktor exceptions themselves.
- **Reads from the database are not wrapped.** A DAO `Flow` does not fail with a network error.
- **Swift consumers.** Generic sealed interfaces lose their type parameter in the Objective-C header.
  If Swift consumes the result, check the generated header; SKIE's sealed-type bridging or a small
  non-generic result type per feature at the boundary keeps Swift `switch` statements exhaustive.

## 7. Tests

```kotlin
// commonTest — core/network/SafeApiCallTest.kt
private val testConfig = NetworkConfig(baseUrl = "https://api.example.com/v1/", isDebug = false, userAgent = "test")

@OptIn(ExperimentalCoroutinesApi::class)   // runCurrent / advanceUntilIdle
class SafeApiCallTest {

    @Test
    fun should_returnNotFound_when_serverReturns404() = runTest {
        val client = createHttpClient(MockEngine { respondError(HttpStatusCode.NotFound) }, testConfig, httpLogger = {})

        val result = safeApiCall(StandardTestDispatcher(testScheduler)) { client.get("notes/n1").body<NoteDto>() }

        assertEquals(ApiResult.Failure(DataError.NotFound), result)
    }

    @Test
    fun should_returnNoConnection_when_engineThrowsIOException() = runTest {
        val client = createHttpClient(MockEngine { throw IOException("offline") }, testConfig, httpLogger = {})

        val result = safeApiCall(StandardTestDispatcher(testScheduler)) { client.get("notes").body<NotesPageDto>() }

        assertEquals(ApiResult.Failure(DataError.NoConnection), result)
    }

    @Test
    fun should_returnSerialization_when_bodyIsNotJson() = runTest {
        val client = createHttpClient(
            MockEngine { respond("<html>", headers = headersOf(HttpHeaders.ContentType, "application/json")) },
            testConfig,
            httpLogger = {},
        )

        val result = safeApiCall(StandardTestDispatcher(testScheduler)) { client.get("notes").body<NotesPageDto>() }

        assertEquals(ApiResult.Failure(DataError.Serialization), result)
    }

    @Test
    fun should_propagateCancellation_when_callerIsCancelled() = runTest {
        var result: ApiResult<Unit>? = null
        val job = launch { result = safeApiCall<Unit>(StandardTestDispatcher(testScheduler)) { awaitCancellation() } }
        runCurrent()

        job.cancel()
        advanceUntilIdle()

        assertTrue(job.isCancelled)
        assertNull(result)
    }
}
```

`createHttpClient` and `NetworkConfig` are the project's client factory; build the test client
through it so the test exercises production configuration.
