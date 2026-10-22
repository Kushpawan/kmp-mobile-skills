---
name: mobile-feature-plan
description: Use when a Kotlin Multiplatform (Android + iOS) feature request, ticket, user story or Figma link needs a written plan before code is written - "plan this feature", "write a spec", "break this into phases", "what would it take to add...", "scope this for both platforms", acceptance criteria, a design hand-off to estimate, or a feature plan file under docs/plans/ to create.
license: Apache-2.0
compatibility: Kotlin Multiplatform project targeting Android and iOS. Figma extraction needs a Figma MCP server or exported frames. Writes only the plan file.
metadata:
  category: workflow
  platforms: android, ios
---

# Mobile feature plan

Turn a feature request into a plan file that another session (or another developer) can execute
without guessing. A good plan names real files, real Gradle tasks and assertable acceptance criteria
for **both** platforms; a vague plan just moves the guessing into implementation, where it costs more.

## When to use

- A feature, ticket or user story arrives and nobody has decided where the code goes yet.
- The request includes Figma links that must be mapped to screens, components and tokens.
- The change touches shared code and at least one platform UI, so Android and iOS scope must be explicit.
- Someone asks "how big is this?" and needs phases, risks and an out-of-scope list to answer it.

## When not to use

- A plan already exists and was approved: use `mobile-feature-implement`.
- A one-line fix or a bug with a known cause: use `mobile-bug-fix`.
- Only creating the module skeleton: use `kmp-feature-module`.
- Only translating one Figma frame into code: use `figma-to-mobile-ui`.

This skill does not write production code. It writes one file: `docs/plans/<feature-slug>.md`
(or wherever the project already keeps plans — see Step 0).

## Step 0 — Read the project first

Plans fail when they describe an architecture the project does not have. Read before planning.

```bash
find . -maxdepth 2 \( -iname 'readme*' -o -iname 'architecture*' -o -iname 'contributing*' \
  -o -name AGENTS.md -o -name CLAUDE.md \) -not -path './build/*'            # written conventions
ls docs/plans docs/specs docs/adr 2>/dev/null                                 # where plans already live
cat settings.gradle.kts                                                        # module list
sed -n '1,60p' gradle/libs.versions.toml                                       # Kotlin / AGP / Compose / libs
find . -name build.gradle.kts -not -path '*/build/*' | sort
grep -rl "binaries.framework" --include=build.gradle.kts .                     # who builds the iOS framework
grep -rl "ComposeUIViewController" --include='*.kt' . | head -3                  # iOS renders Compose?
ls iosApp 2>/dev/null && find iosApp -name '*.swift' | head -20                # or native SwiftUI?
```

Record these answers; the plan cites them.

| Question | Why the plan needs it |
|---|---|
| Module layout (`:shared` monolith, `:feature:<name>`, `:logic` + `:ui` pairs) | Decides every file path in the phases. |
| iOS UI: Compose Multiplatform or SwiftUI over shared logic | Decides whether iOS needs its own UI phase. |
| Presentation pattern (ViewModel + StateFlow, MVI base class, Decompose…) | New screens copy the existing pattern. |
| DI (Koin, kotlin-inject, Metro, Hilt in the Android host, manual) | The wiring phase names the real module file. |
| Networking, persistence, logging libraries | Never plan a second library for a job already done. |
| Test style (`kotlin.test`, fakes vs mocks, Turbine, naming) | The test plan copies it. |
| The exact Gradle test and link task names | Validation commands must run as written. |

Find the closest existing feature and read it end to end — data source, repository, ViewModel,
screen, DI module, tests. The plan says "follow `<that path>`" for each layer.

Confirm task names instead of assuming them:

```bash
./gradlew :shared:tasks --all | grep -iE 'test|link.*Framework|compile.*Metadata' | head -30
```

## Workflow

### 1. Restate the request and close the gaps

Write the objective in two or three sentences: what the user can do afterwards, for whom, and why
now. List every ambiguity as an **open question** — offline behaviour, empty and error states,
permissions, analytics, feature flags, minimum OS versions. Ask the user the blocking ones before
continuing; record the non-blocking ones in the plan.

