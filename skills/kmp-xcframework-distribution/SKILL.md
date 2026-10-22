---
name: kmp-xcframework-distribution
description: Use when shipping a Kotlin Multiplatform module to an iOS app — XCFramework, assembleXCFramework, embedAndSignAppleFrameworkForXcode, Swift Package Manager binaryTarget, Package.swift url and checksum, swift package compute-checksum, KMMBridge, CocoaPods to SPM, static vs dynamic framework, umbrella framework export(), missing iosX64 slice, SPM not resolving a version tag, "checksum does not match", or app targets failing to link a static Kotlin framework.
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle project with iOS targets. Needs macOS with Xcode 16 or newer and the Swift toolchain (swift package). Publishing steps need network access to the artifact host.
metadata:
  category: ios-interop
  platforms: ios
---

# Ship a KMP module to iOS

The iOS app gets exactly **one** Kotlin framework, and that framework is a contract: module name,
slices, the system libraries it needs, a version tag and a checksum. Every distribution failure is
one of those five drifting out of sync.

## When to use

- Choosing how an iOS app consumes Kotlin code: direct integration, local SPM, remote SPM binary,
  CocoaPods.
- Configuring `binaries.framework`, `XCFramework(...)`, `isStatic`, `export(...)`, targets.
- Writing or regenerating `Package.swift` with `binaryTarget(url:checksum:)`; tagging releases.
- Setting up or debugging KMMBridge publishing.
- Symptoms: checksum mismatch, SPM cannot see a new version, a slice missing for a simulator, a
  consumer app with `Undefined symbols` for a system library, two Kotlin frameworks in one app.

## When not to use

- Writing Swift that consumes the framework's API — use `kmp-swiftui-interop`.
- Diagnosing a compiler, KSP or Gradle failure that happens before any framework exists — use
  `kmp-build-failure-triage`.
- Migrating an existing CocoaPods integration step by step — the official
  [CocoaPods → SPM migration skill](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-cocoapods-spm-migration)
  covers it; come back here for the SPM packaging details.

## Step 0 — Read the project first

```bash
# Current integration mode
grep -rn "embedAndSignAppleFrameworkForXcode" --include=project.pbxproj .
find . -name Package.swift -not -path "*/.build/*" -not -path "*/build/*" -exec grep -ln binaryTarget {} +
ls Podfile *.podspec 2>/dev/null; grep -rn "cocoapods {" --include=*.gradle.kts .

# Framework definition: name, static/dynamic, targets, exports, bundle id, linker options
grep -rn -B3 -A20 "binaries.framework\|XCFramework(" --include=*.gradle.kts .

# Publishing tooling and versions
grep -rn "kmmbridge\|co.touchlab.skie\|maven-publish" --include=*.gradle.kts --include=*.toml .
grep -rn "VERSION" gradle.properties 2>/dev/null
git tag -l | tail -20

# System libraries the Kotlin code needs at link time (SQLite drivers are the usual one)
grep -rn "linkerOpts\|NativeSQLiteDriver\|BundledSQLiteDriver\|sqlite-bundled\|native-driver" \
  --include=*.gradle.kts --include=*.kt --include=*.toml . | head -20
```

Record: framework `baseName`, `isStatic`, declared iOS targets, exported modules, who consumes the
framework (same repo or separate repos), where artifacts are hosted, the tag scheme already in use,
and every system library or framework the Kotlin code links against. If CI exists, read its publish
job before changing anything — it is the source of truth for the release sequence.

**Follow what exists.** Change integration mode only when the user asks or the current mode cannot
meet the need.

## Workflow

### 1. Choose the integration mode

| Mode | How | Best for | Watch out for |
|---|---|---|---|
| Direct integration | Xcode Run Script calls `./gradlew :shared:embedAndSignAppleFrameworkForXcode` | App and Kotlin in one repo, one team | Every iOS build runs Gradle; Xcode needs a working JDK; disable User Script Sandboxing |
| Local SPM | `binaryTarget(name:path:)` to a locally built XCFramework, or KMMBridge `spmDevBuild` | Developing a Swift package against local Kotlin | Never commit the local path |
| Remote SPM binary | `binaryTarget(name:url:checksum:)` to a zipped XCFramework, version = git tag | iOS app in a separate repo, multiple consumers, iOS devs without a JVM | Tags, checksums, hosting auth, linker settings |
| CocoaPods | Kotlin `cocoapods { }` plugin or a published podspec | Existing CocoaPods apps | CocoaPods trunk is scheduled to go read-only (announced for 2 December 2026); prefer SPM for new work |

Direct-integration run script (from the Kotlin docs), placed **before** Compile Sources, with
"Based on dependency analysis" unchecked:

