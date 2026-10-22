---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

After bumping Kotlin and Room in `libs.versions.toml`, `./gradlew :composeApp:assembleDebug` still passes, but the iOS app fails in Xcode with "Command PhaseScriptExecution failed with a nonzero exit code". Further up in the log there's "Undefined symbols for architecture arm64" with a bunch of sqlite3 symbols. Can you work out what broke and fix it without breaking Android?
