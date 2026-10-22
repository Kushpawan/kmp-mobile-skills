---
name: kmp-ci-github-actions
description: Use when setting up, fixing or speeding up GitHub Actions CI for a Kotlin Multiplatform (Android + iOS) project - .github/workflows YAML, "add CI", macos-latest or macos-15-intel runners, iosSimulatorArm64Test in CI, ~/.konan re-downloading every run, setup-gradle caching, Xcode version selection, slow or expensive macOS jobs, test or Kover reports as artifacts, or a release workflow with signing secrets.
license: Apache-2.0
compatibility: Kotlin Multiplatform Gradle project hosted on GitHub. iOS jobs use GitHub-hosted macOS runners. Versions verified October 2026.
metadata:
  category: release
  platforms: android, ios
---

# KMP CI on GitHub Actions

Split the pipeline by what each host can build: Linux runs the shared code, Android compile, host
tests and lint cheaply; macOS runs only what needs Apple tooling — the iOS framework link and the
iOS simulator tests. Signing secrets never appear in the pull-request workflow; they live in a
separate release workflow behind a protected environment.

## When to use

- Adding CI to a KMP repository, or porting a pipeline from another CI system to GitHub Actions.
- CI is slow: Kotlin/Native toolchain downloaded on every run, cold Gradle caches, macOS minutes
  burned on work Linux could do.
- iOS compile or link errors only show up after merge.
- Choosing runner labels, Xcode versions, or adding an x86_64 simulator job.
- Adding a release workflow that signs and uploads both apps.

## When not to use

- A specific build failure you need to diagnose: use `kmp-build-failure-triage`.
- A test that fails only in CI or only sometimes: use `kmp-flaky-test-triage`.
- Versioning, store tracks, Fastlane lanes and the release checklist: use `mobile-release`
  (this skill only runs those lanes).
- Slow Kotlin/Native builds in general (local and CI): see the Kotlin native build performance
  skill linked below.

## Step 0 — Read the project first

```bash
ls .github/workflows 2>/dev/null && cat .github/workflows/*.yml   # existing pipelines to extend, not replace
ls .gitlab-ci.yml bitrise.yml .circleci 2>/dev/null               # pipeline being ported
cat gradle/wrapper/gradle-wrapper.properties                       # Gradle version
grep -nE '^(kotlin|agp|android-gradle|androidGradlePlugin|kover)' gradle/libs.versions.toml
grep -rnE "jvmToolchain|JvmTarget" --include='*.kts' . | head        # JDK the build expects
cat .java-version .tool-versions 2>/dev/null
grep -rnE "iosX64|iosArm64|iosSimulatorArm64" --include=build.gradle.kts . | head
grep -nE "configuration-cache|org.gradle.caching|jvmargs" gradle.properties
find . -maxdepth 2 \( -name '*.xcodeproj' -o -name '*.xcworkspace' -o -name Gemfile -o -name fastlane \)
./gradlew :shared:tasks --all | grep -iE 'test|lint|kover|link.*Framework' | head -40
```

Record: module and task names, JDK version, iOS targets declared, whether Kover/detekt/ktlint are
applied, the Xcode project path and scheme, and whether Fastlane exists. Use the real task names in
every `run:` step.

## Workflow

### 1. Split jobs by host

| Job | Runner | Runs | Why there |
|---|---|---|---|
| `android` | `ubuntu-latest` | `compileCommonMainKotlinMetadata`, Android host tests, lint, `assembleDebug`, Kover | Cheapest runner; Apple targets are skipped automatically on Linux |
| `ios` | `macos-latest` (arm64) | `linkDebugFrameworkIosSimulatorArm64`, `iosSimulatorArm64Test`, optional `xcodebuild build` | Kotlin/Native for Apple targets needs macOS + Xcode |
| `ios-x64` (optional) | `macos-15-intel` | `iosX64Test` | Only when x86_64 simulator slices must be tested |

Run `android` and `ios` in parallel. Do not run Android work on macOS: macOS minutes cost more
and the queue is longer.

Done when: every check the team runs locally before a PR is in exactly one job.

### 2. Start from the asset

Copy [assets/ci.yml](assets/ci.yml) to `.github/workflows/ci.yml` and replace every `TODO` with the
names from Step 0. It already contains the pieces below; adjust rather than rewrite.

### 3. Java and Gradle

- `actions/setup-java@v6` with `distribution: temurin` and the JDK the build expects — usually 17 or
  21. Recent AGP and Gradle 9 need JDK 17 or newer. `java-version-file: .java-version` reads it
  from the repo instead.