Done when: every question is answered or written down as an open question with an owner.

### 2. Scope per platform

Fill the scope table. "Both" is not a scope; say what changes on each side.

| Layer | Shared (`commonMain`) | Android | iOS |
|---|---|---|---|
| Data / domain | new repository, use case | — | — |
| Platform APIs | `expect`/interface | `actual` with Android API | `actual` with Apple API |
| UI | Compose screen (if CMP) | host wiring | SwiftUI view (if native UI) |
| Navigation / DI | route, module | — | Swift entry point |

Name the modules touched and any module to create. If a new module is needed, the first phase
calls `kmp-feature-module`. Flag platform-parity risks (one platform has a capability the other
lacks, such as background execution or a system picker) — `mobile-platform-parity` covers them.

Done when: each cell is filled or explicitly "no change".

### 3. Extract the design (only when a design is provided)

With a Figma MCP server available, for each frame URL call `get_metadata` (layer tree),
`get_screenshot` (visual reference), `get_variable_defs` (tokens) and `get_code_connect_map`
(existing component mappings). Without one, ask for exported frames and the token list.

Then build two tables in the plan:

- **Token mapping** — every Figma variable to an existing code token
  (`MaterialTheme.colorScheme.primary`, `AppTheme.spacing.md`, a SwiftUI token). A Figma value
  with no code token becomes a design-system task in the plan, never a hardcoded value.
- **Component mapping** — every Figma component to an existing component, with action `Reuse`,
  `Extend` or `Create`. Search the design-system module before choosing `Create`.

Map every frame to one screen file. Include empty, loading and error frames; if the design lacks
them, add an open question.

Done when: no frame, token or component is unmapped.

### 4. Write acceptance criteria

Number them `AC-1`, `AC-2`, … Each is observable and assertable by a test or a reviewer, and says
which platform it applies to when it is not both.

| Weak | Assertable |
|---|---|
| Search works well | AC-3: typing 2+ characters filters the notes list by title within 300 ms of the last keystroke (both) |
| Handles errors | AC-5: with no network, the list shows cached notes and a retry banner; tapping Retry reloads (both) |
| Looks like the design | AC-7: list row matches the Figma frame spacing and type tokens in light and dark mode (both) |

Include at least one criterion for each of: the happy path, an error path, an empty state, and
accessibility (stable test IDs, screen-reader labels — see `mobile-accessibility-test-ids`).

Done when: every criterion can be marked Verified by a named test or a manual step in the test plan.

### 5. Split into phases with exact validation commands

Order phases so each one compiles and passes tests on its own: data → domain → presentation → UI →
DI and navigation → platform specifics → polish. Each phase lists:

- files to create and to modify (real paths);
- the pattern to follow (a path to an existing example, not a description);
- the ACs it moves forward;
- the **exact** validation commands, already confirmed in Step 0;
- a "done when" line.

Typical commands, adjusted to the real module and task names:

```bash
./gradlew :feature:notes:compileCommonMainKotlinMetadata      # shared code compiles
./gradlew :feature:notes:testAndroidHostTest                  # AGP KMP library plugin (legacy: testDebugUnitTest)
./gradlew :feature:notes:iosSimulatorArm64Test                # macOS only
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64         # iOS framework still links, macOS only
./gradlew :androidApp:assembleDebug                           # or :composeApp:assembleDebug
xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build   # native iOS host, macOS only
```

Keep phases small enough to finish and validate in one sitting. A phase with no validation command
is not a phase.

Done when: every phase has files, pattern, ACs, commands and a done-when line.

### 6. Write the test plan for both platforms

- **Shared unit tests** (`commonTest`): ViewModel state and effects, use cases, mappers,
  repositories with fakes. These run on both the JVM/Android host and the iOS simulator.
- **Platform tests**: `androidHostTest` / `androidDeviceTest` for Android-only code; iOS
  simulator tests for `iosMain` actuals.
- **UI checks**: Compose UI tests or SwiftUI previews/UI tests where the project has them; otherwise
  a manual checklist per platform, with device sizes, light/dark and the largest text size.
- Map each AC to the test or manual step that verifies it.

Done when: every AC appears in the test plan.

