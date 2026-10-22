---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

I just moved the date formatting code from androidMain into commonMain and added an actual in iosMain. The Android build is green, but I haven't touched Xcode. Before I open the PR against main, can you check that everything still builds and the tests pass on both Android and iOS?
