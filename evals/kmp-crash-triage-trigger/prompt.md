---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

Since we shipped 3.1 to TestFlight, the iOS app crashes when you open an order from the history screen. Android is fine. The tester sent me the .ips file (it's in ~/Downloads) and it's mostly hex addresses with an abort at the top. Can you work out what's actually crashing in our shared Kotlin code?
