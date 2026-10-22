# Lens — mobile security, mapped to OWASP MASVS v2

Each row names a weakness, the MASVS v2 control it fails, what to search for, and the minimum
severity. Control IDs follow the OWASP MASVS (https://mas.owasp.org/MASVS/). A hit is a candidate:
read it in context and confirm it is reachable in a **release** build before reporting it.

**Columns.** *Lens* — stable name, becomes the key `security/<lensName>`. *MASVS* — the control(s),
without the `MASVS-` prefix (`STORAGE-1` is `MASVS-STORAGE-1`; write the full id in findings).
*What a hit looks like* — the weakness; *Applies when* states a condition. *Search for* — literal
tokens to grep (case-insensitive), comma-separated; combine them with `grep -rniE 'a|b|c'`.
*Floor* — minimum severity. *Mech?* — `yes`: a scanner or grep decides it; `partial`: grep finds
candidates, reading confirms; `no`: needs reading.

## Contents

1. [Secrets and build artefacts](#1-secrets-and-build-artefacts)
2. [Storage and session lifetime](#2-storage-and-session-lifetime)
3. [Leakage: logs, telemetry, backups, clipboard, keyboard](#3-leakage-logs-telemetry-backups-clipboard-keyboard)
4. [Network](#4-network)
5. [Platform interaction: components, deep links, intents](#5-platform-interaction-components-deep-links-intents)
6. [WebViews](#6-webviews)
7. [User interface](#7-user-interface)
8. [Authentication](#8-authentication)
9. [Code quality and dependencies](#9-code-quality-and-dependencies)
10. [Release hygiene and resilience](#10-release-hygiene-and-resilience)
11. [Privacy](#11-privacy)

## 1. Secrets and build artefacts

Everything in an APK or IPA is readable by whoever holds the file. Build-time injection keeps a value
out of git; it does not keep it out of the binary.

| Lens | MASVS | What a hit looks like | Search for | Floor | Mech? |
|---|---|---|---|---|---|
| Secret in the tree | STORAGE-1 | A credential, private key, client secret, signing secret or connection string committed in source, `strings.xml`, `Info.plist`, an `.xcconfig`, `gradle.properties`, a committed `.env`, or a test fixture | `api_key`, `apikey`, `secret`, `client_secret`, `password`, `BEGIN PRIVATE KEY`, `BEGIN RSA PRIVATE KEY`, `AKIA`, `AIza`, `xox`, `ghp_` | Critical | yes — secret scanner |
| Privileged secret shipped in the binary | STORAGE-1, AUTH-1 | A value that grants privilege (a server API secret, an admin token, a third-party secret key) injected through `buildConfigField`, a generated constants class, `Info.plist` or `resValue` — it is extractable from every install. *Keys designed to be public* (a restricted maps key, a publishable analytics key) are Low; say which it is | `buildConfigField`, `resValue`, `BuildKonfig`, `INFOPLIST_KEY_`, `Bundle.main.object(forInfoDictionaryKey` | High | partial |
| Signing material committed | STORAGE-1 | A keystore, `.p12`, `.p8`, provisioning profile, or `storePassword` / `keyPassword` literal in a build file | `.jks`, `.keystore`, `.p12`, `.p8`, `.mobileprovision`, `storePassword`, `keyPassword` | Critical | yes |
| Hardcoded crypto key | CRYPTO-2 | A symmetric key, IV or salt built from a literal (`SecretKeySpec("…".toByteArray(), …)`, a constant byte array) | `SecretKeySpec`, `IvParameterSpec`, `"AES"`, `kCCAlgorithmAES`, `SymmetricKey(data:` | Critical | partial |

## 2. Storage and session lifetime

| Lens | MASVS | What a hit looks like | Search for | Floor | Mech? |
|---|---|---|---|---|---|
| Token in plain storage | STORAGE-1 | An access token, refresh token, password or API key written to `SharedPreferences`, an unencrypted DataStore, a multiplatform settings store backed by them, `UserDefaults`, a plist or JSON file, or a Room/SQLDelight table without encryption | `SharedPreferences`, `getSharedPreferences`, `DataStore`, `Settings(`, `UserDefaults`, `NSUserDefaults`, `putString(`, `token`, `refresh` | Critical | partial |
| Key outside the platform keystore | STORAGE-1, CRYPTO-2 | An encryption key generated in app code and stored in preferences or a file, instead of the Android Keystore or the iOS Keychain / Secure Enclave | `KeyGenerator`, `SecureRandom`, `generateKey`, `KeyStore.getInstance`, `SecKeyCreateRandomKey` | High | partial |
| Deprecated encrypted-preferences library | STORAGE-1, CODE-3 | New code built on Jetpack Security's `EncryptedSharedPreferences` / `MasterKey` — the library is deprecated with no further releases. Existing use is acceptable short-term; new storage should use a Keystore-wrapped key (for example DataStore with Tink) | `EncryptedSharedPreferences`, `MasterKey`, `security-crypto` | Low | yes |
| Keychain accessibility too wide | STORAGE-1 | A token stored with `kSecAttrAccessibleAlways` / `…AlwaysThisDeviceOnly` (deprecated), or without `ThisDeviceOnly` when it must not migrate to another device through a backup | `kSecAttrAccessible`, `kSecAttrAccessibleAlways`, `kSecAttrSynchronizable` | Medium | yes |
| Keychain survives reinstall | STORAGE-1, AUTH-1 | iOS Keychain items can persist after the app is deleted; the first launch after a reinstall finds the previous user's tokens and resumes their session. *Applies when* the app reads tokens at startup without a first-run check | `SecItemCopyMatching`, first-launch flag | Medium | no |
| Session survives logout | AUTH-3, STORAGE-1 | The logout path clears tokens but not every store holding user data: database tables, files, image and HTTP caches, WebView cookies and storage, Keychain items, scheduled work and notifications, in-memory singletons, the analytics/crash user id | the logout function; `clearAllTables`, `deleteDatabase`, `removeAllCookies`, `WKWebsiteDataStore`, `cancelAllWork`, `removeAllPendingNotificationRequests`, `setUserId` | Critical | no |
| Sensitive file in shared storage | STORAGE-1, STORAGE-2 | User data written to external/shared storage, `Downloads`, a world-readable location, or an iOS `Documents` folder exposed by `UIFileSharingEnabled` / `LSSupportsOpeningDocumentsInPlace` | `getExternalStorage`, `Environment.DIRECTORY_`, `MediaStore`, `UIFileSharingEnabled`, `LSSupportsOpeningDocumentsInPlace` | High | partial |
| iOS file protection disabled | STORAGE-1 | A file holding user data written with `.noFileProtection` / `NSFileProtectionNone` | `noFileProtection`, `NSFileProtectionNone`, `FileProtectionType.none` | Medium | yes |

## 3. Leakage: logs, telemetry, backups, clipboard, keyboard

| Lens | MASVS | What a hit looks like | Search for | Floor | Mech? |
|---|---|---|---|---|---|
| Token in logs | STORAGE-2 | An HTTP logger at headers or body level without redaction (Ktor `LogLevel.ALL` / `HEADERS` / `BODY` with no `sanitizeHeader`; OkHttp `HttpLoggingInterceptor` with no `redactHeader`), or a token, password or session cookie interpolated into any log call | `LogLevel.ALL`, `LogLevel.HEADERS`, `LogLevel.BODY`, `sanitizeHeader`, `HttpLoggingInterceptor`, `redactHeader`, `Authorization` | Critical | partial |
| PII in logs | STORAGE-2 | Email, phone, name, precise location, government id or free-text user content in a log line; `os.Logger` interpolation of such values with `privacy: .public` | `Log.`, `println(`, `print(`, `NSLog(`, `os_log(`, `privacy: .public`, `Napier.`, `Logger.` | High | partial |
| Logging active in release | STORAGE-2 | A log sink installed unconditionally (a debug antilog, a console writer) so verbose output reaches release builds; `Log.*` calls not stripped by R8 when the project relies on stripping | `DebugAntilog`, `Napier.base(`, `Logger.setLogWriters`, `assumenosideeffects` | High | partial |
| PII in crash and analytics telemetry | STORAGE-2, PRIVACY-1 | User identifiers, emails, location or content placed in crash-report keys, breadcrumbs, analytics event properties or user properties | `setCustomKey`, `log(`, `setUserProperty`, `logEvent`, `breadcrumb`, `setTag`, `setUser` | High | partial |
| Backup includes secrets | STORAGE-2 | `android:allowBackup` left at its default (`true`) with no `dataExtractionRules` (API 31+) / `fullBackupContent` (API 30 and lower) excluding token and database files; iOS user-data files outside the Keychain not excluded from backup. Note `allowBackup="false"` does not stop device-to-device transfer on some devices for apps targeting API 31+ | `allowBackup`, `dataExtractionRules`, `fullBackupContent`, `isExcludedFromBackup`, `NSURLIsExcludedFromBackupKey` | High | yes — manifest diff |
| Sensitive clipboard | PLATFORM-1, STORAGE-2 | A password, OTP or token copied to the clipboard without the sensitive flag (Android `ClipDescription.EXTRA_IS_SENSITIVE`, API 33+) or without an expiry / local-only option on iOS (`UIPasteboard` `.expirationDate`, `.localOnly`) | `setPrimaryClip`, `ClipboardManager`, `LocalClipboardManager`, `LocalClipboard`, `UIPasteboard` | Medium | partial |
| Secret field not marked secret | STORAGE-2, PLATFORM-3 | A password or OTP input without password semantics — Compose without `KeyboardType.Password` / a password visual transformation, SwiftUI `TextField` instead of `SecureField`, no `textContentType` — the keyboard may learn and suggest it | `KeyboardType.Password`, `PasswordVisualTransformation`, `SecureField`, `isSecureTextEntry`, `textContentType` | Medium | partial |

## 4. Network

| Lens | MASVS | What a hit looks like | Search for | Floor | Mech? |
|---|---|---|---|---|---|
| Cleartext allowed | NETWORK-1 | `android:usesCleartextTraffic="true"`, a network security config with `cleartextTrafficPermitted="true"` in `base-config` or for a production domain, or an `http://` base URL in a release configuration | `usesCleartextTraffic`, `cleartextTrafficPermitted`, `http://` | Critical | yes |
| ATS exception reaching release | NETWORK-1 | `NSAllowsArbitraryLoads`, `NSAllowsArbitraryLoadsInWebContent`, `NSExceptionAllowsInsecureHTTPLoads` or a `NSExceptionMinimumTLSVersion` below 1.2 in an `Info.plist` used by a release configuration. `NSAllowsLocalNetworking` for local development is not a finding | `NSAppTransportSecurity`, `NSAllowsArbitraryLoads`, `NSExceptionDomains`, `NSExceptionAllowsInsecureHTTPLoads`, `NSExceptionMinimumTLSVersion` | High | yes |
| Certificate validation disabled | NETWORK-1 | A custom `X509TrustManager` with an empty `checkServerTrusted`, a `HostnameVerifier` that returns `true`, a WebView `onReceivedSslError` that calls `proceed()`, a Darwin `handleChallenge` or `URLSession` delegate that answers `.useCredential` without evaluating the server trust (`SecTrustEvaluateWithError`) — including inside a debug branch compiled into release | `X509TrustManager`, `checkServerTrusted`, `HostnameVerifier`, `onReceivedSslError`, `proceed()`, `handleChallenge`, `didReceive challenge`, `serverTrust`, `SecTrustEvaluateWithError` | Critical | partial |
| User CAs trusted in release | NETWORK-1 | `<certificates src="user"/>` in `base-config` or a `domain-config` instead of inside `<debug-overrides>` — any CA the user (or malware with that ability) installs can intercept traffic | `certificates src="user"`, `trust-anchors`, `debug-overrides` | High | yes |
| Pinning misconfigured | NETWORK-2 | Where pinning is used: a single pin with no backup, a leaf pin on a short-lived certificate, no `expiration` on an Android `pin-set`, pins on one platform only, or pins in the Android config while the iOS client (Ktor Darwin engine, `URLSession`) pins nothing. Not pinning is a documented decision, not a defect | `pin-set`, `CertificatePinner`, `NSPinnedDomains`, `NSPinnedCAIdentities`, `NSPinnedLeafIdentities`, `handleChallenge` | Medium | partial |
| Token in a URL | AUTH-1, STORAGE-2 | An access token, session id or one-time code placed in a query string (API calls, WebView URLs, deep links) — it lands in server logs, proxies, history and referrer headers | `?token=`, `access_token=`, `&token=`, `sessionId=`, `loadUrl(`, `URLQueryItem(name: "token"` | High | partial |
| Auth header sent to third parties | AUTH-1, NETWORK-1 | An interceptor or client-wide default that attaches `Authorization` to every request, including CDN, analytics or presigned-storage URLs on other hosts. Scope it to the API host | `Authorization`, `bearerAuth`, `defaultRequest`, `addInterceptor`, `header(HttpHeaders.Authorization` | High | partial |

## 5. Platform interaction: components, deep links, intents

Read the **merged** release manifest: libraries add components and permissions you will not see in
`src/main/AndroidManifest.xml`.

| Lens | MASVS | What a hit looks like | Search for | Floor | Mech? |
|---|---|---|---|---|---|
| Exported component | PLATFORM-1 | An activity, service, receiver or provider newly `exported="true"` (or exported through an intent filter) with no permission and no stated reason | `exported="true"`, `<intent-filter`, `<provider`, `<receiver`, `<service`, `android:permission` | High | yes — manifest diff |
| Provider over-sharing | PLATFORM-1, STORAGE-2 | A `ContentProvider` with `grantUriPermissions` over broad paths, or a `FileProvider` paths file with `<root-path>` or `path="."` | `grantUriPermissions`, `FileProvider`, `root-path`, `external-path`, `path="."` | High | yes |
| Unvalidated deep link | PLATFORM-1, CODE-4 | A deep link, App Link, Universal Link or custom URL scheme whose parameters drive navigation, a WebView load, a file path or a state-changing action without validation; an action (logout, delete, pay, change email) triggered by a link with no user confirmation. The server must still authorise any id the link carries | `<data android:scheme`, `onNewIntent`, `intent.data`, `getQueryParameter`, `navDeepLink`, `CFBundleURLSchemes`, `onOpenURL`, `application(_:open:`, `NSUserActivity`, `continue userActivity` | High | partial |
| Custom scheme for auth redirects | PLATFORM-1, AUTH-1 | An OAuth or magic-link redirect delivered through a custom URL scheme any app can register, without PKCE — another app can receive the code. Prefer verified App Links / Universal Links and PKCE | `redirect_uri`, `code_verifier`, `CFBundleURLSchemes`, `autoVerify` | High | partial |
| Intent redirection | PLATFORM-1 | An `Intent` read from extras and started (`getParcelableExtra<Intent>()` then `startActivity`), or sensitive data sent in an implicit intent or broadcast any app can receive | `getParcelableExtra`, `startActivity(`, `sendBroadcast`, `setPackage`, `Intent.ACTION_SEND` | High | partial |
| Mutable PendingIntent | PLATFORM-1 | A `PendingIntent` created with `FLAG_MUTABLE` around an implicit intent — a receiving app can rewrite its target | `PendingIntent.get`, `FLAG_MUTABLE`, `FLAG_IMMUTABLE` | High | partial |
| Third-party keyboards on secret fields | PLATFORM-1, STORAGE-2 | *Applies to* high-assurance apps (banking, health): custom keyboard extensions allowed while the user types secrets — iOS `application(_:shouldAllowExtensionPointIdentifier:)` not implemented | `shouldAllowExtensionPointIdentifier`, `keyboard` | Low | yes |

## 6. WebViews

| Lens | MASVS | What a hit looks like | Search for | Floor | Mech? |
|---|---|---|---|---|---|
| JavaScript bridge exposed to any origin | PLATFORM-2 | `addJavascriptInterface` or a `WKScriptMessageHandler` that exposes tokens, file access, navigation or other native capability while the WebView can load content from origins you do not control; a message handler that never checks `frameInfo` / the sender origin | `addJavascriptInterface`, `@JavascriptInterface`, `addWebMessageListener`, `WKScriptMessageHandler`, `userContentController`, `frameInfo` | Critical | partial |
| JavaScript with file access | PLATFORM-2, CODE-4 | `javaScriptEnabled = true` together with `allowFileAccess`, `allowFileAccessFromFileURLs`, `allowUniversalAccessFromFileURLs` or `allowContentAccess`, while loading untrusted content. Serve local content through `WebViewAssetLoader` instead | `javaScriptEnabled`, `allowFileAccess`, `allowFileAccessFromFileURLs`, `allowUniversalAccessFromFileURLs`, `allowContentAccess`, `loadFileURL` | High | yes |
| Unrestricted navigation | PLATFORM-2, CODE-4 | A WebView that navigates anywhere — no `shouldOverrideUrlLoading` / `decidePolicyFor` allowlist — loads `http://` URLs, or loads a URL taken straight from a deep link or push payload | `loadUrl(`, `load(URLRequest`, `shouldOverrideUrlLoading`, `decidePolicyFor`, `WKNavigationDelegate` | High | partial |
| Debuggable WebView in release | PLATFORM-2, RESILIENCE-4 | `WebView.setWebContentsDebuggingEnabled(true)` not gated on a debug build, or `isInspectable = true` on a release `WKWebView` | `setWebContentsDebuggingEnabled`, `isInspectable` | Medium | yes |

## 7. User interface

| Lens | MASVS | What a hit looks like | Search for | Floor | Mech? |
|---|---|---|---|---|---|
| Sensitive screen captured | PLATFORM-3, STORAGE-2 | A screen showing credentials, OTPs, payment data, identity documents or health data with no `FLAG_SECURE` on its window (Compose dialogs have their own window — `DialogProperties(securePolicy = SecureFlagPolicy.SecureOn)`), and no iOS privacy cover when the scene becomes inactive — the app-switcher snapshot shows the data | `FLAG_SECURE`, `SecureFlagPolicy`, `setRecentsScreenshotEnabled`, `scenePhase`, `sceneWillResignActive`, `willResignActiveNotification` | Medium | partial |
| Sensitive notification content | PLATFORM-3 | An OTP, message body or balance in a notification shown on the lock screen without a redacted public version (Android `VISIBILITY_PRIVATE` / `setPublicVersion`) | `NotificationCompat.Builder`, `setVisibility`, `setPublicVersion`, `UNMutableNotificationContent` | Medium | partial |
| Tapjacking on a sensitive action | PLATFORM-3 | *Applies when* `minSdk` is below 31 (Android 12 blocks untrusted overlay touches): a confirm/pay/permission button with no `filterTouchesWhenObscured` | `filterTouchesWhenObscured`, `FLAG_WINDOW_IS_OBSCURED` | Low | partial |

## 8. Authentication

The server enforces authorisation. Client-side checks are UX; review them for bypasses that unlock
local data or skip a server round trip.

| Lens | MASVS | What a hit looks like | Search for | Floor | Mech? |
|---|---|---|---|---|---|
| Biometric fall-through | AUTH-2 | A biometric or PIN gate whose error, cancel, lockout or `catch` path continues into the authenticated branch | `BiometricPrompt`, `onAuthenticationError`, `onAuthenticationFailed`, `LAContext`, `evaluatePolicy`, `canEvaluatePolicy` | Critical | no |
| Biometric result not bound to a key | AUTH-2, CRYPTO-2 | *Applies to* high-value actions: the gate trusts a boolean callback instead of unlocking a key — no `CryptoObject` (Android) or no Keychain item protected by `SecAccessControl` with `.biometryCurrentSet` (iOS) — so instrumentation can flip the result | `CryptoObject`, `setUserAuthenticationRequired`, `SecAccessControlCreateWithFlags`, `biometryCurrentSet`, `biometryAny` | Medium | partial |
| Keys survive new biometric enrolment | AUTH-2, CRYPTO-2 | `setInvalidatedByBiometricEnrollment(false)` or `.biometryAny` where adding a fingerprint or face should invalidate access | `setInvalidatedByBiometricEnrollment`, `biometryAny` | Medium | yes |
| Local unlock over an expired session | AUTH-1, AUTH-3 | A biometric or PIN unlock that reuses a stored token without checking or refreshing the server session, so a revoked session keeps working locally | the unlock handler; `refresh`, `expiresAt` | High | no |
| Refresh failure leaves half-auth state | AUTH-1 | A failed token refresh swallowed so the app keeps showing authenticated UI with no valid token, or retries forever | `refreshToken`, `refreshTokens`, `401`, `Unauthorized` | High | no |
| Client-only authorisation | AUTH-1 | A role, plan or ownership check enforced only by hiding UI, for an action whose API the change also calls. Report it as "confirm the server enforces this" | `isAdmin`, `role`, `canEdit`, `permission` | Medium | no |

## 9. Code quality and dependencies

| Lens | MASVS | What a hit looks like | Search for | Floor | Mech? |
|---|---|---|---|---|---|
| Vulnerable dependency | CODE-3 | A new dependency or version with a known advisory, or an abandoned library on a security path (crypto, auth, parsing). Severity follows the advisory | `libs.versions.toml`, `Package.swift`, `Podfile` | High | yes — dependency scanner |
| Path traversal | CODE-4 | A file name from the network, an intent, a deep link or an archive entry joined into a path without canonicalising and checking it stays inside the target directory (zip slip) | `ZipInputStream`, `ZipEntry`, `File(`, `appendingPathComponent`, `../` | High | partial |
| SQL built from input | CODE-4 | Raw SQL concatenated or templated with user or server input — `rawQuery("… $x")`, `@RawQuery` with string building, SQLDelight or SQLite `execute` with interpolation | `rawQuery(`, `execSQL(`, `@RawQuery`, `SimpleSQLiteQuery(`, `sqlite3_exec` | High | partial |
| Dynamic code loading | CODE-4 | Code loaded at runtime from a download or writable location (`DexClassLoader`, a downloaded script evaluated in a WebView or JS engine) | `DexClassLoader`, `PathClassLoader`, `evaluateJavascript(`, `JSContext`, `dlopen` | High | partial |
| Unsafe deserialization | CODE-4 | Polymorphic deserialization of untrusted input into arbitrary types (`ObjectInputStream`, `NSKeyedUnarchiver` without secure coding, a class discriminator mapped to any class) | `ObjectInputStream`, `readObject`, `NSKeyedUnarchiver`, `unarchiveObject`, `requiresSecureCoding` | High | partial |
| Forced-update path missing | CODE-2 | *Whole-app audits only:* no way to block versions with a known vulnerability. Decide explicitly whether the check fails open when the config call fails | `minimumVersion`, `forceUpdate`, `AppUpdateManager` | Low | no |

## 10. Release hygiene and resilience

Obfuscation, root/jailbreak detection and anti-tampering raise attacker cost. None of them protects
a secret that ships in the binary or replaces server-side checks.

| Lens | MASVS | What a hit looks like | Search for | Floor | Mech? |
|---|---|---|---|---|---|
| Debug bypass reachable in release | RESILIENCE-3 (+ what it bypasses) | A developer toggle — skip login, mock server, environment switcher, feature unlock, update-gate bypass — gated only by a runtime flag, a hidden UI, a remote config value or a persisted setting rather than compiled out of release (`src/debug`, `debugImplementation`, `#if DEBUG`). In KMP, check how the iOS side decides "debug": a value injected per build configuration, not a constant | `BuildConfig.DEBUG`, `#if DEBUG`, `isDebugBinary`, `SKIP_`, `BYPASS`, `useMock`, `fakeRepository`, `environmentPicker`, `staging` | High (Critical when it bypasses auth or payment) | partial |
| Debug tooling in release | RESILIENCE-3 | A network inspector, database browser or log viewer added with `implementation` instead of `debugImplementation` (or without its no-op release artifact), or linked into the iOS release configuration | `debugImplementation`, `releaseImplementation`, `no-op`, `chucker`, `inspector` | High | yes — dependency diff |
| Debuggable release | RESILIENCE-4 | `isDebuggable = true` / `android:debuggable="true"` on a release build type; `get-task-allow` set in release entitlements | `isDebuggable`, `debuggable`, `get-task-allow` | High | yes |
| Obfuscation disabled or neutered | RESILIENCE-3 | `isMinifyEnabled = false` on release, `-dontobfuscate`, or a keep rule retaining a whole package (`-keep class com.example.** { *; }`). Low severity — never accept obfuscation as the mitigation for another finding | `isMinifyEnabled`, `-dontobfuscate`, `-keep class`, `{ *; }` | Low | yes |

## 11. Privacy

| Lens | MASVS | What a hit looks like | Search for | Floor | Mech? |
|---|---|---|---|---|---|
| Permission not minimal | PRIVACY-1 | A new manifest permission or `Info.plist` usage key the feature does not need: background location (`ACCESS_BACKGROUND_LOCATION`, `NSLocationAlwaysAndWhenInUseUsageDescription`) where foreground suffices, fine where coarse suffices, `QUERY_ALL_PACKAGES`, contacts, a library-merged permission not removed with `tools:node="remove"`, or a permission requested at launch instead of in context | `uses-permission`, `UsageDescription`, `ACCESS_BACKGROUND_LOCATION`, `ACCESS_FINE_LOCATION`, `QUERY_ALL_PACKAGES`, `tools:node="remove"` | Medium (High for background location, contacts, SMS) | yes — merged manifest diff |
| SDK collects before consent | PRIVACY-1 | *Applies where* consent is required: an analytics, crash or ads SDK initialised in `Application.onCreate` / app launch before the user's choice is known, or ignoring a revoked choice | `initialize(`, `FirebaseApp`, `start(`, `setAnalyticsCollectionEnabled`, `consent` | Medium | partial |
| Cross-purpose identifiers | PRIVACY-2 | A hardware or persistent identifier (`ANDROID_ID`, IMEI, MAC, `identifierForVendor`) used for tracking or joined with analytics; the advertising identifier read without App Tracking Transparency authorisation on iOS | `ANDROID_ID`, `getDeviceId`, `identifierForVendor`, `advertisingIdentifier`, `ATTrackingManager` | Medium | yes |
| Data declarations out of date | PRIVACY-3 | A new required-reason API use (for example `UserDefaults`, file timestamps, system boot time, disk space) or a new SDK with no matching entry in `PrivacyInfo.xcprivacy`; new data collection not reflected in the store data-safety / privacy labels. Check Apple's current list of required-reason APIs | `PrivacyInfo.xcprivacy`, `NSPrivacyAccessedAPITypes`, `NSPrivacyCollectedDataTypes` | Medium | partial |
| No in-app account deletion | PRIVACY-4 | *Whole-app audits:* the app creates accounts but offers no way to delete one from inside the app — both app stores require it | `deleteAccount`, `account deletion` | Medium | no |
