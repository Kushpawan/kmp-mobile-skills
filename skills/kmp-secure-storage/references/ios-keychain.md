# iOS implementation — Keychain from Kotlin/Native

`SecureStore` for `iosMain`, calling the Security framework directly through `platform.Security`.
No third-party dependency.

## Contents

1. [Implementation](#1-implementation)
2. [Core Foundation memory rules](#2-core-foundation-memory-rules)
3. [Choosing accessibility](#3-choosing-accessibility)
4. [Status codes you will meet](#4-status-codes-you-will-meet)
5. [Clearing after reinstall](#5-clearing-after-reinstall)
6. [Biometric-protected items](#6-biometric-protected-items)
7. [Sharing with app extensions](#7-sharing-with-app-extensions)
8. [Testing](#8-testing)

## 1. Implementation

```kotlin
// iosMain — core/security/KeychainSecureStore.kt
import kotlinx.cinterop.BetaInteropApi
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.alloc
import kotlinx.cinterop.convert
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import kotlinx.cinterop.usePinned
import kotlinx.cinterop.value
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.IO
import kotlinx.coroutines.withContext
import platform.CoreFoundation.CFDictionaryCreateMutable
import platform.CoreFoundation.CFDictionaryRef
import platform.CoreFoundation.CFDictionarySetValue
import platform.CoreFoundation.CFMutableDictionaryRef
import platform.CoreFoundation.CFRelease
import platform.CoreFoundation.CFStringRef
import platform.CoreFoundation.CFTypeRef
import platform.CoreFoundation.CFTypeRefVar
import platform.CoreFoundation.kCFAllocatorDefault
import platform.CoreFoundation.kCFBooleanTrue
import platform.CoreFoundation.kCFTypeDictionaryKeyCallBacks
import platform.CoreFoundation.kCFTypeDictionaryValueCallBacks
import platform.Foundation.CFBridgingRelease
import platform.Foundation.CFBridgingRetain
import platform.Foundation.NSData
import platform.Foundation.create
import platform.Security.SecItemAdd
import platform.Security.SecItemCopyMatching
import platform.Security.SecItemDelete
import platform.Security.SecItemUpdate
import platform.Security.errSecItemNotFound
import platform.Security.errSecSuccess
import platform.Security.kSecAttrAccessible
import platform.Security.kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
import platform.Security.kSecAttrAccount
import platform.Security.kSecAttrService
import platform.Security.kSecClass
import platform.Security.kSecClassGenericPassword
import platform.Security.kSecMatchLimit
import platform.Security.kSecMatchLimitOne
import platform.Security.kSecReturnData
import platform.Security.kSecValueData
import platform.posix.memcpy

@OptIn(ExperimentalForeignApi::class)
class KeychainSecureStore(
    private val service: String,                                   // e.g. "com.example.app.session"
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : SecureStore {

    override suspend fun read(key: String): String? = withContext(ioDispatcher) {
        withItemQuery(account = key, extra = {
            put(kSecReturnData, kCFBooleanTrue)
            put(kSecMatchLimit, kSecMatchLimitOne)
        }) { query ->
            memScoped {
                val result = alloc<CFTypeRefVar>()
                when (val status = SecItemCopyMatching(query, result.ptr)) {
                    errSecSuccess -> (CFBridgingRelease(result.value) as? NSData)?.toByteArray()?.decodeToString()
                    errSecItemNotFound -> null
                    // e.g. -25308 before the first unlock after a reboot: unreadable, not absent
                    else -> throw SecureStoreException("Keychain read failed for '$key' (OSStatus $status)")
                }
            }
        }
    }

    override suspend fun write(key: String, value: String): Unit = withContext(ioDispatcher) {
        val data = value.encodeToByteArray().toNSData()
        // Update first: adding an existing service + account returns errSecDuplicateItem.
        var status = withItemQuery(account = key) { query ->
            val changes = CFQuery()
            try {
                changes.putObject(kSecValueData, data)
                changes.put(kSecAttrAccessible, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly)
                SecItemUpdate(query, changes.ref)
            } finally {
                changes.release()
            }
        }
        if (status == errSecItemNotFound) {
            status = withItemQuery(account = key, extra = {
                putObject(kSecValueData, data)
                put(kSecAttrAccessible, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly)
            }) { query -> SecItemAdd(query, null) }
        }
        if (status != errSecSuccess) throw SecureStoreException("Keychain write failed for '$key' (OSStatus $status)")
    }

    override suspend fun delete(key: String): Unit = withContext(ioDispatcher) {
        val status = withItemQuery(account = key) { query -> SecItemDelete(query) }
        if (status != errSecSuccess && status != errSecItemNotFound) {
            throw SecureStoreException("Keychain delete failed for '$key' (OSStatus $status)")
        }
    }

    /** Without an account, the query matches — and deletes — every item of this service. */
    override suspend fun clear(): Unit = withContext(ioDispatcher) {
        val status = withItemQuery(account = null) { query -> SecItemDelete(query) }
        if (status != errSecSuccess && status != errSecItemNotFound) {
            throw SecureStoreException("Keychain clear failed (OSStatus $status)")
        }
    }

    private inline fun <T> withItemQuery(
        account: String?,
        extra: CFQuery.() -> Unit = {},
        block: (CFDictionaryRef?) -> T,
    ): T {
        val query = CFQuery()
        try {
            query.put(kSecClass, kSecClassGenericPassword)
            query.putObject(kSecAttrService, service)
            account?.let { query.putObject(kSecAttrAccount, it) }
            query.extra()
            return block(query.ref)
        } finally {
            query.release()
        }
    }
}

/** A mutable CFDictionary that retains what it holds and is released exactly once. */
@OptIn(ExperimentalForeignApi::class)
internal class CFQuery {
    val ref: CFMutableDictionaryRef = requireNotNull(
        CFDictionaryCreateMutable(kCFAllocatorDefault, 0, kCFTypeDictionaryKeyCallBacks.ptr, kCFTypeDictionaryValueCallBacks.ptr),
    )

    /** Core Foundation constants (kSecClassGenericPassword, kCFBooleanTrue, …). */
    fun put(key: CFStringRef?, value: CFTypeRef?) {
        CFDictionarySetValue(ref, key, value)
    }

    /** Kotlin / Objective-C objects (String, NSData): bridge, let the dictionary retain, drop our +1. */
    fun putObject(key: CFStringRef?, value: Any) {
        val bridged = CFBridgingRetain(value)
        CFDictionarySetValue(ref, key, bridged)
        CFRelease(bridged)
    }

    fun release() {
        CFRelease(ref)
    }
}

@OptIn(ExperimentalForeignApi::class, BetaInteropApi::class)
internal fun ByteArray.toNSData(): NSData =
    if (isEmpty()) NSData() else usePinned { pinned -> NSData.create(bytes = pinned.addressOf(0), length = size.convert()) }

@OptIn(ExperimentalForeignApi::class)
internal fun NSData.toByteArray(): ByteArray {
    val size = length.toInt()
    if (size == 0) return ByteArray(0)
    return ByteArray(size).apply { usePinned { pinned -> memcpy(pinned.addressOf(0), bytes, length) } }
}
```

After adapting it, run a round trip in the app — write, read, overwrite, delete, `clear()`, and an
empty value — before relying on it (section 8 explains why a unit test cannot do this).

## 2. Core Foundation memory rules

- `CFDictionaryCreateMutable` with `kCFTypeDictionaryKeyCallBacks` / `kCFTypeDictionaryValueCallBacks`
  makes the dictionary retain keys and values. Without callbacks (`null, null`) it retains nothing
  and every bridged value must outlive the dictionary — easy to get wrong.
- `CFBridgingRetain(obj)` gives you a +1 reference: release it once the dictionary holds its own.
- `CFBridgingRelease(ref)` hands the +1 returned by `SecItemCopyMatching` to Kotlin's memory
  management; do not also call `CFRelease` on it.
- Constants such as `kSecClass` or `kCFBooleanTrue` are never released.
- An unbalanced retain keeps secret bytes in memory for the life of the process; a double release crashes.

## 3. Choosing accessibility

| Constant | Readable | Leaves the device | Use for |
|---|---|---|---|
| `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | After the first unlock since boot, also while locked | No | Session tokens used by background refresh or sync (default here) |
| `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` | Only while unlocked | No | Secrets used only in the foreground |
| `kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly` | Only while unlocked, only if a passcode is set; deleted if the passcode is removed | No | High-value secrets; base for biometric access control |
| Variants without `ThisDeviceOnly` | — | Yes: iCloud Keychain sync and backup restore to other devices | Not for session tokens |

Changing accessibility of an existing item needs an update (as `write` does) — items keep the value
they were created with.

## 4. Status codes you will meet

| `OSStatus` | Constant | Meaning |
|---|---|---|
| 0 | `errSecSuccess` | Done |
| -25300 | `errSecItemNotFound` | Absent — normal on first launch |
| -25299 | `errSecDuplicateItem` | `SecItemAdd` over an existing item — update first |
| -25308 | `errSecInteractionNotAllowed` | Device locked (or not unlocked since boot) for this accessibility |
| -34018 | `errSecMissingEntitlement` | Process has no Keychain entitlement — typical for unbundled test executables |
| -128 | `errSecUserCanceled` | User dismissed a biometric or passcode prompt |

Log the status code and the key name, never the value.

## 5. Clearing after reinstall

```kotlin
// iosMain — core/security/ReinstallGuard.kt
import platform.Foundation.NSUserDefaults

private const val INSTALL_MARKER_KEY = "secure_store.install_marker"

/** Call once at launch, before anything reads tokens. */
suspend fun clearSecureStoreAfterReinstall(secureStore: SecureStore) {
    val defaults = NSUserDefaults.standardUserDefaults
    if (!defaults.boolForKey(INSTALL_MARKER_KEY)) {
        secureStore.clear()                                  // leftovers from a previous install
        defaults.setBool(true, forKey = INSTALL_MARKER_KEY)
    }
}
```

`NSUserDefaults` are deleted with the app; Keychain items are not. The marker only says "this
install has launched before" — it holds nothing secret.

## 6. Biometric-protected items

- Create a `SecAccessControl` with `SecAccessControlCreateWithFlags(kCFAllocatorDefault,
  kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly, kSecAccessControlBiometryCurrentSet, error)` and
  put it under `kSecAttrAccessControl` instead of `kSecAttrAccessible` when adding the item.
- `kSecAccessControlBiometryCurrentSet` makes the item unreadable after Face ID / Touch ID enrolment
  changes — the safe default; fall back to a full sign-in.
- Add `NSFaceIDUsageDescription` to `Info.plist`, or the prompt never appears.
- `SecItemCopyMatching` blocks while the system prompt is on screen: run it on a background
  dispatcher, never on the main thread.
- Handle `errSecUserCanceled` and authentication failure as "not unlocked" — never as success.
- Keep the background-refresh token in a separate, non-biometric item.

## 7. Sharing with app extensions

A widget or share extension that needs the token reads it through a shared access group: add the
Keychain Sharing capability to both targets and set `kSecAttrAccessGroup` to the shared group in
every query (read, write, delete and clear). Without the attribute, items go to the app's default
group and the extension cannot see them.

## 8. Testing

- Kotlin/Native test executables (`iosSimulatorArm64Test`) run outside an app bundle without
  entitlements — observed: every Keychain call returns `-34018`. Keep the Keychain behind
  `SecureStore` and test shared logic against an in-memory fake.
- Exercise the real store inside the app: an app-hosted XCTest or UI test, or a debug-only screen
  that runs a round trip (write, read, overwrite, delete, clear) and reports status codes.
- Run the reinstall, reboot-before-unlock and logout checks from the skill's **Verify** section on a
  device or simulator.
