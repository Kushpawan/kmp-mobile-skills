---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

Our KMP app crashes on iOS right at launch with "KoinApplication has not been started", while Android starts fine. Koin is started in our Android Application class, and on iOS the SwiftUI app calls into shared code from ContentView. Can you set up Koin start-up properly for both platforms, move the platform-specific bindings into their own modules, and add a test that catches missing definitions before we ship?
