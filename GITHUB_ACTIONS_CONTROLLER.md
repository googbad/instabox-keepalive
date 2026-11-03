# GitHub Actions InstaBox controller

This controller is intentionally separate from the existing read-only status workflow.

## Required repository secrets

Add these under **Settings → Secrets and variables → Actions → Repository secrets**:

- `INSTABOX_API_KEY`: the existing InstaBox API key with the minimum `machines:write` scope.
- `BARK_URL`: the same complete Bark push URL used by the WorkBuddy repository. Do not commit it or paste it into chat.

GitHub Actions secrets are repository-scoped; the WorkBuddy secret is not automatically shared.

## Enablement guard

The controller job is disabled unless one of these explicit gates is true:

- For a one-off manual run, dispatch the workflow with `enable_automation=true`.
- For scheduled operation, add the repository Actions variable `INSTABOX_AUTOMATION_ENABLED=true`.

The variable is deliberately absent by default, so scheduled runs execute tests only. A schedule in a non-default branch does not run automatically; GitHub scheduled workflows run from the default branch after this change is reviewed and merged.

## Runtime policy

- Schedule: every 20 minutes (GitHub may delay or drop scheduled events).
- Every invocation reads `GET /v1/machines` and uses the platform `runStartedAt` as the timer.
- Running machines receive one lightweight `exec` before 450 minutes.
- At or after 450 minutes, the controller performs `suspend → wait suspended → resume → wait running`.
- If a machine is found suspended after an interrupted rotation or platform timeout, the controller waits out any reported cooldown and then attempts recovery resume.
- Rotation is reported successful only after `runStartedAt` advances.
- Bark sends success/failure notifications for lifecycle rotation; ordinary keepalive execs are silent.
- No local state file or Oracle VPS loop is used.

The 20-minute cadence leaves only about 10 minutes before the free-tier 30-minute idle threshold. GitHub scheduling is best-effort, so this is not a hard real-time guarantee.

## Safety

Do not enable the controller until the machine has been manually suspended and resumed in Muse as planned, and the new `runStartedAt` has been verified. The workflow does not run lifecycle actions while its enablement gate is off. Review and merge this branch before expecting scheduled runs.
