# Back handling and returning results

Contents

1. [What already works](#1-what-already-works)
2. [Intercept back — Compose Multiplatform 1.10+](#2-intercept-back--compose-multiplatform-110)
3. [Intercept back — Compose Multiplatform 1.8 and 1.9](#3-intercept-back--compose-multiplatform-18-and-19)
4. [iOS swipe-back specifics](#4-ios-swipe-back-specifics)
5. [Returning a result](#5-returning-a-result)

## 1. What already works

`NavHost` translates each platform's back input into popping the back stack: Android system back
(button or predictive gesture), the iOS edge swipe, and Esc on desktop. Write a handler only to
**change** that behaviour, such as confirming before discarding unsaved changes.

## 2. Intercept back — Compose Multiplatform 1.10+

`gradle/libs.versions.toml` — use the Navigation Event version listed for your Compose
Multiplatform release in its CHANGELOG "Libraries" table:

```toml
[versions]
jetbrains-navigationevent = "<version>"

[libraries]
jetbrains-navigationevent-compose = { module = "org.jetbrains.androidx.navigationevent:navigationevent-compose", version.ref = "jetbrains-navigationevent" }
```

```kotlin
commonMain.dependencies { implementation(libs.jetbrains.navigationevent.compose) }
```

```kotlin
import androidx.navigationevent.NavigationEventInfo
import androidx.navigationevent.compose.NavigationBackHandler
import androidx.navigationevent.compose.rememberNavigationEventState

/** Describes this screen to the navigation-event system; no extra data needed here. */
private object NoteEditorBackInfo : NavigationEventInfo()

@Composable
fun UnsavedChangesBackHandler(hasUnsavedChanges: Boolean, onBackRequested: () -> Unit) {
    NavigationBackHandler(
        state = rememberNavigationEventState(currentInfo = NoteEditorBackInfo),
        isBackEnabled = hasUnsavedChanges,      // when false, back pops normally
        onBackCompleted = onBackRequested,      // send an Action; the ViewModel decides
    )
}
```

Call it from the stateful screen entry, next to the effect handler:

```kotlin
UnsavedChangesBackHandler(
    hasUnsavedChanges = state.hasUnsavedChanges,
    onBackRequested = { viewModel.onAction(NoteEditorAction.BackClicked) },
)
```

`NavigationBackHandler` also accepts `onBackCancelled` for predictive gestures the user abandons.

- Among enabled handlers, the one composed **last** is invoked, so a screen-level handler overrides
  `NavHost`'s own pop while it is enabled.
- Call it **unconditionally** and toggle `isBackEnabled`. Wrapping it in `if (...)` changes the
  composition order and can make a different handler win after recomposition.
- Give each handler its own `rememberNavigationEventState(...)`; recent library sources reject one
  state shared by two handlers.

## 3. Intercept back — Compose Multiplatform 1.8 and 1.9

Compose Multiplatform 1.8 added a multiplatform `BackHandler` / `PredictiveBackHandler`
(`org.jetbrains.compose.ui:ui-backhandler`, experimental API). Later releases deprecate them in
favour of the Navigation Event library above; follow the IDE's deprecation message when you upgrade.

```kotlin
@OptIn(ExperimentalComposeUiApi::class)
@Composable
fun UnsavedChangesBackHandler(hasUnsavedChanges: Boolean, onBackRequested: () -> Unit) {
    BackHandler(enabled = hasUnsavedChanges, onBack = onBackRequested)
}
```

Check the import the IDE offers for your version rather than copying one: the package of this API
is the part most likely to differ between releases.

## 4. iOS swipe-back specifics

- The swipe is enabled by default. To turn it off for the whole Compose hierarchy:

  ```kotlin
  fun MainViewController() = ComposeUIViewController(configure = { enableBackGesture = false }) { AppRoot() }
  ```

  Prefer an enabled back handler on the specific screen instead; users expect the swipe.
- Custom `enterTransition`/`exitTransition` on `NavHost` replace the default native-like swipe
  animation on iOS. Test the swipe on a device or simulator after changing transitions.
- Keep one owner of the back stack per screen hierarchy: if native iOS navigation pushes the Compose
  view controller, back from the Compose root belongs to the native stack, not to `NavHost`.

## 5. Returning a result

Pick the first option that fits.

**1. Through the data layer (preferred).** The editor saves; the list observes the repository's
`Flow` and updates itself. Nothing is passed through navigation, and the result also survives
process death.

**2. Graph-scoped shared ViewModel.** For multi-step flows (checkout, onboarding), scope one
ViewModel to the nested graph's back-stack entry; every step reads and writes it.

```kotlin
val graphEntry = remember(entry) { navController.getBackStackEntry<CheckoutGraph>() }
val checkoutViewModel: CheckoutViewModel = koinViewModel(viewModelStoreOwner = graphEntry)
```

**3. `SavedStateHandle` of the previous entry** — small primitive results only (a picked id, a
boolean):

```kotlin
// Sender (e.g. a tag picker)
navController.previousBackStackEntry?.savedStateHandle?.set(PICKED_TAG_ID, tagId)
navController.popBackStack()

// Receiver (the destination below)
composable<NoteEditorRoute> { entry ->
    val pickedTagId by entry.savedStateHandle
        .getStateFlow<String?>(PICKED_TAG_ID, null)
        .collectAsStateWithLifecycle()
    LaunchedEffect(pickedTagId) {
        pickedTagId?.let { id ->
            viewModel.onAction(NoteEditorAction.TagPicked(id))
            entry.savedStateHandle[PICKED_TAG_ID] = null   // consume once
        }
    }
}

private const val PICKED_TAG_ID = "picked_tag_id"
```

Rules for option 3:

- Write to `previousBackStackEntry` **before** popping.
- Clear the key after consuming, or the result is applied again when the screen is recomposed or
  returned to.
- Keep values to types the saved state can store (primitives, `String`); pass an id, not an object.
