# Test templates for one endpoint

Templates for `GET orders/{orderId}`. They assume the project's client factory
(`createHttpClient(engine, config, httpLogger)`), `ApiResult` / `DataError`, and `kotlin.test` +
`kotlinx-coroutines-test`. Replace those names with the project's own.

## Contents

1. [Shared test helpers](#1-shared-test-helpers)
2. [Mapper tests](#2-mapper-tests)
3. [API tests with MockEngine](#3-api-tests-with-mockengine)
4. [Repository tests](#4-repository-tests)
5. [Fake repository for ViewModel tests](#5-fake-repository-for-viewmodel-tests)

## 1. Shared test helpers

```kotlin
// commonTest — orders/OrdersTestFixtures.kt
internal val jsonHeaders = headersOf(HttpHeaders.ContentType, ContentType.Application.Json.toString())

internal val testNetworkConfig = NetworkConfig(
    baseUrl = "https://api.example.com/v1/",
    isDebug = false,
    userAgent = "test",
)

/** The production factory over a MockEngine: same Json, base URL, expectSuccess and plugins. */
internal fun mockClient(handler: MockRequestHandler): HttpClient =
    createHttpClient(engine = MockEngine(handler), config = testNetworkConfig, httpLogger = {})

/** Paste the response sample from the API docs here, unchanged. */
internal const val ORDER_JSON = """
{
  "id": "o-1",
  "status": "shipped",
  "total_minor": 4599,
  "currency": "eur",
  "placed_at": 1767225600000,
  "items": [
    { "sku": "A-1", "name": "Mug", "quantity": 2 },
    { "sku": "", "name": "broken", "quantity": 1 }
  ],
  "field_added_later": true
}
"""
```

## 2. Mapper tests

```kotlin
// commonTest — orders/OrderMapperTest.kt
class OrderMapperTest {

    private val valid = OrderDto(id = "o-1", status = "pending", totalMinor = 100, currency = "usd")

    @Test
    fun should_mapAllFields_when_dtoIsComplete() {
        val order = valid.copy(items = listOf(OrderItemDto(sku = "A-1", name = "Mug", quantity = 2))).toDomainOrNull()

        assertEquals(
            Order(
                id = "o-1",
                status = OrderStatus.Pending,
                total = Money(amountMinor = 100, currency = "USD"),
                placedAtEpochMillis = 0L,
                items = listOf(OrderItem(sku = "A-1", name = "Mug", quantity = 2)),
            ),
            order,
        )
    }

    @Test
    fun should_dropOrder_when_totalIsMissing() {
        assertNull(valid.copy(totalMinor = null).toDomainOrNull())
    }

    @Test
    fun should_dropOrder_when_idIsBlank() {
        assertNull(valid.copy(id = " ").toDomainOrNull())
    }

    @Test
    fun should_mapUnknownStatus_when_serverSendsNewValue() {
        assertEquals(OrderStatus.Unknown, valid.copy(status = "on_hold").toDomainOrNull()?.status)
    }

    @Test
    fun should_dropItem_when_skuMissingOrQuantityNotPositive() {
        val items = listOf(
            OrderItemDto(sku = null, quantity = 1),
            OrderItemDto(sku = "B", quantity = 0),
            OrderItemDto(sku = "C", quantity = 1),
        )

        assertEquals(listOf("C"), valid.copy(items = items).toDomainOrNull()?.items?.map { it.sku })
    }
}
```

## 3. API tests with MockEngine

```kotlin
// commonTest — orders/KtorOrdersApiTest.kt
class KtorOrdersApiTest {

    @Test
    fun should_getEncodedOrderPath_when_idHasReservedCharacters() = runTest {
        var captured: HttpRequestData? = null
        val api = KtorOrdersApi(mockClient { request ->
            captured = request
            respond(ORDER_JSON, headers = jsonHeaders)
        })

        api.getOrder("a/b?c")

        assertEquals(HttpMethod.Get, captured?.method)
        assertEquals("/v1/orders/a%2Fb%3Fc", captured?.url?.encodedPath)
    }

    @Test
    fun should_parseSample_when_responseHasUnknownFields() = runTest {
        val api = KtorOrdersApi(mockClient { respond(ORDER_JSON, headers = jsonHeaders) })

        val dto = api.getOrder("o-1")

        assertEquals("o-1", dto.id)
        assertEquals(2, dto.items?.size)
    }
}
```

For a POST, assert the body the server receives:

```kotlin
val sentBody = captured?.body?.toByteArray()?.decodeToString()   // io.ktor.client.engine.mock.toByteArray
assertEquals("""{"sku":"A-1","quantity":2}""", sentBody)
```

## 4. Repository tests

Run the repository over the real API class and a MockEngine, so status and parse errors are mapped
exactly as in production.

```kotlin
// commonTest — orders/OrdersRepositoryImplTest.kt
class OrdersRepositoryImplTest {

    private fun TestScope.repository(handler: MockRequestHandler): OrdersRepository {
        val dispatcher = StandardTestDispatcher(testScheduler)
        val dispatchers = object : DispatcherProvider {
            override val main = dispatcher
            override val io = dispatcher
            override val default = dispatcher
        }
        return OrdersRepositoryImpl(ordersApi = KtorOrdersApi(mockClient(handler)), dispatchers = dispatchers)
    }

    @Test
    fun should_returnOrder_when_serverReturnsValidOrder() = runTest {
        val result = repository { respond(ORDER_JSON, headers = jsonHeaders) }.getOrder("o-1")

        val order = assertIs<ApiResult.Success<Order>>(result).value
        assertEquals(Money(amountMinor = 4599, currency = "EUR"), order.total)
        assertEquals(1, order.items.size)                    // the blank-sku item was dropped
    }

    @Test
    fun should_returnNotFound_when_serverReturns404() = runTest {
        val result = repository { respondError(HttpStatusCode.NotFound) }.getOrder("missing")

        assertEquals(ApiResult.Failure(DataError.NotFound), result)
    }

    @Test
    fun should_returnUnauthorized_when_serverReturns401() = runTest {
        val result = repository { respondError(HttpStatusCode.Unauthorized) }.getOrder("o-1")

        assertEquals(ApiResult.Failure(DataError.Unauthorized), result)
    }

    @Test
    fun should_returnSerialization_when_requiredFieldMissing() = runTest {
        val result = repository { respond("""{"id":"o-1"}""", headers = jsonHeaders) }.getOrder("o-1")

        assertEquals(ApiResult.Failure(DataError.Serialization), result)
    }

    @Test
    fun should_returnNoConnection_when_networkFails() = runTest {
        val result = repository { throw IOException("offline") }.getOrder("o-1")

        assertEquals(ApiResult.Failure(DataError.NoConnection), result)
    }
}
```

`IOException` here is `kotlinx.io.IOException`, which is `java.io.IOException` on the JVM, so the
same test runs on Android host tests and the iOS simulator.

## 5. Fake repository for ViewModel tests

```kotlin
// commonTest — orders/FakeOrdersRepository.kt
class FakeOrdersRepository : OrdersRepository {
    var nextResult: ApiResult<Order> = ApiResult.Failure(DataError.NotFound)
    val requestedIds = mutableListOf<String>()

    override suspend fun getOrder(orderId: String): ApiResult<Order> {
        requestedIds += orderId
        return nextResult
    }
}
```

Hand-written fakes over mocking libraries: they compile for every target (mocking frameworks that
rely on JVM bytecode do not run on Kotlin/Native) and they fail loudly when the interface changes.
