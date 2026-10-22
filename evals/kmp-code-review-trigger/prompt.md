---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

I've got a bunch of uncommitted changes on my feature branch — I moved the notes sync into a new NotesSyncRepository in commonMain, changed its constructor, and updated the iOS actual for the file storage. Before I push and open a PR, can you review everything that's not merged into develop yet? I'm worried I broke a Koin binding or the Swift code that calls into the shared framework.
