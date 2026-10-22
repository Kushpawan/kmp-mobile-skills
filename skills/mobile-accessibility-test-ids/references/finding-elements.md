# Finding elements by ID, tool by tool

- [How each tool sees an ID](#how-each-tool-sees-an-id)
- [Appium: UiAutomator2 (Android)](#appium-uiautomator2-android)
- [Appium: XCUITest (iOS)](#appium-xcuitest-ios)
- [One helper for both platforms](#one-helper-for-both-platforms)
- [Maestro](#maestro)
- [XCUITest](#xcuitest)
- [UiAutomator (Android instrumented tests)](#uiautomator-android-instrumented-tests)
- [Compose UI tests](#compose-ui-tests)

Always confirm the attribute that a real build exposes before you write the selector: use Appium
Inspector, `adb shell uiautomator dump`, Xcode's Accessibility Inspector, or Maestro Studio.

## How each tool sees an ID

| Tool | Android: a Compose `testTag` | iOS: a `testTag` (CMP) or `accessibilityIdentifier` |
|---|---|---|
| Compose test (`onNodeWithTag`) | the tag, directly | the tag, directly (CMP tests on the simulator) |
| UiAutomator `By.res("id")` | `resource-id`, only with `testTagsAsResourceId` | not applicable |
| Appium UiAutomator2 | `resource-id`, only with `testTagsAsResourceId` | not applicable |
| Appium XCUITest | not applicable | `name` attribute |
| Maestro `id:` | `resource-id`, only with `testTagsAsResourceId` | `accessibilityIdentifier` |
| XCUITest | not applicable | `identifier` |

## Appium: UiAutomator2 (Android)

The driver's `id` strategy maps to UiAutomator `By.res`. It **adds the app's package prefix**
(`<package>:id/`) to any ID that lacks one. A Compose tag exposed through `testTagsAsResourceId` is
the bare string, so `id("notes_list_add_button")` searches for
`com.example.app:id/notes_list_add_button` and finds nothing. There are two fixes:

```kotlin
// 1. Exact resource-id through a UiSelector
driver.findElement(AppiumBy.androidUIAutomator("new UiSelector().resourceId(\"notes_list_add_button\")"))

// 2. Turn off the prefixing (a UiAutomator2 driver setting), then use the plain id strategy
driver.setSetting("disableIdLocatorAutocompletion", true)
driver.findElement(AppiumBy.id("notes_list_add_button"))
```

```python
# Python client equivalents
driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().resourceId("notes_list_add_button")')
driver.update_settings({"disableIdLocatorAutocompletion": True})
driver.find_element(AppiumBy.ID, "notes_list_add_button")
```

- `accessibility id` maps to `content-desc` on Android (an exact match). It does **not** find a
  `testTag`. Do not "fix" that by copying IDs into `contentDescription`.
- Use XPath (`//*[@resource-id='notes_list_add_button']`) only as a last resort. It is slow, and
  position-based XPath breaks with every layout change.
- Dynamic rows: `UiSelector().resourceIdMatches("notes_list_row_.*")` finds all rows. Select by the
  model ID for a specific one.

## Appium: XCUITest (iOS)

In the XCUITest driver, `id`, `name` and `accessibility id` are all aliases of the element's `name`
attribute. When an `accessibilityIdentifier` is set, that attribute normally shows it. Check this in
Appium Inspector for each new screen.

```kotlin
driver.findElement(AppiumBy.accessibilityId("notes_list_add_button"))
// exact match on the identifier only, even when a label exists:
driver.findElement(AppiumBy.iOSNsPredicateString("identifier == 'notes_list_add_button'"))
```

## One helper for both platforms

Because the Android and iOS strategies differ, wrap them once:

```kotlin
fun AppiumDriver.byTestId(id: String): WebElement =
    if (this is AndroidDriver) findElement(AppiumBy.androidUIAutomator("new UiSelector().resourceId(\"$id\")"))
    else findElement(AppiumBy.iOSNsPredicateString("identifier == '$id'"))
```

The same ID string then drives both platforms, provided the app uses one naming scheme everywhere.

## Maestro

```yaml
appId: com.example.app
---
- launchApp
- assertVisible:
    id: "notes_list_screen"
- tapOn:
    id: "notes_list_add_button"
- tapOn:
    id: "notes_list_row_42"
- tapOn:
    id: "notes_list_row_.*"       # id is a regular expression: any row
    index: 0
```

- `id` matches the Android `resource-id`. For Compose, that needs `testTagsAsResourceId`. On iOS, `id`
  matches the `accessibilityIdentifier`. In Maestro, `accessibilityLabel` maps to `text`, not to `id`.
- `id` is a regular expression, so in dotted IDs a `.` matches any character. Snake_case IDs avoid
  that surprise.
- Maestro can match on visible text. IDs survive copy changes and translation; text matching does not.

## XCUITest

```swift
final class NotesListUITests: XCTestCase {
    func test_openEditor_when_rowTapped() {
        let app = XCUIApplication()
        app.launch()

        // identifier-only match, any element type
        let row = app.descendants(matching: .any)
            .matching(identifier: AccessibilityID.NotesList.row("42"))
            .firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        row.tap()

        XCTAssertTrue(app.otherElements[AccessibilityID.NoteEditor.screen].waitForExistence(timeout: 5))
    }
}
```

- Subscripts such as `app.buttons["..."]` match the identifier **or** the label. That is convenient,
  but a label that happens to equal the ID string hides mistakes. `matching(identifier:)` is exact.
- The element type matters for subscripts: a SwiftUI row may be an `otherElements`, a `cells` or a
  `buttons` element. `descendants(matching: .any)` avoids guessing.
- Print `app.debugDescription` to see the tree that XCUITest sees, identifiers included.
- `try app.performAccessibilityAudit()` (iOS 17+) runs Accessibility Inspector's audit inside a UI
  test.

## UiAutomator (Android instrumented tests)

```kotlin
val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
val add = device.wait(Until.findObject(By.res("notes_list_add_button")), 5_000)
add.click()
```

Use the one-argument `By.res(id)`. `By.res(packageName, id)` builds `<package>:id/<id>`, which never
matches a Compose tag.

## Compose UI tests

```kotlin
onNodeWithTag(NotesListTestTags.ADD_BUTTON).performClick()
onNodeWithTag(NotesListTestTags.row("42")).assertIsDisplayed()
// a tagged child inside a node that merges its descendants (for example a Button's content),
// with fun rowTitle(noteId: String) = "notes_list_row_${noteId}_title" in NotesListTestTags:
onNodeWithTag(NotesListTestTags.rowTitle("42"), useUnmergedTree = true).assertTextEquals("Milk")
```

Compose tests read the semantics tree directly, so `testTagsAsResourceId` is not needed for them.
Use the same `TestTags` constants as production. Never retype the strings.
