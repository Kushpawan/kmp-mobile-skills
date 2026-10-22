---
name: kmp-code-review
description: Use when asked to review local Kotlin Multiplatform, Kotlin, Compose or Swift changes before opening a pull request — "review my changes", "review this branch", "pre-PR review", "what did I break?", uncommitted or unpushed work, or changes that touch expect/actual pairs, Koin or Hilt bindings, coroutines and Flow, Room or SQLDelight, SwiftUI, Swift calls into a Kotlin framework, Gradle, version catalogs or CI pipelines.
license: Apache-2.0
compatibility: Git repository with Kotlin (.kt, .kts) or Swift sources. Read-only review; the GitHub CLI (gh) is optional and used only to check for an open pull request.
metadata:
  category: review
  platforms: android, ios
---

# KMP code review

Review changes that no one has reviewed yet — uncommitted work, or commits on a branch with no pull
request — with the whole repository open. A bot on a pushed diff sees one hunk; you can read every
caller, both sides of an `expect`/`actual`, the DI graph and the Swift code that calls the Kotlin
framework. Use that context: it is the reason this review runs locally.

Two rules carry the skill. **The project's own written rules come first**, generic lenses second.
**Every Critical and High finding is re-checked by trying to disprove it** before it is reported.

## When to use

- Before opening a pull request, to find what a reviewer or a review bot (e.g. Cursor Bugbot,
  CodeRabbit) would otherwise post.
- When asked to review local, staged, unpushed or branch changes in a Kotlin Multiplatform, Android
  or iOS project.
- After a large refactor, to check that callers, DI bindings and platform `actual`s still agree.

## When not to use

- A security-focused audit — use `mobile-security-review` (it has the MASVS-mapped lens).
- The question is "does Android behave like iOS?" — use `mobile-platform-parity`.
- Reviewing a pull request that is already open and has review comments — read the PR thread instead;
  this skill narrows itself to unreviewed work when it finds an open PR.
- Formatting only — run the project's formatter (ktlint, Spotless, SwiftFormat).

## Step 0 — Read the project first

Do this before reading the diff. The review enforces the project's law, not your preferences.

1. **Rules files.** Read every one that exists: `AGENTS.md`, `CLAUDE.md` (root and per-module),
   `CONTRIBUTING.md`, `.cursor/rules/*`, `.github/copilot-instructions.md`, `docs/adr/*`, and any
   module `README.md` that states conventions. A finding that cites one of these is **Tier 1**.
2. **Linters that already run.** Check `detekt.yml`, `.editorconfig` (ktlint), `lint.xml`,
   `.swiftlint.yml`, and the CI workflow that invokes them. A lens row a CI check already enforces
   is skipped — do not duplicate the linter. A config that exists but never runs in CI enforces
   nothing.
3. **Stack.** Note the module layout (`:composeApp`, `:shared`, `:feature:*`), presentation pattern
   (MVVM, MVI, other), DI (Koin, Hilt, kotlin-inject, manual), networking, persistence, logging,
   test style and naming, and versions in `gradle/libs.versions.toml`.
4. **Conflicts.** When a project rule contradicts a lens row, the project rule wins. Never apply an
   MVVM rule to MVI code, or a "no comments" rule from one module to another that documents freely.

Done when you can name the rules files, the enforced linters, and the architecture of each changed
module.

## Workflow

### 1. Resolve the scope

Uncommitted changes (staged, unstaged **and untracked**) are always in scope. Committed work is in
scope from the merge-base with the nearest base branch. Do not trust `origin/HEAD` alone: many
projects integrate on `develop` while `origin/HEAD` points at `main`.

```bash
repo=.                                   # run per repo if the workspace holds several git repos
BR=$(git -C "$repo" rev-parse --abbrev-ref HEAD)
# Integration branches first: on a tie the earlier candidate wins.
best=""; best_n=999999
for cand in origin/develop origin/development origin/main origin/master origin/trunk; do
  git -C "$repo" rev-parse --verify -q "$cand" >/dev/null || continue
  mb=$(git -C "$repo" merge-base "$cand" HEAD) || continue
  n=$(git -C "$repo" rev-list --count "$mb..HEAD")
  if [ "$n" -lt "$best_n" ]; then best_n=$n; best=$cand; fi
done
BASE="${BASE:-$best}"                    # a base the user names always wins
echo "branch=$BR base=$BASE ahead=$best_n"
```

- Remote-tracking refs can be stale. `git fetch --quiet origin` updates only those refs; run it
  unless offline, and say so in the scope line when you could not.
- **Guardrail.** If the current branch *is* an integration branch, or is more than ~40 commits ahead
  of every base (a stale long-lived branch), narrow the scope to unpushed commits
  (`git rev-list "@{upstream}..HEAD"`) plus uncommitted changes, and say why.
- **Open PR check.** `gh pr list --head "$BR" --state open --json number,url`. If a PR is open, its
  commits are already under review: narrow to uncommitted plus unpushed work unless the user asks
  for the whole branch. On GitLab: `glab mr list --source-branch "$BR"`.

