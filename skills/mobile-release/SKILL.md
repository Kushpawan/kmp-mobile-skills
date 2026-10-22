---
name: mobile-release
description: Use when versioning or shipping a Kotlin Multiplatform app or shared library to Google Play and the App Store - "cut a release", "bump the version", versionCode, versionName, CFBundleShortVersionString, CFBundleVersion, release tags, semver for a KMP library, Fastlane lanes, TestFlight, Play internal track, staged or phased rollout, release checklist, signing keys, match, Play service account.
license: Apache-2.0
compatibility: Kotlin Multiplatform app with Android and iOS hosts, or a KMP library published to Maven and/or Swift Package Manager. Fastlane lanes need Ruby + Bundler; iOS lanes need macOS with Xcode.
metadata:
  category: release
  platforms: android, ios
---

# Mobile release

One version number, read by both apps; one tag scheme that package managers cannot misread; one
checklist that is the same every time. Most release incidents in a two-platform app are not code
bugs — they are numbers that moved on one platform and not the other, a tag that resolved to the
wrong artifact, or a signing secret that ended up somewhere it should not be.

## When to use

- Preparing a release of the Android app, the iOS app, or both.
- Setting up versioning so Android and iOS cannot drift apart.
- Choosing tag names in a repo that ships more than one artifact.
- Writing or fixing Fastlane lanes for Play and TestFlight / App Store.
- Planning a staged (Play) or phased (App Store) rollout and what to monitor.
- Versioning a shared KMP library consumed through Maven or Swift Package Manager.

## When not to use

- The CI workflow YAML that runs these lanes: use `kmp-ci-github-actions`.
- Building and publishing an XCFramework / Swift package: use `kmp-xcframework-distribution`.
- A crash spike after release: use `kmp-crash-triage`.
- Security review of the release build (obfuscation, cert pinning, debug flags): use
  `mobile-security-review`.

## Step 0 — Read the project first

```bash
grep -rnE 'versionCode|versionName|applicationIdSuffix|versionNameSuffix|productFlavors' --include=build.gradle.kts .
grep -nE '^app\.|version' gradle.properties 2>/dev/null
grep -rnE 'MARKETING_VERSION|CURRENT_PROJECT_VERSION' iosApp --include='*.pbxproj' --include='*.xcconfig' 2>/dev/null
plutil -p iosApp/iosApp/Info.plist 2>/dev/null | grep -E 'CFBundle(ShortVersionString|Version)'
git tag -l | sort -V | tail -20                # existing tag scheme
ls fastlane Gemfile Gemfile.lock 2>/dev/null && cat fastlane/Fastfile 2>/dev/null
ls CHANGELOG.md 2>/dev/null
ls Package.swift 2>/dev/null                    # does this repo ship a Swift package?
```

Record: where each version number lives today, existing tag format, flavours/build configurations,
whether Fastlane exists and its lanes, whether the repo ships a Swift package. **Follow an existing
scheme** if it is consistent; propose changes only for real defects (drift, ambiguous tags).

## Workflow

### 1. Version policy

Apps and libraries both use semver `MAJOR.MINOR.PATCH` for the user-facing version:

| Change | App `versionName` / `CFBundleShortVersionString` | Library version |
|---|---|---|
| Bug fix only, no new screens or API calls | `PATCH + 1` | `PATCH + 1` |
| New feature, backwards compatible | `MINOR + 1`, `PATCH = 0` | `MINOR + 1` (new public API) |
| Breaking: removed flow, data migration, new minimum backend contract | `MAJOR + 1` | `MAJOR + 1` (any public API/ABI break) |
| Internal/test build only | unchanged | `-SNAPSHOT` / pre-release |

Build numbers are separate:

- Android `versionCode`: an integer, `+1` for **every** artifact uploaded to Play, including
  re-uploads of the same `versionName`. Never reused, never decreased. Play's maximum is
  2100000000.
- iOS `CFBundleVersion`: must increase for every upload of the same `CFBundleShortVersionString`.
  Using the Android `versionCode` value for both keeps them trivially in step.

For libraries: a published version is immutable. Never re-publish the same version with different
bytes — bump the patch. Check public API changes before choosing the bump; the
binary-compatibility-validator plugin (or the ABI validation built into newer Kotlin Gradle plugin
versions) makes breaks visible in review.

### 2. One source of truth, read by both builds

Put `app.versionName` and `app.versionCode` in `gradle.properties`. Android reads them in
`build.gradle.kts`; iOS gets them through a generated xcconfig and, in release lanes, as `xcargs`.
Full snippets — Gradle, signing from env vars, xcconfig sync script, CI drift guard — are in
[references/version-single-source.md](references/version-single-source.md).

Two rules carry most of the value:

- **`versionName` and `versionCode` move together, in the same commit.** Store ordering uses the
  code; humans, crash dashboards and any update-prompt or minimum-version logic use the name. Many
  apps also send the build number to their backend in a request header. Bump one without the
  other and those systems disagree about which build is installed.
