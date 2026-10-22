# Feature plan: <Feature name>

**Status:** Draft · **Issue:** <link or id, optional> · **Owner:** <name or team> · **Date:** <YYYY-MM-DD>

> Copy to `docs/plans/<feature-slug>.md`. Fill every `<placeholder>`. Delete §4 and the visual
> checks in §7 when the change has no UI. Leave §11 (Status) and §12 (Review) for the
> implementation session to fill.

---

## 1. Objective

<What the feature does, for whom, and why now. Two or three sentences.>

## 2. Acceptance criteria

Each criterion is observable and assertable by a test or a reviewer. Note the platform when it is
not both.

- **AC-1** — <happy path: observable behaviour> (both)
- **AC-2** — <error path: what the user sees and can do> (both)
- **AC-3** — <empty state> (both)
- **AC-4** — <accessibility: stable test IDs on every interactive element, screen-reader labels> (both)

## 3. Scope

**Project facts (from Step 0):** module layout `<…>` · iOS UI `<Compose Multiplatform | SwiftUI over shared logic>` ·
presentation `<ViewModel + StateFlow | MVI base | …>` · DI `<…>` · networking `<…>` · persistence `<…>` ·
test style `<…>`.

| Layer | Shared (`commonMain`) | Android | iOS |
|---|---|---|---|
| Data / domain | <…> | <… or no change> | <… or no change> |
| Platform APIs | <expect / interface> | <actual> | <actual> |
| UI | <…> | <…> | <…> |
| Navigation / DI | <…> | <…> | <…> |

Modules touched: <`:feature:notes`, `:shared`, `:androidApp`, `iosApp`>
Modules created: <none | `:feature:notes` via kmp-feature-module>
Platform-parity notes: <capability differences and how each platform handles them>

## 4. Design references

| Screen / state | Figma frame | URL | Code file |
|---|---|---|---|
| <Notes list — default> | <Notes/List> | <https://www.figma.com/design/FILE/Name?node-id=1-2> | <path> |
| <Notes list — empty> | <…> | <…> | <same file> |
| <Notes list — error> | <…> | <…> | <same file> |

### 4.1 Token mapping

| Figma token | Code token | Notes |
|---|---|---|
| <color/surface/primary> | <MaterialTheme.colorScheme.surface> | |
| <spacing/md> | <AppTheme.spacing.md> | |
| <type/body/regular> | <MaterialTheme.typography.bodyMedium> | |
| <value with no code token> | <none — design-system task in Phase N> | |

### 4.2 Component mapping

| Figma component | Code component | Action |
|---|---|---|
| <Button/Primary> | <AppButton(variant = Primary)> | Reuse |
| <ListRow/WithAvatar> | <AppListRow> | Extend |
| <SearchField> | <none> | Create |

## 5. Implementation phases

Each phase compiles and passes its tests on its own.

### Phase 1 — <Data layer>

- Create: <paths>
- Modify: <paths>
- Pattern: follow <path to an existing example>
- Moves: <AC-1, AC-2>
- Validate:
  ```bash
  ./gradlew :<module>:compileCommonMainKotlinMetadata
  ./gradlew :<module>:testAndroidHostTest
  ```
- Done when: <tests for the repository and mapper pass>

### Phase 2 — <Domain / presentation>

- Create: <paths>
- Modify: <paths>
- Pattern: follow <path>
- Moves: <AC-…>
- Validate:
  ```bash
  ./gradlew :<module>:testAndroidHostTest
  ./gradlew :<module>:iosSimulatorArm64Test
  ```
- Done when: <ViewModel state and effect tests pass on both>

### Phase 3 — <UI>

- Create: <paths>
- Modify: <paths>
- Pattern: follow <path>; design source: <frame URLs from §4>
- Moves: <AC-…>
- Validate:
  ```bash
  ./gradlew :<app-module>:assembleDebug
  ./gradlew :shared:linkDebugFrameworkIosSimulatorArm64
  ```
- Done when: <screen renders all states; visual checks in §7 pass>

### Phase 4 — <DI and navigation wiring>

- Modify: <DI module file>, <navigation host file>, <iOS entry point if native UI>
- Moves: <AC-…>
- Validate:
  ```bash
  ./gradlew :<app-module>:assembleDebug
  xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp \
    -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
  ```
- Done when: <the feature is reachable from the app on both platforms>

## 6. Validation commands (full run)

```bash
./gradlew :<module>:allTests
./gradlew :<app-module>:assembleDebug
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64
```

## 7. Test plan

| AC | Shared test | Android | iOS | Manual check |
|---|---|---|---|---|
| AC-1 | <`NotesListViewModelTest.should_showNotes_when_loaded`> | <runs in host tests> | <runs in simulator tests> | <…> |
| AC-2 | <…> | | | |
| AC-3 | <…> | | | |
| AC-4 | <…> | <Compose UI test by test tag> | <UI test by accessibility identifier> | <screen reader pass> |

Visual checks (UI only): compare each screen with its frame for spacing, colour and type tokens,
in light and dark mode, at the smallest supported width and the largest text size.

## 8. Risks

| Risk | Affected flow | Mitigation |
|---|---|---|
| <shared repository change> | <other screen that uses it> | <test that pins its behaviour> |

## 9. Out of scope

- <thing deliberately left out>

## 10. Open questions

| Question | Owner | Blocking? |
|---|---|---|
| <…> | <…> | <yes / no> |

Existing code to reuse:

- <utility or component>: <path>

## 11. Status

*Filled during implementation.*

| AC | Status | Evidence |
|---|---|---|
| AC-1 | Not started | |
| AC-2 | Not started | |
| AC-3 | Not started | |
| AC-4 | Not started | |

Status values: `Not started` · `In progress` · `Implemented` · `Verified` · `Not implemented (reason)`.

Deviations from the plan:

- <none yet>

## 12. Review

*Filled after kmp-build-check and kmp-code-review have run.*

Date: {YYYY-MM-DD}
Build check: {PASS / FAIL / NOT RUN per check}
Code review: {findings and how each was resolved}
Verdict: {ready for PR | not ready — reason}
