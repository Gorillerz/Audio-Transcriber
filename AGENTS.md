# Instructions for coding agents

- Read `PRODUCT_SPEC.md` and `ARCHITECTURE.md` before changing product behavior, storage, or processing flows.
- Read `MVP_PLAN.md` and the brief for the active MVP. Keep changes within that MVP unless the user redirects scope.
- Preserve the raw audio and raw transcription. Treat edits and generated outputs as new versions.
- Keep provider-specific code behind adapters and keep secrets out of files, logs, and source control.
- Prefer small changes that follow the existing structure. Add and run focused automated tests for implemented behavior as part of each MVP, then include a user-run checklist in the MVP brief.
- At the top of each source file, briefly state its responsibility. Give each function a concise docstring explaining its purpose and any non-obvious design choice; avoid comments that merely restate each line.
- Update `PRODUCT_SPEC.md` when user-facing behavior or acceptance criteria change. Update `ARCHITECTURE.md` when storage, data flow, or technical decisions change. Recheck both at the end of each MVP and after major architectural changes.
- Before finishing, summarize changed files, decisions, automated checks added or run, and the user-run checklist.
