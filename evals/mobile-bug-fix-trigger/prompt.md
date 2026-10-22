---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

QA filed a bug against 2.4.0: after editing a note and tapping Save, the notes list still shows the old title until you kill and reopen the app. They saw it on an iPhone, and I'm not sure whether Android does the same. Can you track down why and fix it?
