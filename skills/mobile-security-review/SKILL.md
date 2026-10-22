---
name: mobile-security-review
description: Use when reviewing a Kotlin Multiplatform, Android or iOS app or change for security — API keys or secrets in source, BuildConfig or Info.plist, tokens or PII in logs, cleartext traffic, ATS exceptions, certificate pinning, WebView JavaScript bridges, deep link, intent or URL-scheme input, exported components, permissions, Keychain or Keystore storage, logout data wipe, allowBackup, screenshots, clipboard, debug bypasses in release builds, vulnerable dependencies, OWASP MASVS or MASTG.
license: Apache-2.0
compatibility: Kotlin Multiplatform, Android or iOS project in git. Optional tools — gitleaks, osv-scanner, apkanalyzer (Android SDK command-line tools); iOS checks need macOS with Xcode.
metadata:
  category: review
  platforms: android, ios
---

# Mobile security review

Review a mobile change or app against the threat model of a shipped binary, mapped to OWASP MASVS v2.
That model is not a server's: the device may be controlled by the attacker, everything in the APK or
IPA is readable, and the client cannot enforce authorisation — only the server can.

Three rules carry the skill. **Confirm every hit is reachable in a release build** before reporting
it. **Never print a secret's value** — not in the report, a command or a commit message. **Obfuscation
is not a mitigation** for anything that ships in the binary.

## When to use

- A change touches auth, tokens, storage, networking, WebViews, deep links, manifests, `Info.plist`,
  entitlements, build types, ProGuard/R8 rules or dependencies.
- Before a release, or when asked for a security review, a MASVS check or a pre-pen-test sweep.
- A scanner or store review flagged something and you need to know whether it is real.

## When not to use

- General correctness review — use `kmp-code-review` (run both on security-sensitive changes).
- Android vs iOS behaviour differences — use `mobile-platform-parity`; it covers pinning or wipe
  present on one platform only from the parity side.
- Backend authorisation, tenant isolation or API rate limits — those are server reviews.
- Dynamic testing on a device (Frida, proxies, root bypasses) — see the OWASP MASTG; this skill
  reviews source and build output.

## Step 0 — Read the project first

Before searching, learn where security-relevant decisions live in *this* project:

1. **Rules.** `SECURITY.md`, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `.cursor/rules/*`,
   `.github/copilot-instructions.md`. A documented rule makes a finding Tier 1.
2. **Build variants.** Android `buildTypes` and `productFlavors`, `src/debug/` and flavour source
   sets, `debugImplementation`; iOS build configurations, per-configuration `.xcconfig` and
   `Info.plist`, `#if DEBUG`. Note how shared Kotlin code learns "debug" on iOS — it has no
   `BuildConfig`.
3. **Stack.** Storage (DataStore, Room, SQLDelight, a multiplatform settings library, Keychain
   wrappers), networking (Ktor engines, OkHttp, `URLSession`), logger and crash/analytics SDKs, auth
   and token refresh, the logout path, WebViews, deep link routing.
4. **Entry points.** The merged release `AndroidManifest.xml`, `Info.plist` URL types, associated
   domains in the entitlements, push and notification handlers.

Done when you can name the release variants, where tokens are stored, and the function that logs out.

## Workflow

### 1. Choose the scope

- **Change review:** the uncommitted and unmerged changes (resolve the base the same way
  `kmp-code-review` does), plus the unchanged configuration they depend on — a new endpoint means
  reading the network security config and ATS settings too.
- **Whole-app audit:** every source set, both manifests and plists, build files, ProGuard/R8 rules,
  dependencies and CI secrets handling. State that the audit is static and source-based.

Print the scope line: `scope=change · base=origin/main · 12 files + 3 config files` or
`scope=audit · modules: composeApp, shared, iosApp`.

### 2. Inventory the attack surface

| Surface | Android | iOS | Shared Kotlin |
|---|---|---|---|
| Entry points | Merged manifest: exported components, intent filters, providers | URL types, associated domains, `onOpenURL`, user activities | Deep link router, push payload handling |
| Storage | Preferences, DataStore, databases, files, Keystore | `UserDefaults`, Keychain, files, data protection | Repository and cache layers, logout |
| Network | Network security config, OkHttp/Ktor engine config | ATS keys, `URLSession` / Darwin engine config | `HttpClient` setup, auth plugin, logging plugin |
| Web content | `WebView` settings, JS interfaces | `WKWebView` configuration, message handlers | URLs built for web content |
| Build output | Build types, R8 rules, `BuildConfig` fields, signing config | Entitlements, build settings, privacy manifest | Generated constants, debug flags |