Collect the changed files:

```bash
MB=$(git -C "$repo" merge-base "$BASE" HEAD)
git -C "$repo" diff --name-only "$MB"..HEAD            # committed, not merged
git -C "$repo" diff --name-only HEAD                   # staged + unstaged
git -C "$repo" ls-files --others --exclude-standard    # untracked: git diff does not show these
```

Keep source and build inputs: `*.kt`, `*.kts`, `*.swift`, `*.toml`, `*.gradle`, `*.pro`,
`AndroidManifest.xml`, `res/xml/*.xml`, `Info.plist`, `*.entitlements`, `*.xcconfig`,
`Package.swift`, CI YAML and `*.sh`. Drop generated and build output (`build/`, `.build/`,
`DerivedData/`, generated sources, `Package.resolved`). A lockfile change means a dependency
changed — review the catalog or manifest that caused it.

Print one scope line per repo before reviewing, e.g.
`repo=. · branch=feature/notes-sync · base=origin/develop · 4 commits · 11 files · open PR: none`.
Done when the user can see exactly what is covered and what a guardrail narrowed.

**Empty scope:** report `No changes against <base>` and stop. **Docs-only:** say so and stop — do
not manufacture findings from prose.

### 2. Load the rulebook

1. Tier 1: the project's rules from Step 0, mapped to the changed paths.
2. Tier 2: the lens tables for the file types in scope:

| Changed files | Load |
|---|---|
| `*.kt` (any source set), Compose UI | [references/lens-kotlin-compose.md](references/lens-kotlin-compose.md) |
| `*.swift`, Xcode project files | [references/lens-swift-ios.md](references/lens-swift-ios.md), plus §7–§9 of the Kotlin lens (language-independent state and side-effect rows) |
| `*.kts`, `*.toml`, `*.pro`, manifests, `Info.plist`, `Package.swift`, CI YAML, `*.sh` | [references/lens-build-ci.md](references/lens-build-ci.md) |
| Every review | [references/findings-schema.md](references/findings-schema.md) |

Apply every row whose condition holds, except rows a CI-enforced linter already covers. `Mech? yes`
means a linter *could* catch it, not that one does — still apply the row unless the check really runs.

### 3. Read whole files and their context

For each changed file, read it in full, then follow the edges a diff hides:

- **Callers** of every changed public or `internal` signature: `grep -rn "functionName(" --include=*.kt --include=*.swift`.
- **`expect`/`actual`:** for a changed `expect`, every `actual` in `androidMain`, `iosMain`,
  `appleMain`, `nativeMain`, `jvmMain`; for a changed `actual`, the `expect` and its siblings.
- **DI bindings:** a constructor change against its Koin `module { }` (`single`, `factory`,
  `viewModel`, `singleOf(::X)`), Hilt `@Provides`/`@Binds`, or manual factory. Runtime DI fails at
  runtime, not at compile time.
- **Swift call sites of Kotlin APIs:** a renamed, removed or re-typed public Kotlin declaration in a
  module exported to the iOS framework breaks Swift code that Gradle never compiles. Grep the iOS
  app and any Swift package for the old name.
- **Data contracts:** a DTO change against every mapper and test fixture; an entity change against
  its migration; a serialized enum against values already persisted.
- **Tests** that cover the changed code, and whether the change made any of them unable to fail.

Done when every changed declaration has had its callers, implementations and bindings opened.

### 4. Apply the lenses

Walk the dimensions in order and record each hit as a finding:

1. **Correctness** — error and edge paths, cancellation, races, nullability, resource leaks.
2. **Cross-file integrity** — callers, `actual`s, DI, Swift consumers, mappers, migrations.
3. **Project rules** — each Tier 1 finding names the rule file and section it enforces.
4. **Platform specifics** — the Kotlin/Compose or Swift/iOS lens rows.
5. **Build and release** — the build/CI lens rows.

Severity is never below the row's floor. A row's condition that does not hold means no finding.
A concern no row covers is reported as `lens: "unlisted"`, Tier 2.

### 5. Scale to the diff size

- **Up to ~15 changed files:** review in one context.
- **More than ~15:** split the work. In Claude Code, the `kotlin-reviewer` and `swift-reviewer`
  agents in this repository's `agents/` folder return findings in the same schema; launch them in
  one message so they run concurrently. Elsewhere, review module by module and write findings as
  you go. Merge and dedupe by `(file, line, title)`.
- **More than ~100:** review the highest-risk paths first — auth, session, payments, persistence
  and migrations, deletions, background work — and state what was skimmed. Recommend splitting the
  change.

### 6. Try to disprove every Critical and High

For each Critical or High finding, re-read the cited code and argue against it:

- Is the path reachable — from a real entry point, in a release build, on that platform?
- Does something upstream already guard it (a validated input, a `catch` in the caller, a lock)?
- Does the library already handle it (a migration in another file, a plugin that retries)?
- Was it introduced by this change, or does it exist on the base branch too?

