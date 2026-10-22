# Lens — Swift, SwiftUI and the iOS side of KMP

Tier 2 rows for Swift sources, Xcode project settings and the Swift code that consumes a Kotlin
framework. A hit is a proposal the author can reject with a reason; a project rule that says
otherwise wins. The state and side-effect rows that are language-independent live with the Kotlin
lens; the skill's workflow loads them for Swift changes too.

**Columns.** *Lens* — stable name, becomes the key `swift/<lensName>`. *What a hit looks like* — the
violation; *Applies when* states a condition. *Floor* — minimum severity. *Mech?* — `yes`: the
compiler (with strict concurrency checking), SwiftLint or Xcode's runtime checkers can catch it;
`partial`: a grep finds candidates; `no`: needs reading.

## Contents

1. [Concurrency](#1-concurrency)
2. [Memory and lifecycle](#2-memory-and-lifecycle)
3. [SwiftUI](#3-swiftui)
4. [Consuming a Kotlin framework](#4-consuming-a-kotlin-framework)
5. [Data, files and networking](#5-data-files-and-networking)
6. [Accessibility and UI tests](#6-accessibility-and-ui-tests)
7. [Design tokens and native components](#7-design-tokens-and-native-components)

## 1. Concurrency

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Checked continuation misuse | `withCheckedContinuation` / `withCheckedThrowingContinuation` resumed twice (a timeout path and a delegate callback both resume — a runtime trap) or never resumed on some path (the awaiting task hangs forever) | Critical | no |
| Off-main UI mutation | `@Published`, `@State` or `@Observable` state written from a background context with no `@MainActor` hop. **Critical** when the write touches UIKit directly | High | partial — Main Thread Checker at runtime |
| Main-queue deadlock | `DispatchQueue.main.sync` reachable from the main thread | Critical | partial — grep |
| Actor isolation bypassed | Mutable shared state in a class used from several tasks with no actor or `@MainActor`, hidden behind `@unchecked Sendable` or `nonisolated(unsafe)` | High | yes — Swift 6 language mode or `SWIFT_STRICT_CONCURRENCY = complete` |
| Detached task loses context | `Task.detached` used where a child `Task { }` was meant — loses actor isolation, priority and cancellation from the parent | Medium | partial |

## 2. Memory and lifecycle

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Retain cycle | `self` captured strongly in a closure that `self` stores (a handler property, a Combine `sink` kept in `self`'s cancellables, a long-running `Task` held by `self`). Use `[weak self]` or end the task | High | partial |
| Uncancelled task | A `Task` started in `onAppear`, `init` or `viewDidLoad` with no cancellation on disappear or `deinit`. Prefer the `.task { }` modifier, which cancels automatically | High | no |
| `onAppear` re-entry | Work in `onAppear` that is not idempotent — it runs again on every navigation return and tab switch | High | no |
| Observer never removed | A `NotificationCenter` block observer, KVO observation or timer that outlives the object that registered it | Medium | partial |

## 3. SwiftUI

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| `@ObservedObject` created in the view | `@ObservedObject var model = Model()` — the model is recreated on every view update. Use `@StateObject` (or `@State` for an `@Observable` class) when the view owns it | High | partial |
| `@State` seeded from a parameter | `@State` initialised from an `init` parameter — later changes to the parameter are ignored because `@State` keeps its first value | Medium | partial |
| Non-unique `ForEach` identity | `ForEach(items, id: \.self)` over values that can repeat, or an id that is not stable — rows display the wrong data or animate incorrectly | Medium | no |
| `.task(id:)` not keyed | A `.task` or `onChange` that depends on an input it is not keyed on — the work does not re-run when the input changes | Medium | no |
| Hand-rolled modal | A custom dim-and-card overlay, toolbar or alert where `.alert`, `.confirmationDialog`, `.sheet`, `.fullScreenCover` or the navigation bar exist — loses focus handling, VoiceOver behaviour and keyboard support | Medium | no |

## 4. Consuming a Kotlin framework

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Kotlin throw not caught | Swift calls a Kotlin function annotated `@Throws` without `try` handling every error path; or calls one that can throw and has no `@Throws` — that exception terminates the app (fix it on the Kotlin side) | Critical | partial |
| Kotlin flow collected forever | A Kotlin `Flow` bridged to Swift (an `AsyncSequence` from a bridging tool, or a callback wrapper) collected in a task that is never cancelled — the upstream coroutine and its resources stay alive | High | no |
| `default:` over a Kotlin sealed type | A Swift `switch` on a bridged Kotlin sealed class or enum that uses `default:` — a new Kotlin case silently takes the default branch. Prefer an exhaustive bridge where the project has one | Medium | partial |
| Business logic duplicated in Swift | A validation, threshold, formatting or eligibility rule written in Swift that already exists — or should exist — in shared Kotlin. It will drift from Android | High | no |
| Kotlin type identity across frameworks | A value from one Kotlin framework passed to an API of another Kotlin framework — each framework has its own copy of shared types, so the "same" class is two unrelated Swift types | High | partial |

## 5. Data, files and networking

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| `try!` / force unwrap / `as!` | `try!`, `as!` or `!` on a value that can legitimately be nil or throw — network data, decoded JSON, file reads, URL construction from input | High | yes — SwiftLint `force_try`, `force_cast`, `force_unwrapping` |
| Decode without handling | `JSONDecoder().decode` with no error path, or a `Codable` whose optionality does not match the wire contract — one missing field fails the whole payload | High | partial |
| No request timeout | A `URLSession` request behind a blocking spinner with no explicit timeout — the default request timeout is 60 seconds | Medium | partial |
| Hardcoded container path | A file path built from a literal or a stored absolute path — the app container path changes between installs and updates. Resolve with `FileManager` URLs each launch | Medium | partial |
| Money or time in the wrong type | A currency amount in `Double`/`Float` (use `Decimal` or integer minor units), or a timestamp stored or sent without an explicit time zone | Critical | partial |

## 6. Accessibility and UI tests

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Missing accessibility identifier | An interactive control (button, field, list-row tap target, alert action, retry) with no `.accessibilityIdentifier`. *Applies when* the project's UI tests locate elements by identifier | Medium | no |
| Index used as identifier | A row identifier built from a `ForEach` array index instead of a stable model id — tests hit the wrong row after a reorder | Medium | partial |
| Identifier used as label | The same string passed to `.accessibilityIdentifier` and `.accessibilityLabel` — VoiceOver reads a code string | Medium | partial |
| Over-tagging | An identifier on a decorative image, divider, spacer or layout-only stack — dilutes the locator surface | Low | no |
| Fixed font size | `.font(.system(size:))` on text — fixed sizes do not scale with Dynamic Type. Use a text style or a scaled font | Medium | yes — grep |

## 7. Design tokens and native components

*Applies when* the project ships a design system with colour, typography and spacing tokens for
SwiftUI.

| Lens | What a hit looks like | Floor | Mech? |
|---|---|---|---|
| Hardcoded style value | `Color(red:green:blue:)`, a hex initialiser, a system colour like `.red` / `.gray`, or a padding/corner-radius literal that duplicates an existing token | Medium | partial — grep |
| Font bypasses the type scale | `.font(.system(...))`, `.font(.title)` or `.font(.headline)` where the project's text styles exist | Medium | yes — grep |
| SF Symbol sized with a font | `.font(.system(size:))` on an `Image` where `.imageScale` or the project's icon sizing applies | Low | yes — grep |
| Static palette in a themed view | A light-theme-only colour in a view that must follow light and dark mode, where an environment-provided themed colour exists | Medium | no |
