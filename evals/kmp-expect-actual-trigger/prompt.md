---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

Our notes screen in commonMain has to remember the unsaved draft text when the app gets killed. On Android I'd normally use SharedPreferences and on iOS NSUserDefaults, but I don't know how to reach either from shared code without dragging an Android Context into commonMain. How should I structure this, and can you write the androidMain and iosMain implementations?