```bash
if [ "YES" = "$OVERRIDE_KOTLIN_BUILD_IDE_SUPPORTED" ]; then
  echo "Skipping Gradle build task invocation due to OVERRIDE_KOTLIN_BUILD_IDE_SUPPORTED environment variable set to \"YES\""
  exit 0
fi
cd "$SRCROOT/.."
./gradlew :shared:embedAndSignAppleFrameworkForXcode
```

Set **User Script Sandboxing** (`ENABLE_USER_SCRIPT_SANDBOXING`) to `No`, then `./gradlew --stop`
once so a sandboxed daemon is not reused.

**Done when** the chosen mode and why are stated to the user.

### 2. Define one umbrella framework

```kotlin
// shared/build.gradle.kts
import org.jetbrains.kotlin.gradle.plugin.mpp.apple.XCFramework

kotlin {
    val frameworkName = "SharedKit"
    val xcf = XCFramework(frameworkName)

    listOf(iosArm64(), iosSimulatorArm64() /*, iosX64() — see below */).forEach { target ->
        target.binaries.framework {
            baseName = frameworkName            // the Swift module name: `import SharedKit`
            isStatic = true
            binaryOption("bundleId", "com.example.app.SharedKit")
            export(project(":feature:notes"))   // public API of these modules appears in Swift
            export(libs.kotlinx.datetime)       // only if its types are part of your Swift API
            xcf.add(this)
        }
    }

    sourceSets {
        commonMain.dependencies {
            api(project(":feature:notes"))      // export(...) requires an api(...) dependency
            api(libs.kotlinx.datetime)
        }
    }
}
```

- **One Kotlin framework per app.** Several Kotlin frameworks each carry their own runtime and their
  own copies of shared types, and two *static* ones can collide on duplicate symbols. Combine
  modules into one umbrella module and `export` the ones Swift needs.
- **`export(...)` needs `api(...)`** in the source set that compiles for iOS. With only `api`,
  Android builds fine and the iOS framework silently lacks the module's API (types show up prefixed,
  or not at all). Add both in the same change.
- An umbrella module with no sources of its own needs one Kotlin file, or Gradle cannot assemble
  its framework.
- Avoid `transitiveExport = true`: it exports every transitive dependency and grows link time and
  binary size.
- Set `bundleId` explicitly. Otherwise Kotlin/Native warns that it cannot infer one and falls back
  to the framework name; an explicit id also avoided a `create-xcframework` failure observed with
  SKIE-processed frameworks.
- **Targets.** `iosArm64` (devices) and `iosSimulatorArm64` (Apple-silicon simulators) are the
  baseline. Add `iosX64` only if someone runs the simulator on an Intel Mac — commonly a CI or
  device-farm host. It costs a full extra slice of compile and link time on every release build, and
  without it those hosts fail with a missing-module error for `x86_64-apple-ios-simulator`. Document
  the reason next to the target so nobody "optimises" it away.

### 3. Choose static or dynamic deliberately

| | Static (`isStatic = true`) | Dynamic |
|---|---|---|
| Linking | Archive linked into the app binary by Xcode | Separate dylib, embedded and signed |
| Launch time | No extra dylib load | Extra dylib to load |
| System libraries the Kotlin code needs (e.g. `sqlite3`) | **The consumer's link must provide them** — Kotlin-side `linkerOpts` do not travel with the archive through an SPM `binaryTarget` | Linked into the dylib by Kotlin/Native |
| Duplicate symbols | Possible if two static Kotlin frameworks, or a library linked twice | Isolated, but still one runtime per framework |
| Xcode setting | Do not embed | Embed & Sign |

Static is the common default (and what the Kotlin SPM-export docs show). If you pick static,
record the system libraries consumers must link — step 5 handles it.

### 4. Build and inspect the XCFramework

```bash
./gradlew :shared:assembleSharedKitReleaseXCFramework     # release only
./gradlew :shared:assembleSharedKitDebugXCFramework       # fast local iteration
./gradlew :shared:assembleXCFramework                     # every XCFramework, both build types
# output: shared/build/XCFrameworks/release/SharedKit.xcframework
```

The task name embeds the `XCFramework("SharedKit")` name; list them with
`./gradlew :shared:tasks --all | grep -i xcframework`. KMMBridge registers the same task for its
`frameworkName`.

Check the slices before publishing:

```bash
plutil -p shared/build/XCFrameworks/release/SharedKit.xcframework/Info.plist | grep -E "LibraryIdentifier|SupportedArchitectures" -A3
```

**Done when** every slice your consumers need (device arm64, simulator arm64, and x86_64 if
required) is listed.

### 5. Package for SPM

```bash
cd shared/build/XCFrameworks/release
ditto -c -k --sequesterRsrc --keepParent SharedKit.xcframework SharedKit.xcframework.zip
swift package compute-checksum SharedKit.xcframework.zip
```

