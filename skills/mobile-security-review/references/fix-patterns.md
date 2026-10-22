# Fix patterns for KMP apps

Reference implementations for the fixes the lens asks for most often. Adapt names, DI and logging to
the project — these show the shape, not a library to copy. Package root `com.example.app`.

## Contents

1. [Token storage behind one interface](#1-token-storage-behind-one-interface)
2. [A debug flag both platforms set at build time](#2-a-debug-flag-both-platforms-set-at-build-time)
3. [HTTP logging and auth headers](#3-http-logging-and-auth-headers)
4. [Transport: Android network security config](#4-transport-android-network-security-config)
5. [Transport: iOS App Transport Security and pinning](#5-transport-ios-app-transport-security-and-pinning)
6. [Backups](#6-backups)
7. [Screenshots and the app switcher](#7-screenshots-and-the-app-switcher)
8. [Clipboard](#8-clipboard)
9. [Logout wipe checklist](#9-logout-wipe-checklist)
10. [Debug tooling that cannot ship](#10-debug-tooling-that-cannot-ship)

## 1. Token storage behind one interface

Common code depends on an interface; each platform implements it with its keystore. On iOS the
implementation is written in Swift and handed to Kotlin at startup — Keychain calls are simpler and
safer in Swift than through Kotlin/Native interop.

```kotlin
// commonMain — com/example/app/session/SecureStore.kt
interface SecureStore {
    fun put(key: String, value: String): Boolean
    fun get(key: String): String?
    fun remove(key: String)
    fun clear()
}
```

Android: an AES-GCM key that never leaves the Android Keystore encrypts values kept in a private
preferences file.

```kotlin
// androidMain — com/example/app/session/KeystoreSecureStore.kt
class KeystoreSecureStore(context: Context) : SecureStore {
    private val prefs = context.applicationContext
        .getSharedPreferences("secure_store", Context.MODE_PRIVATE)

    override fun put(key: String, value: String): Boolean {
        val blob = encrypt(value.encodeToByteArray())
        return prefs.edit().putString(key, Base64.encodeToString(blob, Base64.NO_WRAP)).commit()
    }

    override fun get(key: String): String? {
        val stored = prefs.getString(key, null) ?: return null
        return try {
            decrypt(Base64.decode(stored, Base64.NO_WRAP)).decodeToString()
        } catch (e: GeneralSecurityException) {
            // The key is gone (restored to a new device, keystore reset, lock screen removed).
            // Treat it as signed out instead of crashing on every launch.
            prefs.edit().remove(key).apply()
            null
        }
    }

    override fun remove(key: String) { prefs.edit().remove(key).apply() }
    override fun clear() { prefs.edit().clear().apply() }

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private fun encrypt(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())          // the keystore picks a random 12-byte IV
        return cipher.iv + cipher.doFinal(plain)          // store the IV in front of the ciphertext
    }

    private fun decrypt(blob: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, blob, 0, IV_SIZE))
        return cipher.doFinal(blob, IV_SIZE, blob.size - IV_SIZE)
    }

    private companion object {
        const val KEY_ALIAS = "secure_store_key"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_SIZE = 12
    }
}
```

A project already on DataStore can get the same property from DataStore with a Tink-encrypted
serializer; do not add a second storage library to get it.

iOS: the Kotlin interface is exported as an Objective-C protocol; a Swift class implements it.

```swift
import Foundation
import Security
import Shared   // the Kotlin framework

final class KeychainSecureStore: NSObject, SecureStore {
    private let service = "com.example.app.session"

    private func query(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: key]
    }

    func put(key: String, value: String) -> Bool {
        SecItemDelete(query(key) as CFDictionary)
        var item = query(key)
        item[kSecValueData as String] = Data(value.utf8)
        // Readable after first unlock (background refresh works); never restored to another device.
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(item as CFDictionary, nil) == errSecSuccess
    }

    func get(key: String) -> String? {
        var request = query(key)
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(request as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    func remove(key: String) { SecItemDelete(query(key) as CFDictionary) }

    func clear() {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword,
                       kSecAttrService as String: service] as CFDictionary)
    }
}
```

Keychain items can outlive an uninstall. If the app must start signed out after a reinstall, keep a
"has launched" flag in `UserDefaults` (which is deleted with the app) and call `clear()` when it is
missing.

## 2. A debug flag both platforms set at build time

iOS has no `BuildConfig`. Let each host app tell shared code which build it is, at startup, from a
compile-time value. Never read "debug" from remote config or a stored setting.

```kotlin
// commonMain
data class AppBuildInfo(val isDebug: Boolean)

fun initKoin(buildInfo: AppBuildInfo, secureStore: SecureStore) {
    startKoin { modules(appModule(buildInfo, secureStore)) }
}
```

```kotlin
// Android host — Application.onCreate(); BuildConfig of the *app* module, not a library's
initKoin(AppBuildInfo(isDebug = BuildConfig.DEBUG), KeystoreSecureStore(this))
```

```swift
// iOS host — App init. Objective-C reserves the `init` prefix, so `initKoin` is exported as `doInitKoin`.
#if DEBUG
let isDebug = true
#else
let isDebug = false
#endif
KoinKt.doInitKoin(buildInfo: AppBuildInfo(isDebug: isDebug), secureStore: KeychainSecureStore())
```

## 3. HTTP logging and auth headers

```kotlin
HttpClient(engine) {
    install(Logging) {
        logger = object : Logger {
            override fun log(message: String) = appLogger.d(message)   // the project's logger
        }
        level = if (buildInfo.isDebug) LogLevel.HEADERS else LogLevel.NONE
        sanitizeHeader { name -> name == HttpHeaders.Authorization || name == HttpHeaders.Cookie }
    }
    install(Auth) {
        bearer {
            loadTokens { secureStore.get("access")?.let { BearerTokens(it, secureStore.get("refresh")) } }
            refreshTokens { refreshSession(oldTokens) }                 // project-specific
            sendWithoutRequest { request -> request.url.host == API_HOST }
        }
    }
}
```

Use a separate client without the `Auth` plugin for presigned storage URLs, CDNs and other hosts, so
the access token can never be attached to them. With OkHttp, the equivalent is
`HttpLoggingInterceptor().apply { redactHeader("Authorization") }` and an interceptor that checks
`request.url.host` before adding the header.

## 4. Transport: Android network security config

`res/xml/network_security_config.xml`, referenced by `android:networkSecurityConfig` on
`<application>`. It applies to the platform TLS stack, which includes OkHttp and Ktor's OkHttp and
Android engines.

```xml
<network-security-config>
    <base-config cleartextTrafficPermitted="false" />

    <!-- Optional pinning: always ship a backup pin and an expiration date, so a certificate
         rotation cannot lock every installed copy out of the API. -->
    <domain-config>
        <domain includeSubdomains="true">api.example.com</domain>
        <pin-set expiration="2027-06-30">
            <pin digest="SHA-256">primarySpkiHashBase64=</pin>
            <pin digest="SHA-256">backupSpkiHashBase64=</pin>
        </pin-set>
    </domain-config>

    <!-- Lets a proxy's user-installed CA work in debug builds only. -->
    <debug-overrides>
        <trust-anchors>
            <certificates src="user" />
        </trust-anchors>
    </debug-overrides>
</network-security-config>
```

## 5. Transport: iOS App Transport Security and pinning

Ship no ATS exceptions in the release `Info.plist`. If local development needs one, put it in a
debug-only plist selected per build configuration (`INFOPLIST_FILE`), not in the shared one.

Optional identity pinning, enforced by the URL Loading System. Ktor's Darwin engine uses
`NSURLSession`, so it is covered; Network.framework and raw sockets are not.

```xml
<key>NSAppTransportSecurity</key>
<dict>
    <key>NSPinnedDomains</key>
    <dict>
        <key>api.example.com</key>
        <dict>
            <key>NSIncludesSubdomains</key>
            <true/>
            <key>NSPinnedCAIdentities</key>
            <array>
                <dict>
                    <key>SPKI-SHA256-BASE64</key>
                    <string>primaryCaSpkiHashBase64=</string>
                </dict>
                <dict>
                    <key>SPKI-SHA256-BASE64</key>
                    <string>backupCaSpkiHashBase64=</string>
                </dict>
            </array>
        </dict>
    </dict>
</dict>
```

Pin on both platforms or neither — a pin on one side only is a parity gap an attacker picks.

## 6. Backups

Android 12+ (`android:dataExtractionRules`) and Android 11 and lower (`android:fullBackupContent`)
read different files; ship both while `minSdk` is below 31.

```xml
<!-- res/xml/data_extraction_rules.xml -->
<data-extraction-rules>
    <cloud-backup>
        <exclude domain="sharedpref" path="secure_store.xml" />
        <exclude domain="database" path="app.db" />
    </cloud-backup>
    <device-transfer>
        <exclude domain="sharedpref" path="secure_store.xml" />
        <exclude domain="database" path="app.db" />
    </device-transfer>
</data-extraction-rules>
```

```xml
<!-- res/xml/backup_rules.xml -->
<full-backup-content>
    <exclude domain="sharedpref" path="secure_store.xml" />
    <exclude domain="database" path="app.db" />
</full-backup-content>
```

Keystore keys are never backed up, so restored ciphertext cannot be decrypted — exclude it, and
handle the decrypt failure anyway (section 1).

iOS: Keychain items with a `ThisDeviceOnly` accessibility are not restored to another device.
`Library/Caches` and `tmp` are not backed up; files in `Documents` and `Library/Application Support`
are, unless excluded:

```swift
let support = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                          appropriateFor: nil, create: true)
var url = support.appendingPathComponent("session.json")
var values = URLResourceValues()
values.isExcludedFromBackup = true
try url.setResourceValues(values)   // set it again after any rewrite that replaces the file
```

## 7. Screenshots and the app switcher

Android: `FLAG_SECURE` is per window. In a single-activity Compose app, set it while the sensitive
screen is shown and clear it after. Dialogs and popups are separate windows.

```kotlin
// androidMain
@Composable
fun SecureWindowEffect() {
    val window = LocalContext.current.findActivity()?.window ?: return
    DisposableEffect(window) {
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        onDispose { window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE) }
    }
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

// A dialog on that screen needs its own policy:
Dialog(onDismissRequest = onDismiss, properties = DialogProperties(securePolicy = SecureFlagPolicy.SecureOn)) { /* … */ }
```

If two secure screens can be on screen at once, count them before clearing the flag. On API 33+,
`Activity.setRecentsScreenshotEnabled(false)` hides the Recents thumbnail without blocking
screenshots.

iOS cannot block screenshots, but it can cover the app-switcher snapshot:

```swift
@main
struct ExampleApp: App {
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .overlay {
                    if scenePhase != .active { PrivacyCoverView() }   // shown before the snapshot is taken
                }
        }
    }
}
```

## 8. Clipboard

```kotlin
// Android: hides the preview in keyboards and the clipboard UI (constant needs compileSdk 33+;
// below that use the string "android.content.extra.IS_SENSITIVE").
val clip = ClipData.newPlainText("one-time code", code).apply {
    description.extras = PersistableBundle().apply {
        putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, true)
    }
}
clipboardManager.setPrimaryClip(clip)
```

```swift
// iOS: expires after 60 s and does not sync to the user's other devices.
// UTType needs `import UniformTypeIdentifiers`.
UIPasteboard.general.setItems(
    [[UTType.plainText.identifier: code]],
    options: [.expirationDate: Date().addingTimeInterval(60), .localOnly: true]
)
```

## 9. Logout wipe checklist

Logout is one function in shared code that every sign-out path calls (user action, refresh failure,
remote revocation, account deletion). It clears, in this order, and reports failures instead of
skipping them:

1. Cancel in-flight work that would write user data after the wipe (sync jobs, uploads).
2. Tokens and secrets — `SecureStore.clear()` on both platforms.
3. Databases — every table, or delete the file and recreate it.
4. Preferences and DataStore files that hold user data.
5. Files and caches — downloads, image caches, HTTP caches, exported documents.
6. WebView state — Android `CookieManager.getInstance().removeAllCookies(null)` and
   `WebStorage.getInstance().deleteAllData()`; iOS `WKWebsiteDataStore.default().removeData(...)`.
7. Scheduled work — WorkManager jobs, alarms, pending local notifications, background tasks.
8. In-memory state — singletons, caches, ViewModels scoped to the session.
9. Third-party identities — analytics and crash-reporter user id and properties reset.

Test it: sign in, use every feature that stores data, sign out, sign in as a different user, and
check nothing from the first user appears.

## 10. Debug tooling that cannot ship

```toml
# gradle/libs.versions.toml
[versions]
chucker = "..."   # pin the current release

[libraries]
chucker = { module = "com.github.chuckerteam.chucker:library", version.ref = "chucker" }
chucker-noop = { module = "com.github.chuckerteam.chucker:library-no-op", version.ref = "chucker" }
```

```kotlin
// composeApp/build.gradle.kts
dependencies {
    debugImplementation(libs.chucker)
    releaseImplementation(libs.chucker.noop)   // same API, does nothing — release cannot inspect traffic
}
```

Developer screens (environment picker, feature unlocks, fake data) live in `src/debug/` on Android
and behind `#if DEBUG` on iOS, so the release binary does not contain them at all.
