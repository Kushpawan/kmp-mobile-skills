---
name: kmp-secure-storage
description: Use when storing access tokens, refresh tokens, API keys or other secrets from Kotlin Multiplatform shared code — Android Keystore, a replacement for deprecated EncryptedSharedPreferences, iOS Keychain (SecItemAdd, SecItemCopyMatching, kSecAttrAccessible), wiping data on logout, biometric-gated secrets — or when tokens sit in SharedPreferences, DataStore or NSUserDefaults, survive logout or reinstall, appear in logs, or Keychain calls fail with -34018 or -25308.
license: Apache-2.0
compatibility: Kotlin Multiplatform project (Android + iOS). Android Keystore needs a device or emulator to test; iOS Keychain steps need macOS with Xcode.
metadata:
  category: data
  platforms: android, ios
---

# Secure storage for secrets in KMP

Secrets never touch plain preferences, a database column, a log line or a backup. Shared code sees
one small `SecureStore` interface; Android backs it with a non-exportable Android Keystore key, iOS
with the Keychain. Writes fail loudly instead of falling back to plaintext, reads fail closed, and
logout wipes everything the session left behind.

## When to use

- Storing session tokens, refresh tokens, per-user API keys or encryption keys from shared code.
- Replacing `EncryptedSharedPreferences` / `MasterKey` (Jetpack Security crypto, deprecated).
- Fixing: tokens in `SharedPreferences`, DataStore or `NSUserDefaults` in plain text; a session that
  survives logout or an iOS reinstall; tokens in Logcat or the Xcode console; Keychain status
  `-34018` (`errSecMissingEntitlement`) or `-25308` (`errSecInteractionNotAllowed`).
- Adding biometric unlock in front of a stored secret.

## When not to use

- Non-secret settings (theme, last tab) — DataStore or multiplatform-settings.
- Encrypting a whole database or large files — a dedicated solution (for example SQLCipher); this
  skill covers small values.
- A full security review of the app — **mobile-security-review**.
- Where the token is *used* (bearer auth, refresh) — **kmp-data-layer**.

## Step 0 — Read the project first

```bash
grep -nE "security-crypto|tink|datastore|multiplatform-settings|kvault|keychain" gradle/libs.versions.toml
grep -rnE "EncryptedSharedPreferences|MasterKey|KeyGenParameterSpec|SecItemAdd|KeychainSettings|NSUserDefaults|getSharedPreferences" --include=*.kt --include=*.swift .
grep -rniE "(token|secret|password|api_?key)" --include=*.kt --include=*.swift . | grep -iE "putString|setString|setObject|prefs\[|edit \{|forKey" | head -20
grep -rn "allowBackup\|fullBackupContent\|dataExtractionRules" --include=AndroidManifest.xml .
```

| Finding | Then |
|---|---|
| A secure store abstraction already exists | Use it. Check it against **Common mistakes**; fix gaps in place. |
| `EncryptedSharedPreferences` | Works today but deprecated (Jetpack Security crypto 1.1.0-alpha07+). Keep it running; migrate with step 8 when you touch it. |
| multiplatform-settings `KeychainSettings` on iOS | A reasonable iOS backend (marked experimental by the library); pair it with an encrypted Android implementation. |
| Tokens in plain prefs, DataStore, `NSUserDefaults` or a Room table | Treat as a defect: migrate (step 8). |
| `allowBackup="true"` without exclusion rules | Add rules (step 7). |

## Workflow

### 1. Decide what is secret

| Secret — store with this skill | Not a storage problem |
|---|---|
| Access and refresh tokens, session cookies | Build-time API keys shipped in the binary (extractable anyway; restrict them server-side) |
| Per-user API keys, OAuth client secrets issued at runtime | User preferences |
| Keys used to encrypt other local data | Cached server data — that belongs in the database |

Never store the user's password; store the tokens the password bought.

### 2. One interface in `commonMain`

