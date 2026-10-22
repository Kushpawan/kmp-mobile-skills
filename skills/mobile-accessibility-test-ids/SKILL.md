---
name: mobile-accessibility-test-ids
description: Use when adding or fixing stable UI-test locators and accessibility labels in a Kotlin Multiplatform or native mobile app - Compose testTag, testTagsAsResourceId, SwiftUI accessibilityIdentifier versus accessibilityLabel, contentDescription, Appium (UiAutomator2, XCUITest), Maestro or XCUITest not finding an element, flaky XPath or text-based selectors, or QA asking for test IDs.
license: Apache-2.0
compatibility: Compose Multiplatform or Jetpack Compose on Android; Compose Multiplatform or SwiftUI on iOS. Inspecting the iOS accessibility tree needs macOS with Xcode.
metadata:
  category: testing
  platforms: android, ios
---

# Mobile accessibility test IDs

Every interactive element carries two different things:

- a **locator**: a stable, never-translated ID that tests use. This is `Modifier.testTag` in Compose
  and `accessibilityIdentifier` in SwiftUI and UIKit.
- a **spoken label**: localised prose that TalkBack and VoiceOver read aloud. This is
  `contentDescription` in Compose and `accessibilityLabel` in SwiftUI and UIKit.

They are never the same string. IDs live in one namespaced object per screen, shared with the tests,
and they follow one naming scheme on both platforms.

## When to use

- Building or reviewing a screen that QA automation, end-to-end tests or Compose UI tests will drive.
- Appium, Maestro, UiAutomator or XCUITest cannot find a Compose or SwiftUI element.
- Selectors are flaky: XPath by position, matching on visible text, list rows by index.
- Someone put an ID into `contentDescription` or `accessibilityLabel` to make a test pass.

## When not to use

- A full accessibility audit (Dynamic Type, contrast, focus order, VoiceOver rotors): see the
  external accessibility skills under Related skills.
- Writing unit tests for ViewModels: use `kmp-testing-patterns`.

## Step 0 - Read the project first

1. **Find the existing ID convention.** Search for `testTag(`, `TestTags`, `accessibilityIdentifier(`
   and `AccessibilityID`. If the project already has a scheme (for example dot notation such as
   `login.email`), keep it. Mixing schemes breaks shared test helpers.
2. **Find where IDs live.** Look for `<Screen>TestTags` objects next to the screens, and a Swift
   `enum` namespace in the app or in a package.
3. **Find the test tools.** Appium suites (look for `capabilities`, `UiAutomator2`, `XCUITest`),
   `.maestro/` flows, `*UITests` targets, and Compose `runComposeUiTest` / `createComposeRule` tests.
   The tool decides how an ID must be exposed (see Workflow step 4).
4. **Find the Android host root.** The `setContent {}` call in the `Activity`, plus every
   `Dialog`, `ModalBottomSheet` or `Popup`. That is where `testTagsAsResourceId` belongs.
5. **Check the UI layer.** Compose Multiplatform on both platforms, Compose on Android with SwiftUI
   on iOS, or fully native.

## Workflow

1. **Pick the elements to tag.** Tag every element a test acts on or waits for:
   - buttons, links and tab items;
   - text fields, toggles and pickers;
   - list-row tap targets;
   - dialog and sheet actions (confirm **and** cancel);
   - the screen root, so a test can assert "we are on screen X";
   - error banners, empty states, retry buttons, loading indicators.

   Do **not** tag decorative images, dividers, spacers or layout-only containers. Over-tagging makes
   page sources noisy and invites accidental duplicates.