### 3. Sweep, then read

Run a first-pass search, then load [references/lens-security.md](references/lens-security.md) and
apply every row whose condition holds. Each row lists the tokens to grep for.

```bash
# High-yield first pass. Prints file:line only — never pipe secret matches into a chat or ticket.
grep -rnIE --include='*.kt' --include='*.kts' --include='*.swift' --include='*.xml' \
  --include='*.plist' --include='*.xcconfig' --include='*.properties' --include='*.toml' \
  'usesCleartextTraffic|cleartextTrafficPermitted|NSAllowsArbitraryLoads|checkServerTrusted|onReceivedSslError|HostnameVerifier|exported="true"|allowBackup|addJavascriptInterface|allowUniversalAccessFromFileURLs|setWebContentsDebuggingEnabled|isDebuggable|storePassword|BEGIN (RSA |EC )?PRIVATE KEY|LogLevel\.(ALL|HEADERS|BODY)|UserDefaults|getSharedPreferences' . \
  | grep -v '/build/' | cut -d: -f1,2
```

Then read every hit in context. The search finds candidates; reading decides findings.

### 4. Confirm release reachability

For each candidate, decide whether it exists in what users install:

- **Source set and build type:** code in `src/debug/`, a `debugImplementation` dependency, or Swift
  inside `#if DEBUG` does not ship. Code in `commonMain` or `src/main` does.
- **Runtime gates:** a check on a value set from remote config, a stored preference, a hidden
  gesture or a launch argument is reachable in release. Only compile-time gates remove code.
- **Merged configuration:** a library can add an exported component, a permission or a cleartext
  exception the app's own manifest does not show. Check the merged manifest of the release build.
- **Shipped secrets:** a value injected at build time into `BuildConfig`, generated constants,
  resources or `Info.plist` is in the binary. Decide whether it is *meant* to be public (a key
  restricted by package and signature) or grants privilege (a server secret).

### 5. Rate and try to disprove

Set severity no lower than the row's floor, and add the MASVS control. Then, for every Critical and
High, argue against it: Is the input really attacker-controlled? Does the server enforce the check
anyway? Is the vulnerable branch compiled out of release? Does a platform default already block it
(cleartext is off by default for apps targeting API 28+; ATS blocks plain HTTP unless an exception
exists)? Mark survivors `CONFIRMED`; downgrade or drop the rest.

### 6. Report

Emit one JSON object per line, then the human report grouped by MASVS category, most severe first.

```json
{"file":"composeApp/src/main/res/xml/network_security_config.xml","line":4,"severity":"High","tier":2,"lens":"security/userCAsTrustedInRelease","title":"User-installed CAs trusted in release","why":"certificates src=\"user\" sits in base-config, so any user-added CA can intercept API traffic in production builds","fix":"move the user trust anchor into <debug-overrides>","rule":"User CAs trusted in release","masvs":"MASVS-NETWORK-1","verdict":"CONFIRMED"}
```

Fields: `file`, `line`, `severity` (`Critical` · `High` · `Medium` · `Low`), `tier` (`1` project rule ·
`2` lens row), `lens` (`security/<lensName>`), `title`, `why`, `fix`, `rule`, `masvs` (full id, e.g.
`MASVS-STORAGE-2`), `verdict` (`CONFIRMED` · `PLAUSIBLE`; every Critical and High is `CONFIRMED`).
Finish with `reviewed: <n> files · <m> findings`. "No findings" is a valid result; list what was
covered so it means something.

Human report, per finding: severity, `file:line`, the MASVS control, why it is exploitable, the fix,
and whether it needs a server-side change too. For a secret, give its type and location only, and
say: **rotate it** — deleting the line does not remove it from git history or from builds already
shipped.

### 7. Offer fixes

Ask which findings to fix. [references/fix-patterns.md](references/fix-patterns.md) has KMP-shaped
fixes for storage, debug flags, logging, transport, backups, screenshots, clipboard, logout and debug
tooling. **Stop and ask before** touching signing configuration, keystores, provisioning profiles or
CI secrets, and leave secret rotation to the user — it happens outside the repository.

## Quick reference

