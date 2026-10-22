# Distribution troubleshooting

Contents

1. Symptom table
2. Cache locations and safe resets
3. SQLite: system library vs bundled copy
4. Slow release links

Quoted error text marked *(typical wording)* varies by Xcode / SwiftPM version; match on the key
phrase, not the whole line.

## 1. Symptom table

| Symptom | Likely cause | Fix |
|---|---|---|
| `checksum of downloaded artifact … does not match checksum specified by the manifest` *(typical wording)* | The zip changed after the checksum was computed (re-zipped, re-uploaded to the same URL, CDN served an old copy) | Recompute on the exact uploaded file. Never overwrite an uploaded artifact; publish a new version |
| Xcode keeps using the old binary after a "fixed" re-publish | Same version re-used; SwiftPM and Xcode cache artifacts per version | Bump the version. If you must recover locally, reset caches (section 2) |
| Fingerprint / "does not match previously recorded value" error *(typical wording)* after a tag was moved | SwiftPM records each version's revision and refuses a changed one | Do not move tags. Last resort, per developer: remove that package's entry from the fingerprint store (section 2), after asking |
| New version not offered in Xcode / "no versions … match the requirement" *(typical wording)* | Tag not pushed, not semver (`ios/1.4.0`, `release-1.4.0`), or a prefixed tag | `git ls-remote --tags origin`; tag `1.4.0` (or `v1.4.0`); prefix only other platforms |
| Version resolves but the wrong XCFramework downloads | A non-iOS release used a bare semver tag in the same repo | Re-tag non-iOS releases with a prefix going forward; publish a new iOS version |
| `Could not find module 'SharedKit' for target 'x86_64-apple-ios-simulator'; found: arm64-apple-ios-simulator` *(typical wording)* | XCFramework has no `iosX64` slice; the build host is an Intel Mac or the simulator runs as x86_64 | Add `iosX64()` (and keep it, with a comment), or build for an arm64 simulator |
| Swift members missing only on one slice (works on Apple silicon, "has no member" on an Intel simulator) | Slices built from different configurations, or one slice missing so another was picked | Build every slice in one `assemble…XCFramework` run; check `Info.plist` |
| `No such module 'SharedKit'` | Product not added to the target; binary target / framework / module names differ; package not resolved | Add the product; align names; File → Packages → Resolve Package Versions |
| `Undefined symbols for architecture arm64: "_sqlite3_…"` in the app | Static framework needs system SQLite; the binary target does not pass linker flags | Wrapper target with `linkerSettings: [.linkedLibrary("sqlite3")]` next to the binary target |
| `Undefined symbols … "_OBJC_CLASS_$_<SomeSDKClass>"` | Kotlin code links an Apple framework or a native SDK the app does not link | Add `.linkedFramework("…")` in the wrapper, or the SDK's own package |
| `duplicate symbol` errors | Two static Kotlin frameworks, or the same one linked twice (SPM *and* direct integration, or app *and* an embedded dynamic framework) | One umbrella framework; one linking point |
| `xcodebuild -create-xcframework` fails with "No 'swiftinterface' files found" *(typical wording)* | Observed with SKIE-processed frameworks when no explicit bundle id was set, and when certain exports changed the produced Swift module | Set `binaryOption("bundleId", …)`; re-check what you `export`; rebuild clean |
| Kotlin/Native warns it "Cannot infer a bundle ID" *(typical wording)* | No explicit bundle id | `binaryOption("bundleId", "com.example.app.SharedKit")` |
| 401/403/404 downloading the binary in Xcode, works in a browser | Private host; Xcode has no credentials | `~/.netrc` or keychain for the host; test with `curl -fsIL --netrc` |
| App launches, crashes with `Library not loaded: @rpath/SharedKit.framework` *(typical wording)* | Dynamic framework not embedded | Set the framework to Embed & Sign (or switch to static) |

## 2. Cache locations and safe resets

Prefer the least destructive step. **Ask the user before deleting any cache directory.**

