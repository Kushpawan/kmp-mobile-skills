---
name: mobile-feature-implement
description: Use when an approved feature plan for a Kotlin Multiplatform (Android + iOS) app must be executed - "implement the plan", "build docs/plans/notes-search.md", "start phase 1", "continue the plan", "pick up where the last session stopped", or a plan file with numbered acceptance criteria (AC-1...) and phases waiting to be coded.
license: Apache-2.0
compatibility: Kotlin Multiplatform project targeting Android and iOS with a written plan file. iOS validation needs macOS with Xcode.
metadata:
  category: workflow
  platforms: android, ios
---

# Mobile feature implement

Execute an approved plan one phase at a time, proving each phase with its own validation commands
before starting the next. The plan file is the contract and the progress log: acceptance-criterion
status and every deviation are written back into it, so the next session — or the reviewer — can
see exactly what was built and what was verified.

## When to use

- A plan file exists (usually `docs/plans/<feature>.md`) and the user has approved it.
- A previous session stopped mid-plan and the work must resume at the right phase.
- The user says "implement phase 2" or "build the rest of the plan".

## When not to use

- No plan, or the plan has not been approved: use `mobile-feature-plan` first.
- A small bug fix: use `mobile-bug-fix`.
- The build is already broken before you start: use `kmp-build-failure-triage`, then come back.

## Step 0 — Read the project and the plan first

1. Read the plan end to end. Confirm with the user that it is approved; if it has open questions
   marked blocking, stop and ask them.
2. Read the **Status** section. Resume at the first phase whose ACs are not all `Implemented` or
   `Verified`. Read the **Deviations** list so you do not undo an earlier decision.
3. Re-check the project facts the plan relies on — they may have changed since it was written:

```bash
git status --short && git log --oneline -5           # clean tree? what landed since the plan?
cat settings.gradle.kts
sed -n '1,60p' gradle/libs.versions.toml
./gradlew help --task :feature:notes:testAndroidHostTest   # each task the plan names still exists
```

4. For each layer the plan touches, open the "pattern" file it cites and the files it will modify.
   Follow what exists: DI framework, presentation pattern, logging, naming, test style, package root.

5. Check the baseline before changing anything — run the plan's full validation commands once. If
   they already fail, report it and ask whether to fix the baseline first; otherwise every later
   failure is ambiguous.

6. Work on a feature branch. Create it **without** tracking the base branch, so a plain `git push`
   from any client cannot land on `main`:

```bash
git switch --no-track -c feature/notes-search origin/main   # set an upstream only when pushing: git push -u origin feature/notes-search
```

Ask once whether the user wants a commit per phase. Do not commit unless they say yes or the
project's contributing guide asks for it.

## Workflow

### 1. Load the design context (UI phases only)

If the plan has design sections, keep the token-mapping and component-mapping tables open while
writing UI. For each frame, use `figma-to-mobile-ui` (or the Figma MCP `get_design_context`,
`get_screenshot` and `get_variable_defs` tools directly). MCP output is a reference, typically
React + Tailwind — translate it to the project's own components and tokens. Never paste Tailwind
classes, hex colours or raw dp/pt values; a token that is missing from the mapping table is a
deviation to record, not a value to inline.

### 2. Run the phase loop

For each phase, in the plan's order:

**a. Mark it started.** Set the phase's ACs to `In progress` in the Status table.

**b. Implement exactly the phase's file list.** Follow the cited pattern file. Put business logic in
`commonMain`; platform code goes through `expect`/`actual` or an interface bound per platform in DI
(`kmp-expect-actual`). Write the tests alongside the code, in the project's test style
(`should_<expected>_when_<condition>` unless it uses another convention).

**c. Validate with the phase's own commands** — exactly as written in the plan. Typical set:

```bash
./gradlew :feature:notes:compileCommonMainKotlinMetadata
./gradlew :feature:notes:testAndroidHostTest          # legacy com.android.library: testDebugUnitTest
./gradlew :feature:notes:iosSimulatorArm64Test        # macOS only
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64 # macOS only, whenever a public type or export changed
```

**d. Self-correct, at most 3 attempts per phase.** On failure: read the first real error (not the
last line), form one hypothesis, make one targeted fix, re-run the same commands. Count attempts.
Do not weaken or delete a test to make it pass, and do not add `@Ignore` or exclude tasks
(`-x <task>`) to get a green run.

**e. Stop after the third failed attempt.** Do not start the next phase. Report to the user:
the phase, the command, the exact error, the three hypotheses tried and what each changed, and
your best current diagnosis. Leave the ACs as `In progress`. Suggest `kmp-build-failure-triage`
or `kmp-flaky-test-triage` if the failure looks environmental.

**f. Record the result.** When the phase's commands pass, set its ACs to `Implemented` (code exists,
compiles and its tests pass) and write the evidence — the test name or command — in the Evidence
column. Use `Verified` only after the AC has been checked end to end (a passing UI test, or a manual
check on that platform that you or the user actually performed).