- `gradle/actions/setup-gradle@v6` owns Gradle caching and validates the wrapper checksum. Do not
  also set `cache: gradle` on setup-java; two caches of the same directory waste time and quota.
- **Cache provider (decide once per organisation).** In v6 the default `enhanced` provider is a
  closed-source component under Gradle's Terms of Use (free for public repositories, preview for
  private ones). `cache-provider: basic` is MIT-licensed, built on `actions/cache`, free everywhere,
  with coarser keys. The asset uses `basic`; switch if the team accepts the terms.
- By default only the default branch writes the Gradle cache; pull requests read it. Keep that.
- **Configuration cache:** `org.gradle.configuration-cache=true` in `gradle.properties` is a
  project choice, not a CI flag. setup-gradle v6 does not persist configuration-cache entries
  between runs (its experimental support was removed), so in CI it mainly proves compatibility. Put
  all tasks in **one** Gradle invocation per job so configuration happens once.

### 4. Kotlin/Native toolchain cache

Kotlin/Native downloads its compiler and LLVM dependencies into `~/.konan` on first use — large,
and slow to fetch. setup-gradle does not cache it. Cache it with `actions/cache@v6`, keyed on the
Kotlin version read from the catalog plus runner OS and architecture:

```yaml
- name: Read Kotlin version
  id: kotlin
  run: |
    version=$(sed -nE 's/^kotlin[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' gradle/libs.versions.toml | head -n 1)
    echo "version=${version:-unknown}" >> "$GITHUB_OUTPUT"
- uses: actions/cache@v6
  with:
    path: ~/.konan
    key: konan-${{ runner.os }}-${{ runner.arch }}-${{ steps.kotlin.outputs.version }}
```

No `restore-keys`: an old Kotlin's toolchain is useless to a new one and only bloats the entry.
If the Kotlin version is not in `libs.versions.toml`, change the `sed` to read wherever it lives.

### 5. Xcode and runners

- Select Xcode explicitly with `maxim-lobanov/setup-xcode@v1` (`xcode-version: latest-stable`, or a
  pinned `'26.6'`). Pin in release workflows; the image's default Xcode moves without notice.
- `macos-latest` is arm64 (currently macOS 26); `macos-15` and `macos-26` are arm64 too. Pin a
  versioned label when an image change breaks the build.
- Intel (x86_64): `macos-15-intel` is the standard-runner label; `-large` labels are paid larger
  runners. GitHub has announced it stops supporting Intel macOS after the macOS 15 image retires
  (announced for fall 2027). Plan the x86_64 job as temporary.