`Package.swift` (remote binary). A `binaryTarget` accepts only a name, a location and a checksum —
**it cannot carry linker settings or dependencies**. When the static framework needs a system
library, add a thin wrapper target that does:

```swift
// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "SharedKit",
    platforms: [.iOS(.v15)],
    products: [
        // Both targets: the binary provides the module, the wrapper carries the linker settings.
        .library(name: "SharedKit", targets: ["SharedKit", "SharedKitWrapper"]),
    ],
    targets: [
        .binaryTarget(
            name: "SharedKit",
            url: "https://example.com/releases/1.4.0/SharedKit.xcframework.zip",
            checksum: "<output of swift package compute-checksum>"
        ),
        // Only needed when the static framework uses system libraries.
        .target(
            name: "SharedKitWrapper",
            dependencies: ["SharedKit"],
            path: "Sources/SharedKitWrapper",          // contains one small .swift file
            linkerSettings: [.linkedLibrary("sqlite3")]
        ),
    ]
)
```

If the binary is consumed by an intermediate Swift package instead, put
`linkerSettings: [.linkedLibrary("sqlite3")]` on that package's target. Prefer package-level
`linkerSettings` over asking every host app to edit `OTHER_LDFLAGS`. More templates (local path,
consumer wiring, CI script): [references/package-swift-templates.md](references/package-swift-templates.md).

### 6. Version and tag

- SPM resolves versions from **git tags that are semantic versions**. A leading `v` (`v1.4.0`) is
  accepted by SwiftPM and Xcode, but plain `1.4.0` is the recommended form. Tags that are not
  semver are invisible to SPM.
- In a repo that publishes several platforms, reserve the bare semver slot for the SPM release and
  **prefix every other platform's tags** (`android-v1.4.0`, `web-v1.4.0`). Otherwise
  `.upToNextMajor(from: "1.0.0")` can resolve to an Android-only tag whose `Package.swift` points
  at a different or missing XCFramework. Use a hyphen, not a slash.
- The `Package.swift` committed **at the tag** must reference the zip built for that version. Commit
  the manifest, then tag that commit.
- **Never move or reuse a published tag.** Consumers' `Package.resolved` and SwiftPM's fingerprint
  store remember it; re-tagging produces fingerprint or checksum failures for everyone. Bump the
  patch version instead.
- The Kotlin docs recommend keeping `Package.swift` in a **separate repository** from the Kotlin
  sources when the Kotlin repo has its own tags. If you keep it in the same repo, the prefix rule
  above is mandatory.

### 7. Publish (KMMBridge or your own CI)

