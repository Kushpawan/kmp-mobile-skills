---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

Our KMP repo has no CI yet and we keep merging changes that break the iOS framework link. Can you add a GitHub Actions workflow that runs the Android unit tests and lint on Linux and the iOS simulator tests on a Mac runner? It should also stop downloading the Kotlin/Native toolchain from scratch on every run.
