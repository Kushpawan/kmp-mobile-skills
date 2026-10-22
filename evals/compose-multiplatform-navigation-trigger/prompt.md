---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

Our Compose Multiplatform app currently switches between the login screen and the home screen with a plain if/else on a boolean. I want to move to a proper NavHost with typed routes: a splash while we check the stored token, a login flow, and a bottom bar with Feed, Search and Profile tabs that each keep their own back stack. When the refresh token expires we should land back on login, and a link like myapp://article/123 should open the article after the user signs in on both Android and iOS.
