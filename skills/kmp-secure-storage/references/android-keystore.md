# Android implementation — Keystore + DataStore

`SecureStore` for `androidMain`: an AES-256-GCM key that never leaves the Android Keystore, and a
dedicated Preferences DataStore file holding `Base64(IV + ciphertext)` per key.

## Contents

1. [Dependencies](#1-dependencies)
2. [Implementation](#2-implementation)
3. [Failure handling](#3-failure-handling)
4. [Backup exclusion](#4-backup-exclusion)
5. [Biometric-bound keys](#5-biometric-bound-keys)
6. [Alternatives](#6-alternatives)
7. [Testing](#7-testing)

## 1. Dependencies

```toml
# gradle/libs.versions.toml — keep the version the catalog pins
[libraries]
androidx-datastore-preferences = { module = "androidx.datastore:datastore-preferences", version.ref = "datastore" }
```

```kotlin
// shared/build.gradle.kts
kotlin {
    sourceSets {
        androidMain.dependencies { implementation(libs.androidx.datastore.preferences) }
    }
}
```

The Keystore, `javax.crypto` and `android.util.Base64` are platform APIs — no dependency.

## 2. Implementation

```kotlin
// androidMain — core/security/AndroidSecureStore.kt
import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.datastore.core.DataStore
import androidx.datastore.core.handlers.ReplaceFileCorruptionHandler
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import java.security.GeneralSecurityException
import java.security.KeyStore
import java.security.ProviderException
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.flow.first

// One DataStore per file per process: declare the delegate once, at top level.
private val Context.secureStoreDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "secure_store",                                         // files/datastore/secure_store.preferences_pb
    corruptionHandler = ReplaceFileCorruptionHandler { emptyPreferences() },
)

class AndroidSecureStore(
    context: Context,
    private val cipher: KeystoreCipher = KeystoreCipher(keyAlias = "secure_store_key"),
) : SecureStore {

    private val dataStore = context.applicationContext.secureStoreDataStore

    override suspend fun read(key: String): String? {
        val stored = dataStore.data.first()[stringPreferencesKey(key)] ?: return null
        return cipher.decryptOrNull(stored) ?: run {
            delete(key)                           // undecryptable (key lost, restored backup): fail closed
            null
        }
    }

    override suspend fun write(key: String, value: String) {
        val encrypted = cipher.encrypt(value)     // throws SecureStoreException; never stores plaintext
        dataStore.edit { preferences -> preferences[stringPreferencesKey(key)] = encrypted }
    }

    override suspend fun delete(key: String) {
        dataStore.edit { preferences -> preferences.remove(stringPreferencesKey(key)) }
    }

    override suspend fun clear() {
        dataStore.edit { preferences -> preferences.clear() }
        cipher.deleteKey()                        // the next sign-in generates a fresh key
    }
}

class KeystoreCipher(private val keyAlias: String) {

    fun encrypt(plaintext: String): String = try {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())       // the Keystore picks a random 12-byte IV
        val ciphertext = cipher.doFinal(plaintext.encodeToByteArray())
        Base64.encodeToString(cipher.iv + ciphertext, Base64.NO_WRAP)
    } catch (e: GeneralSecurityException) {
        throw SecureStoreException("Encryption failed", e)
    } catch (e: ProviderException) {                             // some devices' Keystore throws this
        throw SecureStoreException("Keystore unavailable", e)
    }

    fun decryptOrNull(payload: String): String? = try {
        val bytes = Base64.decode(payload, Base64.NO_WRAP)
        val key = existingKey()
        if (key == null || bytes.size <= IV_BYTES) {
            null
        } else {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(TAG_BITS, bytes, 0, IV_BYTES))
            cipher.doFinal(bytes, IV_BYTES, bytes.size - IV_BYTES).decodeToString()
        }
    } catch (e: GeneralSecurityException) {      // includes AEADBadTagException and invalidated keys
        null
    } catch (e: ProviderException) {
        null
    } catch (e: IllegalArgumentException) {      // not Base64
        null
    }

    fun deleteKey() {
        keyStore().deleteEntry(keyAlias)
    }

    private fun keyStore(): KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

    private fun existingKey(): SecretKey? = keyStore().getKey(keyAlias, null) as? SecretKey

    @Synchronized
    private fun getOrCreateKey(): SecretKey = existingKey() ?: KeyGenerator
        .getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        .apply {
            init(
                KeyGenParameterSpec.Builder(keyAlias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
        }
        .generateKey()

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
        const val TAG_BITS = 128
    }
}
```

Why each choice:

- **GCM** authenticates as well as encrypts: a tampered or truncated value fails to decrypt instead
  of producing garbage.
- **The IV comes from the Keystore.** Keystore keys require randomised encryption by default, so you
  cannot (and must not) supply your own IV for encryption; store the one it generated.
- **A dedicated DataStore file** keeps secrets out of the general settings file, so the backup rule can
  exclude exactly this file.
- **`@Synchronized` key creation** prevents two threads generating two keys for one alias on first use.

## 3. Failure handling

| Event | What happens | Correct reaction |
|---|---|---|
| Encryption throws | `SecureStoreException` | Fail the sign-in or token rotation; never store plaintext |
| Decryption fails (bad tag, missing key, restored backup) | `null`, value deleted | Treat as signed out |
| Key permanently invalidated (biometric-bound keys after enrolment change) | `null` from decrypt | Delete the key (`clear()`), require a full sign-in |
| DataStore file corrupt | Replaced with empty preferences | Treat as signed out |
| A second DataStore instance for the same file | `IllegalStateException: There are multiple DataStores active for the same file` | One top-level delegate |

## 4. Backup exclusion

Keystore keys are never included in backups. If the encrypted file is restored to a new device, it
cannot be decrypted. Exclude it — the path is relative to `filesDir`:

```xml
<!-- res/xml/data_extraction_rules.xml — Android 12 (API 31) and later -->
<data-extraction-rules>
    <cloud-backup>
        <exclude domain="file" path="datastore/secure_store.preferences_pb" />
    </cloud-backup>
    <device-transfer>
        <exclude domain="file" path="datastore/secure_store.preferences_pb" />
    </device-transfer>
</data-extraction-rules>
```

```xml
<!-- res/xml/backup_rules.xml — Android 11 (API 30) and earlier -->
<full-backup-content>
    <exclude domain="file" path="datastore/secure_store.preferences_pb" />
</full-backup-content>
```

```xml
<!-- AndroidManifest.xml -->
<application
    android:dataExtractionRules="@xml/data_extraction_rules"
    android:fullBackupContent="@xml/backup_rules">
```

If the app holds no data worth backing up, `android:allowBackup="false"` is simpler. Exclude the
database too if it holds user data that must not leave the device.

## 5. Biometric-bound keys

```kotlin
KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
    .setKeySize(256)
    .setUserAuthenticationRequired(true)
    .setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)   // API 30+; 0 = every use
    .setInvalidatedByBiometricEnrollment(true)
    .build()
```

Initialise the `Cipher` with the key, wrap it in `BiometricPrompt.CryptoObject(cipher)` and use the
cipher only inside `onAuthenticationSucceeded`. Use a separate alias from the token store so a
biometric change never locks out background token refresh.

## 6. Alternatives

- **Tink** (`com.google.crypto.tink:tink-android`) with a keyset protected by an Android Keystore
  key — a good fit when you need more than small strings, such as streaming file encryption.
- **multiplatform-settings** has no encrypted Android implementation of its own; wrap values with
  `KeystoreCipher` before storing if the project standardises on it.
- `EncryptedSharedPreferences` / `MasterKey` — deprecated; migrate away (read old → write new →
  verify → delete old).

## 7. Testing

- The `AndroidKeyStore` provider does not exist in JVM host tests; `KeyStore.getInstance` fails there.
  Run `AndroidSecureStore` tests as instrumented tests on an emulator or device.
- Instrumented cases: round trip; overwrite; delete; `clear()` then read returns null; a payload
  written, then the key deleted, then read returns null **and** the entry is gone.
- Shared logic above the store is tested in `commonTest` against an in-memory fake.
