# Pitfalls at the Kotlin ↔ SwiftUI seam

Contents

1. State and events
2. Lifecycle and memory
3. Threading and concurrency
4. Errors and cancellation
5. Types and names
6. SwiftUI rendering — native components and the iOS 26 alert tint trap
7. Accessibility identifiers
8. Previews and tests

Each item: symptom → cause → fix.

## 1. State and events

- **Swift UI does not update after a Kotlin change.** `StateFlow` only emits when the new value is
  *not equal* to the old one. Mutating a list inside the state, or emitting an equal `data class`,
  emits nothing. Emit a new immutable value (`copy(notes = notes + note)`).
- **Intermediate states never reach Swift.** `StateFlow` is conflated: a slow collector sees only the
  latest value. That is correct for screen state and wrong for one-shot events.
- **Navigation / toast events lost or replayed.** One-shot events do not belong in `StateFlow`
  (replayed on resubscribe) nor in a `SharedFlow(replay = 0)` that Swift subscribes to late (lost).
  Use a `Channel(Channel.BUFFERED).receiveAsFlow()` collected in its own `.task`, or model the event
  as state the UI acknowledges ("consumed") with an action.
- **Stale value on first frame.** Initialise the Swift property from `state.value` (SKIE) before the
  `for await` loop starts, or the screen flashes a placeholder.
- **Huge state on every emission.** Each emission bridges the whole object graph to Swift on the
  main actor. Page long lists; keep emitted state small.
- **Dates.** Kotlin date types arrive as opaque objects. Expose epoch milliseconds (`Long`) or ISO
  strings from Kotlin and build `Date` in Swift.

## 2. Lifecycle and memory

- **Collection keeps running after the screen closes.** Started with `onAppear { Task { … } }` or
  stored in a long-lived object. Use `.task { }`; use `.task(id: input)` when observation depends on
  an input that can change.
- **Kotlin ViewModel keeps polling after pop.** On iOS nobody clears its `ViewModelStore`. Release
  it deterministically: a non-actor-isolated Swift handle whose `deinit` calls the Kotlin owner's
  `clear()`, or the coordinator when the route is popped.
- **Duplicate network calls on open.** The Swift model (and so the Kotlin ViewModel) was created in a
  view initializer that SwiftUI evaluated several times. Create it once.
- **`onAppear` work repeats.** `onAppear` / `.task` re-run on every navigation return and tab
  switch. Make the triggered Kotlin action idempotent, or gate it in Kotlin state.
- **Kotlin objects are not freed when Swift lets go.** Kotlin memory is garbage-collected; Swift
  releasing the last reference only makes the object collectable. Never rely on Kotlin-side
  finalization for cleanup — call an explicit `close()` / `clear()`.
- **Retain cycles through callbacks.** A Swift closure handed to Kotlin that captures `self` strongly,
  while `self` holds the Kotlin object, keeps both alive. Capture `[weak self]` and close Kotlin
  subscriptions.

## 3. Threading and concurrency

- **"Publishing changes from background threads" or random UI glitches.** A Kotlin callback (not
  SKIE) arrived on a background dispatcher and wrote Swift UI state. Mark the model `@MainActor`
  and hop before writing, or collect on `Dispatchers.Main` in Kotlin.
- **Main-thread freeze.** A non-`suspend` Kotlin function doing I/O or heavy work called from the
  main actor blocks the UI. Make it `suspend` and move work off main in Kotlin with `withContext`.
- **Deadlock.** `runBlocking` used in Kotlin to give Swift a synchronous API, called on the main
  thread, while the inner work dispatches to `Dispatchers.Main`. Never offer synchronous wrappers
  over coroutine code; expose `suspend` (with SKIE) or a callback.
- **Swift 6 "non-Sendable type" errors on every Kotlin type.** Kotlin classes are imported without
  Sendable annotations. Use `@preconcurrency import SharedKit` and confine Kotlin objects to the
  `@MainActor` model; do not blanket-add `@unchecked Sendable` extensions.
- **`suspend` call crashes or hangs when called off-main without SKIE.** The default export
  restricts the thread that may start a `suspend` call. SKIE lifts it; otherwise call from the main
  thread or set `kotlin.native.binary.objcExportSuspendFunctionLaunchThreadRestriction=none` in
  `gradle.properties`.

## 4. Errors and cancellation

- **App terminates with "doesn't have or inherit @Throws annotation".** A Kotlin exception crossed
  into Swift from a function without a matching `@Throws`. Catch in Kotlin and return a result/error
  state, or declare `@Throws(…, CancellationException::class)`.
- **Kotlin work continues after the Swift Task is cancelled.** Cancellation arrives in Kotlin as a
  `CancellationException`. Code that does `catch (e: Exception)` around `suspend` calls swallows it.
  Rethrow `CancellationException`, or catch narrower types. Avoid `runCatching` around `suspend`
  calls for the same reason.
- **Swift `catch` never fires.** The error was converted to a UI state in Kotlin (good) and Swift is
  still waiting for a throw (stale code). Pick one error channel per API.