- **Keep `versionName` clean semver in every flavour.** Distinguish `staging` from `production`
  with `applicationIdSuffix` (Android) and a per-configuration `PRODUCT_BUNDLE_IDENTIFIER` (iOS),
  not with `versionNameSuffix`.

Done when: changing the two lines in `gradle.properties` (plus the sync script) changes the version
shown by both apps.

### 3. Tag scheme

Swift Package Manager resolves versions only from tags that are valid semver, optionally prefixed
with `v`. Anything else is invisible to it. So in any repository that ships a Swift package, the
bare tags belong to the package:

| Artifact | Tag | Example |
|---|---|---|
| Swift package / XCFramework (SPM) | `vX.Y.Z` or `X.Y.Z` (match what consumers already use) | `v2.0.3` |
| Android app | `android-vX.Y.Z` | `android-v1.4.0` |
| iOS app | `ios-vX.Y.Z` | `ios-v1.4.0` |
| Maven/Gradle library from a repo that also ships SPM | `android-vX.Y.Z` (or `maven-v…`) | `android-v1.5.0` |
| Anything else | `<platform>-vX.Y.Z` | `web-v3.1.0` |

If an Android-only tag used the bare `v1.5.0`, an SPM range such as `.upToNextMajor(from: "1.0.0")`
could resolve to it and fetch a `Package.swift` pointing at the wrong binary. Use a hyphen, not a
slash (`android-v1.4.0`, not `android/v1.4.0`): slashes are treated as paths by some tools and
UIs. Use annotated tags (`git tag -a`). Tags are immutable contracts — to fix a bad release, ship
`X.Y.Z+1`; do not delete and re-push a tag.

Audit:

```bash
git tag -l 'v[0-9]*.[0-9]*.[0-9]*'            # SPM-visible
git tag -l 'android-v*' 'ios-v*'               # app tags
```

### 4. Fastlane lanes

Copy [assets/Fastfile.example](assets/Fastfile.example) to `fastlane/Fastfile`, pin `fastlane` in
a `Gemfile` (run lanes with `bundle exec fastlane …`), and adjust the TODOs. Lanes:

| Lane | Does |
|---|---|
| `android internal` | `gradle` → signed `bundleRelease` → `upload_to_play_store(track: "internal")` |
| `android promote_production rollout:0.1` | promotes the internal build to production as a staged rollout |
| `android update_rollout rollout:0.5` | raises the rollout fraction; `1` completes it |
| `ios beta` | `setup_ci` → `match(readonly: true)` → `build_app` with the shared version → `upload_to_testflight` |
| `ios release` | submits the TestFlight build for review with `phased_release: true` |

For Kotlin Multiplatform iOS builds, the Xcode build phase usually runs Gradle to build the Kotlin
framework — the machine running `build_app` needs a JDK on `PATH`.

### 5. Signing secrets never in git

- **Android:** upload keystore and passwords come from CI secrets (keystore as base64, decoded to a
  temp dir at build time). The Play service-account JSON is a secret passed as `json_key_data`.
  Enrol in Play App Signing so a lost upload key can be reset.
- **iOS:** certificates and profiles via `match` in a private repo (or cloud storage), encrypted with
  `MATCH_PASSWORD`; CI uses `readonly: true` so it never creates or revokes certificates.
  Authenticate with an App Store Connect API key (`app_store_connect_api_key`), not an Apple ID
  password with 2FA.
- `.gitignore`: `*.jks`, `*.keystore`, `*.p8`, `*.p12`, `*.mobileprovision`, service-account JSON,
  `fastlane/report.xml`, `fastlane/README.md` if generated.

**Stop and ask the user before** creating, rotating or deleting any keystore, certificate,
provisioning profile or API key, and before running `match` without `readonly`.

### 6. Release checklist

Copy this into the release issue or PR and tick it off.

```markdown
- [ ] Release branch / commit chosen; CI green on it (both platforms)
- [ ] Version bumped in gradle.properties (name + code together); iOS xcconfig synced
- [ ] CHANGELOG.md updated (user-facing notes; links to issues/PRs)
- [ ] Store "what's new" text written for Play and App Store / TestFlight
- [ ] Crash-free baseline recorded for the current production version (users and sessions)
- [ ] Android: internal track build smoke-tested on a real device
- [ ] iOS: TestFlight build smoke-tested on a real device
- [ ] R8 mapping and dSYMs uploaded to the crash reporter (or archived)
- [ ] Tags created: android-vX.Y.Z / ios-vX.Y.Z (pushed only after approval)
- [ ] Play: staged rollout started (e.g. 10 %) · App Store: phased release on
- [ ] Monitoring window: crash-free rate, ANR rate, top new crashes, reviews, backend errors
- [ ] Rollout expanded, or halted with a fix plan
```

