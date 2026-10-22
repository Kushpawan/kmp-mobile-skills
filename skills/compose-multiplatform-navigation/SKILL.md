---
name: compose-multiplatform-navigation
description: Use when building or debugging navigation in Compose Multiplatform commonMain — type-safe @Serializable routes, NavHost, nested graphs, splash/login gate, session expiry, bottom tabs with per-tab back stacks, deep links on Android and iOS, back handling and iOS swipe-back, returning results. Also for back stacks resetting, tabs losing state, double navigation, deep links that crash or skip login.
license: Apache-2.0
compatibility: Kotlin Multiplatform project using Compose Multiplatform 1.8+ and the multiplatform navigation-compose artifact (org.jetbrains.androidx.navigation). iOS steps need macOS with Xcode.
metadata:
  category: ui
  platforms: android, ios
---

# Compose Multiplatform navigation

One `NavController` per host, typed `@Serializable` routes, each feature registering its own
destinations, and every navigation call made from one place per screen (its effect handler) or
from the app shell. Session, tabs and deep links are app-shell concerns, not screen concerns.

## When to use

- Adding destinations, routes or a nested graph to a Compose Multiplatform app.
- Building the app shell: splash → signed-out graph vs signed-in graph, reacting to session expiry.
- Bottom navigation that keeps each tab's back stack.
- Deep links (custom scheme, App Links, Universal Links) into shared navigation.
- Intercepting back (unsaved changes) on Android and the iOS swipe-back gesture.
- Passing a result back to the previous screen.
- Symptoms: back stack resets after rotation, tab switch loses scroll/stack, a deep link opens a
  screen before login or crashes with `IllegalArgumentException`, a transition fires on the wrong
  edge, navigation happens twice.

## When not to use

