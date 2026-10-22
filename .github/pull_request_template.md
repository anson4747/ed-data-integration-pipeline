## What changed and why

<!-- One or two sentences. Link the issue if there is one. -->

## Type of change

- [ ] New pipeline step or source
- [ ] Schema change (new migration under `db/*/migrations`)
- [ ] Data quality rule
- [ ] Fix
- [ ] Documentation only

## Reviewer checklist

- [ ] No applied migration was edited; schema changes are a new `V###__` script
- [ ] Migration is safe to rerun or is guarded (`IF NOT EXISTS`, `IF OBJECT_ID(...) IS NULL`)
- [ ] Loads are idempotent: running the step twice gives the same result
- [ ] Row counts reconcile source to target, and rejected rows land in `dq.exception_log`
- [ ] New step writes to `etl.step_run` and fails loudly (no silent `try/except: pass`)
- [ ] No credentials, patient identifiers or raw source files committed
- [ ] Runbook and data dictionary updated if behaviour or columns changed
- [ ] CI is green (unit, deploy, redeploy, integration)

## Deployment notes

<!-- Anything an operator needs to know before deploying to test or prod. -->
