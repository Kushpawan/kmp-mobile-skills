---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

QA's Appium suite can't find any buttons on our new Compose Multiplatform checkout screen. On Android they fall back to XPath, and on iOS nothing matches at all. Can you add proper test IDs to that screen so the same locators work on both platforms, without breaking TalkBack and VoiceOver labels?
