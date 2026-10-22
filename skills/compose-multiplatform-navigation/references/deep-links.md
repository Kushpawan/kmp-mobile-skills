# Deep links into shared navigation (Android + iOS)

Contents

1. [Choose the shape](#1-choose-the-shape)
2. [Shared inbox and listener (commonMain)](#2-shared-inbox-and-listener-commonmain)
3. [Parse in commonMain](#3-parse-in-commonmain)
4. [Android](#4-android)
5. [iOS](#5-ios)
6. [Declarative shape (ungated destinations)](#6-declarative-shape-ungated-destinations)
7. [Testing](#7-testing)

## 1. Choose the shape

| | Declarative | Gated (recommended when any sign-in exists) |
|---|---|---|
| Matching | `navDeepLink<Route>(basePath = ...)` on the destination | A parser in `commonMain` returns a typed target |
| Who navigates | `NavController.navigate(NavUri(uri))` | The app-shell ViewModel, after the session is known |
| Signed-out user | Opens the destination anyway | Signs in first, then opens the target |
| Unknown URI | `IllegalArgumentException` unless you call `graph.hasDeepLink` first | Parser returns `null`; ignore or open home |

Do not use both for the same destination: the link would be handled twice.

## 2. Shared inbox and listener (commonMain)

A URI can arrive before Compose has subscribed (cold start), so the inbox keeps one pending value.
Both platforms call it on the main thread.

```kotlin
package com.example.app.navigation

/** Platform entry points deliver URIs here. Main thread only. */
object DeepLinkInbox {
    private var pendingUri: String? = null
    private var listener: ((String) -> Unit)? = null

    fun deliver(uri: String) {
        val current = listener
        if (current != null) current(uri) else pendingUri = uri
    }

    internal fun setListener(newListener: ((String) -> Unit)?) {
        listener = newListener
        if (newListener != null) {
            pendingUri?.let { uri -> pendingUri = null; newListener(uri) }
        }
    }
}

@Composable
fun DeepLinkListener(onUri: (String) -> Unit) {
    val currentOnUri by rememberUpdatedState(onUri)
    DisposableEffect(Unit) {
        DeepLinkInbox.setListener { uri -> currentOnUri(uri) }
        onDispose { DeepLinkInbox.setListener(null) }
    }
}
```

JetBrains' deep-link guide shows the same idea under the name `ExternalUriHandler`; keep whichever
the project already has.

## 3. Parse in commonMain

Treat every incoming URI as untrusted input: match a strict pattern and validate ids.

```kotlin
private val noteLink = Regex(
    """^(?:example://notes|https://example\.com/notes)/note/([A-Za-z0-9_-]{1,64})/?(?:[?#].*)?$""",
)

fun parseDeepLink(uri: String): DeepLinkTarget? =
    noteLink.matchEntire(uri)?.let { match -> DeepLinkTarget.Note(noteId = match.groupValues[1]) }
```

```kotlin
class ParseDeepLinkTest {
    @Test fun should_returnNoteTarget_when_customSchemeLink() =
        assertEquals(DeepLinkTarget.Note("42"), parseDeepLink("example://notes/note/42"))

    @Test fun should_returnNoteTarget_when_httpsLinkWithQuery() =
        assertEquals(DeepLinkTarget.Note("a-1"), parseDeepLink("https://example.com/notes/note/a-1?ref=mail"))

    @Test fun should_returnNull_when_idHasPathTraversal() =
        assertNull(parseDeepLink("example://notes/note/..%2Fadmin"))

    @Test fun should_returnNull_when_unknownPath() =
        assertNull(parseDeepLink("example://notes/unknown"))
}
```

## 4. Android

`AndroidManifest.xml`:

```xml
<activity
    android:name=".MainActivity"
    android:exported="true"
    android:launchMode="singleTop">
    <!-- Custom scheme -->
    <intent-filter>
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.DEFAULT" />
        <category android:name="android.intent.category.BROWSABLE" />
        <data android:scheme="example" android:host="notes" />
    </intent-filter>
    <!-- Verified App Links: also publish https://example.com/.well-known/assetlinks.json -->
    <intent-filter android:autoVerify="true">
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.DEFAULT" />
        <category android:name="android.intent.category.BROWSABLE" />
        <data android:scheme="https" android:host="example.com" android:pathPrefix="/notes" />
    </intent-filter>
</activity>
```

`singleTop` (or `singleTask`, if that matches the app's task behaviour) makes a link that arrives
while the activity is on top go to `onNewIntent` instead of creating a second activity.

Gated shape — forward the URI yourself:

```kotlin
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Only on a fresh start: after rotation or process death the same intent is
        // redelivered to onCreate and the navigation state is already restored.
        if (savedInstanceState == null) intent?.dataString?.let(DeepLinkInbox::deliver)
        setContent { AppRoot() }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.dataString?.let(DeepLinkInbox::deliver)
    }
}
```

On Android the multiplatform navigation artifact uses the AndroidX `NavController`, which tries to
handle the **launching** activity's intent as a deep link when the graph is set. In the gated shape
that is harmless only because no destination declares `deepLinks`; if one does, the link is handled
twice.

## 5. iOS

Custom scheme — `iosApp/iosApp/Info.plist` (or Xcode → target → Info → URL Types):

```xml
<key>CFBundleURLTypes</key>
<array>
    <dict>
        <key>CFBundleURLName</key>
        <string>com.example.app</string>
        <key>CFBundleURLSchemes</key>
        <array>
            <string>example</string>
        </array>
    </dict>
</array>
```

Universal Links: add the Associated Domains capability with `applinks:example.com` and publish
`https://example.com/.well-known/apple-app-site-association`.

SwiftUI app (scene-based lifecycle):

```swift
import SwiftUI
import Shared            // the name of your Kotlin framework

@main
struct iOSApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()                          // hosts ComposeUIViewController
                .onOpenURL { url in
                    DeepLinkInbox.shared.deliver(uri: url.absoluteString)
                }
                // Fallback if a Universal Link does not reach onOpenURL in your setup:
                .onContinueUserActivity(NSUserActivityTypeBrowsingWeb) { activity in
                    if let url = activity.webpageURL {
                        DeepLinkInbox.shared.deliver(uri: url.absoluteString)
                    }
                }
        }
    }
}
```

UIKit apps:

- **With a `SceneDelegate`**: URLs arrive in `scene(_:openURLContexts:)`; on a cold start read
  `connectionOptions.urlContexts` in `scene(_:willConnectTo:options:)`. Universal Links arrive as
  `NSUserActivity` in `scene(_:continue:)` / `connectionOptions.userActivities`.
- **Without scenes**: `application(_:open:options:)` and
  `application(_:continue:restorationHandler:)` in the app delegate.

When an app uses scenes, the app-delegate URL method is not called — a common reason a deep link
"does nothing" on iOS only.

Kotlin `object DeepLinkInbox` is exposed to Swift as `DeepLinkInbox.shared`; `fun deliver(uri: String)`
becomes `deliver(uri:)`.

## 6. Declarative shape (ungated destinations)

```kotlin
composable<NoteDetailRoute>(
    deepLinks = listOf(
        navDeepLink<NoteDetailRoute>(basePath = "example://notes/note"),        // example://notes/note/42
        navDeepLink<NoteDetailRoute>(basePath = "https://example.com/notes/note"),
    ),
) { entry -> NoteDetailScreen(noteId = entry.toRoute<NoteDetailRoute>().noteId) }
```

Required route properties become path segments in declaration order; optional ones become query
parameters. Then, in the root composable:

```kotlin
DeepLinkListener { uri ->
    val navUri = NavUri(uri)
    if (navController.graph.hasDeepLink(navUri)) navController.navigate(navUri)
}
```

On Android, forward only `onNewIntent` URIs in this shape — the launching intent is already handled
by the `NavController`.

## 7. Testing

```bash
# Android (device or emulator); -W waits for launch to finish
adb shell am start -W -a android.intent.action.VIEW -d "example://notes/note/42" com.example.app
adb shell pm get-app-links com.example.app        # App Links verification state (Android 12+)

# iOS simulator
xcrun simctl openurl booted "example://notes/note/42"
```

Run each link in three app states and report each as PASS / FAIL / NOT RUN:

1. App not running (cold start), signed in and signed out.
2. App in background.
3. App in foreground on another tab, then rotate (Android) after the link opens — the screen must
   not open a second time.
