---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

OrdersViewModelTest keeps failing on CI maybe one run in four, but it always passes when I run it on my laptop. When it fails it's the "should emit NavigateToConfirmation when checkout succeeds" case, and the iOS simulator job fails it more often than the Android one. Someone suggested adding a retry, but I'd rather find out what's actually wrong.
