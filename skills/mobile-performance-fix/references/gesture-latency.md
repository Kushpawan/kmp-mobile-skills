# Gesture latency with a background sync queue

Contents

1. The failure mode
2. The pattern
3. Worked example (orders)
4. What not to do
5. Measuring it
6. Tests

Applies to apps that write user actions to a local database and upload them through a background
sync queue (offline-first apps, field apps, anything with "pending" items). The example domain is
orders; the same shape fits notes, check-ins, form submissions and attachments.

## 1. The failure mode

A button tap shows a blocking progress indicator and then awaits a call that drains the **whole**
sync queue. The drain uploads every pending item — other records, photos, attachments — each with
its own network timeout, and if a background drain is already running it waits for that first.
The tap's latency now depends on backlog size and network quality, not on the user's own record.
Symptoms: "the button spins for a long time", worse after a period offline, worse on poor
connections, fine on a developer's fresh install.

An uncapped location fetch on the same path adds the platform's fix timeout — several seconds
indoors or with a cold GPS.

## 2. The pattern

1. **Write locally first** as `Pending`, in a transaction.
2. **Trigger** the queue — a non-suspending call that starts a drain in the queue's own scope, or
   records that another drain is needed if one is running. The caller does not wait for it.
3. **Wait, with a short bound, for this record only** — observe its row until its status leaves
   `Pending`, or the bound expires.
4. **Return either outcome as success.** `Pending` after the bound is a supported result, exactly
   like the offline case. The UI renders from the database stream and updates when the
   acknowledgement lands.
5. **Cap any location fetch** on the path with `withTimeoutOrNull`; location on the record is
   metadata. A decision that truly needs location (a geofence check, for example) happens
   explicitly before the gesture's work, with its own UX for "location unavailable".

Waiting for the whole queue is right where that is the purpose — an explicit "Sync now", or a
final submit that must not proceed until everything is uploaded. Show progress there.

Pick the bounds from the UX budget for the gesture. As a data point, one production app used 2 s
for the location fetch and 3 s for the acknowledgement wait.

## 3. Worked example (orders)

```kotlin
// commonMain
enum class SyncStatus { Pending, Synced, Failed }

interface SyncQueue {
    /** Starts a drain in the queue's own scope, or schedules a follow-up drain. Never suspends. */
    fun trigger()

    /** Uploads everything pending. For "Sync now" and flows that require a fully synced state. */
    suspend fun drainAll()
}

class PlaceOrderUseCase(
    private val orderDao: OrderDao,
    private val syncQueue: SyncQueue,
    private val locationProvider: LocationProvider,
) {
    suspend operator fun invoke(draft: OrderDraft): Order {
        // Metadata only: a slow or unavailable fix must not hold the button's progress indicator.
        val location = withTimeoutOrNull(LOCATION_TIMEOUT) { locationProvider.currentLocation() }

        val pending = draft.toEntity(location = location, status = SyncStatus.Pending)
        orderDao.insert(pending)

        // The queue uploads in its own scope and owns ordering between dependent records.
        syncQueue.trigger()

        // Bounded wait on this order's row only. Still Pending after the bound is a valid result.
        val acknowledged = withTimeoutOrNull(ACK_TIMEOUT) {
            orderDao.observe(pending.id).first { it != null && it.status != SyncStatus.Pending }
        }
        return (acknowledged ?: pending).toDomain()
    }
}

private val LOCATION_TIMEOUT = 2.seconds
private val ACK_TIMEOUT = 3.seconds
```

```kotlin
// commonMain — the ViewModel records local-ack latency; the list renders from the DAO stream.
class CheckoutViewModel(
    private val placeOrder: PlaceOrderUseCase,
    private val analytics: Analytics,
) : ViewModel() {
    private val _state = MutableStateFlow(CheckoutUiState())
    val state: StateFlow<CheckoutUiState> = _state.asStateFlow()

    fun onPlaceOrder(draft: OrderDraft) {
        viewModelScope.launch {
            val started = TimeSource.Monotonic.markNow()
            _state.update { it.copy(isPlacing = true) }
            val order = placeOrder(draft)
            _state.update { it.copy(isPlacing = false, placedOrderId = order.id) }
            // Local acknowledgement: tap -> the UI shows a saved (Pending or Synced) order.
            analytics.track("order_placed", mapOf("local_ack_ms" to started.elapsedNow().inWholeMilliseconds))
        }
    }
}
```

Record server-acknowledgement latency separately — for example when the queue marks the row
`Synced` — so the two numbers are never mixed.

## 4. What not to do

```kotlin
// Don't: the tap now waits for every queued upload, each with its own network timeout.
orderDao.insert(pending)
syncQueue.drainAll()

// Don't: cancelling a drain can abort an upload mid-request; the queue then has to recover it.
withTimeoutOrNull(3.seconds) { syncQueue.drainAll() }

// Don't: posting inline skips the queue, so this order can reach the server before an earlier
// record it depends on (for example one that references the previous record's id).
api.postOrder(pending.toDto())

// Don't: an unbounded fetch holds the indicator for the platform's whole fix timeout.
val location = locationProvider.currentLocation()
```

## 5. Measuring it

- **Before:** log timestamps through the project's logger at the tap and at the state change, over
  at least five runs, in three conditions: empty queue, a backlog (go offline, create several
  records with attachments, come back online), and a poor connection (Android emulator network
  throttling, or the iOS Network Link Conditioner).
- **After:** the same three conditions. Expected: local-ack latency roughly flat across them and
  within the bounds; server-ack latency unchanged or better.
- Report both numbers. An analytics event named "…latency" that used to span the drain will drop
  sharply after this change; document that it now measures local acknowledgement.

## 6. Tests

`runTest` uses virtual time, so the bounds can be tested without waiting.

```kotlin
class PlaceOrderUseCaseTest {

    @Test
    fun should_returnPendingOrder_when_serverDoesNotAcknowledgeInTime() = runTest {
        val dao = InMemoryOrderDao()
        val queue = FakeSyncQueue(onTrigger = { /* never acknowledges */ })
        val useCase = PlaceOrderUseCase(dao, queue, FakeLocationProvider(location = null))

        val order = useCase(OrderDraft(item = "Coffee beans"))

        assertEquals(SyncStatus.Pending, order.status)
        assertEquals(1, queue.triggerCount)
        assertEquals(0, queue.drainAllCount)            // the gesture never drains the queue
    }

    @Test
    fun should_returnWithoutLocation_when_locationFixIsSlow() = runTest {
        val dao = InMemoryOrderDao()
        val queue = FakeSyncQueue(onTrigger = { dao.markAllSynced() })
        val slowLocation = FakeLocationProvider(location = SampleLocation, delay = 30.seconds)
        val useCase = PlaceOrderUseCase(dao, queue, slowLocation)

        val order = useCase(OrderDraft(item = "Coffee beans"))

        assertNull(order.location)
        assertEquals(SyncStatus.Synced, order.status)
        assertTrue(testScheduler.currentTime <= 2_000)  // bounded by the location cap, not 30 s
    }
}
```

`InMemoryOrderDao` backs `observe(id)` with a `MutableStateFlow`, so status changes made by the
fake queue reach the use case's wait.