2. **Name the IDs: `<screen>_<element>_<role>`**, in snake_case and English-only. They are never shown
   to users and never translated.

   | Role suffix | Example |
   |---|---|
   | `_screen` | `notes_list_screen` |
   | `_button` | `notes_list_add_button` |
   | `_input` | `note_editor_title_input` |
   | `_toggle`, `_link`, `_tab` | `settings_sync_toggle`, `settings_privacy_link` |
   | `_row_<stableId>` | `notes_list_row_42` |
   | `_dialog`, `_dialog_confirm_button`, `_dialog_cancel_button` | `notes_list_delete_dialog_confirm_button` |
   | `_error`, `_empty_state`, `_loading` | `notes_list_empty_state` |

   - An ID is unique on its screen. Give global surfaces (an app-wide error dialog) a global name
     such as `app_error_dialog`.
   - **Dynamic rows use a stable model ID, never the list index.** An insert, a sort or a new page
     shifts indices, and the test then taps the wrong row without any error.
   - Use the **same string on Android and iOS**. A Compose Multiplatform `testTag` becomes the iOS
     `accessibilityIdentifier`, so one Maestro or Appium flow can drive both platforms.

3. **Declare the IDs once per screen.**

   ```kotlin
   // commonMain, next to NotesListScreen.kt
   object NotesListTestTags {
       const val SCREEN = "notes_list_screen"
       const val ADD_BUTTON = "notes_list_add_button"
       const val EMPTY_STATE = "notes_list_empty_state"
       const val DELETE_DIALOG = "notes_list_delete_dialog"
       const val DELETE_DIALOG_CONFIRM_BUTTON = "notes_list_delete_dialog_confirm_button"
       const val DELETE_DIALOG_CANCEL_BUTTON = "notes_list_delete_dialog_cancel_button"
       private const val ROW_PREFIX = "notes_list_row_"

       fun row(noteId: String): String = ROW_PREFIX + noteId
   }
   ```

   ```kotlin
   @Composable
   fun NotesList(state: NotesUiState, onAction: (NotesAction) -> Unit, modifier: Modifier = Modifier) {
       Box(modifier.fillMaxSize().testTag(NotesListTestTags.SCREEN)) {
           LazyColumn {
               items(state.notes, key = { it.id }) { note ->          // stable key AND stable tag
                   NoteRow(
                       note = note,
                       onClick = { onAction(NotesAction.Open(note.id)) },
                       // the tag goes on the node that receives the click, not on an inner Text
                       modifier = Modifier.testTag(NotesListTestTags.row(note.id)),
                   )
               }
           }
           FloatingActionButton(
               onClick = { onAction(NotesAction.Add) },
               modifier = Modifier.align(Alignment.BottomEnd).testTag(NotesListTestTags.ADD_BUTTON),
           ) {
               // contentDescription is the spoken label: localised prose, not the ID
               Icon(painterResource(Res.drawable.ic_add), contentDescription = stringResource(Res.string.add_note))
           }
       }
   }
   ```

   SwiftUI screens get a namespaced `enum`. Put it in a package (`public`) or in a file that belongs
   to both the app target and the UI-test target, so tests use the same constants:

   ```swift
   public enum AccessibilityID {
       public enum NotesList {
           public static let screen = "notes_list_screen"
           public static let addButton = "notes_list_add_button"
           public static func row(_ noteID: String) -> String { "notes_list_row_\(noteID)" }
       }
   }

   extension View {
       func accessibilityID(_ id: String) -> some View { accessibilityIdentifier(id) }

       /// A card or row whose wrapper carries the ID while its children stay individually queryable.
       func accessibilityContainerID(_ id: String) -> some View {
           accessibilityElement(children: .contain).accessibilityIdentifier(id)
       }
   }

   // Call sites: never an inline string literal
   Button("Add note", action: onAdd).accessibilityID(AccessibilityID.NotesList.addButton)
   ForEach(notes) { note in
       NoteRow(note: note).accessibilityContainerID(AccessibilityID.NotesList.row(note.id))
   }
   ```

   Never inline a raw ID string at a call site. The constant is what keeps a rename safe across the
   app and its tests.

