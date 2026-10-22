---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

The networking code in our shared module has grown messy: three features each build their own Ktor HttpClient, the repositories catch Exception and return null, and one malformed item in the notes response blanks the whole list. I want to restructure the data layer in commonMain properly — one client with bearer token refresh, DTOs separate from domain models, and a typed result for errors. Can you propose the structure and then refactor the notes feature first?
