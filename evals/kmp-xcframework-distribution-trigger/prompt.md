---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

Our iOS team wants to consume the `:shared` module as a Swift package instead of running Gradle inside their Xcode build. Can you set up a release XCFramework for it and a `Package.swift` with a remote `binaryTarget`? The Kotlin code uses the native SQLite driver, and this repo already has `android-v*` tags for the Android library, so I'm not sure how the iOS versions should be tagged.