4. **Expose the IDs to the tools.**

   - **Compose tests** (`runComposeUiTest`, `createComposeRule`) see `testTag` directly through
     `onNodeWithTag(...)`. Nothing else is needed.
   - **Android UiAutomator, Appium (UiAutomator2) and Maestro** read the accessibility tree, not the
     Compose tree. A `testTag` appears there as a `resource-id` only when an ancestor sets
     `testTagsAsResourceId = true`. Set it once, high in the tree, at the Activity root:

     ```kotlin
     // androidMain - host Activity
     setContent {
         Box(Modifier.fillMaxSize().semantics { testTagsAsResourceId = true }) {
             App()
         }
     }
     ```

     `testTagsAsResourceId` is an Android API of Jetpack Compose UI. Use it from `androidMain`. If your
     Compose version reports it as experimental, add `@OptIn(ExperimentalComposeUiApi::class)`.
     Content in a `Dialog`, `ModalBottomSheet` or `Popup` is hosted in a separate window, and the
     Activity root's flag may not reach it. When that content is declared in `commonMain`, add a
     one-line `expect`/`actual` modifier: the Android `actual` sets the flag, the iOS `actual` returns
     `this`. Apply it at the dialog's content root.

     ```kotlin
     // commonMain
     expect fun Modifier.exposeTestTagsAsResourceIds(): Modifier
     // androidMain
     actual fun Modifier.exposeTestTagsAsResourceIds(): Modifier = semantics { testTagsAsResourceId = true }
     // iosMain
     actual fun Modifier.exposeTestTagsAsResourceIds(): Modifier = this
     ```

   - **iOS with Compose Multiplatform**: the official docs state that `testTag` maps to the native
     `accessibilityIdentifier`, which is what XCUITest, Appium's XCUITest driver and Maestro query.
     Before Compose Multiplatform 1.8.0, the iOS accessibility tree synced only while an accessibility
     service ran. On those versions, test builds set
     `accessibilitySyncOptions = AccessibilitySyncOptions.Always(debugLogger = null)` in
     `ComposeUIViewController(configure = { ... })`. From 1.8.0 the option is gone: the tree loads on
     demand. Compose's iOS accessibility support is still maturing. Confirm each ID in Accessibility
     Inspector (Xcode > Open Developer Tool > Accessibility Inspector; look at "Identifier"), or print
     `app.debugDescription` in a UI test.
   - **SwiftUI and UIKit** expose `accessibilityIdentifier` directly. If you put an identifier on a
     container without `.accessibilityElement(children: .contain)`, SwiftUI may apply it to every child
     element. Use the container helper above, then confirm in Accessibility Inspector.

5. **Add spoken labels separately, only where needed.** Material and SwiftUI controls with visible
   text already have a label. Add `contentDescription` / `accessibilityLabel` to icon-only buttons,
   images that carry meaning, and rows that need a summary. Never put an ID in a label. A screen reader
   would read "notes underscore list underscore add underscore button" aloud, and every copy change
   would then break a test.

6. **Find elements in tests by ID.** The per-tool syntax and pitfalls are in
   [references/finding-elements.md](references/finding-elements.md): Appium UiAutomator2 (which adds a
   package prefix to `id` locators by default), Appium XCUITest, Maestro, XCUITest, UiAutomator and
   Compose tests.
   *Done when* each new ID is located once by the real tool, on each platform that ships the screen.

## Quick reference

| Concept | Compose (Android and CMP) | SwiftUI / UIKit |
|---|---|---|
| Locator (tests) | `Modifier.testTag("id")` | `.accessibilityIdentifier("id")` |
| Spoken label | `contentDescription` / `semantics { contentDescription = ... }` | `.accessibilityLabel(...)` |
| Hint | `semantics { onClick(label = ...) }` (action label) | `.accessibilityHint(...)` |
| Expose to UiAutomator / Appium / Maestro | `semantics { testTagsAsResourceId = true }` on a root (`androidMain`) | automatic |
| Seen on iOS as | `accessibilityIdentifier` (Compose Multiplatform) | `accessibilityIdentifier` |
| ID home | `<Screen>TestTags` object in `commonMain` | `enum AccessibilityID { enum <Screen> { ... } }` |
| Composite rows | tag the clickable row root; `useUnmergedTree = true` to reach children in Compose tests | `.accessibilityElement(children: .contain)` + identifier |

## Verify