### 7. Risks, out of scope, reuse

- **Risks**: what could break elsewhere, and in which flow (shared repository used by another
  screen, a migration, a public API used by the iOS app, binary size, a new permission prompt).
  Give each a mitigation.
- **Out of scope**: list what you deliberately left out so it is not silently added later.
- **Existing code to reuse**: utilities, components and patterns, with paths.

### 8. Write the plan file and stop

Copy [assets/feature-plan-template.md](assets/feature-plan-template.md) to
`docs/plans/<feature-slug>.md` (kebab-case slug) and fill every section. Delete the design
sections when there is no UI. Leave the **Status** table and the **Review** section's placeholders
unfilled — `mobile-feature-implement` fills them.

Present a short summary to the user: objective, phase list, open questions, and the decisions you
need from them. **Do not start implementing.** Implementation starts only after the user approves
the plan.

## Quick reference

| Plan section | Must contain |
|---|---|
| Objective | 2–3 sentences: what, for whom, why now |
| Scope | Shared / Android / iOS table; modules touched or created |
| Design | Frame → screen, token → code token, component → Reuse/Extend/Create |
| Acceptance criteria | `AC-n`, assertable, platform noted |
| Phases | Files, pattern path, ACs, exact commands, done-when |
| Test plan | Every AC mapped to a test or manual step, per platform |
| Risks | Risk → affected flow → mitigation |
| Out of scope | Explicit list |
| Open questions | Question → owner → blocking or not |

## Verify

Check the plan file itself before handing it over. Report each check as `PASS`, `FAIL` or
`NOT RUN` with the reason. Never mark a check PASS that you did not run.

```bash
PLAN=docs/plans/notes-search.md
grep -cE '^- \*\*AC-[0-9]+\*\*' "$PLAN"                  # >= 1 numbered criterion
grep -nE 'TODO|<[a-z][^>]*>' "$PLAN"                      # no unfilled placeholders outside the Status/Review sections
grep -c '^### Phase' "$PLAN"                              # >= 1 phase
./gradlew help --task :feature:notes:testAndroidHostTest  # each task named in the plan exists (repeat per task)
```

- Every AC appears in the test plan: compare the AC ids with the test-plan table.
- `./gradlew help --task <path>` fails for a task that does not exist; fix the plan, not the build.
- iOS-only tasks can only be confirmed on macOS; otherwise report them `NOT RUN (no macOS host)`.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| Planning from memory of "typical KMP" | File paths and patterns do not match the repo; implementation rewrites the plan | Do Step 0; cite a real sibling feature per layer |
| "Both platforms" with no per-platform detail | iOS work is discovered late, usually the native UI or a missing `actual` | Fill the scope table cell by cell |
| Criteria like "works smoothly" | Nobody can mark them done; review turns into opinion | `AC-n` with an observable outcome and a test |
| Validation commands that do not exist | The implementer hits "Task not found" in phase 1 | Confirm with `./gradlew help --task` |
| Only the Android test task in the plan | iOS-only compile or link errors appear after merge | Add the iOS simulator test and framework link tasks |
| Hardcoded hex or dp values from Figma | Breaks dark mode and theming; drifts from the design system | Token mapping table; missing tokens become DS tasks |
| No empty, error or offline states | They are the first thing QA files | One AC each; ask for missing frames |
| No out-of-scope list | Scope creeps silently during implementation | Write it, and get the user to confirm it |
| Starting to code "while planning" | The user never approved the approach | Stop after writing the plan |

## Related skills

- `mobile-feature-implement` — executes the approved plan phase by phase.
- `kmp-feature-module` — when the plan needs a new module.
- `figma-to-mobile-ui` — frame-by-frame design translation during implementation.
- `compose-multiplatform-screen`, `kmp-data-layer`, `kmp-koin-di`, `kmp-expect-actual` — layer patterns the phases point to.
- `mobile-platform-parity` — Android/iOS capability gaps found while scoping.
- `kmp-testing-patterns` — shapes for the test plan.
- `mobile-accessibility-test-ids` — the accessibility acceptance criteria.
- External: [Kotlin Multiplatform documentation](https://kotlinlang.org/docs/multiplatform/).