- **Reading the Kotlin exception in Swift.** A caught `NSError` from Kotlin carries the original
  exception; prefer mapping to domain error codes in Kotlin rather than parsing messages in Swift.

## 5. Types and names

- **Swift casts break after a framework update.** Bridged names (prefixes, nested-class
  concatenation, SKIE helpers) can change between Kotlin/SKIE versions or when an `export` is added
  or removed. Rebuild and fix casts whenever the framework version moves; keep casts in one adapter
  file.
- **Two Kotlin frameworks in one app.** Each embeds its own Kotlin runtime and its own copies of
  shared types: `AKit.KotlinThrowable` is not `BKit.KotlinThrowable`, and a `Note` from one cannot be
  passed to the other. Ship one umbrella framework (see `kmp-xcframework-distribution`).
- **`Int` arithmetic surprises.** Kotlin `Int` is Swift `Int32`. Convert explicitly at the boundary;
  prefer `Long` for counts that can grow.
- **`switch` over a Kotlin enum needs `default`** without SKIE — so a new Kotlin case compiles and
  silently takes the default branch. Use SKIE or add an exhaustiveness test in Kotlin.

## 6. SwiftUI rendering — native components and the iOS 26 alert tint trap

**Use system components.** `.alert`, `.confirmationDialog`, `.sheet`, `.fullScreenCover`,
`NavigationStack` with the real navigation bar (`.navigationTitle`, `.toolbar`). Hand-rolled dim
overlays, `HStack` "toolbars" with a fake back chip, and custom modal containers lose VoiceOver
focus handling, keyboard and Dynamic Type behaviour, and system gestures. Build the visual parts
from the app's SwiftUI design system; never inline raw colours, fonts or spacing.

**The iOS 26 filled-alert contrast trap** (observed on iOS 26 with Xcode 26):

- *Symptom:* the primary button of a native alert shows a filled capsule whose label is nearly
  invisible.
- *Cause:* the app sets a global `.tint(brandColor)` near the root (often inside a design-system
  theme wrapper). On iOS 26 the alert's default action renders as a capsule filled with the ambient
  tint, and iOS chooses the label colour automatically by contrast. With a mid-lightness brand colour
  (a typical "blue-500"), iOS can pick a dark label that blends into the fill. There is no API to set
  that label colour on a native alert.
- *It bites only when all three hold:*
  1. the modern `.alert(_:isPresented:actions:message:)` API (the legacy `Alert(...)` struct with
     `primaryButton:` renders the classic style and was not affected);
  2. a filled default action: a button with no role, `role: .confirm`, or
     `.keyboardShortcut(.defaultAction)`, or a lone non-cancel button that iOS promotes. Alerts whose
     emphasised button is `.destructive`, cancel-only alerts, and `.confirmationDialog` action
     sheets were not affected;
  3. the ambient tint at the alert is that light brand colour. A screen that already sets a dark
     tint renders a readable button.
- *Fixes, in order of preference:* use `.destructive` / `.cancel` where that is the true meaning;
  reset the tint for the alert with `.tint(nil)` so iOS uses the system accent; or set a darker
  brand token as the tint. If a pixel-exact brand-coloured fill with a guaranteed white label is a
  hard requirement, only a design-system component (not a native alert) can promise it.
- *Blast radius of `.tint(nil)`:* the modifier applies to the whole view it is chained on. Placed on
  a screen's root, it was observed to also reset that screen's navigation-bar / toolbar tint and any
  `.borderedProminent` button that relied on the inherited brand tint. Do not add it on screens that
  set their own tint on purpose; re-assert the brand tint explicitly on prominent buttons inside the
  subtree; or attach the alert (and the override) to a smaller subview and confirm the alert still
  picks it up.
- *Verify* on an iOS 26 simulator or device, in light and dark appearance, for every native alert
  with a filled default action. Previews are not a reliable check.

## 7. Accessibility identifiers

- Every interactive control gets a stable `.accessibilityIdentifier(...)` from one namespace
  (`AccessibilityID.Notes.addButton`) so UI tests and QA automation do not break on copy changes.
- Identifiers are locators; `accessibilityLabel` is VoiceOver prose. Set both when needed; never the
  same string for both.
- Rows use a stable backend id (`AccessibilityID.Notes.row(note.id)`), never a `ForEach` index.
- Alert and confirmation-dialog buttons need identifiers too.

## 8. Previews and tests

- **Previews crash or hang.** The preview booted DI or a real Kotlin ViewModel that hits the network
  or database. Feed previews a Swift fake through a protocol boundary.
- **Swift tests are flaky.** They wait on real Kotlin coroutines with `Task.sleep`. Use finite fake
  streams so `await model.observe()` returns, and test Kotlin behaviour in Kotlin `commonTest`.
- **Mocking a Kotlin class in Swift fails.** Kotlin classes are final in Swift. Mock at a Swift
  protocol, or depend on a Kotlin interface.
