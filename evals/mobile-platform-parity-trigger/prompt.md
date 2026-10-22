---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

QA says the profile photo upload behaves differently on iPhone: on Android a slow connection shows an error after a few seconds, but on iOS the spinner just sits there for ages. I only touched the androidMain implementation of the uploader last sprint. Can you compare the Android and iOS sides of this feature and tell me everywhere else they don't match?
