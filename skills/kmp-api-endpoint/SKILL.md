---
name: kmp-api-endpoint
description: Use when adding, wiring or fixing one REST endpoint in a Kotlin Multiplatform shared module — "add a GET/POST/PUT/DELETE call", "integrate this API", "call /orders from shared code" — covering the Ktor request, @Serializable DTOs, mapper, repository, use case, Koin wiring and MockEngine tests, or when a new endpoint crashes with MissingFieldException, returns 404 because of a wrong path, or works on Android but not iOS.
license: Apache-2.0
compatibility: Kotlin Multiplatform project (Android + iOS) with Ktor client 3.x and kotlinx.serialization. iOS test runs need macOS with Xcode.
metadata:
  category: data
  platforms: android, ios
---

# Add one REST endpoint to a KMP app

A concrete recipe: one endpoint, from wire contract to tested repository, in the project's own shape.
The architecture behind each step — untrusted DTOs, one shared client, typed errors — is in
**kmp-data-layer**; this skill applies it file by file.

## When to use

- Adding a new GET, POST, PUT, PATCH or DELETE call to shared code.
- Adding a method to an existing API service, repository and use case.
- Fixing a freshly added endpoint: parse failures, wrong URL, missing auth header, untested errors.

## When not to use

- Designing the data layer, HttpClient, auth refresh or result type from scratch — use **kmp-data-layer** first.
- Caching the response in a database or syncing offline writes — **kmp-data-layer** (offline-first) and **kmp-room-database**.
- DI start-up problems (`NoDefinitionFoundException` at launch) — **kmp-koin-di**.

## Inputs — get these before writing code

| Input | Example | If missing |
|---|---|---|
| Method and path | `GET orders/{orderId}` | Ask. |
| Path and query parameters | `orderId: String`, `?expand=items` | Ask which are optional. |
| Request body sample | JSON | Required for POST/PUT/PATCH. |
| Response sample | Real JSON, ideally from the API docs or a recorded call | **Ask. Never invent field names.** |
| Error statuses | 404 unknown id, 409 already cancelled | Use the defaults in the error mapping. |
| Auth | bearer / none | Picks the authenticated or plain client. |
| Pagination | cursor / page+size / none | Shapes the domain return type. |

## Step 0 — Read the project first

1. **Find the closest existing endpoint and copy its shape.**
   ```bash
   grep -rln "client.get\|client.post\|HttpClient" --include=*.kt */src/commonMain | head
   ```
   Open one complete vertical (API → repository → use case → DI → tests). Note package layout, file
   names, the `toDomain()` style, whether use cases exist, and how tests are written.
2. **Detect the building blocks** — reuse each one, never add a parallel version:
   ```bash
   grep -rnE "sealed (class|interface) [A-Za-z]*(Result|Outcome)" --include=*.kt .    # result type
   grep -rnE "suspend fun <T> [A-Za-z]*(Call|Request)" --include=*.kt .               # error-boundary helper
   grep -rn "named(" --include=*.kt . | grep -i client                                 # client qualifiers
   grep -rnE "DispatcherProvider|MockEngine|class Fake" --include=*.kt . | head -20    # dispatchers, test helpers
   ```
3. **Check whether files already exist.** If `OrdersApi` exists, add a method; don't create `OrdersApi2`.

If the project has none of this, set up the data layer with **kmp-data-layer** first. The examples
below use its defaults: `ApiResult` / `DataError`, `safeApiCall`, `DispatcherProvider`, Koin with
`named("authenticated")`, package `com.example.app`.

## Workflow

Example endpoint: `GET orders/{orderId}` → one order with line items.

### 1. Response DTOs — `orders/data/remote/dto/OrderDto.kt`

```kotlin
@Serializable
data class OrderDto(
    @SerialName("id") val id: String? = null,
    @SerialName("status") val status: String? = null,
    @SerialName("total_minor") val totalMinor: Long? = null,
    @SerialName("currency") val currency: String? = null,
    @SerialName("placed_at") val placedAtEpochMillis: Long? = null,
    @SerialName("items") val items: List<OrderItemDto>? = null,
)

@Serializable
data class OrderItemDto(
    @SerialName("sku") val sku: String? = null,
    @SerialName("name") val name: String? = null,
    @SerialName("quantity") val quantity: Int? = null,
)
```

Every response field nullable, `= null`, explicit `@SerialName`. Enums arrive as `String?`.
Request DTOs (for POST/PUT) may be non-null. Done when the DTO round-trips the sample JSON in a test.

### 2. Domain model — `orders/domain/Order.kt`

```kotlin
data class Order(
    val id: String,
    val status: OrderStatus,
    val total: Money,
    val placedAtEpochMillis: Long,
    val items: List<OrderItem>,
)

data class Money(val amountMinor: Long, val currency: String)
data class OrderItem(val sku: String, val name: String, val quantity: Int)
enum class OrderStatus { Pending, Shipped, Delivered, Cancelled, Unknown }
```

Plain, non-null, no annotations. Money as minor units plus currency, never `Double`.

### 3. Mapper — `orders/data/OrderMappers.kt`

