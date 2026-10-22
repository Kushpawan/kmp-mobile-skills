---
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
tags: [trigger]
---

I need unit tests for the new OrdersViewModel in shared/src/commonMain. It loads orders through OrdersRepository on viewModelScope, exposes a StateFlow<OrdersUiState>, and sends a one-shot NavigateToOrderDetail effect when a row is tapped. We can't use MockK because the tests have to run on iosSimulatorArm64Test too. Can you write the commonTest tests, covering the loading, error and navigation cases?
