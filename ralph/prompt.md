# ISSUES

Local issue files from `issues/` are provided at start of context. Parse them to understand the open issues.

You will work on the AFK issues only, not the HITL ones.

You've also been passed a file containing the last few commits. Review these to understand what work has been done.

If all AFK tasks are complete, output the phrase `NO MORE TASKS`.

# TASK SELECTION

Pick the next task. Prioritize tasks in this order:

1. Critical bugfixes
2. Development infrastructure

Getting development infrastructure like tests and dev scripts ready is an important precursor to building features.

3. Tracer bullets for new features

Tracer bullets are small slices of functionality that go through all layers of the system, allowing you to test and validate your approach early. This helps in identifying potential issues and ensures that the overall architecture is sound before investing significant time in development.

TL;DR - build a tiny, end-to-end slice of the feature first, then expand it out.

4. Polish and quick wins
5. Refactors

# EXPLORATION

Explore the repo. Read AGENTS.md for critical context, conventions, and known pitfalls. Read config.yaml to understand runtime behaviour. Read CONTEXT.md and docs/adr/ if they exist.

# IMPLEMENTATION

Implement the task following the conventions in AGENTS.md.

# FEEDBACK LOOPS

Before committing, run the feedback loops:

- `pytest tests/ -v` to run the tests
- `pytest tests/` must pass with zero failures

# COMMIT

Make a git commit. The commit message must follow the repo convention:

- Prefix with scope: `core:`, `docs:`, `tui:`, `ci:`, `wip:`, `ignore:`
- Describe WHY from end-user perspective, not WHAT changed
- Include files changed
- Blockers or notes for next iteration

# THE ISSUE

If the task is complete, move the issue file to `issues/done/`.

If the task is not complete, add a note to the issue file with what was done.

# FINAL RULES

ONLY WORK ON A SINGLE TASK.