**g. Record deviations.** Any change from the plan — a different file, an extra dependency, a
dropped step, a new design token — goes into the plan's Deviations list with one line of reason.

**h. Commit, if the user asked for commits.** One conventional commit per phase, scoped to the
module:

```text
feat(notes): add search query to notes repository
feat(notes): expose search state from NotesListViewModel
test(notes): cover empty and error search results
```

Never `git push`, never open a PR, never force-push, and never rewrite history without the user's
explicit go-ahead.

### 3. Visual check (UI phases only)

For each screen with a frame, compare the running screen (Android emulator, iOS simulator) or a
screenshot against the frame: layout direction, spacing, colour and type tokens, light and dark
mode. At most 2 refinement passes per screen; then record what still differs as a deviation and
ask the user.

### 4. Full validation

After the last phase, run the plan's full validation section and both app builds:

```bash
./gradlew :feature:notes:allTests
./gradlew :androidApp:assembleDebug                 # or :composeApp:assembleDebug
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64
```

The self-correct limit applies here too: 3 attempts, then stop and report.

### 5. Build check, then code review

Run `kmp-build-check` (both platforms, every check reported as PASS / FAIL / NOT RUN), then
`kmp-code-review` on the branch diff. Present review findings by severity and let the user decide
each one: fix now, defer (with a follow-up issue), or reject (with a reason). Fix the accepted ones,
re-run the affected validation, then fill the plan's **Review** section.

The work is ready for a PR only when: no AC is `Not implemented` without a stated reason, every
build check is PASS or NOT RUN with a reason, and no critical review finding is open.

### 6. Hand over

Report: phases done, AC table, deviations, build-check results, review outcome, and the commits made
(hashes and messages). Ask whether to push and open the PR. Do nothing further until the user answers.

## Quick reference

| Situation | Action |
|---|---|
| Plan has a blocking open question | Stop and ask before Phase 1 |
| Baseline already fails | Report; ask whether to fix the baseline first |
| Phase command fails | Diagnose → one fix → re-run; max 3 attempts |
| Third attempt fails | Stop; report error, attempts, diagnosis; do not start the next phase |
| Plan step is wrong or impossible | Do the minimal correct thing; log it under Deviations |
| Figma value has no token | Log a deviation; add the token through the design system, never inline |
| AC code done and tests pass | `Implemented` + evidence |
| AC checked end to end on the platform | `Verified` + evidence |
| All phases done | Full validation → `kmp-build-check` → `kmp-code-review` → fill Review |
| Ready to ship | Ask before push / PR |

## Verify

Report each check as `PASS`, `FAIL` or `NOT RUN` with the reason (for example "NOT RUN — no macOS
host for iOS tasks"). Never report a check as passed that you did not run in this session.

```bash
./gradlew :feature:notes:allTests
./gradlew :androidApp:assembleDebug
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64          # macOS
grep -nE 'Not started|In progress' docs/plans/notes-search.md  # expect no output when finished
grep -nE '^(Date|Build check|Code review|Verdict): \{' docs/plans/notes-search.md   # expect no output: Review filled
git status --short                                             # nothing unexpected left uncommitted
```

Plus the full `kmp-build-check` report and the `kmp-code-review` findings list.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Validating only at the end | Five phases of errors interleave; the root cause is buried | Run the phase's commands after every phase |
| Only Android tasks run | iOS compile, link or `actual` errors surface after merge | Run the iOS test and framework link tasks on macOS, or report NOT RUN |
| Unlimited retry loop | Burns time, drifts into rewriting unrelated code | 3 attempts per phase, then stop and report |
| "Fixing" a failure by skipping or weakening a test | The AC is no longer proven | Fix the code; if the test is wrong, say so and log a deviation |
| Marking an AC `Verified` from a compile | Status lies to the reviewer | `Implemented` for code + tests; `Verified` only after an end-to-end check |
| Silent deviations | The reviewer compares code to a plan that no longer describes it | One line per deviation in the plan |
| Branch tracking `origin/main` | A plain push from an IDE or git client lands commits on `main` | `git switch --no-track -c …`; set the upstream on first push |
| Pushing or opening the PR unprompted | The user loses the chance to review first | Ask; wait for a yes |
| Inlining Figma hex/dp values | Breaks dark mode and theming | Use mapped tokens; add missing ones to the design system |
| Adding a second library for an existing job | Two HTTP clients, two loggers, two DI graphs | Reuse what the project already uses |

## Related skills

- `mobile-feature-plan` — writes the plan this skill executes.
- `kmp-build-check` — the both-platform build and test gate before review.
- `kmp-code-review` — the review pass before opening a PR.
- `kmp-build-failure-triage`, `kmp-flaky-test-triage` — when the self-correct limit is reached.
- `figma-to-mobile-ui` — frame translation during UI phases.
- `kmp-feature-module`, `compose-multiplatform-screen`, `kmp-data-layer`, `kmp-koin-di`, `kmp-expect-actual`, `kmp-testing-patterns` — per-layer patterns.
- External: [Conventional Commits](https://www.conventionalcommits.org/).
