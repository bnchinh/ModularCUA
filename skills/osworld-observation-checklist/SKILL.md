---
name: osworld-observation-checklist
description: Use when performing multi-step GUI tasks in OSWorld and before reporting completion; keep actions tied to the latest screenshot and verify visible or saved outcomes.
allowed-tools: ipython
metadata:
  modularcua.requires-tools: ipython
---

# OSWorld observation checklist

1. Before a coordinate-based GUI action, use a fresh full-screen screenshot and work in the screenshot's coordinate space.
2. Prefer the registered `cua` helpers for mouse, keyboard, screenshot, and file operations. Use the shell only when it is suitable for the requested task.
3. After an action that should change application state, inspect a fresh observation or the saved artifact before proceeding when the result is not otherwise explicit.
4. Keep requested state separate from observed state. A successful function return or the Actor's own claim does not establish that the application accepted the change.
5. Before finishing, check each requested outcome and report unresolved items accurately. Do not infer task success from activity alone.
