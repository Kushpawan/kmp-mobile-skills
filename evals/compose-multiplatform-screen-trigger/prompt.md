---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

I need a new "Order details" screen in our shared Compose UI module. It should load the order by id, show a loading spinner and an error state with retry, and have a "Cancel order" button that asks for confirmation and then navigates back. Please follow the same ViewModel and side-effect pattern the other screens use, and include previews and unit tests for the ViewModel.
