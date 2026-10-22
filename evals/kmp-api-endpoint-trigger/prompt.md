---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

I need to call a new backend endpoint from our shared KMP module: GET /v1/orders/{orderId} returns the order with its line items (sample JSON below). Please add it end to end — DTO, API call, repository, use case and the Koin wiring — following how the existing profile endpoint is done, and include tests with MockEngine.

{"id":"o-1","status":"shipped","total_minor":4599,"currency":"eur","items":[{"sku":"A-1","name":"Mug","quantity":2}]}