- The screen itself (state, ViewModel, effects, tests) → `compose-multiplatform-screen`.
- Android-only app on Jetpack Navigation 3 → Google's
  [navigation-3 skill](https://github.com/android/skills/tree/main/navigation).
- Native SwiftUI navigation (`NavigationStack`) over shared logic → SwiftUI skills in Related.
- Projects on Voyager, Decompose, Appyx or another navigation library: follow that library; only the
  session/deep-link principles here transfer.

## Step 0 — Read the project first

1. **Library and version.** In `gradle/libs.versions.toml` find
   `org.jetbrains.androidx.navigation:navigation-compose` (Navigation 2 API),
   `org.jetbrains.androidx.navigation3:*` (Navigation 3), or another library. Typed routes need
   navigation-compose **2.8 or newer**. Note the Compose Multiplatform version: it decides the
   back-handler API (step 8).
2. **Route style.** Typed `@Serializable` routes or string routes? Do not mix; if the project uses
   strings, ask before migrating.
3. **Host shape.** Find every `NavHost(`. Is there one root host? A nested host for tabs? Where do
   features register destinations (`fun NavGraphBuilder.xxx(...)`)?
4. **Session model.** How the app knows it is signed in (token store, session repository, a
   `Flow`) and how expiry is signalled (401 → refresh failed → event).
5. **Transitions.** Are `enterTransition`/`exitTransition` set on `NavHost`, on individual
   `composable<...>()` calls, or nowhere?
6. **Platform entry points.** Android `MainActivity` (`launchMode`, `onNewIntent`, intent filters);
   iOS entry (`ComposeUIViewController` in a SwiftUI `App` or a UIKit `AppDelegate`/`SceneDelegate`),
   `Info.plist` URL types, Associated Domains entitlement.
7. **Screen ↔ navigation contract.** Do screens receive lambdas, a `NavController`, or a navigator
   interface? Keep whatever exists.

## Workflow

### 1. Define routes

```kotlin
@Serializable data object NotesListRoute
@Serializable data class NoteDetailRoute(val noteId: String)
@Serializable data class NoteEditorRoute(val noteId: String? = null)   // optional arg = default value
@Serializable data object NotesGraph                                   // nested graph key
```

- Pass **ids**, not objects. Arguments are serialised into the back stack's saved state; large or
  sensitive payloads do not belong there.
- Primitives, `String`, enums and lists of those work out of the box. Any other type needs a
  `NavType` passed through `typeMap` on `composable<T>(typeMap = ...)` **and** on `toRoute<T>()`
  callers — prefer an id instead.
- Read arguments with `backStackEntry.toRoute<NoteDetailRoute>()`; in a ViewModel with
  `SavedStateHandle.toRoute<T>()`, or pass them as DI parameters.

Done when every destination has a route type and no string route literal remains in new code.

### 2. Let each feature own its graph; keep the root host flat

```kotlin
fun NavGraphBuilder.notesGraph(navController: NavController) {
    navigation<NotesGraph>(startDestination = NotesListRoute) {
        composable<NotesListRoute> { NotesListScreen(onOpenNote = { id -> navController.navigate(NoteDetailRoute(id)) }) }
        composable<NoteDetailRoute> { NoteDetailScreen(onBack = navController::popBackStack) }
    }
}
```

The root `NavHost { }` then lists one line per feature. Routes live next to the feature (or in its
logic module if the project separates Compose-free code).

### 3. Configure transitions once, on the `NavHost`

- **Default:** set none. Compose Multiplatform then gives iOS its native-like swipe-back animation;
  per the JetBrains docs, specifying `enterTransition`/`exitTransition` on `NavHost` turns that
  default off.
- **If the design needs custom transitions:** set all four on `NavHost` only. Do **not** set them on
  individual `composable<Route>(...)` calls: `popEnterTransition`/`popExitTransition` default to the
  `enterTransition`/`exitTransition` you pass there, so a fade added for one edge silently applies to
  every push and pop touching that destination.
- Need a special case (splash hand-off)? Branch on `initialState.destination` /
  `targetState.destination` inside the single `NavHost`-level lambda.

### 4. Gate the app on the session

Shape: `SplashRoute` (start) → `AuthGraph` (signed out) or `MainRoute` (signed in). An app-shell
ViewModel observes the session and emits **effects** for the transitions; the root composable
handles them by replacing the whole back stack:

```kotlin
fun NavController.navigateClearingBackStack(route: Any) = navigate(route) {
    popUpTo(graph.id) { inclusive = true }   // clear everything, including the start destination
    launchSingleTop = true
}
```

- Startup, sign-in, sign-out and session expiry are all session changes → one place handles them.
- Drive transitions from one-shot effects (or guard a state observer by checking the current graph).
  A bare `LaunchedEffect(sessionState) { navigateClearingBackStack(...) }` re-runs when the composition is
  recreated (Android configuration change) and wipes the back stack the `NavController` just
  restored.
- Keep the OS splash up while the session is unknown (Android `installSplashScreen()` +
  `setKeepOnScreenCondition`) instead of flashing the sign-in screen.
- Session expiry: show the "signed out" message from shell state, then navigate to `AuthGraph`.
  Remember a pending deep link and replay it after sign-in.

Full shell code (routes, ViewModel, root host, tests):
[references/app-shell-session-tabs.md](references/app-shell-session-tabs.md).

### 5. Bottom tabs with a back stack per tab

- Host the tabs in a **nested `NavHost`** inside `composable<MainRoute>`, with one nested graph per
  tab. The auth gate then never interferes with the tab host's start destination.
- Switch tabs with the multiple-back-stacks recipe:

```kotlin
fun NavController.switchTab(tabGraph: Any) = navigate(tabGraph) {
    popUpTo(graph.findStartDestination().id) { saveState = true }
    launchSingleTop = true
    restoreState = true
}
```

- Derive the selected tab from `currentBackStackEntryAsState()` +
  `destination.hierarchy.any { it.hasRoute(tab.graph::class) }` — never a separate `var selectedTab`
  that can drift from the back stack.
- Re-selecting the current tab: pop that tab to its root (`popBackStack(tabRootRoute, inclusive = false)`).
- Full-screen flows that should cover the bar (editor, checkout) go on the **root** controller.

### 6. Share a ViewModel across a nested graph

```kotlin
composable<CheckoutPaymentRoute> { entry ->
    val graphEntry = remember(entry) { navController.getBackStackEntry<CheckoutGraph>() }
    val checkoutViewModel: CheckoutViewModel = koinViewModel(viewModelStoreOwner = graphEntry)
}
```

The ViewModel lives as long as the graph is on the back stack. Without Koin use
`viewModel(viewModelStoreOwner = graphEntry) { ... }`.

### 7. Deep links

Two shapes — pick by whether the target needs a signed-in user:

| Shape | How | Use when |
|---|---|---|
| Declarative | `composable<NoteDetailRoute>(deepLinks = listOf(navDeepLink<NoteDetailRoute>(basePath = "example://notes/note")))` + `navController.navigate(NavUri(uri))` | Destination is reachable without the auth gate |
| Gated | Parse the URI in `commonMain` into a route, hand it to the shell ViewModel, navigate after the session is known | Anything behind sign-in |

- Check `navController.graph.hasDeepLink(NavUri(uri))` first: `navigate(NavUri)` throws
  `IllegalArgumentException` for a URI no destination matches.
- Android: intent filters in the manifest. iOS: `CFBundleURLTypes` (custom scheme) or Associated
  Domains (Universal Links), then forward the URL from Swift into a shared handler.
- In a SwiftUI `App` (scene-based lifecycle) use `.onOpenURL`; `application(_:open:options:)` in an
  app delegate is not called when the app uses scenes.

Platform code, the shared URI handler, testing commands:
[references/deep-links.md](references/deep-links.md).

### 8. Back handling

- `NavHost` already maps Android system back and the iOS swipe-back to `popBackStack()`.
- To intercept (unsaved changes), on Compose Multiplatform **1.10+** use `NavigationBackHandler`
  from `org.jetbrains.androidx.navigationevent:navigationevent-compose`. On **1.8–1.9**, use the
  multiplatform `BackHandler` (`org.jetbrains.compose.ui:ui-backhandler`), which later releases
  deprecate; follow the IDE's deprecation message when upgrading.
- Enable interception only while needed (`isBackEnabled = state.hasUnsavedChanges`) and send an
  action to the ViewModel; never pop inside the handler and again in an effect.
- Disable the iOS swipe gesture app-wide only if required:
  `ComposeUIViewController(configure = { enableBackGesture = false }) { App() }`.

Code: [references/back-and-results.md](references/back-and-results.md).

### 9. Return a result to the previous screen

Prefer, in order: (1) the data layer — the editor saves, the list observes a `Flow` and updates
itself; (2) a graph-scoped shared ViewModel; (3) `previousBackStackEntry?.savedStateHandle` for a
small primitive result, read with `getStateFlow` and **cleared after it is consumed**.
Code in [references/back-and-results.md](references/back-and-results.md).

### 10. Navigation 3

Since Compose Multiplatform 1.10, Navigation 3 is available for Android, iOS, desktop and web
(`org.jetbrains.androidx.navigation3:navigation3-ui`). On non-JVM targets it needs polymorphic
serializers registered for every `NavKey` in a `SavedStateConfiguration`. JetBrains describes moving
from Navigation 2 as "less of a migration and more of a rewrite" — use it for new projects that
choose it; do not mix it with navigation-compose in one host.

## Quick reference

| Task | API |
|---|---|
| Typed destination | `composable<Route> { entry -> entry.toRoute<Route>() }` |
| Nested graph | `navigation<GraphKey>(startDestination = FirstRoute) { ... }` |
| Clear stack and go | `navigate(route) { popUpTo(graph.id) { inclusive = true }; launchSingleTop = true }` |
| Pop to a typed route | `popBackStack<NotesListRoute>(inclusive = false)` |
| Current destination check | `destination.hierarchy.any { it.hasRoute(NotesGraph::class) }` |
| Observe current entry | `navController.currentBackStackEntryAsState()` |
| Graph-scoped owner | `navController.getBackStackEntry<GraphKey>()` |
| Deep link pattern | `navDeepLink<NoteDetailRoute>(basePath = "example://notes/note")` matches `example://notes/note/42` |
| Navigate by URI | `navController.navigate(NavUri(uri))` (`androidx.navigation.NavUri`) |
| Back interception, CMP 1.10+ | `NavigationBackHandler(state = rememberNavigationEventState(...), isBackEnabled, onBackCompleted)` |
| Disable iOS swipe-back | `ComposeUIViewController(configure = { enableBackGesture = false })` |

## Verify

Report every check as **PASS**, **FAIL** or **NOT RUN (reason)**; never claim one you did not run.

```bash
./gradlew :composeApp:compileKotlinMetadata                 # routes + graphs compile in common code
./gradlew :composeApp:assembleDebug                         # Android build
./gradlew :shared:testAndroidHostTest                       # shell ViewModel / deep-link parser tests (or testDebugUnitTest)
./gradlew :shared:iosSimulatorArm64Test                     # same tests on iOS
adb shell am start -W -a android.intent.action.VIEW -d "example://notes/note/42" <applicationId>
xcrun simctl openurl booted "example://notes/note/42"
```

Manual run on both platforms (report NOT RUN if no device/simulator):

1. Cold start signed out → sign-in; sign in → main tabs; back from the first tab exits the app.
2. Rotate (Android) on a deep screen → the back stack is unchanged.
3. Tab A → push detail → tab B → tab A: the detail is still there.
4. Expire the session → message, then sign-in; after sign-in the pending deep link opens.
5. Deep link while signed out → sign-in first, then the target. Unknown URI → no crash.
6. iOS swipe-back pops one screen; unsaved-changes guard intercepts it.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| `enterTransition`/`exitTransition` on one `composable<Route>()` | Pop transitions default to them: the effect leaks onto unrelated push/pop edges | Configure transitions only on `NavHost` |
| Custom `NavHost` transitions without checking iOS | Disables the default iOS swipe-back animation | Leave defaults, or accept and test the custom feel on iOS |
| `LaunchedEffect(session) { navigateClearingBackStack(...) }` | Re-runs after recreation and wipes the restored stack | Effect-driven transitions, or guard on the current graph |
| Tabs as a `var selectedTab` + `when` | Loses each tab's stack and state; drifts from back stack | Nested tab `NavHost` + `saveState`/`restoreState`; derive selection |
| `popUpTo(graph.findStartDestination().id)` on a root whose start is the splash | Start destination is no longer on the stack; tab stacks accumulate | Put tabs in their own nested host |
| `navigate(NavUri(uri))` without `hasDeepLink` | `IllegalArgumentException` on unknown links | Check first, fall back to home |
| Declarative deep link to a gated screen | Opens before session resolution, skipping sign-in | Gated shape: parse → pending → navigate after sign-in |
| Forwarding the Android launch intent **and** letting `NavHost` handle it | The AndroidX `NavController` already handles the launching intent's deep link; the screen opens twice | Forward only `onNewIntent`, or use the gated shape end-to-end |
| `application(_:open:options:)` in a SwiftUI `App` | Not called with the scene lifecycle | `.onOpenURL { }` |
| Passing whole objects as route arguments | Saved-state bloat, custom `NavType` boilerplate, stale data | Pass the id; load in the destination |
| Navigating from a ViewModel | Leaks the controller; untestable | Effect → effect handler / shell |
| Back handler always enabled | Swallows back on every screen state | `isBackEnabled` bound to the state that needs it |
| `savedStateHandle` result never cleared | Re-applied on every recomposition or return | Reset the key after consuming |

## Related skills

- `compose-multiplatform-screen` — the screen contract that emits navigation effects.
- `compose-multiplatform-localization` — localised labels for tabs and titles.
- [android/skills — navigation](https://github.com/android/skills/tree/main/navigation) — Google's
  `navigation-3` and `navigation-event` skills for Android-only apps.
- [chrisbanes/skills](https://github.com/chrisbanes/skills) — `compose-state-and-effects`.
- [AvdLee/SwiftUI-Agent-Skill](https://github.com/AvdLee/SwiftUI-Agent-Skill) and
  [twostraws/SwiftUI-Agent-Skill](https://github.com/twostraws/SwiftUI-Agent-Skill) — when iOS uses
  native SwiftUI navigation instead of shared Compose navigation.