- Check the [runner-images list](https://github.com/actions/runner-images) for current labels and
  the Xcode versions each image carries.

### 6. Triggers, concurrency, path filters

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

New pushes cancel the stale PR run; `main` runs always finish. Use `paths-ignore` for docs-only
changes — but if a job is a **required** status check, a skipped workflow leaves the check pending
and blocks merge. Either keep required workflows unfiltered, or filter inside the job.

Set `permissions: contents: read` at the top. Add more only to the job that needs it.

### 7. Reports as artifacts

Upload with `actions/upload-artifact@v7` and `if: ${{ !cancelled() }}` so reports survive a failing
test step:

- tests: `**/build/reports/tests/` and `**/build/test-results/`
- lint: `**/build/reports/lint-results-*.html`
- Kover: run `koverXmlReport` (and `koverHtmlReport` if wanted), upload `**/build/reports/kover/`

Use distinct artifact names per job; v4+ artifacts are immutable and a duplicate name fails.
Set `retention-days` (7 for CI is plenty).

### 8. Optional iOS app build

`linkDebugFrameworkIosSimulatorArm64` proves the framework links; it does not prove the Swift code
still compiles against the changed Kotlin API. Add the commented `xcodebuild … CODE_SIGNING_ALLOWED=NO
build` step from the asset when the iOS app has meaningful Swift code. If the Xcode project runs a
Gradle build phase, the JDK from setup-java must be set up first in that job.

### 9. Release workflow

Copy [assets/release.yml](assets/release.yml). It triggers on app tags (`android-v*`, `ios-v*`) or
a manual run, checks that the tag matches the version in `gradle.properties`, and runs the Fastlane
lanes from `mobile-release`. Rules:

- Secrets exist only in this workflow, only on a GitHub **environment** (`release`) with required
  reviewers and a deployment-branch/tag rule.
- Never trigger it from `pull_request` or `pull_request_target`; fork code must never see signing
  secrets.
- Decode the keystore into `$RUNNER_TEMP`, never into the workspace; delete it in an
  `if: always()` step.
- Keep the R8 `mapping.txt` and the iOS dSYMs as artifacts — they are needed to symbolicate crashes.
- `cache-read-only: true` on setup-gradle: release jobs must not write the shared cache.

### 10. Porting from GitLab CI

`stages` become `needs:` between jobs; `rules: changes:` become `paths`/`paths-ignore`; protected
variables become environment secrets; `tags:` selecting a macOS runner become `runs-on:` labels.

## Quick reference

| Need | Use |
|---|---|
| Checkout | `actions/checkout@v7` |
| JDK | `actions/setup-java@v6` + `distribution: temurin` |
| Gradle + cache | `gradle/actions/setup-gradle@v6` (`cache-provider: basic` or default `enhanced`) |
| `~/.konan` | `actions/cache@v6`, key on Kotlin version + `runner.os` + `runner.arch` |
| Xcode | `maxim-lobanov/setup-xcode@v1` |
| Reports | `actions/upload-artifact@v7`, `if: ${{ !cancelled() }}` |
| Ruby + Fastlane | `ruby/setup-ruby@v1` with `bundler-cache: true` |
| Linux | `ubuntu-latest` (x64) · `ubuntu-24.04-arm` (arm64) |
| macOS arm64 | `macos-latest`, `macos-26`, `macos-15` |
| macOS x86_64 | `macos-15-intel` (standard), `*-large` (paid) |

## Verify

Report each check as `PASS`, `FAIL` or `NOT RUN` with the reason. Never mark a check PASS that you
did not run.

```bash
ruby -ryaml -e 'ARGV.each { |f| YAML.safe_load(File.read(f)); puts "#{f}: ok" }' .github/workflows/*.yml   # YAML parses
python3 -c 'import sys, yaml; [yaml.safe_load(open(f)) for f in sys.argv[1:]]; print("ok")' .github/workflows/*.yml   # if PyYAML is installed
actionlint                                       # if installed: schema, expressions, shellcheck of run steps
./gradlew help --task :shared:iosSimulatorArm64Test   # every task named in the YAML exists (repeat per task)
grep -n "secrets\." .github/workflows/ci.yml     # expect no output: no secrets in PR CI
```

Then push a branch and open a draft PR: confirm both jobs start, the iOS job restores `~/.konan` on
the second run (cache hit in the step log), and the report artifacts appear on the run page.
A workflow that only parses is `NOT RUN` for execution until a real run has been observed.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Everything on macOS | Slower queue, higher cost, same result for Android work | Linux for common/Android, macOS for Apple targets only |
| No `~/.konan` cache | Every iOS run re-downloads the Kotlin/Native toolchain | `actions/cache` keyed on the Kotlin version |
| `restore-keys` on the konan cache | Restores an old toolchain next to the new one; the entry keeps growing | Exact key only |
| `cache: gradle` on setup-java **and** setup-gradle | Double caching of the same directory | Let setup-gradle own it |
| One Gradle call per step | Configuration and daemon start-up repeated per step | One invocation with `--continue` |
| `macos-latest` assumed to be Intel | It has been arm64 since 2024; x86_64 simulator testing belongs on an Intel runner | `iosSimulatorArm64Test` on arm64; `macos-15-intel` for x64 |
| Unpinned Xcode in release | The image default changes and the App Store build changes with it | Pin `xcode-version` |
| Signing secrets in the PR workflow | Any workflow change in a PR can exfiltrate them | Separate release workflow + protected environment |
| `paths-ignore` on a required check | Docs-only PRs stay blocked on a pending check | Unfiltered required workflow or in-job filtering |
| Reports uploaded only on success | The run you need to debug has no report | `if: ${{ !cancelled() }}` |
| Same artifact name in two jobs | Upload fails: artifacts are immutable | One name per job |
| Moving to the v6 cache provider without reading its terms | Licence surprise for a private repository | Pick `basic` or `enhanced` deliberately |

## Related skills

- `kmp-build-check` — the local both-platform check this CI mirrors.
- `mobile-release` — versioning, tags, store tracks and the Fastfile the release workflow calls.
- `kmp-build-failure-triage`, `kmp-flaky-test-triage` — when a CI run fails.
- `kmp-test-coverage-backfill` — raising Kover numbers once reports are published.
- `kmp-xcframework-distribution` — publishing a framework from CI.
- External: [gradle/actions](https://github.com/gradle/actions) ·
  [actions/runner-images](https://github.com/actions/runner-images) ·
  [Kotlin native build performance skill](https://github.com/Kotlin/kotlin-agent-skills/tree/main/skills/kotlin-tooling-native-build-performance) ·
  [fastlane docs](https://docs.fastlane.tools).
