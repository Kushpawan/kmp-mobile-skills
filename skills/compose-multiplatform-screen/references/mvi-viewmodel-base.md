# A minimal MVI ViewModel base for Compose Multiplatform

Use this only when the project has **no** presentation base class yet. If it has one, use it — even
if it differs from this — and read the "Auditing an existing base" checklist at the end instead.

Contents

1. [Dependencies](#1-dependencies)
2. [`MviViewModel<State, Effect>`](#2-mviviewmodelstate-effect)
3. [`CollectEffects` — the effect handler helper](#3-collecteffects--the-effect-handler-helper)
4. [Optional `DispatcherProvider`](#4-optional-dispatcherprovider)
5. [Why a Channel, and when to use state instead](#5-why-a-channel-and-when-to-use-state-instead)
6. [Auditing an existing base](#6-auditing-an-existing-base)

## 1. Dependencies

`gradle/libs.versions.toml` (pick the versions listed for your Compose Multiplatform release in the
"Libraries" table of the Compose Multiplatform CHANGELOG):

```toml
[versions]
jetbrains-lifecycle = "<version>"
kotlinx-coroutines = "<version>"

[libraries]
jetbrains-lifecycle-viewmodel = { module = "org.jetbrains.androidx.lifecycle:lifecycle-viewmodel", version.ref = "jetbrains-lifecycle" }
jetbrains-lifecycle-viewmodel-compose = { module = "org.jetbrains.androidx.lifecycle:lifecycle-viewmodel-compose", version.ref = "jetbrains-lifecycle" }
jetbrains-lifecycle-runtime-compose = { module = "org.jetbrains.androidx.lifecycle:lifecycle-runtime-compose", version.ref = "jetbrains-lifecycle" }
kotlinx-coroutines-test = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-test", version.ref = "kotlinx-coroutines" }
```

`build.gradle.kts` of the module:

```kotlin
kotlin {
    sourceSets {
        commonMain.dependencies {
            implementation(libs.jetbrains.lifecycle.viewmodel)
            implementation(libs.jetbrains.lifecycle.viewmodel.compose)
            implementation(libs.jetbrains.lifecycle.runtime.compose)
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
            implementation(libs.kotlinx.coroutines.test)
        }
    }
}
```

If the base must live in a module **without Compose** (shared logic consumed by SwiftUI), keep
`MviViewModel` there with only `lifecycle-viewmodel`, and put `CollectEffects` in the Compose
module.

## 2. `MviViewModel<State, Effect>`

```kotlin
package com.example.app.core.presentation

import androidx.lifecycle.ViewModel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update

/**
 * State + one-shot effects. Subclasses expose a single `fun onAction(action: XAction)`.
 *
 * The initial state is a constructor argument on purpose: calling an abstract
 * `initialState()` from this constructor would run before the subclass's own
 * properties are initialised.
 */
abstract class MviViewModel<State : Any, Effect : Any>(initialState: State) : ViewModel() {

    private val _state = MutableStateFlow(initialState)
    val state: StateFlow<State> = _state.asStateFlow()

    // BUFFERED (64): effects sent while nobody collects (init, rotation, app in background)
    // wait here and are delivered once, to one collector.
    private val _effects = Channel<Effect>(capacity = Channel.BUFFERED)
    val effects: Flow<Effect> = _effects.receiveAsFlow()

    protected val currentState: State get() = _state.value

    /** Atomic read-modify-write; safe to call from any coroutine or thread. */
    protected fun updateState(reducer: State.() -> State) {
        _state.update { current -> current.reducer() }
    }

    /** Non-suspending. Preserves order. Drops only if 64 effects are already pending. */
    protected fun sendEffect(effect: Effect) {
        _effects.trySend(effect)
    }
}
```

Swift consumers: `state` is a `StateFlow` and `effects` a `Flow`; expose them through SKIE or a
small wrapper if the same ViewModel drives a SwiftUI view.

## 3. `CollectEffects` — the effect handler helper

Lives in the Compose module (`commonMain`).

```kotlin
package com.example.app.core.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.withContext

/**
 * The only place a screen executes one-shot effects (navigation, snackbars).
 *
 * - Collects only while the host is at least STARTED, so effects sent while the
 *   screen is stopped stay buffered in the ViewModel's Channel instead of being
 *   consumed off-screen.
 * - Main.immediate runs the handler in the same frame the effect is received,
 *   which narrows the window in which a lifecycle change could cancel the
 *   collector between receiving and handling an effect.
 */
@Composable
fun <E> CollectEffects(
    effects: Flow<E>,
    onEffect: suspend (E) -> Unit,
) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val currentOnEffect by rememberUpdatedState(onEffect)
    LaunchedEffect(effects, lifecycleOwner) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
            withContext(Dispatchers.Main.immediate) {
                effects.collect { effect -> currentOnEffect(effect) }
            }
        }
    }
}
```

`rememberUpdatedState` keeps the latest navigation lambdas without restarting the collector when
the caller recomposes with new lambda instances.

## 4. Optional `DispatcherProvider`

`viewModelScope` already runs on `Dispatchers.Main.immediate`. If repositories are main-safe (they
switch to IO themselves), the ViewModel needs no dispatcher. Inject one only when the ViewModel
itself does CPU-heavy work:

```kotlin
interface DispatcherProvider {
    val main: CoroutineDispatcher
    val default: CoroutineDispatcher
    val io: CoroutineDispatcher
}

object DefaultDispatcherProvider : DispatcherProvider {
    override val main: CoroutineDispatcher = Dispatchers.Main
    override val default: CoroutineDispatcher = Dispatchers.Default
    override val io: CoroutineDispatcher = Dispatchers.IO   // commonMain: import kotlinx.coroutines.IO
}

class TestDispatcherProvider(dispatcher: CoroutineDispatcher) : DispatcherProvider {
    override val main = dispatcher
    override val default = dispatcher
    override val io = dispatcher
}
```

In tests, pass `TestDispatcherProvider(StandardTestDispatcher(testScheduler))` so every coroutine
runs on the test scheduler and `advanceUntilIdle()` drains it.

## 5. Why a Channel, and when to use state instead

| Transport | What happens to an effect sent with no collector | Risk |
|---|---|---|
| `Channel(BUFFERED).receiveAsFlow()` | Buffered; delivered to the next collector, once | A second collector would split effects between them — keep exactly one |
| `MutableSharedFlow()` | Dropped | Navigation after a save that finished during rotation never happens |
| `MutableSharedFlow(extraBufferCapacity = n)` | Still dropped (buffer only applies to slow subscribers) | Same as above |
| `MutableSharedFlow(replay = 1)` | Replayed to **every** new subscriber | Double navigation / repeated snackbar after rotation |

Android's architecture guidance prefers modelling events as state (`UiState.pendingMessage` plus an
`Action.MessageShown` acknowledgement). That is the safest option when losing an event is
unacceptable, because state survives cancellation and configuration change. The Channel approach
is a pragmatic default for navigation and transient messages; choose per event, and do not mix
both styles for the same kind of event in one screen.

## 6. Auditing an existing base

When the project already has a base class, check it for these before relying on it, and report
findings rather than silently replacing it:

- Effects backed by `MutableSharedFlow()` with no replay: effects posted from `init` or while the
  screen is stopped are lost.
- State updates via `emit(reducer(value))` or `value = reducer(value)` inside separately launched
  coroutines: not atomic; concurrent updates can overwrite each other. `MutableStateFlow.update {}`
  is atomic.
- An abstract initial-state function invoked from the base constructor: runs before the
  subclass's properties are initialised.
- Every `updateState` launching a new coroutine: updates become asynchronous and tests must
  `advanceUntilIdle()` even for pure reducers.
- Hard-coded `Dispatchers.IO` / `Dispatchers.Main` in the base: tests need an injectable dispatcher
  or `Dispatchers.setMain`.

Fixing a shared base affects every screen; propose it as a separate change with its own tests.