```kotlin
internal fun OrderDto.toDomainOrNull(): Order? {
    val id = id?.takeIf { it.isNotBlank() } ?: return null
    val amount = totalMinor ?: return null            // never default money to 0
    val currency = currency?.takeIf { it.length == 3 } ?: return null
    return Order(
        id = id,
        status = status.toOrderStatus(),
        total = Money(amountMinor = amount, currency = currency.uppercase()),
        placedAtEpochMillis = placedAtEpochMillis ?: 0L,
        items = items.orEmpty().mapNotNull { it.toDomainOrNull() },
    )
}

internal fun OrderItemDto.toDomainOrNull(): OrderItem? {
    val sku = sku?.takeIf { it.isNotBlank() } ?: return null
    val quantity = quantity?.takeIf { it > 0 } ?: return null
    return OrderItem(sku = sku, name = name.orEmpty(), quantity = quantity)
}

private fun String?.toOrderStatus(): OrderStatus = when (this?.lowercase()) {
    "pending" -> OrderStatus.Pending
    "shipped" -> OrderStatus.Shipped
    "delivered" -> OrderStatus.Delivered
    "cancelled" -> OrderStatus.Cancelled
    else -> OrderStatus.Unknown                       // new server values must not crash old apps
}
```

List each field as **required** (drop or fail) or **cosmetic** (fall back). Each rule gets a test.

### 4. API service — `orders/data/remote/OrdersApi.kt`

```kotlin
interface OrdersApi {
    suspend fun getOrder(orderId: String): OrderDto
}

internal class KtorOrdersApi(private val client: HttpClient) : OrdersApi {
    override suspend fun getOrder(orderId: String): OrderDto =
        client.get("orders/${orderId.encodeURLPathPart()}").body()
}
```

- Relative path, no leading `/` — it resolves against the client's base URL.
- **Encode path parameters.** `encodeURLPathPart()` (from `io.ktor.http`) escapes `/`, `?` and `#`;
  raw interpolation lets an id like `../admin` or `a?b=c` change the request.
- No `try`/`catch`, no mapping, no headers the shared client already adds.

### 5. Repository — `orders/domain/OrdersRepository.kt` + `orders/data/OrdersRepositoryImpl.kt`

```kotlin
interface OrdersRepository {
    suspend fun getOrder(orderId: String): ApiResult<Order>
}

class OrdersRepositoryImpl(
    private val ordersApi: OrdersApi,
    private val dispatchers: DispatcherProvider,
) : OrdersRepository {

    override suspend fun getOrder(orderId: String): ApiResult<Order> =
        safeApiCall(dispatchers.default) {
            ordersApi.getOrder(orderId).toDomainOrNull()
                ?: throw SerializationException("Order response is missing required fields")
        }
}
```

The error boundary maps HTTP status, transport and parse failures to `DataError` and rethrows
cancellation. An order missing required fields becomes `DataError.Serialization`, not a crash and
not a half-empty screen.

### 6. Use case — only if the project uses them

```kotlin
// orders/domain/GetOrderUseCase.kt
class GetOrderUseCase(private val ordersRepository: OrdersRepository) {
    suspend operator fun invoke(orderId: String): ApiResult<Order> {
        if (orderId.isBlank()) return ApiResult.Failure(DataError.Validation(serverMessage = null))
        return ordersRepository.getOrder(orderId)
    }
}
```

If the project's ViewModels call repositories directly, skip this file — a pass-through use case
adds a layer and tests nothing.

### 7. DI — `orders/di/OrdersModule.kt`

```kotlin
val ordersModule = module {
    single<OrdersApi> { KtorOrdersApi(client = get(named("authenticated"))) }
    single<OrdersRepository> { OrdersRepositoryImpl(ordersApi = get(), dispatchers = get()) }
    factoryOf(::GetOrderUseCase)
}
```

Add `ordersModule` to the app's module list (or the feature aggregator's `includes(...)`). Use the
plain client for endpoints that must not carry a token. Done when the DI verification test passes
(see **kmp-koin-di**) or the app starts and resolves the screen's ViewModel.

### 8. Tests — `commonTest/.../orders/`

Write these four, using the templates in [references/test-templates.md](references/test-templates.md):

| File | Covers |
|---|---|
| `OrderMapperTest` | every required-field drop, every fallback, unknown enum value |
| `KtorOrdersApiTest` | method, encoded path, query, headers, body; parses the sample JSON through the real client |
| `OrdersRepositoryImplTest` | success; 404 → `NotFound`; 401 → `Unauthorized`; malformed body → `Serialization`; offline → `NoConnection` |
| `FakeOrdersRepository` | a fake for ViewModel and use-case tests (not a test itself) |

Name tests `should_<expected>_when_<condition>` unless the project uses another convention.

### 9. Run the checks in **Verify**.

## Variations