- **Compile**: the module builds on both platforms (`kmp-build-check`, or the module's compile tasks).
- **Android**: open Appium Inspector or `uiautomatorviewer`, or run `adb shell uiautomator dump`.
  Each tagged element shows `resource-id` equal to the tag. If there is no `resource-id`, the
  `testTagsAsResourceId` ancestor is missing for that window.
- **iOS**: in Accessibility Inspector, or in Appium Inspector (the `name` attribute), each element
  shows its identifier.
- **Tests**: the new IDs are found by the project's real suite (Maestro flow, Appium test, XCUITest or
  Compose test).

Report each item as PASS, FAIL or NOT RUN with the reason. For example: "iOS inspection NOT RUN: no
macOS host". Never report an ID as working on a platform where it was not inspected or exercised.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| ID placed in `contentDescription` / `accessibilityLabel` | Screen readers read it aloud; translations and copy edits break tests | Locator in `testTag` / `accessibilityIdentifier`; prose in the label |
| No `testTagsAsResourceId` ancestor | UiAutomator, Appium and Maestro on Android see no `resource-id` | Set it once at the Activity root, and again in dialog or sheet windows |
| `semantics { testTagsAsResourceId = true }` in `commonMain` | It is an Android API, so the common compile fails | `androidMain` host root, or an `expect`/`actual` modifier |
| Appium `id` locator for a Compose tag | UiAutomator2 adds `<package>:id/`, so the bare tag never matches | Turn off ID autocompletion, or use a `UiSelector().resourceId(...)` (see reference) |
| Appium `accessibility id` on Android for a `testTag` | On Android it matches `content-desc`, not the tag | Use `resource-id` on Android; `accessibility id` works on iOS |
| Row ID built from the list index | Reordering or paging taps the wrong row silently | `row(note.id)` from a stable model ID |
| Tag on an inner `Text` instead of the clickable node | The test taps a node that has no click action | Tag the node that has the click handler |
| Identifier on a SwiftUI stack without `.contain` | Children may all inherit the same identifier | `.accessibilityElement(children: .contain)` first |
| Inline ID strings at call sites | Renames drift between the app and the tests | Constants in `TestTags` / `AccessibilityID` |
| Different schemes on Android and iOS | One cross-platform flow cannot drive both | One `<screen>_<element>_<role>` string per element |
| ID parameters added to every design-system component | API noise; IDs end up inside components | Tag at the call site; add a sub-element ID parameter only for a documented QA need |

## Review checklist

1. Every new interactive element, screen root, dialog action, error, empty state and retry has an ID.
2. IDs come from the screen's `TestTags` object or the `AccessibilityID` enum. No inline literals.
3. IDs follow `<screen>_<element>_<role>` (or the project's existing scheme) and are identical across
   platforms.
4. Dynamic rows use a stable model ID. Lazy lists also use `key = { it.id }`.
5. Locator and spoken label are separate, and labels are localised.
6. Android: one `testTagsAsResourceId` root per window (activity, dialogs, sheets), set from
   `androidMain`.
7. SwiftUI: composite rows use `.accessibilityElement(children: .contain)`.
8. Each new ID has been seen in an inspector, or found by a test, on each platform.

## Related skills

- `kmp-testing-patterns`: Compose UI tests with `onNodeWithTag`, plus unit tests for the state behind
  the screen.
- `kmp-build-check`: confirm the tagged screens compile on both platforms.
- `compose-multiplatform-screen`: the screen shape that owns a `<Screen>TestTags` object.
- `compose-design-system-component`: design-system components, tagged at the call site.
- [dadederk/iOS-Accessibility-Agent-Skill](https://github.com/dadederk/iOS-Accessibility-Agent-Skill): VoiceOver, Dynamic Type and accessible SwiftUI/UIKit.
- [skydoves/android-testing-skills](https://github.com/skydoves/android-testing-skills): Compose UI testing, UiAutomator and Espresso skills.
- [chrisbanes/skills](https://github.com/chrisbanes/skills): Compose skills, including UI testing patterns.
- [AvdLee/Swift-Testing-Agent-Skill](https://github.com/AvdLee/Swift-Testing-Agent-Skill): Swift Testing.
