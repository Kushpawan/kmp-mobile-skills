---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

I added coil-compose to our shared module's commonMain and now the iosSimulatorArm64 build fails with "No matching variant" while Android builds fine. Our libs.versions.toml is also a mess, with a few versions hardcoded straight in build.gradle.kts files. Can you add the dependency properly through the version catalog and tell me where else we're bypassing it?
