# CI/CD Pipeline Setup

## Overview

The PointCheck repository has two GitHub Actions workflows:

- **CI** (`.github/workflows/ci.yml`) — Runs automatically on every PR and push to main
- **Deploy** (`.github/workflows/deploy.yml`) — Manual workflow_dispatch only; never auto-deploys

## CI Workflow

**Trigger:** Every PR to main, every push to main  
**Duration:** ~3-5 minutes  
**GPU/Modal required:** No

### What it checks

1. **Backend tests** (`pytest backend/tests_ci/`)
   - SSRF guard validation
   - Page cap enforcement
   - Schema validation
   - strip_b64 persistence
   - Rate limiter logic
   - Job eviction

2. **Frontend checks**
   - TypeScript type checking (`tsc --noEmit`)
   - Build validation (`npm run build`)
   - Npm audit (moderate advisory level)

All checks must pass before merging to main.

## Deploy Workflow

**Trigger:** Manual via Actions ▸ Deploy backend ▸ "Run workflow"  
**Duration:** ~20-30 minutes (staging regression suite ~10 min, prod ~10 min)  
**Requires:** Modal API credentials + optional production environment approval

### Setup (one-time)

1. **Add Modal secrets to the repository:**
   - Go to Settings ▸ Secrets and variables ▸ Actions
   - Create two new repository secrets:
     - `MODAL_TOKEN_ID` — from `modal config show` (client_id)
     - `MODAL_TOKEN_SECRET` — from `modal config show` (client_secret)

2. **Optional: Require approval before prod deploy**
   - Go to Settings ▸ Environments
   - Create an environment named `production`
   - Enable "Required reviewers" to gate the deploy step

### How to deploy

1. Ensure CI passes (all tests green on main)
2. Go to Actions ▸ Deploy backend ▸ Run workflow
3. Choose whether to deploy to production (after staging validation passes)
4. If you set up the `production` environment, an approver must click "Approve and deploy" for prod

### Deployment sequence

```
1. Validate — Python syntax check (main.py, modal_app.py)
2. Deploy to staging — modal deploy --env staging
3. Regression suite — staging only, ~10 min
4. [GATE] If deploy_prod == true and no staging regression failures
5. Deploy to production — modal deploy (prod)
6. Regression suite — production only, ~10 min
```

Rollback from the Modal dashboard or CLI: `modal app rollback wcag-tester`

## Known limitations

- **Regression suites use `--skip-judge --skip-axe`** — OLMo is not installed in the CI environment. The full suite runs locally before deciding to deploy.
- **Tests don't run on the local Jetson** — they run in the GitHub Actions runner with mocked inference endpoints.

## Next steps after merge

1. Add Modal secrets (see Setup above)
2. Optionally add `production` environment with required approver
3. Try a manual test deploy: Actions ▸ Deploy backend ▸ tick "deploy_prod" checkbox
