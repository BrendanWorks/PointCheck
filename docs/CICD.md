# CI/CD

Two GitHub Actions workflows.

## `ci.yml` — automatic, safe, free

Runs on every pull request and every push to `main`. No Modal, no GPU, no
deploy. Two jobs:

- **Backend** — Python syntax check + `pytest backend/tests_ci/`. These are
  torch-free unit tests that lock in the security/integrity behaviour: SSRF
  guard (`url_guard`), request page cap and validation (`schemas`), persist
  hygiene (`report_generator.strip_b64`), the per-IP rate limiter and job
  eviction (`job_store`). CI never installs the inference stack.
- **Frontend** — lint (advisory), `tsc --noEmit`, `next build`, and
  `npm audit` on production deps (fails on high/critical).

## `deploy.yml` — manual, run during a maintenance window

`workflow_dispatch` only, because it deploys to Modal and runs the real GPU
regression suite (~10 min per environment). It encodes the project's mandatory
sequence:

```
validate  ->  staging deploy  ->  staging regression  ->  [prod deploy  ->  prod regression]
```

The production jobs run only when you tick the **deploy_prod** input. The
frontend is not deployed here — Vercel auto-deploys it on push to `main`.

### One-time setup (before the first run)

1. Create a Modal API token (Modal dashboard → Settings → API Tokens).
2. Add two repo secrets (Settings → Secrets and variables → Actions):
   - `MODAL_TOKEN_ID`
   - `MODAL_TOKEN_SECRET`
3. (Recommended) Create a `production` Environment (Settings → Environments)
   and add yourself as a **required reviewer**. The prod job will then pause
   mid-run and wait for your approval — a human checkpoint between a green
   staging regression and touching prod.

### Running a deploy

Actions → **Deploy backend** → Run workflow.
- Leave `deploy_prod` unchecked to deploy + regression-test staging only.
- Tick `deploy_prod` to continue to production after staging passes (pausing
  for approval if the environment reviewer is configured).

Rollback if a prod deploy goes bad: `modal app rollback wcag-tester`.

## Enabling this

The workflows live on a branch until reviewed. Merge to `main` during a
maintenance window, add the secrets above, then dispatch **Deploy backend**.
Merging the workflows changes nothing on its own — `ci.yml` just starts
running checks, and `deploy.yml` never runs until you dispatch it.