Mark the survivors `"verdict": "CONFIRMED"`. Downgrade or drop the rest. A pre-existing defect goes
in a separate "Noticed, not introduced" list and does not count toward the summary. Never report an
unchecked Critical or High.

### 7. Report

Emit the findings as JSON Lines first, exactly as [references/findings-schema.md](references/findings-schema.md)
specifies, then the human report: grouped by repo, most severe first.

```text
CRITICAL  shared/src/commonMain/kotlin/com/example/app/notes/NotesSync.kt:88
  Cancellation swallowed in the sync loop
  Why:  catch (e: Exception) around syncPage() also catches CancellationException. After logout
        cancels the scope, the loop keeps calling the API with a cleared token.
  Fix:  catch (e: CancellationException) { throw e } before the generic catch, or catch IOException only.
  Rule: kotlin/swallowedCancellation (Tier 2) · CONFIRMED
```

Close with a count line (`1 Critical · 3 High · 2 Medium · 1 Low across 1 repo`) and the scope
lines from step 1. "No findings" is a valid result — say what was covered.

Say when a human review is still needed regardless of findings: more than ~50 files, more than one
repo, schema migrations, and anything touching auth, session, payments or data deletion.

### 8. Offer to fix

Ask which findings to fix: all, by severity, or a list. Only after approval, edit the files, re-read
each change against the same rules, and run the checks in **Verify** for the touched modules. Never
commit, push, stage or rewrite history.

## Quick reference

| Severity | Consequence that sets it |
|---|---|
| **Critical** | Crash, data loss, credential exposure, or silently wrong behaviour on a money, time-record or legal-record path |
| **High** | Ships working but breaks a consumer, violates a written project rule, regresses latency on a user-blocking path, or leaves new behaviour untested where the project requires tests |
| **Medium** | Convention drift, maintainability, stale docs, a latent defect with a narrow trigger |
| **Low** | Style the project's gates do not enforce |

| Tier | Cites | A hit is |
|---|---|---|
| 1 | A rule written in the project's files | A finding the author must address or explicitly reject |
| 2 | A known defect class from the lens tables | A proposal — cheap to reject when the context makes it safe |

## Verify

Run what the touched modules need after applying fixes, and report each check as `PASS`, `FAIL` or
`NOT RUN — <reason>`. Never claim a check that was not run. Use the project's own task names when
they differ.

```bash
./gradlew :shared:compileCommonMainKotlinMetadata          # common code compiles for every target
./gradlew :shared:testAndroidHostTest                      # host tests (testDebugUnitTest on the older Android plugin)
./gradlew :shared:iosSimulatorArm64Test                    # Kotlin tests on iOS (macOS only)
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64      # the framework Swift consumes still links
./gradlew :composeApp:assembleDebug                        # Android app builds
xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp \
  -destination 'platform=iOS Simulator,name=iPhone 16' build   # Swift callers still compile
./gradlew detekt lint                                      # only if the project configures them
```

iOS checks need macOS with Xcode; on Linux report them `NOT RUN — needs macOS`. A review with no
fixes applied may report the whole section `NOT RUN — review only`.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Reviewing the hunk, not the file | The bug is usually in the caller, the other `actual` or the DI module | Step 3: open every edge before judging |
| Using `git diff HEAD` as "everything uncommitted" | New untracked files are invisible to it | Add `git ls-files --others --exclude-standard` |
| Trusting `origin/HEAD` as the base | Projects that integrate on `develop` get a range full of other people's commits | Nearest merge-base, integration branches first, explicit base wins |
| Applying generic rows over project rules | Fires on correct code and teaches the team to ignore the review | Tier 1 first; project rule wins on conflict |
| Reporting a Critical from a first read | One false Critical costs the credibility of every later one | Step 6: try to disprove it, then mark `CONFIRMED` |
| Re-reporting what a linter already flags | Duplicate noise; the linter is cheaper and deterministic | Skip rows a CI-enforced check covers |
| Commenting on commit messages, branch names or PR titles | Process metadata is not code | Out of scope at every severity |
| Editing before the user chooses fixes | The user loses control of what changed | Report, ask, then edit |

## Related skills

- `mobile-security-review` — MASVS-mapped security pass over the same change.
- `mobile-platform-parity` — Android vs iOS behaviour divergence.
- `kmp-expect-actual`, `kmp-gradle-version-catalog`, `kmp-module-health` — when a finding needs a
  structural fix rather than a line change.
- `agents/kotlin-reviewer.md`, `agents/swift-reviewer.md` — Claude Code subagents that run this
  review's lenses in parallel.
- External: [chrisbanes/skills](https://github.com/chrisbanes/skills) (Compose state, effects and
  Kotlin concurrency), [android/skills](https://github.com/android/skills),
  [twostraws/SwiftUI-Agent-Skill](https://github.com/twostraws/SwiftUI-Agent-Skill).
