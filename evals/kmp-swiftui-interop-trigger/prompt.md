---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

I'm wiring the SwiftUI notes screen in our iOS app to the shared Kotlin `NotesViewModel`, which exposes a `StateFlow<NotesUiState>`. We already apply SKIE in `shared/build.gradle.kts`. Right now I start a `Task` in `onAppear` that loops over the flow, and I think it keeps running after the user leaves the screen. What's the right way to observe that state from an `@Observable` class so it stops cleanly, and how should I switch over the sealed `NotesUiState` in Swift?