```kotlin
// commonMain — core/security/SecureStore.kt
interface SecureStore {
    /** Null when absent. Throws [SecureStoreException] when the store is temporarily unreadable. */
    suspend fun read(key: String): String?

    /** Throws [SecureStoreException] if the value cannot be stored securely. Never stores plaintext. */
    suspend fun write(key: String, value: String)

    suspend fun delete(key: String)

    /** Removes every value this store owns. */
    suspend fun clear()
}

class SecureStoreException(message: String, cause: Throwable? = null) : Exception(message, cause)
```

The contract matters more than the code: **absent** (null), **unreadable right now** (exception —
for example an iOS device not yet unlocked after a reboot) and **stored** are three different
states. Treating "unreadable" as "absent" signs users out after every reboot.

### 3. Android — Keystore key + DataStore

AES-256-GCM key generated inside the Android Keystore (never exportable), a fresh IV per write,
ciphertext stored Base64-encoded in a dedicated Preferences DataStore file that is excluded from
backup. Full implementation, failure handling and tests:
[references/android-keystore.md](references/android-keystore.md).

Do not add `androidx.security:security-crypto` to new code: all of its APIs are deprecated "in
favour of existing platform APIs and direct use of Android Keystore".

### 4. iOS — Keychain via `platform.Security`

One `kSecClassGenericPassword` item per key under the app's service name, accessibility
`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` (readable by background work after the first
unlock, never synced to iCloud, never restored to another device). Update first, add on
`errSecItemNotFound`. Full Kotlin/Native implementation with correct Core Foundation memory
handling: [references/ios-keychain.md](references/ios-keychain.md).

### 5. Bind per platform

```kotlin
// androidMain — di/PlatformModule.android.kt
single<SecureStore> { AndroidSecureStore(context = androidContext()) }

// iosMain — di/PlatformModule.ios.kt
single<SecureStore> { KeychainSecureStore(service = "com.example.app.session") }
```

A single instance per process. See **kmp-koin-di** for platform modules.

### 6. Build the token store on top

```kotlin
// commonMain — core/session/SecureSessionTokenStore.kt
data class SessionTokens(val accessToken: String, val refreshToken: String) {
    override fun toString(): String = "SessionTokens(***)"     // a stray log line must not leak them
}

class SecureSessionTokenStore(private val secureStore: SecureStore) : SessionTokenStore {
    private val mutex = Mutex()                                 // the pair changes together, never half-written

    override suspend fun read(): SessionTokens? = mutex.withLock {
        val access = secureStore.read(KEY_ACCESS) ?: return@withLock null
        val refresh = secureStore.read(KEY_REFRESH) ?: return@withLock null
        SessionTokens(access, refresh)
    }

    override suspend fun write(tokens: SessionTokens) = mutex.withLock {
        secureStore.write(KEY_ACCESS, tokens.accessToken)
        secureStore.write(KEY_REFRESH, tokens.refreshToken)
    }

    override suspend fun clear() = mutex.withLock {
        secureStore.delete(KEY_ACCESS)
        secureStore.delete(KEY_REFRESH)
    }

    private companion object {
        const val KEY_ACCESS = "access_token"
        const val KEY_REFRESH = "refresh_token"
    }
}
```

`SessionTokenStore` is the interface the bearer-auth setup reads (**kmp-data-layer**). If a write
of the pair fails half-way, delete what was written and rethrow — a sign-in that cannot be stored
securely must fail, not continue with tokens only in memory.

### 7. Wipe everything on logout — and on reinstall

Logout is a checklist, not one call. Run every step even if one fails, and log failures by name only:

```kotlin
// commonMain — core/session/SessionDataCleaner.kt
interface SessionDataCleaner {
    val name: String                          // for logs: anonymous objects and lambdas have no useful class name
    suspend fun clearSessionData()
}

class LogoutUseCase(private val cleaners: List<SessionDataCleaner>, private val log: (String) -> Unit) {
    suspend operator fun invoke() {
        cleaners.forEach { cleaner ->
            try {
                cleaner.clearSessionData()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                log("Session cleaner '${cleaner.name}' failed: ${e::class.simpleName}")
            }
        }
    }
}
```

