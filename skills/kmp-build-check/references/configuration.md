# kmp-build-check configuration

- [File location and shape](#file-location-and-shape)
- [Check fields](#check-fields)
- [Qualified and unqualified tasks](#qualified-and-unqualified-tasks)
- [Example: app repository](#example-app-repository)
- [Consumers: validating a library change](#consumers-validating-a-library-change)
- [Clean builds and untracked files](#clean-builds-and-untracked-files)
- [Results JSON](#results-json)

## File location and shape

`kmp-build-check.json` sits next to `gradlew`. Use `--config PATH` to point the tool at another file.
The file is plain JSON. It has no comments, but any key that starts with `_` is ignored, so use
`"_comment"` to explain a choice.

```json
{
  "version": 1,
  "checks": [ { "name": "...", "platform": "...", "task": "..." } ],
  "consumers": [ { "name": "...", "path": "...", "args": ["..."], "task": "..." } ]
}
```

`--validate` reports every problem at once: unknown keys, duplicate names, a bad platform, or a
string that is not a Gradle task path.

## Check fields

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Label in the report. Must be unique. |
| `platform` | yes | `any`, `android` or `ios`. `android` checks need an Android SDK. `ios` checks need macOS and Xcode. `--only` filters on this field. |
| `task` | yes | One Gradle task: `:shared:jvmTest` (one module) or `jvmTest` (every module that has it). |
| `kind` | no | `common`, `android_build`, `unit_test`, `ios_compile`, `ios_link`, `ios_test` or `other`. It is inferred from the task name when left out. Set it when the inference is wrong, for example for a custom aggregate task. |

The kind drives `--base` scoping and the host checks. An `ios_test` check also needs a simulator
runtime. An `ios_link` or `ios_compile` check needs only Xcode.

## Qualified and unqualified tasks

- `:shared:testAndroidHostTest` runs in one module. If that module lacks the task, the check FAILs
  with "configured task not found". This is deliberate: a stale config is a problem to fix, not
  something to skip.
- `testAndroidHostTest` (no leading colon or module path) runs in **every** module that has the task.
  Gradle fails only when no module has it. `--detect` prefers this form for common compiles, tests
  and links, because one check then covers a multi-module build.
- With `--base`, the tool narrows test checks to `:<changedModule>:<task>`. When a changed module lacks
  that task, the narrowed check is NOT RUN ("does not exist in this build"), not FAIL.

## Example: app repository

```json
{
  "version": 1,
  "checks": [
    { "name": "KMP common compile",        "platform": "any",     "task": "compileCommonMainKotlinMetadata" },
    { "name": "Android assemble",          "platform": "android", "task": ":composeApp:assembleDevDebug" },
    { "name": "Unit tests (Android host)", "platform": "android", "task": "testAndroidHostTest" },
    { "name": "Unit tests (JVM)",          "platform": "any",     "task": "jvmTest" },
    { "name": "iOS framework link",        "platform": "ios",     "task": "linkDebugFrameworkIosSimulatorArm64" },
    { "name": "iOS simulator tests",       "platform": "ios",     "task": "iosSimulatorArm64Test" }
  ]
}
```

Notes:

- Pick **one** flavour for the assemble check. Plain `assembleDebug` builds every flavour's debug
  variant.
- A library that ships a klib and declares no `framework {}` has no link task. Use
  `compileKotlinIosSimulatorArm64` (kind `ios_compile`) instead.
- Use `iosSimulatorArm64Test` on Apple-silicon Macs and `iosX64Test` on Intel Macs. `iosArm64Test`
  builds a device binary that the Mac cannot run.

## Consumers: validating a library change

In a library repository, the apps that depend on the library normally resolve the **published**
artifact, so your local edit never reaches them. To test the edit, each consumer declares a Gradle
property. When the property is set, the consumer swaps the published artifact for your checkout with
a composite build:

```kotlin
// In the CONSUMER's settings.gradle.kts
val useLocalNotesCore = providers.gradleProperty("local.notes-core").orNull == "true"
if (useLocalNotesCore) {
    includeBuild("../notes-core") {
        dependencySubstitution {
            // the coordinate the consumer depends on  ->  the library's project inside that build
            substitute(module("com.example:notes-core")).using(project(":core"))
        }
    }
}
```

Then list the consumer in the library's `kmp-build-check.json`:

```json
"consumers": [
  {
    "name": "notes-app",
    "path": "../notes-app",
    "args": ["-Plocal.notes-core=true"],
    "task": ":shared:compileCommonMainKotlinMetadata"
  }
]
```

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Label in the report |
| `path` | yes | The consumer's Gradle root, relative to the library's Gradle root |
| `task` | yes | A task in a module that **really depends on the library**. A module that does not would PASS without testing anything. |
| `args` | no | Extra Gradle arguments, usually the substitution property |
| `platform`, `kind` | no | As for checks. `platform` defaults to `any`. |

How a consumer result is decided:

- Consumer directory missing: NOT RUN, with the path.
- Run with `args` passes: PASS.
- Run with `args` fails: the tool runs the same task again **without** `args`, against the published
  library.
  - If that run passes, the local change broke the consumer: FAIL.
  - If that run also fails, the consumer was already broken: NOT RUN, marked "pre-existing breakage".
    Fix the consumer first, then judge the change.
- A consumer with no substitution property can be validated only after the library is published.
  Leave it out, and say so in the report.

## Clean builds and untracked files

If the working tree has untracked `.kt`, `.kts` or `.swift` files, the build compiles them, even
though the commit you push will not contain them. The tool prints a warning when it finds such files.
`--clean` builds a temporary `git worktree` of `HEAD` instead, copies `local.properties` (your SDK
path) into it, runs the project's checks there, and then removes the worktree. Consumers are NOT RUN
under `--clean`: they would build against the working copy, not the clean tree.

A fresh worktree has no initialised submodules. Add `--init-submodules` when the build needs one, such
as a version catalog kept in a submodule.

## Results JSON

`--json PATH` writes one document:

```json
{
  "tool": "kmp-build-check",
  "project": "/abs/path/to/repo",
  "dry_run": false,
  "scope": "3 changed file(s) since origin/main (android 1, shared 2); modules: :shared",
  "warnings": [],
  "summary": { "pass": 4, "fail": 1, "not_run": 1 },
  "results": [
    { "name": "iOS framework link", "platform": "ios", "task": "linkDebugFrameworkIosSimulatorArm64",
      "state": "FAIL", "reason": "Platform.ios.kt:12:5 Unresolved reference 'NSUUID'.", "seconds": 84.2,
      "consumer": "", "command": "./gradlew linkDebugFrameworkIosSimulatorArm64",
      "log": "/abs/path/to/repo/build/kmp-build-check/logs/project-linkDebugFrameworkIosSimulatorArm64.log" }
  ]
}
```

`scope` is `null` for an unscoped run. Logs go to `build/kmp-build-check/logs/` by default (change it
with `--logs`). Most projects already ignore `build/` in git.
