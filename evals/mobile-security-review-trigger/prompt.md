---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

We're about to ship our first release of the KMP app and a pen test is booked for next month. Can you go through the Android manifest, Info.plist, the Ktor client setup and how we store the auth token, and flag anything insecure? I'm especially unsure whether our debug logging and the staging-server switch end up in release builds.
