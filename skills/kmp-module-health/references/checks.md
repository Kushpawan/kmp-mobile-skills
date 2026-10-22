# Module health checks: commands and criteria

Set `M` to the module directory and run commands from the repository root. All commands are
read-only. They are written for bash and zsh; keep the quotes around glob patterns, or zsh stops
with "no matches found".

```bash
M=feature/notes/logic
```

## Contents

- [C0. Inventory](#c0-inventory)
- [C1. Source sets and targets](#c1-source-sets-and-targets)
- [C2. commonMain purity](#c2-commonmain-purity)
- [C3. expect/actual](#c3-expectactual)
- [C4. Boundaries and dependency direction](#c4-boundaries-and-dependency-direction)
- [C5. Public API surface](#c5-public-api-surface)
- [C6. Tests](#c6-tests)
- [C7. Build configuration](#c7-build-configuration)
- [C8. Documentation](#c8-documentation)

## C0. Inventory

```bash
sed -n '1,/^kotlin/p' "$M/build.gradle.kts"                       # plugins block
grep -nE 'iosArm64|iosSimulatorArm64|iosX64|androidTarget|android \{|jvm\(|wasmJs|js\(' "$M/build.gradle.kts"
find "$M/src" -name '*.kt' | sed -E 's#^.*/src/([^/]+)/.*#\1#' | sort | uniq -c   # files per source set
grep -nE '(api|implementation|compileOnly)\(' "$M/build.gradle.kts"
```

Write down: role, targets, plugins, source sets, direct dependencies.

## C1. Source sets and targets

```bash
find "$M/src" -mindepth 1 -maxdepth 1 -type d | sort
```

| Finding | Severity |
|---|---|
| Module uses `com.android.kotlin.multiplatform.library` and has `src/androidUnitTest`, `src/androidInstrumentedTest`, `src/test`, `src/main` or `src/androidTest` — the plugin reads only `androidMain`, `androidHostTest`, `androidDeviceTest`, so those files are silently ignored | High |
| Code duplicated across `iosArm64Main` / `iosSimulatorArm64Main` / `iosX64Main` instead of living once in `iosMain` | Medium |
| A source-set directory for a target the module does not declare (dead code) | Medium |
| A declared target with no consumer (for example `iosX64` nobody builds) | Low; ask before recommending removal, some teams need Intel-Mac simulators |

## C2. commonMain purity

```bash
grep -rnE '^import (android|java|javax|dalvik|sun|platform)\.' "$M/src/commonMain"
grep -rnE '^import androidx\.' "$M/src/commonMain"            # review: is each artifact multiplatform?
grep -rnE '\b(println|print|Log\.[vdiwe]|NSLog)\(|System\.(out|err)' "$M/src/commonMain"
grep -rlE '@Composable|import androidx\.compose|import org\.jetbrains\.compose' "$M/src/commonMain"
grep -rnE 'Dispatchers\.(IO|Default|Main)' "$M/src/commonMain"
```

| Finding | Severity |
|---|---|
| `android.*`, `java.*`, `javax.*`, `platform.*` import in `commonMain` (confirm with `compileCommonMainKotlinMetadata`) | Critical |
| Compose in a module whose output SwiftUI consumes | High |
| `println` / `Log` / `NSLog` where the project has a logger | Medium (High if it can print personal data or tokens) |
| Hardcoded dispatchers in a project that injects them for tests | Medium |
| `androidx.*` import of an Android-only artifact | Critical (it will not compile for iOS); multiplatform ones are fine |

## C3. expect/actual

Inventory every `expect` and where its `actual`s live:

```bash
grep -rhoE 'expect +(fun|val|var|class|object|interface|enum +class|annotation +class) +[A-Za-z0-9_]+' \
  "$M/src/commonMain" | awk '{print $NF}' | sort -u | while read -r name; do
    where=$(grep -rlE "actual .*\b${name}\b" "$M/src" --include='*.kt' | grep -v /commonMain/ \
      | sed -E 's#^.*/src/([^/]+)/.*#\1#' | sort -u | tr '\n' ' ')
    echo "$name -> ${where:-NONE}"
  done
```

Read the output against the declared targets. Android needs `androidMain` (or a JVM intermediate
set that feeds it). Each iOS target needs the `actual` in `iosMain`, `appleMain`, `nativeMain`, or in
**every** per-architecture set. `Clock -> androidMain iosArm64Main` means the simulator targets lack
it. The snippet is a heuristic (extension functions and generics can confuse it); the compile tasks
are authoritative.

| Finding | Severity |
|---|---|
| No `actual` on the path of a declared target | Critical |
| `actual` only in one per-architecture set | Critical for the missing targets |
| `expect class` / `expect object` with many members or state, where an interface + DI would allow fakes | Medium |
| `-Xexpect-actual-classes` set but no expect/actual classes remain | Low |

## C4. Boundaries and dependency direction

Project dependencies of one module:

```bash
grep -nE 'project\(|projects\.' "$M/build.gradle.kts"
```

Whole-build graph with feature → feature edges, `:core` → upper-layer edges and cycles (adjust the
`feature` naming rule and the upper-layer module names to the project):

```bash
python3 - <<'EOF'
import pathlib, re
root = pathlib.Path(".")
edges = {}
for f in root.rglob("build.gradle.kts"):
    if any(part in ("build", ".gradle", "build-logic", "buildSrc") for part in f.parts):
        continue
    rel = f.parent.relative_to(root).as_posix()
    module = ":" if rel == "." else ":" + rel.replace("/", ":")
    text = f.read_text(encoding="utf-8", errors="replace")
    deps = set(re.findall(r'project\(\s*"(:[^"]+)"\s*\)', text))
    # Type-safe accessors; hyphenated project names appear camelCased and may not map back exactly.
    deps |= {":" + d.replace(".", ":") for d in re.findall(r'\bprojects\.([A-Za-z0-9_.]+)', text)}
    edges[module] = sorted(deps - {module})

def feature(m):
    parts = m.split(":")
    return parts[2] if len(parts) > 2 and parts[1] == "feature" else None

UPPER = {":shared", ":app", ":androidApp", ":composeApp"}
for m, deps in sorted(edges.items()):
    for d in deps:
        if feature(m) and feature(d) and feature(m) != feature(d):
            print(f"FEATURE->FEATURE {m} -> {d}")
        if m.startswith(":core") and (feature(d) or d in UPPER):
            print(f"CORE->UPPER      {m} -> {d}")

seen, stack, cycles = set(), [], set()
def visit(m):
    if m in stack:
        cycles.add(" -> ".join(stack[stack.index(m):] + [m])); return
    if m in seen:
        return
    seen.add(m); stack.append(m)
    for d in edges.get(m, []):
        visit(d)
    stack.pop()
for m in sorted(edges):
    visit(m)
for c in sorted(cycles):
    print(f"CYCLE            {c}")
EOF
```

Umbrella framework parity (Shape B projects): every module Swift uses must appear in both lists.

```bash
U=shared/build.gradle.kts
diff <(grep -oE 'api\(project\("[^"]+"\)\)' "$U" | grep -oE '":[^"]+"' | sort -u) \
     <(grep -oE 'export\(project\("[^"]+"\)\)' "$U" | grep -oE '":[^"]+"' | sort -u)
```

Lines prefixed `<` are `api` without `export` (Swift cannot see them); `>` are `export` without
`api` (the build fails).

| Finding | Severity |
|---|---|
| Dependency cycle | Critical |
| Module Swift calls is `api` but not `export`ed | Critical |
| Feature → feature dependency | High |
| `:core` module depends on a feature or the app | High |
| `api(...)` for a dependency whose types do not appear in the public API | Medium |

## C5. Public API surface

```bash
grep -nE 'explicitApi' "$M/build.gradle.kts" build.gradle.kts build-logic -r 2>/dev/null
grep -rnE '^(public )?((data|sealed|abstract|open|value|enum) )*(class|interface|object) \w*(Impl|Dto|DTO|Entity)\b' "$M/src/commonMain"
grep -rnE '^\s*(public )?val \w+\s*(:|=)\s*Mutable(StateFlow|SharedFlow)' "$M/src/commonMain"
grep -rnE 'abiValidation|binary-compatibility-validator|apiValidation' "$M/build.gradle.kts" build.gradle.kts gradle/libs.versions.toml
ls "$M/api" 2>/dev/null
```

ABI tooling: the Kotlin Gradle plugin has built-in, experimental ABI validation
(`kotlin { abiValidation { } }`, tasks `checkKotlinAbi` / `updateKotlinAbi`; older 2.2.x releases
named them `checkLegacyAbi` / `updateLegacyAbi`). Projects on the standalone
`org.jetbrains.kotlinx.binary-compatibility-validator` plugin use `apiCheck` / `apiDump`. Either is
fine; the finding is a published library with neither.

Swift-facing modules (exported from an iOS framework) — check what Swift will receive:

| Pattern | Consequence in Swift |
|---|---|
| A function that can throw, without `@Throws` | A Kotlin exception crossing into Swift terminates the app; `suspend` functions declare only `CancellationException` implicitly |
| Generic Kotlin *interfaces* | Objective-C generics exist only on classes; type parameters are lost |
| Default arguments | Not visible through the Objective-C header; Swift passes every argument |
| `Flow` / `suspend` / sealed hierarchies without SKIE or wrappers | Callback-style APIs and non-exhaustive `switch` in Swift |

| Finding | Severity |
|---|---|
| Published library without ABI validation | High |
| Swift-facing API that can throw without `@Throws` | High |
| Public `Impl`/`Dto`/`Entity` types or public mutable flows | Medium |
| Library without explicit API mode (`explicitApi()`) | Medium for published libraries, Low otherwise |

## C6. Tests

```bash
find "$M/src" -path '*Test*' -name '*.kt' | sed -E 's#^.*/src/([^/]+)/.*#\1#' | sort | uniq -c
for f in $(find "$M/src/commonMain" -name '*ViewModel.kt' -o -name '*UseCase.kt' -o -name '*RepositoryImpl.kt' -o -name '*Mapper.kt'); do
  n=$(basename "$f" .kt); find "$M/src" -path '*Test*' -name "${n}Test.kt" | grep -q . || echo "untested: $f"
done
grep -rnE 'io\.mockk|org\.mockito' "$M/src/commonTest" 2>/dev/null
grep -rnE 'assertTrue\(true\)|assertEquals\([0-9]+, *[0-9]+( *[-+*] *[0-9]+)?\)' "$M/src" --include='*Test.kt'
grep -rnE 'Thread\.sleep|delay\([0-9]{3,}' "$M/src" --include='*Test.kt'
grep -nE 'withHostTest|withDeviceTest' "$M/build.gradle.kts"
```

| Finding | Severity |
|---|---|
| JVM-only mocking (MockK, Mockito) in `commonTest` of a module with iOS targets | Critical (iOS test compilation fails) |
| AGP KMP library plugin without `withHostTest {}` while `androidHostTest` sources exist | High |
| No `commonTest` at all for a module with business logic | High |
| Logic classes (ViewModel, use case, repository, mapper) without a test | Medium each, High if the module is published |
| Placeholder assertions or sleep/delay-based waits | Medium |
| iOS test task never run (no macOS in CI) | Medium; record as a process gap |

If the project uses Kover, `./gradlew :<module>:koverXmlReport` gives line coverage; report the
number, do not invent a target.

## C7. Build configuration

```bash
grep -nE '"[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[0-9]' "$M/build.gradle.kts"     # hardcoded coordinates
grep -nE '\) +version +"' "$M/build.gradle.kts"                              # hardcoded plugin versions
grep -nE 'namespace *=' "$M/build.gradle.kts"
grep -rnE 'namespace *= *"' --include='build.gradle.kts' . | grep -v /build/ | awk -F'"' '{print $2}' | sort | uniq -d
grep -nE '(compileSdk|minSdk|targetSdk) *= *[0-9]' "$M/build.gradle.kts"     # literal SDK levels
grep -nE 'binaries\.framework|export\(|isStatic|transitiveExport|linkerOpts|freeCompilerArgs|binaryOption' "$M/build.gradle.kts"
grep -nE 'androidResources|withHostTest|ksp[A-Z][A-Za-z0-9]*\(|add\("ksp' "$M/build.gradle.kts"
```

The bundled `catalog_drift.py` in the `kmp-gradle-version-catalog` skill can scan a whole tree for
hardcoded versions.

| Finding | Severity |
|---|---|
| Hardcoded dependency or plugin versions | High |
| Duplicate `namespace` across modules | High (AGP 9 rejects it by default) |
| KSP processor configured for some targets only | High |
| Compose resources used without `androidResources { enable = true }` (AGP KMP plugin) | High (runtime failure on Android) |
| `-lsqlite3` in linker options of a framework that also bundles SQLite (Room's `BundledSQLiteDriver`) | High; teams have observed the release link keeping the system SQLite and the app failing with `SQLITE_MISUSE` (seen with Kotlin 2.3 and iOS 26). Ask for the reason |
| Linker or compiler flags with no comment explaining them | Medium |
| Literal SDK levels where siblings read the catalog or a convention plugin | Medium |
| Plugin set differs from sibling modules of the same role | Medium |
| `transitiveExport = true` | Medium (binary size and link time) |

## C8. Documentation

```bash
ls "$M"/README* "$M"/CHANGELOG* 2>/dev/null
grep -rlE '^(public )?(class|interface|object|fun) ' "$M/src/commonMain" | while read -r f; do
  grep -q '/\*\*' "$f" || echo "no KDoc: $f"
done | head
grep -rn "$(basename "$M")" README.md docs 2>/dev/null | head -3
```

| Finding | Severity |
|---|---|
| Published library without a changelog or release notes | Medium |
| No README stating purpose, entry points and how to depend on the module | Low (Medium for published libraries) |
| Public API files with no KDoc in a published library | Low |
| Module absent from the project's architecture overview | Low |