**Rollout and monitoring.** Play staged rollouts take an explicit fraction you raise over time and
can be halted. App Store phased release spreads an update over 7 days to users with automatic
updates (1 %, 2 %, 5 %, 10 %, 20 %, 50 %, 100 %) and can be paused for up to 30 days in total;
users can still update manually. Compare the new version's crash-free users and sessions with the
baseline you recorded before expanding. Google Play's core-vitals "bad behaviour" thresholds are a
1.09 % user-perceived crash rate and 0.47 % user-perceived ANR rate overall (8 % per phone model) —
check the current values in Play Console before relying on them.

### 7. Commit and tag

```text
chore(release): bump to 1.4.0 (42)
```

Create annotated tags locally. Push commits and tags, upload to stores and start rollouts **only
after the user confirms** — each of those is visible to users or irreversible.

## Quick reference

| Item | Android | iOS |
|---|---|---|
| User-facing version | `versionName` | `CFBundleShortVersionString` ← `MARKETING_VERSION` |
| Build number | `versionCode` (int, +1 per upload) | `CFBundleVersion` ← `CURRENT_PROJECT_VERSION` (grows per upload) |
| Side-by-side environments | `applicationIdSuffix` | per-configuration `PRODUCT_BUNDLE_IDENTIFIER` |
| Tag | `android-vX.Y.Z` | `ios-vX.Y.Z` (bare `vX.Y.Z` reserved for SPM) |
| Upload | `upload_to_play_store` (`supply`) | `upload_to_testflight` (`pilot`) |
| Store release | `track_promote_to: "production"` + `rollout` | `upload_to_app_store` (`deliver`) + `phased_release` |
| Signing | upload keystore from CI secrets | `match` readonly + App Store Connect API key |

## Verify

Report each check as `PASS`, `FAIL` or `NOT RUN` with the reason. Never mark a check PASS that you
did not run.

```bash
grep -E '^app\.version(Name|Code)=' gradle.properties                    # both present
./gradlew :androidApp:assembleRelease --dry-run                           # config resolves (no signing needed for --dry-run)
bash scripts/sync-ios-version.sh && git diff --exit-code iosApp/Configuration/Version.xcconfig
xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp -showBuildSettings -configuration Release \
  | grep -E ' (MARKETING_VERSION|CURRENT_PROJECT_VERSION) ='              # macOS: matches gradle.properties
bundle exec fastlane lanes                                                # lanes parse and are listed
ruby -c fastlane/Fastfile                                                 # Ruby syntax
git tag -l 'v[0-9]*' 'android-v*' 'ios-v*'                                # scheme consistent
git ls-files | grep -iE '\.(jks|keystore|p8|p12|mobileprovision)$'      # expect no output
```

Uploads, promotions and submissions are verified only by their real run — report them `NOT RUN`
unless the user asked you to run them and you saw them succeed.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Bumping `versionName` without `versionCode` (or the reverse) | Store, crash dashboards and backend update checks disagree about the build | Both in one commit, from one file |
| `versionNameSuffix` per flavour | The version is no longer plain semver; version comparisons break | `applicationIdSuffix` only |
| iOS version typed by hand in Xcode | Drifts from Android within a release or two | xcconfig generated from `gradle.properties`; `xcargs` in release lanes |
| Reusing a `versionCode` / `CFBundleVersion` | Upload rejected | `+1` per upload, including re-uploads |
| Bare `vX.Y.Z` tags for Android in an SPM repo | SPM resolves the Android tag and fetches the wrong binary | Prefix every non-SPM tag: `android-v…` |
| `android/v1.4.0` slash tags | Some tools and UIs treat them as paths | Hyphen: `android-v1.4.0` |
| Deleting and re-pushing a tag | Consumers pinned to it now get different bytes | Ship a patch version |
| Keystore, `.p8` or service-account JSON committed | Permanent leak in history; rotation required | Secrets in CI only; `.gitignore`; scan with `git ls-files` |
| `match` without `readonly` on CI | CI can create or revoke certificates for the whole team | `readonly: true`; `setup_ci` |
| Runtime signature check lists only the upload key | Play-signed builds fail the check in production | Include the Play app signing certificate |
| 100 % rollout on day one | A crash reaches every user before you see it | Staged / phased rollout against a recorded baseline |
| No mapping file / dSYMs kept | Production stack traces cannot be symbolicated | Upload or archive them in the release job |

## Related skills

- `kmp-ci-github-actions` — the release workflow that runs these lanes with protected secrets.
- `kmp-xcframework-distribution` — Swift package and XCFramework publishing (the bare-semver tags).
- `kmp-crash-triage` — investigating a crash spike during rollout.
- `mobile-security-review` — release build hardening.
- `kmp-build-check` — the both-platform check before cutting the release.
- External: [fastlane docs](https://docs.fastlane.tools) ·
  [App Store Connect CLI skills](https://github.com/rorkai/app-store-connect-cli-skills) ·
  [Google Play CLI skills](https://github.com/tamtom/gplay-cli-skills).
