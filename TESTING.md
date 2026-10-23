# Testing and review

Each MVP brief defines its own automated test ideas and a user-run checklist. Automated tests protect behavior that can be reproduced consistently. The user-run checklist covers media handling, usability, and real-provider behavior that needs the user's machine or judgment.

For every MVP, the agent should:

- Add focused automated tests alongside the feature.
- Keep test fixtures synthetic or explicitly safe to publish; never use private journal audio or transcripts in the public repository.
- Run the relevant automated checks for each MVP and report what ran, including failures and environment limitations.
- Give the user the manual checklist in a concise format and capture any reported issues in the active MVP brief.
- Avoid claiming a behavior is verified when a test was written but not run.

The active MVP brief is the source of its acceptance criteria and checklist. Update `PRODUCT_SPEC.md` for changed user behavior and `ARCHITECTURE.md` for changed technical decisions after each MVP review or major change.