[KMMBridge](https://touchlab.co/kmmbridge/) automates most of steps 4–6: build the XCFramework,
upload the zip, and write `Package.swift` with url and checksum. With GitHub Releases, its workflow
also creates the release and its tag; with other hosts, check who tags.

```toml
# gradle/libs.versions.toml — use the current release from the KMMBridge docs
[versions]
kmmbridge = "…"

[plugins]
kmmbridge = { id = "co.touchlab.kmmbridge", version.ref = "kmmbridge" }
```

```kotlin
// shared/build.gradle.kts
plugins {
    alias(libs.plugins.kmmbridge)
}

kmmbridge {
    frameworkName.set("SharedKit")
    gitHubReleaseArtifacts()   // or mavenPublishArtifacts() with a maven-publish repository
    spm()
}
```

- Publish with `./gradlew kmmBridgePublish`; local SPM development with
  `./gradlew spmDevBuild -PspmBuildTargets=ios_simulator_arm64`.
- Artifact managers: GitHub Releases, Maven repositories (including GitHub Packages), public S3, or
  a custom `ArtifactManager`. Private hosts need credentials on the consumer side (`~/.netrc` or the
  keychain).
- KMMBridge 0.3.x used plugin id `co.touchlab.faktory.kmmbridge` and a different DSL; follow the
  docs for the version you install.
- A valid alternative: let KMMBridge only register the assemble task and `spm()` manifest
  generation, and do upload + manifest commit + tag in your own CI job. Keep that job idempotent: a
  re-run must not re-tag an existing version.
- Keep the Kotlin, SKIE and KMMBridge versions compatible and bump them together.

### 8. Wire the consumer

Xcode → File → Add Package Dependencies → the package URL and version rule → add the `SharedKit`
product to the app target → `import SharedKit`. Match the app's deployment target to the package's
`platforms`. For a static framework, do not also add it under "Embed Frameworks".

## Quick reference

| Task | Command |
|---|---|
| List XCFramework tasks | `./gradlew :shared:tasks --all \| grep -i xcframework` |
| Release XCFramework | `./gradlew :shared:assembleSharedKitReleaseXCFramework` |
| Single simulator framework (fast) | `./gradlew :shared:linkDebugFrameworkIosSimulatorArm64` |
| Zip (keeps symlinks) | `ditto -c -k --sequesterRsrc --keepParent SharedKit.xcframework SharedKit.xcframework.zip` |
| Checksum | `swift package compute-checksum SharedKit.xcframework.zip` |
| Validate manifest | `swift package reset && swift package show-dependencies --format json` |
| SPM-visible tags | `git tag -l '[0-9]*.[0-9]*.[0-9]*' 'v[0-9]*.[0-9]*.[0-9]*'` |
| Purge SwiftPM global cache | `swift package purge-cache` (ask first) |
| KMMBridge publish | `./gradlew kmmBridgePublish` |

Failure symptoms and fixes (checksum mismatch, stale caches, missing slices, auth, undefined
symbols in the consumer): [references/troubleshooting.md](references/troubleshooting.md).

## Verify

Report each as `PASS`, `FAIL` or `NOT RUN` (with the reason). Never mark a check passed that did not
run. No macOS/Xcode → every check below is `NOT RUN — requires macOS with Xcode`.

1. **Build:** `./gradlew :shared:assembleSharedKitReleaseXCFramework` succeeds.
2. **Slices:** `plutil -p …/SharedKit.xcframework/Info.plist` lists every required slice.
3. **API present:** the exported module's types appear unprefixed in
   `…/ios-arm64/SharedKit.framework/Headers/SharedKit.h` (`grep -n "NotesRepository"`).
4. **Checksum:** recompute it on the exact zip that was uploaded; it equals the `checksum:` in the
   tagged `Package.swift`.
5. **Download:** `curl -fsIL "<zip url>"` returns 200 (with credentials if private).
6. **Manifest:** `swift package reset && swift package show-dependencies --format json` succeeds in
   the package repo.
7. **Consumer build, both destinations:**
   `xcodebuild -scheme <App> -destination 'generic/platform=iOS Simulator' build` and
   `xcodebuild -scheme <App> -destination 'generic/platform=iOS' build CODE_SIGNING_ALLOWED=NO`.
   A missing system library shows up here as `Undefined symbols`.
8. **Tag:** `git ls-remote --tags origin <version>` shows the tag on the commit whose
   `Package.swift` has the new url and checksum.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Two Kotlin frameworks in one app | Duplicate runtimes and types; static ones can clash at link time | One umbrella framework with `export(...)` |
| `export(x)` without `api(x)` (or the reverse) | Android is fine; iOS silently lacks the API | Add both together; check the header |
| `-lsqlite3` only in Gradle `linkerOpts` of a static framework shipped via SPM | The binary target does not carry it; consumers fail with `Undefined symbols … _sqlite3_…` | Wrapper target with `linkerSettings: [.linkedLibrary("sqlite3")]` |
| Re-tagging an existing version with a new zip | Checksum and fingerprint mismatch for every consumer | Bump the patch version |
| Bare `vX.Y.Z` tags for both Android and iOS in one repo | SPM resolves an Android tag; wrong or missing XCFramework | Bare semver for SPM only; `android-vX.Y.Z` for others |
| Committing a local `path:` binary target or `spmDevBuild` output | CI and teammates cannot resolve the package | Keep local manifests out of release commits |
| Dropping `iosX64` to save build time while an Intel CI host runs simulators | Those builds lose the module | Keep it, with a comment saying who needs it |
| `zip -r` that dereferences framework symlinks | Corrupt or oversized framework bundle | `ditto -c -k --sequesterRsrc --keepParent` (or `zip -ry`) |
| Checksum computed before a re-zip | Checksum no longer matches the uploaded file | Compute on the exact uploaded artifact |
| `transitiveExport = true` "to make types appear" | Bloats the API, link time and size | Export the specific modules |

## Related skills

- `kmp-swiftui-interop` — consuming the framework from SwiftUI.
- `kmp-build-failure-triage` — link errors, Xcode run-script failures, Kotlin/Native memory and caches.
- `mobile-release` — versioning and release process across Android and iOS.
- `kmp-ci-github-actions` — running the XCFramework build and publish job in CI on macOS runners.
- `kmp-gradle-version-catalog` — keeping Kotlin, SKIE and KMMBridge versions aligned.
- [Kotlin CocoaPods → SPM migration skill](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-cocoapods-spm-migration)
  and [Kotlin/Native build performance skill](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-native-build-performance).
- [MobileBuildMCP](https://github.com/getsentry/MobileBuildMCP) (formerly XcodeBuildMCP) — build and
  test the consumer app from an agent.
- Docs: [Kotlin SPM export](https://kotlinlang.org/docs/multiplatform/multiplatform-spm-export.html),
  [direct integration](https://kotlinlang.org/docs/multiplatform/multiplatform-direct-integration.html),
  [native binaries and XCFrameworks](https://kotlinlang.org/docs/multiplatform/multiplatform-build-native-binaries.html),
  [KMMBridge](https://touchlab.co/kmmbridge/).
