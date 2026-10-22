# iOS SQLite linking for Room KMP

Room on iOS talks to SQLite through a driver. Which SQLite ends up in the shipped app is decided by
the linker, not by your Kotlin code — so check the artifact, not just the build result.

## Contents

1. [Two drivers, two rules](#1-two-drivers-two-rules)
2. [Where -lsqlite3 comes from](#2-where--lsqlite3-comes-from)
3. [Check what you actually shipped](#3-check-what-you-actually-shipped)
4. [Symptoms and causes](#4-symptoms-and-causes)
5. [When two SQLite users must coexist](#5-when-two-sqlite-users-must-coexist)
6. [SPM and XCFramework consumers](#6-spm-and-xcframework-consumers)

## 1. Two drivers, two rules

| | `BundledSQLiteDriver` (`androidx.sqlite:sqlite-bundled`) | `NativeSQLiteDriver` (`androidx.sqlite:sqlite-framework`) |
|---|---|---|
| SQLite used | A copy compiled into the klib — same version on Android, iOS and JVM | The OS library, `/usr/lib/libsqlite3.dylib` |
| `-lsqlite3` | **Do not add** | **Required**, on every binary |
| Gradle | nothing | `binaries.all { linkerOpts("-lsqlite3") }` inside each iOS target |

```kotlin
// shared/build.gradle.kts — only for NativeSQLiteDriver
kotlin {
    listOf(iosArm64(), iosSimulatorArm64()).forEach { target ->
        // binaries.all, not binaries.framework: test executables link too,
        // and iosSimulatorArm64Test fails with undefined _sqlite3_ symbols otherwise.
        target.binaries.all { linkerOpts("-lsqlite3") }
    }
}
```

`room-runtime` depends on `sqlite-framework` transitively on iOS, but that klib does not add
`-lsqlite3` for iOS targets; with the bundled driver nothing in Room's dependency graph needs the
system library.

## 2. Where -lsqlite3 comes from

When the bundled driver is in use and the system library still shows up, it came from one of these:

| Source | Where to look |
|---|---|
| Your own build script | `grep -rn "lsqlite3" --include=*.gradle.kts .` — often left over from a `NativeSQLiteDriver` era |
| A Gradle plugin | SQLDelight's native setup links SQLite automatically for dynamic frameworks (`linkSqlite`, default `true`) |
| The Xcode app target | Build Settings → Other Linker Flags; Build Phases → Link Binary With Libraries → `libsqlite3.tbd` |
| Swift packages and pods | `linkerSettings: [.linkedLibrary("sqlite3")]`, podspec `libraries`, or any library that uses system SQLite |

## 3. Check what you actually shipped

**Bundled SQLite present in the framework?** A defined `_sqlite3_sourceid` means the bundled copy is
inside:

```bash
FW=shared/build/bin/iosArm64/releaseFramework/Shared.framework/Shared    # adjust name and path
nm -gU "$FW" | grep -c " _sqlite3_sourceid$"        # ≥ 1: bundled copy present
otool -L "$FW" 2>/dev/null | grep -i sqlite          # dynamic framework: lists libsqlite3.dylib if linked
```

A static framework is an `ar` archive; `nm` lists each member and `otool -L` prints nothing useful —
check the app binary after the Xcode link instead.

**Which SQLite runs?** Log it once in debug builds:

```kotlin
// commonMain — debug diagnostics
suspend fun AppDatabase.sqliteVersion(): String =
    useReaderConnection { connection ->
        connection.usePrepared("SELECT sqlite_version()") { statement ->
            statement.step()
            statement.getText(0)
        }
    }
```

With the bundled driver the value must match on Android and iOS and change only when you upgrade
`androidx.sqlite`. A value that differs on iOS means the system library is answering.

## 4. Symptoms and causes

| Symptom | Likely cause | Fix |
|---|---|---|
| `Undefined symbols for architecture arm64: "_sqlite3_open_v2"` (or any `_sqlite3_`) when linking a framework or test binary | `NativeSQLiteDriver` without `-lsqlite3` | Add it to `binaries.all`, or switch to the bundled driver |
| `Undefined symbols ... "_sqlite3_load_extension"` with `NativeSQLiteDriver` and `-lsqlite3` | Observed with `androidx.sqlite` 2.6.2 and the iOS 26.4 SDK: the system library does not export it. The `androidx.sqlite` 2.7.0-alpha02 notes list a fix for missing symbols with `NativeSQLiteDriver` and the system library | Upgrade `androidx.sqlite`, or use the bundled driver |
| `SQLITE_MISUSE` on the first query on iOS, bundled driver configured | The bundled copy is not in the shipped binary; the system SQLite answers | Section 2: remove every `-lsqlite3`; verify with section 3 |
| Works in a local debug build, fails in the CI-built release framework | Linker and toolchain differences between machines | Check the artifact CI produces, not the local one |

The `SQLITE_MISUSE` case is **observed, not universal**: in one production app with a large static
umbrella framework, `-lsqlite3` on the link line made the release link drop the bundled SQLite, and
the system SQLite of iOS 26 then rejected Room's statements with `SQLITE_MISUSE`. A small test
project linked the same way can keep both copies and behave. Treat the combination as a risk you
remove, not one you test away.

## 5. When two SQLite users must coexist

If the app genuinely needs both — Room with the bundled driver plus a library that requires the
system SQLite:

1. **Never let two SQLite copies open the same database file.** SQLite's own documentation lists
   "multiple copies of SQLite linked into the same application" as a way to corrupt a database: the
   copies do not share POSIX lock state. Give each its own file.
2. Prefer removing the second consumer, or turning off its automatic system link where the library
   allows it.
3. Last resort, observed in one production project: force-load the bundled static archive so its
   symbols are always present in the framework — `-Wl,-force_load,<path to libandroidXBundledSqlite.a>`,
   where the archive is extracted from the resolved `sqlite-bundled` cinterop klib for each iOS
   target. A `-u _sqlite3_sourceid` linker flag alone did not help there, because the system
   library satisfies it. Verify the result with section 3 on the artifact you ship.

## 6. SPM and XCFramework consumers

A Swift Package `binaryTarget` cannot carry linker flags.

- **Bundled driver:** consumers add nothing — and must not add `sqlite3` themselves.
- **Native driver:** every consuming target needs `linkerSettings: [.linkedLibrary("sqlite3")]` in
  `Package.swift` (or `-lsqlite3` in Other Linker Flags), or the app fails to link with undefined
  `_sqlite3_` symbols.
