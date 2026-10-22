# Memory growth and leaks in KMP apps

Contents

1. Confirm it is growth, not a high plateau
2. Android: heap dumps and LeakCanary
3. iOS: Allocations, Leaks and the Memory Graph
4. How Kotlin/Native memory interacts with Swift
5. Cross-runtime retain cycles
6. Collections started from Swift that nothing cancels
7. Interop objects in long loops
8. Proving the fix

## 1. Confirm it is growth, not a high plateau

Repeat the suspect flow (open and close the screen, scroll the list, run the sync) N times and
measure after each repetition. A leak grows roughly linearly with N; a cache or a GC that has not
run yet plateaus. On iOS, memory released by Kotlin is reclaimed only when its GC runs, so take
measurements after a pause, and compare several repetitions rather than one before/after pair.

## 2. Android: heap dumps and LeakCanary

- Heap dump after warm-up and after N repetitions (Android Studio Memory profiler, or
  `adb shell am dumpheap <package> <path>`); compare instance counts of your own classes.
- LeakCanary (debug builds) reports retained `Activity`, `Fragment`, `View` and ViewModel
  instances with the reference chain that keeps them.
- Usual KMP-on-Android causes: a ViewModel or singleton holding an `Activity` / `View` / `Context`
  that is not the application context; a coroutine launched in a scope that outlives the screen
  (`GlobalScope`, an application-level scope) collecting a flow and capturing the screen; a DI
  singleton that stores a listener registered by a screen.

Deeper analysis: [android/skills `profilers/android-profiler`](https://github.com/android/skills/tree/main/profilers/android-profiler).

## 3. iOS: Allocations, Leaks and the Memory Graph

Profile on a device with a release-configured build.

- **Allocations** with **Mark Generation** between repetitions: each generation lists what was
  allocated and is still alive. Persistent growth per generation is the leak. Kotlin allocation
  sites appear as `kfun:` frames in the call tree when symbols are available.
- **Leaks** finds unreachable ObjC/Swift cycles. A cycle that runs through Kotlin may not be
  reported as a leak, because the Kotlin side looks like a live reference — absence of a Leaks
  report does not clear the code.
- **Xcode Memory Graph** (Debug Memory Graph while running) shows who references a Swift object.
  Look for Kotlin-exported types or Kotlin blocks among the referrers.
- The Kotlin/Native heap is managed by its own allocator. In the **VM Tracker** instrument it shows
  as a region with its mmap tag (246 by default, configurable with `kotlin.native.binary.mmapTag`).

Deeper analysis: [CharlesWiltgen/Axiom `axiom-audit-memory`](https://github.com/CharlesWiltgen/Axiom/tree/main/axiom-codex/skills/axiom-audit-memory)
for the Swift side.

## 4. How Kotlin/Native memory interacts with Swift

From the Kotlin documentation on ARC integration:

- Kotlin uses a tracing GC; Swift and Objective-C use reference counting.
- **Cycles of Kotlin objects are collected. Cycles that include at least one Swift/ObjC object are
  not** — and cannot be broken from the Kotlin side. No tool detects them automatically; the
  documented remedy is weak or unowned references.
- Swift/ObjC objects passed into Kotlin are released only during a Kotlin GC, and their `deinit`
  runs after that cycle — so a `deinit` log line arriving late is expected, not proof of a leak.
- `deinit` of those objects runs on the main thread if they were passed to Kotlin on the main
  thread; otherwise (or if the main queue is not being processed) on a GC thread.
- In GC logs (`-Xruntime-logs=gc=info`), a number of stable references in the root set that keeps
  growing suggests Swift/ObjC objects are not being freed.

## 5. Cross-runtime retain cycles

The common shape: a Kotlin object stores a Swift closure; the closure captures `self`; `self`
holds the Kotlin object. Neither side can free the cycle, so `deinit` never runs — and if the
subscription was meant to be cancelled in `deinit`, it never is.

```kotlin
// commonMain — a Swift-facing observation API that hands back an explicit handle.
fun interface ObservationHandle {
    fun cancel()
}

class NotesStateObserver(
    private val viewModel: NotesViewModel,
    private val scope: CoroutineScope,
) {
    fun observe(onState: (NotesUiState) -> Unit): ObservationHandle {
        val job = scope.launch(Dispatchers.Main) {
            viewModel.state.collect { onState(it) }
        }
        return ObservationHandle { job.cancel() }
    }
}
```

```swift
// iOS app — updates arrive on the main thread because the Kotlin side collects on Dispatchers.Main.
final class NotesScreenModel: ObservableObject {
    @Published private(set) var state: NotesUiState?
    private var handle: ObservationHandle?

    init(observer: NotesStateObserver) {
        // [weak self]: Kotlin holds this closure. A strong capture forms a Kotlin<->Swift cycle
        // that neither runtime can collect, so deinit (and cancel) would never run.
        handle = observer.observe { [weak self] state in
            self?.state = state
        }
    }

    deinit { handle?.cancel() }
}
```

Check every closure passed into Kotlin that Kotlin keeps (listeners, callbacks, flow collectors):
it should capture `self` weakly, and the subscription should have an explicit end.

## 6. Collections started from Swift that nothing cancels

A collection launched on behalf of a Swift screen in a scope that outlives the screen keeps
running after the screen is gone: the closure, everything it captures, and the upstream work all
stay alive.

- Return a handle (section 5) and cancel it when the screen goes away (`deinit`, `onDisappear`).
- With SKIE, flows are Swift `AsyncSequence`s and cancellation is two-way; iterate them inside a
  SwiftUI `.task {}` so the task — and the collection — ends when the view disappears.
  KMP-NativeCoroutines offers similar Swift wrappers.
- Shared ViewModels used directly from Swift: their `viewModelScope` is cancelled only when the
  ViewModel is cleared. On Android the framework does that; on iOS make sure something you own
  clears it (for example a `ViewModelStore` you manage per screen), or its coroutines live until
  the process ends.

## 7. Interop objects in long loops

Objective-C objects created through interop in a long-running Kotlin loop (for example per item
while importing thousands of records) can stay alive until an autorelease pool drains. Wrap the
loop body:

```kotlin
// iosMain
fun importAll(items: List<RawItem>) {
    items.forEach { item ->
        autoreleasepool {
            importOne(item)   // makes Foundation / UIKit calls
        }
    }
}
```

## 8. Proving the fix

Repeat the same flow the same N times on the same device and build. Report memory after each
repetition before and after, and — for a retain-cycle fix — a `deinit` log line (or Memory Graph)
showing the Swift object is released after the screen closes and a Kotlin GC has run.