| Location | Holds |
|---|---|
| `~/Library/Caches/org.swift.swiftpm/` | Global SwiftPM cache: repositories and downloaded artifacts |
| `~/Library/org.swift.swiftpm/` | SwiftPM configuration and security data (including fingerprints) |
| `~/Library/Developer/Xcode/DerivedData/<Project>-<hash>/SourcePackages/` | Xcode's per-project package checkouts and artifacts |

In order:

1. Xcode → File → Packages → **Resolve Package Versions**.
2. Xcode → File → Packages → **Reset Package Caches**.
3. `swift package purge-cache` (global SwiftPM cache).
4. Delete the project's `DerivedData/<Project>-<hash>` folder (ask first).
5. Only for a moved tag: remove the affected package's fingerprint entry under
   `~/Library/org.swift.swiftpm/security/` (ask first). Then fix the publishing process so it cannot
   happen again.

## 3. SQLite: system library vs bundled copy

Two ways for Kotlin code to get SQLite on iOS, and they must not be mixed by accident:

- **System SQLite** (e.g. a native driver over the OS `libsqlite3`). The app's final link needs
  `sqlite3`: `linkerOpts("-lsqlite3")` for a dynamic framework or the Kotlin test executables, and
  `linkedLibrary("sqlite3")` in the consumer package for a static framework.
- **Bundled SQLite** (e.g. `androidx.sqlite:sqlite-bundled`, as recommended for Room KMP). The
  framework carries its own SQLite. Do **not** also add `-lsqlite3`.

Observed failure (Room 2.8, androidx.sqlite 2.6, Kotlin 2.3, iOS 26): a framework using the bundled
driver *and* linking system SQLite (directly, or through a transitive dependency that adds
`-lsqlite3`) shipped without its bundled SQLite — the linker satisfied the `sqlite3_*` symbols from
the system library first and never pulled the bundled archive in. At runtime the bundled driver ran
against the OS SQLite and failed with `SQLITE_MISUSE`. It passed locally and failed only on CI's
release link.

Checks and fixes:

```bash
# A bundled SQLite defines sqlite3_sourceid inside the framework binary; system-only does not.
nm -gU SharedKit.xcframework/ios-arm64/SharedKit.framework/SharedKit | grep -c "_sqlite3_sourceid"
```

- Remove `-lsqlite3` from your own build when using the bundled driver.
- If a dependency you cannot drop still adds system SQLite, the observed fix was to force-load the
  bundled archive (`linkerOpts("-Wl,-force_load,<path to libandroidXBundledSqlite.a>")`, extracted
  from the `sqlite-bundled` cinterop klib per target) plus `linkerOpts("-u", "_sqlite3_sourceid")` as
  a loud backstop. This is fragile across library versions; re-verify with the `nm` check on every
  upgrade and add that check to the publish job.
- Put linker options that the Kotlin test executables also need in `binaries.all { }`, not only in
  `binaries.framework { }`, or `iosSimulatorArm64Test` fails to link while the framework builds.

## 4. Slow release links

Release XCFramework links of large umbrella frameworks can take tens of minutes per slice.

1. Build only the slices you ship; use debug frameworks for day-to-day work.
2. Export only modules Swift uses; never `transitiveExport = true`.
3. Give Gradle enough heap (`org.gradle.jvmargs`) — the Kotlin/Native compiler runs in the Gradle
   daemon by default.
4. Persist `~/.konan` between CI runs.
5. Last resort, observed with Kotlin 2.x: disabling two expensive whole-program optimisation phases
   with `freeCompilerArgs += "-Xdisable-phases=Devirtualization,RemoveRedundantCallsToStaticInitializersPhase"`
   cut one 30+ minute link to about 10. Phase names are compiler internals: a wrong name is
   **silently ignored**, and names change between Kotlin versions. Confirm with a temporary
   `-Xprofile-phases` that the phases no longer appear, and measure binary size and runtime
   performance before keeping it.

See also the official [Kotlin/Native build performance skill](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-native-build-performance).
