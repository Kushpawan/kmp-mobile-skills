---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

I added Room to our shared module so the articles list works offline. Android is fine, but on the iOS simulator the app crashes the first time the database is opened with "Cannot find the associated androidx.room.RoomDatabaseConstructor for AppDatabase". Can you look at shared/build.gradle.kts and the database setup and fix it? I also need to add a bookmarked column without wiping existing users' data.