| MASVS group | What to check in a KMP app |
|---|---|
| STORAGE-1/2 | Token storage per platform, logs and crash keys, backups, clipboard, shared storage |
| CRYPTO-1/2 | Keys in the Android Keystore / iOS Keychain, no literal keys, current algorithms |
| AUTH-1/2/3 | Refresh handling, header scope, biometric fall-through, logout wipe |
| NETWORK-1/2 | Cleartext, ATS, trust managers and challenge handlers on **both** engines, pinning config |
| PLATFORM-1/2/3 | Exported components, deep links and intents, WebView settings and bridges, screenshots |
| CODE-1..4 | Dependencies, input validation (paths, SQL, deserialization), update enforcement |
| RESILIENCE-1..4 | Debug flags and tooling compiled out, `debuggable` off, R8 on — defence in depth only |
| PRIVACY-1..4 | Permissions, SDK consent, identifiers, privacy manifest, account deletion |

| Severity | Consequence |
|---|---|
| **Critical** | Credential or session exposure, auth bypass, remote code or script execution, user data readable by other apps or users |
| **High** | Exploitable with a precondition (malicious app installed, network position, user tapping a link), or PII exposure |
| **Medium** | Hardening gap with limited impact, or a privacy-compliance gap |
| **Low** | Defence-in-depth or hygiene |

## Verify

Run what applies and report each as `PASS`, `FAIL` or `NOT RUN — <reason>`. Never claim a scan that
did not run; a missing tool is `NOT RUN — gitleaks not installed`.

```bash
# Secrets in history and working tree (gitleaks 8.19+; older versions: gitleaks detect --redact)
gitleaks git --redact .
gitleaks dir --redact .

# What the release APK really contains — merged manifest and string constants
./gradlew :composeApp:assembleRelease
apkanalyzer manifest print <release.apk> | grep -nE 'exported="true"|allowBackup|usesCleartextTraffic|debuggable'
unzip -p <release.apk> 'classes*.dex' | strings | grep -ciE 'api[_-]?key|secret|bearer'   # count only

# iOS build output (macOS)
plutil -p <App>.app/Info.plist | grep -nE 'NSAppTransportSecurity|NSAllowsArbitraryLoads|CFBundleURLSchemes'
codesign -d --entitlements - <App>.app

# Release logs while signing in — no tokens, no PII
adb logcat --pid=$(adb shell pidof -s com.example.app)
xcrun simctl spawn booted log stream --level debug --predicate 'subsystem BEGINSWITH "com.example.app"'

# Known-vulnerable dependencies (osv-scanner v2 reads Gradle lockfiles; enable dependency locking first)
osv-scanner scan source -r .
```

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Reading `src/main/AndroidManifest.xml` only | Libraries merge in exported components, permissions and network config | Review the merged release manifest |
| "It's injected from CI, so it's secret" | Build-time injection keeps a value out of git, not out of the binary | Privileged secrets stay on a server; the app gets short-lived tokens |
| Reverting a committed secret | It stays in git history and in every build already shipped | Rotate it, then remove it |
| Gating a bypass on a runtime flag | Remote config, stored settings and hidden menus are reachable in release | Compile it out: `src/debug`, `debugImplementation`, `#if DEBUG` |
| Fixing pinning or TLS on one engine | Android uses OkHttp/the platform stack, iOS uses `URLSession` — they are configured separately | Check both engines for every transport finding |
| Pinning with one pin and no expiry | The next certificate rotation locks every installed copy out | Backup pin, an expiry, or no pinning by decision |
| Treating `allowBackup="false"` as complete | Device-to-device transfer still runs on some devices for apps targeting API 31+ | Exclude sensitive files in `dataExtractionRules` too |
| Assuming Keychain items die with the app | They can survive uninstall and resume the previous user's session | First-launch check that clears the Keychain |
| Logout that clears only the token | Databases, caches, WebView cookies and scheduled work keep the user's data | One shared logout that wipes every store |
| Accepting root detection or obfuscation as the fix | Both are bypassable; they raise cost, they do not protect a shipped secret | Fix the underlying exposure |

## Related skills

- `kmp-code-review` — the general review; its findings schema is the one used here.
- `mobile-platform-parity` — security controls present on only one platform.
- External: [OWASP MASVS](https://mas.owasp.org/MASVS/),
  [OWASP secure-agent-playbook](https://github.com/OWASP/secure-agent-playbook) (mobile code review
  play for native apps), [ivan-magda/swift-security-skill](https://github.com/ivan-magda/swift-security-skill)
  (Keychain, biometrics and CryptoKit on Apple platforms), [android/skills](https://github.com/android/skills)
  (Android security guidance).
