---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

koverVerify is failing on our :shared module. The last report says 52% line and 38% branch coverage, and the team target is 80/60. Most of the gap is in the ViewModels and use cases under commonMain. Can you add the missing unit tests until we hit the target, and show me the real numbers before and after?
