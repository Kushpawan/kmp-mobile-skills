---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

I need a new "orders" feature in our KMP app. The iOS side is SwiftUI, so I want the order history logic in its own Kotlin module that the iOS framework exposes, and the Compose screens in a separate Android-only module next to it. Can you set up both modules, register them in settings.gradle.kts, and hook them into the shared framework, the Koin graph and the nav host?
