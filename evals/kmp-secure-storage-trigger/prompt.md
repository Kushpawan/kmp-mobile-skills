---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

Right now our KMP app keeps the access and refresh tokens in DataStore on Android and NSUserDefaults on iOS, in plain text. I want a proper secure store in shared code — Android Keystore on one side, Keychain on the other — with existing users migrated without being logged out, and logout should wipe everything. Also, on iOS a user who deletes and reinstalls the app is still signed in; please fix that too.
