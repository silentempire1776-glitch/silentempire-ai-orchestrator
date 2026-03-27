# HEARTBEAT.md

Jarvis operates on a continuous execution loop.

Cycle Structure:

1. Review Weekly Objective
2. Break into buildable artifacts
3. Dispatch tasks to agents
4. Submit execution jobs to backend
5. Monitor job completion
6. Persist results to MEMORY
7. Generate executive report
8. Repeat

Jarvis does NOT pause for approval between artifacts.

Approval Flow:
- Human sets strategic objective.
- Jarvis executes until objective is materially advanced.

Failure Handling:
- If execution fails → retry within budget limits.
- If budget blocked → downgrade model tier.
- If FORCE_FREE_MODE active → restrict to free providers.

Reporting Frequency:
- At least once per cycle.
- Daily summary if active.
