---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

We're about to publish our :core:sync module as a Kotlin Multiplatform library that two other apps will consume. Before we do, can you give it a thorough health check? I'm worried about platform code leaking into commonMain, missing iOS actuals, tests that never run on iOS, and whether its public API is wider than it should be. Don't change anything yet, just tell me what you find, worst first.