Register a cleaner for each of: the secure store, user tables in the database, in-memory caches and
session scopes, the HTTP client's cached bearer token
(`client.authProvider<BearerAuthProvider>()?.clearToken()`), scheduled background work, and the
push-notification token. If a feature holds **unsynced offline writes**, decide before wiping —
block logout with a warning or discard explicitly; never lose them silently.

- **iOS reinstall:** Keychain items are not removed when the app is deleted (long-standing behaviour,
  not a documented guarantee), while `NSUserDefaults` are. On launch, if a "has launched" flag in
  `NSUserDefaults` is missing, clear the store before reading tokens — code in
  [references/ios-keychain.md](references/ios-keychain.md). The first release that adds this signs
  existing users out once, because they have no flag yet.
- **Android backup:** Keystore keys are never backed up, so restored ciphertext cannot be decrypted on
  a new device. Exclude the secure DataStore file from cloud backup and device transfer
  (`dataExtractionRules` on API 31+, `fullBackupContent` below) — rules in
  [references/android-keystore.md](references/android-keystore.md).

### 8. Migrate secrets out of plain storage

1. Read the old value.
2. Write it to `SecureStore`, then read it back and compare.
3. Only then delete the old copy.
4. If the secure write is refused (for example the iOS device is locked), keep the old copy and
   retry on the next launch — do not sign the user out.

Run the migration once per launch before the first authenticated request, behind the same mutex as
token reads.

### 9. Optional — biometrics in front of a secret

- Android: a Keystore key with `setUserAuthenticationRequired(true)` and
  `setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)`; unlock the `Cipher`
  through `BiometricPrompt.CryptoObject` (androidx.biometric).
- iOS: an item protected by `SecAccessControlCreateWithFlags(..., kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly, kSecAccessControlBiometryCurrentSet, ...)`
  in `kSecAttrAccessControl` (instead of `kSecAttrAccessible`), plus `NSFaceIDUsageDescription` in
  `Info.plist`. The read blocks while the prompt shows — never call it on the main thread.
- Success, cancel, lockout and "biometrics changed" are four different outcomes. Only success
  unlocks; a new enrolment invalidates the key or item (Android throws
  `KeyPermanentlyInvalidatedException`) — fall back to a full sign-in, never to the unlocked path.
- Do not gate the refresh token that background sync needs; gate a separate secret or the UI.

### 10. Test with a fake; test the real stores on devices

```kotlin
// commonTest — core/security/InMemorySecureStore.kt
class InMemorySecureStore : SecureStore {
    private val values = mutableMapOf<String, String>()
    var failWrites = false

    override suspend fun read(key: String): String? = values[key]
    override suspend fun write(key: String, value: String) {
        if (failWrites) throw SecureStoreException("write refused")
        values[key] = value
    }
    override suspend fun delete(key: String) { values.remove(key) }
    override suspend fun clear() = values.clear()
}
```

- Test token store, logout and migration logic against the fake, including `failWrites = true`.
- Android Keystore is not available in JVM host tests — test `AndroidSecureStore` in instrumented tests.
- Observed: a Kotlin/Native iOS test executable runs without an app bundle or entitlements, and
  every Keychain call returns `-34018` (`errSecMissingEntitlement`). Test the real Keychain store from
  the app (a debug screen or app-hosted UI test), not from `iosSimulatorArm64Test`.

## Quick reference