| Need | Do this |
|---|---|
| Query parameters | `client.get("orders") { parameter("status", status) }` — a `null` value is skipped |
| Repeated query key | `client.get("orders") { url { parameters.appendAll("tag", tags) } }` |
| POST with JSON body | `client.post("orders") { contentType(ContentType.Application.Json); setBody(CreateOrderRequest(...)) }` |
| PATCH (partial update) | Request DTO with only the changed fields. With `explicitNulls = false` a `null` is **omitted**, so "clear this field" needs an explicit design (a `JsonObject` body or a dedicated flag) |
| 204 No Content | `client.delete("orders/${id.encodeURLPathPart()}")` and return `Unit`; do not call `.body()` |
| Pagination | DTO carries `next_cursor`; domain returns `Page<Order>(items, nextCursor)`; the ViewModel owns "load more" |
| Multipart upload | `client.submitFormWithBinaryData(url = "uploads", formData = formData { append("file", bytes, Headers.build { append(HttpHeaders.ContentDisposition, "filename=\"receipt.jpg\"") }) }) { timeout { requestTimeoutMillis = 120_000 } }` |
| Pre-signed upload URL (third-party host) | Absolute URL through a client **without** the bearer provider, or a bearer config whose `sendWithoutRequest` excludes that host |
| Retry-safe create | If the backend supports it, send a client-generated idempotency key header so a retried POST does not create a duplicate |
| Response wrapped in an envelope | `{"data": {...}}` → an `EnvelopeDto<T>(@SerialName("data") val data: T? = null)`; unwrap in the mapper |

## Quick reference — files for `GET orders/{orderId}`

| Layer | File (commonMain) | Contains |
|---|---|---|
| DTO | `orders/data/remote/dto/OrderDto.kt` | `OrderDto`, `OrderItemDto` |
| Domain | `orders/domain/Order.kt` | `Order`, `Money`, `OrderItem`, `OrderStatus` |
| Mapper | `orders/data/OrderMappers.kt` | `toDomainOrNull()` |
| API | `orders/data/remote/OrdersApi.kt` | interface + `KtorOrdersApi` |
| Repository | `orders/domain/OrdersRepository.kt`, `orders/data/OrdersRepositoryImpl.kt` | `ApiResult<Order>` |
| Use case | `orders/domain/GetOrderUseCase.kt` | only if the project uses them |
| DI | `orders/di/OrdersModule.kt` | bindings, added to the app module list |
| Tests | `commonTest/.../orders/*Test.kt` | mapper, API, repository, fake repository |

## Verify

Report each check as `PASS`, `FAIL` or `NOT RUN` (with the reason). Do not report a check you did
not run. Read `settings.gradle.kts` for the real module name; the Android host-test task is
`testDebugUnitTest` with `com.android.library` and `testAndroidHostTest` with
`com.android.kotlin.multiplatform.library`.

```bash
./gradlew :shared:testDebugUnitTest --tests "com.example.app.orders.*"     # fast JVM loop
./gradlew :shared:iosSimulatorArm64Test --tests "com.example.app.orders.*" # Kotlin/Native
./gradlew :shared:allTests                                                 # everything before you finish
./gradlew :composeApp:assembleDebug                                        # app still builds
```

Static checks (adjust `shared/src/commonMain` to the module you changed; review every hit):

```bash
grep -rnE "val [A-Za-z0-9_]+: [^?=]+(,|$)" --include=*Dto.kt shared/src/commonMain           # non-null DTO fields
grep -rnE 'client\.(get|post|put|patch|delete)\("[^"]*\$' --include=*.kt shared/src/commonMain | grep -v encodeURLPathPart   # unencoded path params
grep -rn "HttpClient(" --include=*.kt shared/src/commonMain                                   # clients outside the network module
```

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| DTO fields copied as non-null from the sample | The sample had every field; production data does not | Nullable, `= null`, decide in the mapper |
| Money or quantity defaulted to `0` | A missing total renders as "free" and may be acted on | Treat as required: drop or fail |
| `"orders/$id"` | Ids containing `/`, `?` or `#` rewrite the request | `"orders/${id.encodeURLPathPart()}"` |
| Path starts with `/` | Drops the base path (`/v1/`), request hits the wrong URL, 404 | Relative path |
| New `HttpClient` or `install(...)` in the feature | No auth, no timeouts, no log redaction | Inject the shared client by qualifier |
| `try`/`catch` in the API class | Errors mapped in two places, differently | Only the repository's error boundary maps |
| Catching `Exception` without rethrowing `CancellationException` | Cancelled screens keep running and report fake failures | Use the project's error boundary helper |
| Pass-through use case in a project without use cases | Extra layer, extra DI, no behaviour | Follow the project's layering |
| Tests with their own `Json { }` or a hand-built client | Pass while production parsing fails | Build the test client with the production factory and `MockEngine` |
| Only the happy path tested | 404, 401 and malformed bodies ship untested | The four repository error tests are mandatory |
| Endpoint added but module not registered | `NoDefinitionFoundException` at runtime, only on the screen that needs it | Add the module to the app's list; run the DI verification test |

## Related skills

- **kmp-data-layer** — the architecture these steps implement: client, DTO rules, `ApiResult`, offline-first.
- **kmp-koin-di** — module registration and the DI verification test.
- **kmp-room-database** — caching the response locally.
- Ktor client testing: <https://ktor.io/docs/client-testing.html>
- Ktor requests (parameters, bodies, forms): <https://ktor.io/docs/client-requests.html>
