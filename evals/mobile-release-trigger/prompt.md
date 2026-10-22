---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

We're about to ship version 1.4.0 of the app on both Google Play and the App Store, and last time the Android and iOS build numbers ended up different. How should we bump versionCode/versionName and the iOS version so they stay in sync, and what should we tag the release with? A Fastlane setup for uploading to the Play internal track and TestFlight would help too.