| Concern | Android | iOS |
|---|---|---|
| Key / item | AES-256-GCM key in `AndroidKeyStore` | `kSecClassGenericPassword`, service + account |
| Storage | Dedicated Preferences DataStore file, Base64(IV + ciphertext) | Keychain item `kSecValueData` |
| Accessibility | Keystore default; optional user authentication | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` |
| Backup | Exclude the file from `cloud-backup` and `device-transfer` | `ThisDeviceOnly` items never leave the device |
| Reinstall | Data removed with the app | Items survive — clear on first launch |
| Logout | `clear()` + delete the key | `SecItemDelete` with service only |
| Failure | Encryption error → exception, never plaintext | Non-success `OSStatus` → exception |
| Tests | Instrumented | App-hosted; unentitled test binaries get `-34018` |

## Verify

Report each check as `PASS`, `FAIL` or `NOT RUN` (with the reason).

```bash
./gradlew :shared:allTests                         # token store, logout, migration against the fake
./gradlew :composeApp:connectedDebugAndroidTest    # AndroidSecureStore on a device or emulator (task name varies)
grep -rniE "(token|secret|password)" --include=*.kt --include=*.swift . | grep -iE "println|NSLog|Log\.[dviwe]|\.d\(|\.i\(" | head   # secrets near log calls
grep -rnE "getSharedPreferences|NSUserDefaults" --include=*.kt --include=*.swift . | head                                          # review every hit
```

Manual checks on both platforms — each one a separate line in the report:

1. Sign in, kill the app, relaunch: still signed in.
2. Sign out, relaunch: signed out, and no user data visible offline.
3. iOS: sign in, delete the app, reinstall: signed out.
4. iOS: sign in, reboot, start background work before unlocking: no forced sign-out after unlock.
5. Android: back up and restore to another device (or `adb shell bmgr`): the app starts signed out, without crashing.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Tokens in `SharedPreferences`, DataStore, `NSUserDefaults` or Room | Readable from backups, rooted or jailbroken devices | `SecureStore` |
| Encryption failure falls back to storing plaintext | Silently defeats the whole store on the devices where the Keystore misbehaves | Throw; the caller fails the sign-in |
| Undecryptable value returned as-is | Garbage sent as a bearer token | Delete it and return null |
| "Keychain locked" treated as "no token" | Users signed out after every reboot | Distinguish absent from unreadable (exception) |
| `kSecAttrAccessibleWhenUnlocked` for tokens used by background work | Background refresh fails while the screen is locked | `AfterFirstUnlockThisDeviceOnly` |
| Non-`ThisDeviceOnly` accessibility | Tokens sync via iCloud Keychain or restore onto another device | `...ThisDeviceOnly` |
| Keychain not cleared after reinstall | A deleted-and-reinstalled app is already signed in | First-launch flag in `NSUserDefaults` |
| Secure DataStore file included in Android backup | Restore on a new device yields ciphertext without a key | Exclusion rules |
| `data class` holding tokens, logged by accident | `toString()` prints the secrets | Override `toString()` |
| Logout only deletes the tokens | Cached user data, scheduled jobs and the HTTP client's cached token survive | Cleaner registry |
| `SecItemAdd` without update-first | `errSecDuplicateItem` (-25299) on the second write | Update, then add on `errSecItemNotFound` |
| `CFBridgingRetain` without a matching release | Secret bytes leak for the process lifetime | Release every bridged value (reference shows the pattern) |
| New code on `EncryptedSharedPreferences` | Deprecated; no further fixes | Keystore + DataStore |

## Related skills

- **kmp-data-layer** — bearer auth that reads these tokens; clearing the HTTP client's token cache.
- **kmp-koin-di** — platform bindings for the store.
- **kmp-room-database** — user tables to wipe on logout.
- **mobile-security-review** — the wider review: transport, logging, backups, exported components.
- OWASP MASVS (MASVS-STORAGE-1 "The app securely stores sensitive data", MASVS-STORAGE-2 "The app prevents leakage of sensitive data"): <https://mas.owasp.org/MASVS/>
- Android Keystore: <https://developer.android.com/privacy-and-security/keystore>
- Apple Keychain services: <https://developer.apple.com/documentation/security/keychain-services>
- multiplatform-settings: <https://github.com/russhwolf/multiplatform-settings>
