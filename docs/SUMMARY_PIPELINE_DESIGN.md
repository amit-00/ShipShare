# Pipeline Spec (Revised MVP)

## 1) Goals

### MVP outcomes

1. Ingest “shipped work” signals from GitHub reliably using **push webhooks**.
2. Build queryable **ChangeSets** that are independent of recap generation.
3. Keep ChangeSet construction **deterministic and idempotent**.
4. Hydrate only the most important ChangeSets to control GitHub API cost.
5. Include targeted code snippets only when a ChangeSet is important enough.
6. Store LLM-generated semantic fields on ChangeSets so recap generation is cheap.
7. Generate **one recap per requested time window** from existing ChangeSets.

### Non-goals (MVP)

- No PR enrichment logic, even though PR permissions exist.
- No automatic posting.
- No full repository sync or full history reconstruction beyond bounded recovery behavior.

---

# 1.1) Tech Stack

## Language & runtime

- **Python 3.12+** — all backend services
- **Sync-first** approach: standard `def` route handlers, sync DB driver, sync HTTP clients. Simpler debugging, easier to reason about, sufficient for the I/O profile (webhook receipt is fast; builder/recap workers are batch-oriented, not high-concurrency).

## Web framework

- **FastAPI** with **Uvicorn** (`--workers N` for process-based concurrency)
- Used for: webhook ingestion endpoint, builder dispatch/worker endpoints, recap trigger, health checks
- Pydantic v2 for request/response validation and ChangeSet body schema

## Infrastructure (GCP-native)

### Compute — Cloud Run

All services are deployed as **Cloud Run services** (gen2, CPU always-allocated for workers).

| Service | Cloud Run config | Trigger |
|---------|-----------------|---------|
| **Ingestion API** | min 1 instance, concurrency 80, timeout 10s | GitHub webhook HTTPS POST |
| **Builder dispatcher** | min 0, concurrency 1, timeout 30s | Cloud Scheduler (daily) |
| **Builder worker** | min 0, concurrency 1, timeout 900s (15 min), CPU always-allocated | Cloud Tasks HTTP target |
| **Normalization worker** | min 0, concurrency 10, timeout 60s | Cloud Tasks HTTP target |
| **Recap dispatcher** | min 0, concurrency 1, timeout 30s | Cloud Scheduler (runs frequently, e.g. hourly) |
| **Recap worker** | min 0, concurrency 1, timeout 300s | Cloud Tasks HTTP target or manual API call |

For MVP, these can be **routes within a single FastAPI application** deployed as one Cloud Run service. The route groups are:

- `/webhooks/github` — ingestion (sync handler, fast)
- `/internal/normalize/{delivery_id}` — normalization (Cloud Tasks target)
- `/internal/builder/dispatch` — builder fan-out (Cloud Scheduler target)
- `/internal/builder/run` — builder per-repo work (Cloud Tasks target)
- `/internal/recap/dispatch` — recap fan-out: finds users due for a recap (Cloud Scheduler target)
- `/internal/recap/generate` — recap generation for a single user (Cloud Tasks target or manual API call)
- `/health` — health checks

When scaling demands it, split into separate Cloud Run services by route group. The split is clean because each route group has independent scaling characteristics.

### Task queue — Cloud Tasks

- Builder fan-out: the dispatcher endpoint queries `user_repo WHERE status = 'active'` and creates one Cloud Task per `(user_id, repo_id)`, targeting `/internal/builder/run`
- Normalization: the webhook handler stores the raw delivery and creates one Cloud Task targeting `/internal/normalize/{delivery_id}`
- **Task naming for deduplication**: use `build-{user_id}-{repo_id}-{date}` as the task name — Cloud Tasks rejects duplicate task names within the deduplication window, replacing Postgres advisory locks for concurrency control in this deployment model
- Built-in retry with exponential backoff for transient failures
- Rate limiting per queue to respect GitHub API quotas

### Scheduling — Cloud Scheduler

- Builder dispatch: daily cron (e.g. `0 6 * * *` UTC) → HTTPS POST to `/internal/builder/dispatch`
- Recap dispatch: frequent cron (e.g. every hour `0 * * * *` UTC) → HTTPS POST to `/internal/recap/dispatch`
  - The dispatcher checks each user's `recap_cadence` and `last_recap_at` to decide who is due
  - Enqueues one Cloud Task per due user targeting `/internal/recap/generate`
  - This supports per-user cadences (weekly default, daily optional) without requiring a separate Cloud Scheduler job per user
- Both use OIDC authentication to the Cloud Run service

### Database — Cloud SQL for PostgreSQL 15+

- Connect via **Cloud SQL Auth Proxy** (sidecar container in Cloud Run) or **Private IP** with Serverless VPC Connector
- Connection pooling: use **Cloud SQL Auth Proxy** built-in pooling, or add a **PgBouncer** sidecar if connection count becomes a concern
- Automated backups, point-in-time recovery enabled
- High-availability (regional) for production

### Object storage — Cloud Storage (GCS)

- Single bucket with prefix-based organization (as defined in Section 6)
- Lifecycle rules (Section 14.4) configured at the bucket level
- Uniform bucket-level IAM access (no per-object ACLs)

### LLM — Vertex AI

- **Gemini models** (e.g. Gemini 2.0 Flash for semantic enrichment, Gemini 2.5 Pro for recap generation)
- `vertexai` SDK (sync client)
- Structured output via Gemini's JSON mode for deterministic schema compliance on semantic fields
- Request retry with `tenacity` for transient Vertex AI errors
- Model and prompt version tracked in ChangeSet metadata for reproducibility

### Secrets — Secret Manager

- GitHub App private key
- GitHub webhook secret
- Any API keys or credentials not handled by IAM
- Mounted as environment variables in Cloud Run via secret references (not baked into images)

## Python dependencies

### Core

| Package | Purpose |
|---------|---------|
| `fastapi` | HTTP framework |
| `uvicorn[standard]` | ASGI server |
| `pydantic>=2.0` | Validation, ChangeSet body schema, settings |
| `psycopg[binary]>=3.1` | Sync Postgres driver (psycopg3) |
| `sqlalchemy>=2.0` | ORM / query builder (sync engine) |
| `alembic` | Database migrations |

### GCP

| Package | Purpose |
|---------|---------|
| `google-cloud-tasks` | Enqueue builder/normalization work items |
| `google-cloud-storage` | GCS read/write for ChangeSet bodies and drafts |
| `vertexai` | Vertex AI Gemini calls for semantic enrichment and recap |
| `google-cloud-secret-manager` | Secrets access (if not using env var mount) |
| `cloud-sql-python-connector` | Cloud SQL connection (alternative to Auth Proxy sidecar) |

### GitHub

| Package | Purpose |
|---------|---------|
| `httpx` | Sync HTTP client for GitHub API hydration calls |
| `PyJWT` + `cryptography` | GitHub App JWT generation and webhook HMAC-SHA256 signature validation |

### Utilities

| Package | Purpose |
|---------|---------|
| `structlog` | Structured JSON logging (compatible with Cloud Logging) |
| `tenacity` | Retry logic for GitHub API, Vertex AI, and GCS calls |
| `detect-secrets` | Secret pattern detection for snippet sanitization |

### Testing

| Package | Purpose |
|---------|---------|
| `pytest` | Test runner |
| `pytest-cov` | Coverage reporting |
| `factory-boy` | Test data fixtures |
| `respx` | HTTP request mocking (pairs with httpx) |
| `testcontainers[postgres]` | Postgres in Docker for integration tests |

## Project structure

```
ShipShare/
  apps/
    web/                  # existing Next.js frontend
    pipeline/             # Python backend (new)
      pyproject.toml      # dependencies, project metadata
      alembic/            # database migrations
        alembic.ini
        versions/
      src/
        pipeline/
          __init__.py
          main.py             # FastAPI app, route registration
          config.py           # pydantic Settings (env vars, secrets)
          models/
            db.py             # SQLAlchemy models
            schemas.py        # Pydantic request/response schemas
          routes/
            webhooks.py       # /webhooks/github
            normalize.py      # /internal/normalize
            builder.py        # /internal/builder/dispatch, /internal/builder/run
            recap.py          # /internal/recap/dispatch, /internal/recap/generate
            health.py         # /health
          services/
            ingestion.py      # raw delivery storage
            normalization.py  # async normalization logic
            changeset.py      # clustering, fingerprinting, ChangeSet build
            hydration.py      # GitHub API hydration
            scoring.py        # prelim and final impact scoring
            snippets.py       # patch extraction, file filtering, redaction
            semantic.py       # Vertex AI semantic enrichment
            recap.py          # recap generation, diversity selection
            reconciliation.py # body status reconciliation sweep
          github/
            auth.py           # JWT generation, installation tokens
            webhooks.py       # signature validation, payload parsing
            client.py         # httpx-based GitHub API client
          gcs/
            client.py         # GCS read/write helpers
          tasks/
            enqueue.py        # Cloud Tasks enqueue helpers
      tests/
        conftest.py
        test_ingestion.py
        test_normalization.py
        test_builder.py
        test_recap.py
        ...
      Dockerfile
      .env.example
```

## Container & CI

- **Base image**: `python:3.12-slim`
- **Build**: `uv sync` from `pyproject.toml` (`uv` for fast, deterministic installs with lockfile support)
- **CI/CD**: GitHub Actions triggered by pushes to `apps/pipeline/**` on `main`
- **Registry**: Artifact Registry (GCP)
- **Deploy**: `gcloud run deploy` from GitHub Actions workflow step
- **Infrastructure**: Terraform manages all GCP resources; GitHub Actions applies infra changes on merge to `main`
- Separate GitHub Actions workflows for `apps/web`, `apps/pipeline`, and `infra/` so frontend, backend, and infrastructure deploy independently

---

# 2) Architecture Overview

## Stage A — Ingestion (event-based, async normalization)

**GitHub App Webhooks → Ingestion Service → Postgres**

- Receive webhook deliveries (push, installation, installation_repositories)
- Validate signatures
- Dedupe by delivery id
- Store raw delivery with retention policy
- Return 2xx immediately
- Normalize asynchronously: a lightweight internal worker (or async task) reads raw deliveries and writes normalized `ingested_commit` rows, `repo_push_state` updates, and `github_installation` / `user_repo` state changes

This stage stays cheap and fast. The synchronous webhook handler only validates and stores the raw delivery; all downstream writes happen asynchronously so burst traffic never risks timeouts.

## Stage B — ChangeSet Build (fan-out queue)

**Scheduler → per-repo work items → Worker pool → Deterministic ChangeSets**

- A periodic scheduler (e.g. daily cron) enqueues one work item per eligible `(user_id, repo_id)` pair
- Workers pull items from the queue with exclusive claim semantics (Cloud Tasks task-name deduplication, with advisory lock fallback for local development)
- Each worker processes a single repo build:
  - Process only default-branch commit observations
  - Rebuild the recent tail interval deterministically
  - Detect suspicious branch history changes and widen rebuild when needed
  - Compute preliminary impact from commit-level data
  - Hydrate only high-priority candidates, plus a tiny bounded fallback if desired later
  - Compute final impact for hydrated candidates
  - Include targeted patch snippets only when final impact is high enough
  - Run LLM semantic enrichment only when the semantic fingerprint changes
  - Persist queryable index in Postgres and body artifact in GCS with explicit artifact state
  - Run reconciliation sweep for stale `body_status = pending` records (see Section 11)

Fan-out enables horizontal scaling: adding workers linearly reduces wall-clock time. Exclusive claims prevent two workers from rebuilding the same repo concurrently.

## Stage C — Recap Generation (per-user schedule or manual trigger)

**Recap Dispatcher → per-user Cloud Tasks → Recap Worker → LLM recap**

- A frequent dispatcher (hourly Cloud Scheduler) checks which users are due for a recap based on their configured cadence (weekly default, daily optional)
- Enqueues one Cloud Task per due user
- Each recap worker:
  - Computes the recap window from the user's cadence and last recap time
  - Queries active ChangeSets overlapping the window
  - Selects top ChangeSets by impact with deterministic diversity algorithm (see Section 12)
  - Fetches ChangeSet bodies only for ready artifacts
  - Generates one draft per platform
  - Stores drafts and run record idempotently
  - Updates `user_recap_config.last_recap_at` and recomputes `next_recap_due_at`
- Users can also trigger a recap manually for any arbitrary window via the API

---

# 3) GitHub App Setup

## 3.1 Installation model

- Users install your **GitHub App** on selected repositories.

## 3.2 Repository permissions (MVP)

- **Metadata: Read**
- **Contents: Read**
- **Pull Requests: Read** _(kept, not used in MVP)_

## 3.3 Subscribed events (MVP)

- **Push** (required)
- **Installation** (required) — tracks app installs, uninstalls, and permission changes
- **Installation Repositories** (required) — tracks repos added/removed from an installation

No PR event handling is required for MVP. Installation lifecycle events are free and essential for keeping `github_installation` and `user_repo` state accurate. Without them, uninstalls and repo removals are invisible — the builder would continue processing stale repos and hydration API calls would fail silently.

---

# 4) Services

## 4.1 Webhook Ingestion Service

### Responsibility

Split into two phases:

**Phase 1 — Synchronous handler (in the HTTP request path):**

- Receive GitHub webhook deliveries (push, installation, installation_repositories)
- Validate webhook signature
- Dedupe by `X-GitHub-Delivery`
- Write raw `webhook_delivery` row to Postgres
- Return 2xx immediately

**Phase 2 — Async normalization worker (Cloud Tasks target):**

- Triggered by a Cloud Task enqueued during Phase 1 (targeting `/internal/normalize/{delivery_id}`)
- For **push** events:
  - Extract and upsert `ingested_commit` rows
  - Update `repo_push_state` for branch head tracking
  - Update `repo_default_branch` if payload indicates a change
- For **installation** events:
  - On install: create/update `github_installation`, create `user_repo` entries for selected repos
  - On uninstall: mark `github_installation` as `suspended` and disable associated `user_repo` entries
- For **installation_repositories** events:
  - On repos added: create `user_repo` entries
  - On repos removed: mark `user_repo` entries as `disabled`
- Mark `webhook_delivery.processed_at` on completion

### Inputs

- GitHub webhook payload
- GitHub headers

### Outputs

- `webhook_delivery` row (sync)
- `ingested_commit` rows (async)
- `repo_push_state` update (async)
- `github_installation` upsert (async)
- `user_repo` upserts (async)

### Non-functional requirements

- idempotent
- low latency for the sync handler
- replay-safe (reprocessing a raw delivery produces the same normalized output)

### Notes

The synchronous handler does no heavy work — no multi-row writes, no GitHub API calls, no LLMs. Normalization happens asynchronously so webhook delivery latency is bounded even under burst traffic (e.g. large merges with many commits).

---

## 4.2 ChangeSet Builder (fan-out workers)

### Responsibility

A periodic scheduler (Cloud Scheduler) triggers a dispatcher endpoint that queries `user_repo WHERE status = 'active'` and enqueues one Cloud Task per eligible `(user_id, repo_id)` pair. Task deduplication is enforced via Cloud Tasks task naming (`build-{user_id}-{repo_id}-{date}`), which prevents duplicate builds within the deduplication window.

Each worker processes a single repo build:

- resolve `installation_id` from `github_installation` for API authentication
- determine current default branch
- load recent default-branch commit observations using a builder cursor
- detect branch history anomalies using observed head state and the push payload's `forced` flag
- choose rebuild window
- rebuild ChangeSets deterministically for that window
- compute preliminary impact
- select hydration candidates
- selectively hydrate candidate ChangeSets from GitHub API (using installation token)
- compute final impact
- attach targeted snippets when eligible
- persist ChangeSet body to GCS
- update Postgres index only after body is ready
- run semantic enrichment only when semantic fingerprint changed; on LLM failure, set `has_semantic = false` and log warning
- run reconciliation sweep for stale `body_status = pending` records (see Section 11)
- persist run metadata and counters

### Inputs

- Postgres ingested commits
- Postgres `user_repo` and `github_installation` for repo-to-user mapping and API auth
- Postgres repo config and repo state
- GitHub API for selective hydration (authenticated via installation token)
- LLM API for ChangeSet semantic enrichment

### Outputs

- `changeset_index` upserts
- GCS ChangeSet bodies
- builder cursor updates
- `collection_run` record

### Concurrency model

- **Primary**: Cloud Tasks task-name deduplication prevents the same `(user_id, repo_id, date)` build from being enqueued twice
- **Fallback**: if running outside Cloud Tasks (e.g. local development, manual retrigger), use a Postgres advisory lock on `(user_id, repo_id)` to prevent concurrent builds
- Partial failure (some repos succeed, some fail) is safe: each repo build is independent and cursor updates are per-repo

### Notes

Hydration failures and rate limits are represented explicitly, not silently ignored. Semantic enrichment failures are also explicit: on LLM error, the ChangeSet is preserved without semantic fields rather than blocking the build.

---

## 4.3 Recap Dispatcher

### Responsibility

Triggered by Cloud Scheduler (hourly):

- query `user_recap_config` for users where `enabled = true` and `next_recap_due_at <= now()`
- for each due user, enqueue a Cloud Task targeting `/internal/recap/generate` with `user_id` and computed window
- task naming: `recap-{user_id}-{window_end_date}` for deduplication

---

## 4.4 Recap Generation Worker

### Responsibility

Triggered by Cloud Task (from dispatcher) or manual API request:

- receive `user_id` and recap window (or compute window from `user_recap_config` cadence)
- query active ChangeSets overlapping the window
- select top N by impact with deterministic diversity algorithm
- require ready body artifacts
- fetch body artifacts from GCS
- pass normalized recap inputs to the LLM
- generate one draft per platform
- store drafts and run metadata idempotently
- update `user_recap_config.last_recap_at` and recompute `next_recap_due_at`

### Inputs

- Postgres ChangeSet index
- Postgres `user_recap_config` for schedule state
- GCS ChangeSet bodies
- LLM API for recap generation

### Outputs

- `recap_run`
- GCS draft artifacts
- `user_recap_config` update (next due time)

---

# 5) Postgres Data Model

## 5.0 Stable identifiers

All tables use `repo_id` (bigint, from GitHub's numeric repository ID) as the stable internal key for repositories. `repo_full_name` is stored as a denormalized display field and updated on every push event (the webhook payload includes both `repository.id` and `repository.full_name`). This ensures repo renames and transfers do not break join paths, orphan ChangeSets, or corrupt builder cursors.

---

## 5.1 Installation and repo mapping

### `github_installation`

Tracks GitHub App installations. Required for API authentication (installation tokens are scoped to the installation).

- `installation_id` (PK) — from GitHub
- `user_id` — the ShipShare user who owns this installation
- `account_login` — GitHub org or user account name
- `account_type` — `Organization` or `User`
- `status` — `active | suspended | deleted`
- `permissions` jsonb — snapshot of granted permissions
- `created_at`
- `updated_at`

Notes:

- Updated by `installation` webhook events (install, uninstall, suspend, unsuspend).
- When `status` changes to `suspended` or `deleted`, all associated `user_repo` entries should be disabled.

---

### `user_repo`

Maps users to their enabled repositories. This is the source of truth for which repos the builder should process.

- `user_id`
- `repo_id` (bigint) — GitHub's numeric repository ID (stable across renames)
- `installation_id` — FK to `github_installation`
- `repo_full_name` — denormalized display field, updated on each push event
- `status` — `active | disabled | removed`
- `created_at`
- `updated_at`

**Primary key:** `(user_id, repo_id)`

**Index:** `(user_id, status)`

Notes:

- Created when a user installs the GitHub App and selects repos, or when repos are added via `installation_repositories` events.
- Set to `disabled` when repos are removed from the installation or the installation is uninstalled.
- The builder only enqueues work items for `user_repo` entries where `status = 'active'`.

---

## 5.2 Webhook and ingestion data

### `webhook_delivery`

Stores raw webhook data for short-term debugging and audit.

- `delivery_id` (PK) — from `X-GitHub-Delivery`
- `event_type`
- `repo_id` bigint nullable — from `repository.id` in payload (null for installation-level events without a repo)
- `repo_full_name` — denormalized display field
- `received_at`
- `signature_valid` bool
- `payload_json` jsonb
- `processed_at` timestamptz nullable
- `expires_at` timestamptz nullable

Notes:

- Raw payload retention should be bounded.
- Normalized data is the long-term source of truth.

---

### `ingested_commit`

Represents a commit observed on a specific branch from a webhook push payload.

- `repo_id` (bigint) — stable GitHub numeric repo ID
- `repo_full_name` — denormalized display field
- `branch_name`
- `sha`
- `commit_ts`
- `author_login` nullable — may be null for commits from non-GitHub-linked accounts
- `author_email` — always present in git commit data within the webhook payload
- `committer_login` nullable
- `committer_email` nullable
- `message`
- `url`
- `delivery_id`
- `ingested_at`

**Unique constraint:** `(repo_id, branch_name, sha)`

**Index:**

- `(repo_id, branch_name, commit_ts DESC)`

Notes:

- MVP may ingest all branches.
- Builder only processes commits where `branch_name == default_branch`.
- `author_email` is stored because `author_login` can be null when the commit author's email is not linked to a GitHub account. Email provides a reliable fallback for attribution.

---

### `repo_default_branch`

Cached repo default branch state.

- `repo_id` (PK) — stable GitHub numeric repo ID
- `repo_full_name` — denormalized display field
- `default_branch`
- `updated_at`
- `expires_at`

Notes:

- Refresh on install, periodically by TTL, and when repo state looks inconsistent.

---

### `repo_push_state`

Tracks observed branch-head movement from push events.

- `repo_id` (bigint)
- `repo_full_name` — denormalized display field
- `branch_name`
- `last_before_sha` nullable
- `last_after_sha` nullable
- `last_push_forced` bool nullable — from the webhook payload's `forced` field
- `last_push_received_at`
- `updated_at`

**Primary key:** `(repo_id, branch_name)`

Notes:

- Used to detect history rewrites or other suspicious branch movement.
- `last_push_forced` is authoritative for force-push detection (GitHub provides this on push events).
- This is lightweight branch topology state, not a full sync model.

---

### `repo_builder_cursor`

Tracks builder progress separately from ingestion timing.

- `repo_id` (PK) — stable GitHub numeric repo ID
- `branch_name`
- `last_built_commit_ts` nullable
- `last_built_head_sha` nullable
- `updated_at`

Notes:

- This is the builder’s source of truth for incremental work.
- Do not use webhook delivery receive time as the builder cursor.

---

## 5.3 ChangeSet storage

### `changeset_index`

Small, queryable header for overlap queries and recap selection.

- `changeset_id` (PK)
- `user_id`
- `repo_id` (bigint) — stable GitHub numeric repo ID
- `repo_full_name` — denormalized display field
- `branch`
- `start_ts`
- `end_ts`
- `commit_count`
- `commit_shas` text[]
- `cluster_fingerprint`
- `enrichment_fingerprint`
- `semantic_fingerprint`
- `clustering_version`
- `impact_prelim`
- `impact_final` nullable
- `hydration_status`
  values: `not_needed | pending | ready | deferred | failed`
- `has_snippets` bool
- `has_semantic` bool
- `semantic_version` int nullable
- `body_status`
  values: `pending | ready | failed`
- `gcs_body_key` nullable
- `is_active` bool
- `active_until` timestamptz nullable — TTL for automatic deactivation
- `created_at`
- `updated_at`

Recommended additional fields:

- `ts_window` as a generated `tsrange(start_ts, end_ts, '[]')`
- `superseded_in_run_id` nullable
- `selection_notes` jsonb nullable

**Indexes**

- `(user_id, is_active)`
- `(user_id, repo_id, is_active)`
- GiST index on `ts_window`

### ChangeSet identity rule

`changeset_id` must be deterministic.

Recommended construction:

- hash of `(repo_id, ordered commit SHAs, clustering_version)`

This keeps unchanged logical clusters stable across rebuilds.

### ChangeSet TTL and archival

- `active_until` defaults to `end_ts + 90 days` at creation time
- A periodic sweep (can piggyback on the builder schedule) deactivates ChangeSets where `active_until < now()` and `is_active = true`
- This bounds the active set so recap overlap queries stay fast regardless of account age
- Inactive ChangeSets remain for debugging but are excluded from recap selection

### Clustering version migration

When `clustering_version` is bumped, all changeset IDs change for the same commits. To handle this:

- Run a one-time migration that deactivates all prior-version active ChangeSets
- Trigger a full rebuild (widened lookback) on the next builder run
- Document this as an operational procedure with a runbook

---

### `collection_run`

- `collection_run_id` (PK)
- `user_id`
- `started_at`
- `finished_at`
- `status`
- `repos_processed`
- `commits_seen`
- `changesets_built`
- `changesets_hydrated`
- `changesets_skipped_by_hydration_cap`
- `snippets_omitted_count`
- `semantic_cache_hits`
- `repos_rate_limited`
- `warnings` jsonb
- `error` jsonb

---

### `user_recap_config`

Per-user recap scheduling preferences. Drives the recap dispatcher.

- `user_id` (PK)
- `recap_cadence` — `weekly | daily` (default `weekly`)
- `recap_day_of_week` int nullable — 0=Monday..6=Sunday (default `4`, Friday). Ignored when cadence is `daily`.
- `recap_hour_utc` int — hour of day in UTC to generate recap (default `8`)
- `last_recap_at` timestamptz nullable — when the last recap was successfully completed
- `next_recap_due_at` timestamptz nullable — precomputed next due time for efficient dispatch queries
- `enabled` bool (default `true`)
- `updated_at`

Notes:

- The recap dispatcher (Cloud Scheduler, hourly) queries `user_recap_config WHERE enabled = true AND next_recap_due_at <= now()` to find users due for a recap.
- After a successful recap, update `last_recap_at` and recompute `next_recap_due_at` based on cadence.
- Manual triggers bypass the schedule and generate a recap immediately for any requested window.

---

### `recap_run`

- `recap_run_id` (PK)
- `user_id`
- `window_start`
- `window_end`
- `template_version`
- `trigger` — `scheduled | manual`
- `status`
- `selected_changeset_ids` text[]
- `draft_gcs_keys` jsonb
- `created_at`
- `finished_at`
- `error` jsonb

Recommended uniqueness for idempotency:

- unique on `(user_id, window_start, window_end, template_version)`

This allows reruns to update or replace the same logical recap.

---

# 6) GCS Artifacts

## ChangeSet body

Key:
`gs://bucket/changesets/user=<user_id>/repo=<owner__repo>/<changeset_id>.json`

Contains:

- deterministic cluster data
- commit list
- build rationale
- hydration summary if present
- eligible file list
- snippet payload if present
- semantic fields if present
- prompt/version/model metadata
- omission and truncation notes
- hydration status
- body schema version

Notes:

- Postgres index should only reference a body as usable when `body_status = 'ready'`.

---

## Drafts

Key:
`gs://bucket/drafts/user=<user_id>/recap_run=<recap_run_id>/<platform>.json`

Contains:

- generated draft
- generation metadata
- selected ChangeSet references
- prompt/template version

---

# 7) Deterministic ChangeSet Build

## 7.1 Input filtering

Builder processes only commits where:

- `branch_name == default_branch`

MVP may ingest all branches, but only default-branch work is considered “shipped work.”

---

## 7.2 Builder cursor and rebuild scope

For each repo:

1. Load cached default branch.
2. Load `repo_builder_cursor`.
3. Load observed `repo_push_state` for the default branch.
4. Determine rebuild window.

### Default rebuild rule

Use a normal tail lookback:

- `DEFAULT_LOOKBACK_HOURS = 26`

The lookback must be **at least as long as the run interval** to avoid gaps. If the builder runs every 24 hours, a 6-hour lookback would miss commits landing in the 18-hour gap. The recommended default of 26 hours (24h interval + 2h buffer) ensures full coverage with some overlap for safety.

### Escalation rule

Widen rebuild window when any of the following are detected:

- default branch changed
- `repo_push_state.last_push_forced = true` (authoritative force-push detection from the GitHub webhook payload's `forced` boolean)
- builder head SHA and observed head SHA are inconsistent
- builder state is missing or clearly stale

Recommended widened window:

- `ESCALATED_LOOKBACK_HOURS = 72` or more

Notes:

- The `forced` field on push webhooks is authoritative and free — no need for heuristic SHA-chain analysis.
- Squash merges on GitHub are legitimate and do not set `forced = true`, so they will not trigger escalation.
- This keeps normal runs cheap while preserving correctness when repo history looks suspicious.

---

## 7.3 Tail rebuild procedure

For the chosen rebuild window:

1. `tail_start = last_built_commit_ts - lookback`
2. Load ingested commits for default branch in `[tail_start, now]`
3. Load active ChangeSets overlapping that interval
4. Mark overlapping active ChangeSets inactive
5. Recluster deterministically
6. Upsert new active ChangeSets
7. Update builder cursor with:
   - `last_built_commit_ts`
   - `last_built_head_sha`

Notes:

- This is a bounded deterministic rebuild, not append-only mutation.
- Inactive ChangeSets remain available for debugging but are not eligible for recap.

---

## 7.4 Clustering rules (MVP)

### Primary rules

- Hard split on time gap > 90 minutes
- Prefer conservative clustering
- Prefer smaller ChangeSets over overly broad merges

### Cheap structural heuristics

Use message similarity only as a weak signal.

Also consider:

- shared author as a weak grouping signal
- merge-like/bot-like commit patterns as split signals
- common noisy prefixes as low-value similarity:
  - `merge`
  - `chore`
  - `deps`
  - `release`
  - similar automated messages

This keeps clustering straightforward while reducing obvious false merges.

---

# 8) Scoring and selective hydration

## 8.1 Stage A — Preliminary impact

Computed without GitHub API calls.

Inputs may include:

- commit count
- cluster duration
- message keywords
- noise penalty ratio

Output:

- `impact_prelim`

## 8.2 Hydration candidate selection

Hydrate candidates where:

- `impact_prelim >= HYDRATION_THRESHOLD` (default `0.7`)

`HYDRATION_THRESHOLD` should be stored as a configurable setting (per-user or global) rather than a compile-time constant. This allows tuning without redeployment as real-world scoring data accumulates. Post-MVP, a user feedback mechanism (e.g. marking ChangeSets as irrelevant) can inform threshold calibration.

And enforce a hard cap such as:

- `MAX_HYDRATED_CHANGESETS_PER_USER_PER_RUN = 10`

For selected candidates:

- set `hydration_status = pending`

For non-selected candidates:

- set `hydration_status = not_needed`

---

## 8.3 Stage B — Final impact via selective hydration

For each hydration candidate:

- fetch commit details for up to `MAX_COMMITS_HYDRATED_PER_CHANGESET`
- aggregate:
  - files touched
  - churn
  - path-based risk flags

Output:

- `impact_final`
- `hydration_status = ready` if successful

If GitHub API limits or failures occur:

- set `hydration_status = deferred` or `failed`
- preserve the ChangeSet using prelim-only data
- retry deferred hydration on a later run

Notes:

- Lack of hydration is explicit state, not silent absence.

---

# 9) Targeted patch snippets

## 9.1 Eligibility

Include snippets only if:

- `impact_final >= 0.7`
- `hydration_status = ready`

## 9.2 Extraction limits

- max files per ChangeSet: 3
- max hunks per file: 5
- max chars per hunk: 800
- max total chars per ChangeSet: 4000

## 9.3 File selection rules

Do not choose snippet files by churn alone.

First exclude or down-rank low-signal files such as:

- lockfiles
- generated code
- vendored code
- minified/bundled assets
- snapshot files
- large mechanical diffs

Then choose top eligible files by churn.

## 9.4 Sanitization

Before storing snippets:

- redact secret-like patterns using a structured approach:
  - use a proven secret detection library (e.g. `detect-secrets` or equivalent) rather than hand-rolled regex
  - at minimum, detect: API keys/tokens (common prefixes like `sk-`, `ghp_`, `AKIA`), private keys (PEM headers), connection strings, high-entropy strings adjacent to assignment operators
  - replacement: substitute matched regions with `[REDACTED]` and record the redaction count in the ChangeSet body
- optionally strip ticket IDs if enabled
- record truncation or omission explicitly

If patch text is missing or truncated from GitHub responses:

- record omission in ChangeSet body
- continue without failing the ChangeSet

---

# 10) Semantic enrichment (ChangeSet-level)

After deterministic build and any eligible snippet extraction, run the LLM once per new or changed ChangeSet to generate:

- `semantic_title`
- `semantic_bullets[]`
- `semantic_tags[]`
- `semantic_risk_notes` optional

Store:

- `semantic_version`
- `prompt_hash`
- model metadata
- `generated_at`

### Error handling

If the LLM call fails (timeout, rate limit, malformed output):

- Set `has_semantic = false` on the ChangeSet index
- Log the failure in the `collection_run.warnings` jsonb array
- Do **not** block the ChangeSet build — the ChangeSet remains usable with commit-message fallback in recap generation
- Retry on the next builder run if the semantic fingerprint still indicates work is needed (the fingerprint won't have changed, so the next run will attempt enrichment again)

If the LLM returns output that fails schema validation (missing required fields, wrong types):

- Treat it as a failure — do not persist partial semantic data
- Same recovery path as above

---

## 10.1 Layered fingerprints

Use layered fingerprints instead of one blended fingerprint.

### Cluster fingerprint

Represents cluster identity.

Recommended inputs:

- ordered commit SHAs
- clustering version

### Enrichment fingerprint

Represents deterministic enriched content.

Recommended inputs:

- cluster fingerprint
- hydration summary version
- snippet inclusion state

### Semantic fingerprint

Represents semantic generation inputs.

Recommended inputs:

- enrichment fingerprint
- semantic prompt version

### Regeneration rules

- if cluster fingerprint unchanged: cluster identity is unchanged
- if enrichment fingerprint unchanged: do not rebuild enriched body unnecessarily
- if semantic fingerprint unchanged: do not rerun semantic enrichment

This keeps runs stable and avoids needless LLM calls.

---

# 11) Body persistence and consistency rules

Because ChangeSet index lives in Postgres and the full body lives in GCS:

1. Build or update ChangeSet body content
2. Write body to GCS
3. Mark `body_status = ready`
4. Set `gcs_body_key`
5. Only then allow recap consumers to use the ChangeSet body

If body write fails:

- set `body_status = failed`
- do not expose the body as available
- leave the ChangeSet in a safe partial state

This prevents recap generation from chasing missing artifacts.

## 11.1 Reconciliation sweep

If the process crashes between writing to GCS (step 2) and updating Postgres (steps 3-4), the system enters an inconsistent state: an orphaned GCS object exists with no corresponding `body_status = ready` record.

A reconciliation sweep runs as part of each builder cycle (or as a separate periodic job):

1. Find `changeset_index` records where `body_status = 'pending'` and `updated_at < now() - STALE_BODY_THRESHOLD` (e.g. 30 minutes)
2. For each stale record:
   - Check if the expected GCS object exists at the `gcs_body_key` path
   - If GCS object exists and is valid: update `body_status = 'ready'` (the Postgres update was lost)
   - If GCS object does not exist: update `body_status = 'failed'` (the GCS write never completed)
3. Optionally: garbage-collect orphaned GCS objects that have no matching `changeset_index` entry with `body_status = 'ready'` (run less frequently, e.g. weekly)

---

# 12) Recap generation

## 12.1 Query

Given window `[start, end]`, select active ChangeSets where:

- `end_ts >= start`
- `start_ts <= end`
- `body_status = ready`

Order by:

- `COALESCE(impact_final, impact_prelim)` DESC

### Diversity selection algorithm

The goal is to pick the top N ChangeSets (default `N = 5`, configurable 3–7) while preventing any single repo from dominating the recap. The algorithm must be deterministic to support idempotent recap runs.

1. Rank all candidate ChangeSets globally by `COALESCE(impact_final, impact_prelim)` DESC, breaking ties by `end_ts` DESC then `changeset_id` ASC.
2. Compute `per_repo_cap = ceil(N / distinct_repo_count)`, with a floor of 1 and a ceiling of 3.
3. Greedily select from the ranked list:
   - Accept the ChangeSet if its repo has not yet reached `per_repo_cap`.
   - Skip if the repo is at cap.
4. If fewer than N ChangeSets are selected after one pass (some repos had fewer candidates), do a second pass over skipped candidates in rank order, ignoring the cap, until N is reached or candidates are exhausted.

This ensures:
- High-impact work always surfaces regardless of repo
- A single very active repo cannot crowd out all others
- When a user has only one active repo, the cap relaxes naturally
- The output is fully deterministic (no randomness)

---

## 12.2 Normalized recap input

For each selected ChangeSet, pass a normalized schema to the recap LLM including:

- repo name
- start/end timestamps
- impact score used for ranking
- hydration status
- semantic title if present
- semantic bullets if present
- commit messages fallback
- snippet summary or omission state
- semantic/snippet availability flags

This ensures recap quality remains stable even when some ChangeSets are richer than others.

---

## 12.3 Recap outputs

Generate:

- LinkedIn recap draft
- X recap draft
- optional X thread outline

Store drafts and metadata in GCS and `recap_run`.

Recap runs should be idempotent for the same:

- `user_id`
- `window_start`
- `window_end`
- `template_version`

---

# 13) Operational guardrails

Given expected repo counts:

- average: 5–10 repos
- worst case: 20–30 repos

The design stays bounded because:

- ingestion is write-only and cheap
- daily build only rebuilds a bounded tail interval
- hydration is capped
- snippets are capped
- semantics are cached behind semantic fingerprints

Recommended caps:

- `MAX_REPOS_PER_USER = 30`
- `MAX_COMMITS_PER_REPO_PER_DAY = 500`
- `MAX_HYDRATED_CHANGESETS_PER_USER_PER_RUN = 10`
- `MAX_COMMITS_HYDRATED_PER_CHANGESET = 20`

Recommended run metrics:

- repos processed
- commits seen
- ChangeSets built
- ChangeSets hydrated
- ChangeSets skipped by cap
- hydration deferred due to rate limits
- snippet omissions
- semantic cache hits
- semantic enrichment failures
- missing/failed bodies
- reconciliation repairs (pending bodies resolved)

## 13.1 Alerting and health checks

Minimum alerting for MVP:

- **Builder run failure**: alert if `collection_run.status = 'error'` or if no successful run completes within 2x the expected interval
- **Recap generation failure**: alert if `recap_run.status = 'error'`
- **Hydration rate limiting**: alert if `repos_rate_limited > 0` on more than N consecutive runs (indicates a persistent GitHub API issue)
- **Body write failures**: alert if `body_status = 'failed'` count exceeds a threshold within a run
- **Webhook normalization backlog**: alert if unprocessed `webhook_delivery` records (where `processed_at IS NULL`) older than 15 minutes exist
- **Installation health**: alert if a `github_installation` transitions to `suspended` or `deleted` (may need user action)

Health check endpoints:

- Ingestion service: responds to synthetic webhook-like probes, confirms DB connectivity
- Builder workers: report heartbeat and current lock state
- Async normalization worker: reports queue depth and processing latency

---

# 14) Data retention and cache behavior

## 14.1 Webhook raw payload retention

- retain `webhook_delivery.payload_json` for a bounded period (recommended: 30 days)
- null out `payload_json` on expiry via a periodic cleanup job, keeping the delivery metadata row for audit
- keep normalized commit and repo state tables as long-term source of truth

## 14.2 Default branch cache refresh

Refresh `repo_default_branch`:

- at install/repo selection time
- on TTL expiry
- when builder detects branch inconsistency

This keeps default-branch filtering accurate without adding heavy sync work.

## 14.3 Table partitioning strategy

As the system scales, large tables benefit from time-based partitioning:

- **`ingested_commit`**: partition by month on `commit_ts`. Enables efficient pruning of old data and fast range queries for the builder.
- **`webhook_delivery`**: partition by month on `received_at`. Supports the retention cleanup job and keeps the active partition small.
- **`changeset_index`**: does not need partitioning at MVP scale. Monitor row count; if it exceeds ~1M rows, consider partitioning by `user_id` hash or by `created_at` month.

Partitioning is not required for MVP but the schema should be designed to support it (avoid cross-partition foreign keys, ensure partition keys are part of unique constraints).

## 14.4 GCS lifecycle management

- ChangeSet bodies for inactive ChangeSets: transition to Nearline storage after 90 days, delete after 1 year
- Draft artifacts: retain for 1 year, then delete
- Set GCS lifecycle rules on the bucket using prefix-based conditions
- The reconciliation sweep (Section 11.1) handles orphaned objects; the lifecycle rules handle long-term cleanup

## 14.5 ChangeSet archival

- ChangeSets are deactivated (`is_active = false`) by the builder during tail rebuilds and by the TTL sweep (see Section 5.3)
- Inactive ChangeSets older than the GCS lifecycle retention period can be hard-deleted from Postgres to reclaim space
- A periodic archival job (e.g. monthly) handles this cleanup

---

# 15) MVP Implementation Checklist

## GitHub App

- permissions:
  - Metadata read
  - Contents read
  - Pull Requests read

- subscribed events:
  - Push
  - Installation
  - Installation Repositories

- install flow:
  - select repos
  - store `github_installation` and `user_repo` records

## Data Model

- `github_installation` table with `installation_id`, `user_id`, `status`
- `user_repo` mapping table with `(user_id, repo_id)` PK, `installation_id` FK, `status`
- `repo_id` (bigint) as stable key on all repo-referencing tables
- `repo_full_name` as denormalized display field (updated on push events)
- `author_email` and `committer_email` on `ingested_commit`
- `last_push_forced` on `repo_push_state`
- `active_until` TTL on `changeset_index`

## Ingestion Service (sync handler + Cloud Tasks normalization)

- sync handler (`/webhooks/github`): signature validation, delivery dedupe, raw delivery storage, enqueue Cloud Task, return 2xx
- normalization worker (`/internal/normalize/{delivery_id}`): Cloud Tasks target
  - commit upsert using `(repo_id, branch_name, sha)`
  - push head state tracking (including `forced` flag)
  - default branch cache update path
  - installation lifecycle handling (install, uninstall, repo add/remove)

## ChangeSet Builder (Cloud Tasks fan-out)

- dispatcher (`/internal/builder/dispatch`): Cloud Scheduler triggers daily, enqueues one Cloud Task per active `(user_id, repo_id)`
- worker (`/internal/builder/run`): Cloud Tasks target, processes single repo build
- Cloud Tasks task-name deduplication for concurrency control (`build-{user_id}-{repo_id}-{date}`)
- resolve `installation_id` for GitHub API authentication
- separate builder cursor from ingestion timing
- default branch filtering
- bounded tail rebuild (lookback >= run interval)
- widened rebuild on force-push (`forced = true`) or suspicious branch history
- deterministic `changeset_id` using `repo_id`
- layered fingerprints
- prelim scoring with configurable `HYDRATION_THRESHOLD`
- selective hydration via installation token
- explicit hydration status
- snippet extraction with file filtering and secret redaction
- semantic enrichment behind semantic fingerprint with explicit LLM error handling
- body write before index readiness
- reconciliation sweep for stale `body_status = pending` records
- ChangeSet TTL sweep (`active_until` expiry)
- run counters and warnings

## Recap Dispatcher + Worker

- `user_recap_config` table with per-user cadence (weekly default, daily optional)
- dispatcher (`/internal/recap/dispatch`): Cloud Scheduler hourly, finds due users, enqueues Cloud Tasks
- worker (`/internal/recap/generate`): Cloud Tasks target or manual API trigger
- overlap query on active ready ChangeSets
- deterministic diversity selection algorithm (per-repo cap with greedy fallback)
- normalized recap input schema
- draft generation
- idempotent recap run storage
- update `last_recap_at` and `next_recap_due_at` after successful generation

## Infrastructure

- All GCP resources managed via **Terraform** (see Section 16 for full plan)
- Cloud Run service with route groups (webhook, normalization, builder, recap, health)
- Cloud Tasks queues: `normalize-queue`, `builder-queue`, `recap-queue` (each with rate limiting)
- Cloud Scheduler jobs: builder dispatch (daily), recap dispatch (hourly)
- Cloud SQL for PostgreSQL 15+ with Auth Proxy sidecar
- GCS bucket with lifecycle rules
- Secret Manager for GitHub App credentials
- Artifact Registry for container images
- **GitHub Actions** for CI/CD: automatic deployment on merge to `main` (see Section 16)
- **Workload Identity Federation** for keyless GitHub Actions → GCP authentication

## Operational

- alerting on builder failures, recap failures, rate limiting, body write failures, normalization backlog
- health check endpoint (`/health`) with DB and GCS connectivity probes
- Cloud Logging integration via `structlog` JSON output
- webhook raw payload retention cleanup (30 days)
- GCS lifecycle rules for ChangeSet bodies and drafts

---

# 16) Deployment & Infrastructure Management

All GCP infrastructure is managed declaratively with **Terraform**. Application code is deployed automatically via **GitHub Actions** when changes are merged to `main`. There is a single environment: **production**. No staging or preview environments exist at MVP.

---

## 16.1 Repository layout for infra and CI

```
ShipShare/
  infra/
    terraform/
      backend.tf              # GCS remote state backend config
      main.tf                 # provider config, API enablement
      variables.tf            # input variables
      outputs.tf              # outputs (Cloud Run URL, DB connection, etc.)
      terraform.tfvars        # variable values (gitignored)
      networking.tf           # VPC, Serverless VPC Connector
      cloud_sql.tf            # Cloud SQL instance, database, user
      cloud_run.tf            # Cloud Run service (pipeline)
      cloud_tasks.tf          # normalize-queue, builder-queue, recap-queue
      cloud_scheduler.tf      # builder dispatch, recap generation cron jobs
      gcs.tf                  # app bucket, lifecycle rules
      artifact_registry.tf    # Docker repository
      secrets.tf              # Secret Manager secret resources
      iam.tf                  # service accounts, IAM bindings
      workload_identity.tf    # Workload Identity Federation for GitHub Actions
  .github/
    workflows/
      deploy-pipeline.yml     # build + deploy pipeline service
      terraform.yml           # plan on PR, apply on merge
```

`terraform.tfvars` is gitignored. Sensitive values (database passwords, etc.) are either passed via Terraform variables at apply time or managed through Secret Manager and referenced by resource.

---

## 16.2 Terraform resource plan

### 16.2.1 Provider and state backend

- **Provider**: `google` and `google-beta`, pinned to a specific version
- **State backend**: GCS bucket (`shipshare-terraform-state`) with object versioning and a state-locking prefix
- **Required APIs** enabled via `google_project_service`:
  - `run.googleapis.com`
  - `sqladmin.googleapis.com`
  - `cloudtasks.googleapis.com`
  - `cloudscheduler.googleapis.com`
  - `storage.googleapis.com`
  - `artifactregistry.googleapis.com`
  - `secretmanager.googleapis.com`
  - `aiplatform.googleapis.com` (Vertex AI)
  - `vpcaccess.googleapis.com`
  - `iam.googleapis.com`
  - `iamcredentials.googleapis.com` (Workload Identity Federation)

### 16.2.2 Networking

| Resource | Purpose |
|----------|---------|
| `google_compute_network` | Custom VPC for internal connectivity |
| `google_compute_subnetwork` | Regional subnet |
| `google_compute_global_address` + `google_service_networking_connection` | Private services access range for Cloud SQL private IP |
| `google_vpc_access_connector` | Serverless VPC Connector so Cloud Run can reach Cloud SQL over private IP |

### 16.2.3 Cloud SQL

| Resource | Config |
|----------|--------|
| `google_sql_database_instance` | PostgreSQL 15, `db-f1-micro` (MVP), regional HA, private IP only, automated backups with PITR enabled, maintenance window |
| `google_sql_database` | Database name: `shipshare_pipeline` |
| `google_sql_user` | Application user (password stored in Secret Manager) |

The Cloud Run service connects via the **Cloud SQL Auth Proxy sidecar** (configured as a Cloud Run container annotation) or via private IP through the VPC Connector. Auth Proxy sidecar is preferred for automatic IAM-based authentication without managing passwords in the connection string.

### 16.2.4 Artifact Registry

| Resource | Config |
|----------|--------|
| `google_artifact_registry_repository` | Docker format, regional, repository name: `shipshare` |

### 16.2.5 GCS

| Resource | Config |
|----------|--------|
| `google_storage_bucket` | App bucket: `shipshare-pipeline-{project_id}`, regional, uniform bucket-level IAM |
| Lifecycle rules | Nearline transition at 90 days for `changesets/` prefix; delete at 365 days for `changesets/` prefix; delete at 365 days for `drafts/` prefix |

### 16.2.6 Secret Manager

| Secret | Content |
|--------|---------|
| `github-app-private-key` | GitHub App PEM private key |
| `github-webhook-secret` | Webhook HMAC secret |
| `cloud-sql-password` | Database user password (if not using IAM auth) |

Secrets are created as `google_secret_manager_secret` resources. Secret **versions** (the actual values) are populated manually or via a bootstrap script — Terraform manages the secret containers but not the secret data itself. Cloud Run references secrets as environment variable mounts.

### 16.2.7 Cloud Tasks

| Queue | Config |
|-------|--------|
| `normalize-queue` | Max dispatches/sec: 50, max concurrent: 20, retry config: max attempts 5, min backoff 10s, max backoff 300s |
| `builder-queue` | Max dispatches/sec: 5, max concurrent: 3, retry config: max attempts 3, min backoff 30s, max backoff 600s. Lower throughput to respect GitHub API rate limits |
| `recap-queue` | Max dispatches/sec: 10, max concurrent: 5, retry config: max attempts 3, min backoff 30s, max backoff 300s |

Both queues target the Cloud Run service URL with OIDC authentication.

### 16.2.8 Cloud Scheduler

| Job | Schedule | Target |
|-----|----------|--------|
| `builder-dispatch` | `0 6 * * *` (daily 06:00 UTC) | `POST {cloud_run_url}/internal/builder/dispatch` |
| `recap-dispatch` | `0 * * * *` (hourly) | `POST {cloud_run_url}/internal/recap/dispatch` |

Both jobs use OIDC token authentication with the pipeline service account as the audience. Retry config: 1 retry, 5-minute deadline.

### 16.2.9 Cloud Run

| Attribute | Value |
|-----------|-------|
| `google_cloud_run_v2_service` | Service name: `shipshare-pipeline` |
| Image | `{region}-docker.pkg.dev/{project}/shipshare/pipeline:latest` (overridden by CI on each deploy) |
| Min instances | 1 (for webhook responsiveness) |
| Max instances | 10 |
| CPU | 1 vCPU, always-allocated |
| Memory | 512 Mi |
| Timeout | 900s (to accommodate builder worker runs) |
| Concurrency | 80 |
| VPC connector | Serverless VPC Connector for Cloud SQL private IP |
| Cloud SQL connection | Auth Proxy sidecar annotation |
| Env vars | Non-secret config: `GCP_PROJECT`, `GCS_BUCKET`, `CLOUD_TASKS_NORMALIZE_QUEUE`, `CLOUD_TASKS_BUILDER_QUEUE`, `CLOUD_RUN_SERVICE_URL` |
| Secret env vars | Mounted from Secret Manager: `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`, `DATABASE_URL` (if not using IAM auth) |
| Ingress | All traffic (webhook endpoint must be publicly reachable by GitHub) |

The image tag is set to a placeholder in Terraform. The actual image is deployed by the GitHub Actions workflow, which updates the Cloud Run service to a specific image digest on each deploy.

### 16.2.10 IAM and service accounts

| Service Account | Purpose | Roles |
|-----------------|---------|-------|
| `pipeline-sa` | Cloud Run runtime identity | `roles/cloudsql.client`, `roles/cloudsql.instanceUser`, `roles/storage.objectAdmin` (scoped to app bucket), `roles/cloudtasks.enqueuer`, `roles/secretmanager.secretAccessor`, `roles/aiplatform.user`, `roles/logging.logWriter`, `roles/monitoring.metricWriter` |
| `scheduler-sa` | Cloud Scheduler invoker | `roles/run.invoker` (on the Cloud Run service) |
| `github-actions-sa` | GitHub Actions deployer (via Workload Identity Federation) | `roles/run.developer`, `roles/artifactregistry.writer`, `roles/iam.serviceAccountUser` (on `pipeline-sa`) |

### 16.2.11 Workload Identity Federation

Enables keyless authentication from GitHub Actions to GCP — no service account keys stored as GitHub secrets.

| Resource | Config |
|----------|--------|
| `google_iam_workload_identity_pool` | Pool name: `github-actions-pool` |
| `google_iam_workload_identity_pool_provider` | OIDC provider, issuer: `https://token.actions.githubusercontent.com`, attribute mapping for `repository` and `ref` |
| `google_service_account_iam_member` | Binds `github-actions-sa` to the pool, scoped to `repo:amit-00/ShipShare:ref:refs/heads/main` |

This ensures only workflows running on the `main` branch of `amit-00/ShipShare` can authenticate as the deployer service account.

---

## 16.3 GitHub Actions workflows

### 16.3.1 Pipeline deployment (`deploy-pipeline.yml`)

Triggered on push to `main` when files under `apps/pipeline/**` change.

```yaml
name: Deploy Pipeline
on:
  push:
    branches: [main]
    paths:
      - "apps/pipeline/**"

permissions:
  contents: read
  id-token: write  # required for Workload Identity Federation

jobs:
  deploy:
    runs-on: ubuntu-latest
    env:
      PROJECT_ID: ${{ vars.GCP_PROJECT_ID }}
      REGION: ${{ vars.GCP_REGION }}
      SERVICE: shipshare-pipeline
      IMAGE: ${{ vars.GCP_REGION }}-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/shipshare/pipeline

    steps:
      - uses: actions/checkout@v4

      - name: Authenticate to GCP
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.WIF_PROVIDER }}
          service_account: ${{ vars.GCP_SA_EMAIL }}

      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v2

      - name: Configure Docker for Artifact Registry
        run: gcloud auth configure-docker ${{ env.REGION }}-docker.pkg.dev --quiet

      - name: Build and push image
        working-directory: apps/pipeline
        run: |
          docker build -t ${{ env.IMAGE }}:${{ github.sha }} .
          docker push ${{ env.IMAGE }}:${{ github.sha }}

      - name: Run database migrations
        uses: google-github-actions/run-jobs@v1
        with:
          project_id: ${{ env.PROJECT_ID }}
          region: ${{ env.REGION }}
          image: ${{ env.IMAGE }}:${{ github.sha }}
          command: alembic upgrade head
          wait: true
          timeout: 300

      - name: Deploy to Cloud Run
        uses: google-github-actions/deploy-cloudrun@v2
        with:
          service: ${{ env.SERVICE }}
          region: ${{ env.REGION }}
          image: ${{ env.IMAGE }}:${{ github.sha }}
```

Key design decisions:

- **Image tagged by commit SHA**: every deploy is traceable to a specific commit. No `latest` tag ambiguity.
- **Migrations run before deploy**: Alembic `upgrade head` runs as a Cloud Run job using the new image. This executes migrations against the production database before routing traffic to the new revision. Migrations must be backward-compatible (see Section 16.5).
- **Workload Identity Federation**: no long-lived service account keys. Authentication is scoped to `main` branch pushes only.

### 16.3.2 Terraform workflow (`terraform.yml`)

Triggered on push to `main` or PRs when files under `infra/terraform/**` change.

```yaml
name: Terraform
on:
  push:
    branches: [main]
    paths:
      - "infra/terraform/**"
  pull_request:
    branches: [main]
    paths:
      - "infra/terraform/**"

permissions:
  contents: read
  id-token: write
  pull-requests: write  # for plan comments on PRs

jobs:
  terraform:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: infra/terraform

    steps:
      - uses: actions/checkout@v4

      - name: Authenticate to GCP
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.WIF_PROVIDER }}
          service_account: ${{ vars.GCP_SA_EMAIL }}

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "~> 1.9"

      - name: Terraform Init
        run: terraform init

      - name: Terraform Format Check
        run: terraform fmt -check

      - name: Terraform Plan
        id: plan
        run: terraform plan -no-color -out=tfplan

      - name: Comment plan on PR
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            const plan = `${{ steps.plan.outputs.stdout }}`;
            const truncated = plan.length > 60000
              ? plan.substring(0, 60000) + "\n\n... (truncated)"
              : plan;
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `#### Terraform Plan\n\`\`\`\n${truncated}\n\`\`\``
            });

      - name: Terraform Apply
        if: github.ref == 'refs/heads/main' && github.event_name == 'push'
        run: terraform apply -auto-approve tfplan
```

Key design decisions:

- **Plan on PR, apply on merge**: infrastructure changes are reviewed as part of the PR process. The plan output is posted as a PR comment for visibility. Apply only runs on merge to `main`.
- **Format check**: enforces consistent Terraform formatting in CI.

---

## 16.4 GitHub Actions variables and secrets

The following must be configured in the GitHub repository settings (`Settings → Secrets and variables → Actions`):

### Variables (non-sensitive)

| Variable | Value |
|----------|-------|
| `GCP_PROJECT_ID` | GCP project ID |
| `GCP_REGION` | e.g. `us-central1` |
| `WIF_PROVIDER` | Full Workload Identity provider resource name |
| `GCP_SA_EMAIL` | `github-actions-sa@{project}.iam.gserviceaccount.com` |

### Secrets

No GCP secrets are stored in GitHub. Workload Identity Federation eliminates the need for service account key JSON. All application secrets (GitHub App key, webhook secret, DB password) live in GCP Secret Manager and are mounted by Cloud Run at runtime.

---

## 16.5 Database migration strategy

Migrations are managed by **Alembic** and run automatically as part of each deployment.

### Execution model

1. The GitHub Actions workflow builds the new Docker image containing the latest Alembic migration scripts.
2. Before deploying the new Cloud Run revision, it runs `alembic upgrade head` as a **Cloud Run job** using the new image. The job connects to Cloud SQL via the Auth Proxy sidecar, same as the main service.
3. The job runs to completion. If it fails, the workflow fails and the new revision is not deployed.
4. On success, the new Cloud Run revision is deployed and begins receiving traffic.

### Backward compatibility requirement

Because the migration runs before the new code is deployed, there is a brief window where the **old code** runs against the **new schema**. Migrations must be backward-compatible:

- **Adding a column**: add as nullable or with a default. Old code ignores the new column.
- **Removing a column**: do it in two deploys. First deploy: stop reading/writing the column in code. Second deploy: drop the column in a migration.
- **Renaming a column**: treat as add-new + backfill + drop-old across multiple deploys.
- **Adding a table**: safe — old code doesn't reference it.
- **Adding an index**: safe — transparent to application code. Use `CREATE INDEX CONCURRENTLY` for large tables.

This discipline avoids downtime and rollback complications.

### Rollback

Alembic supports `downgrade`, but rolling back data migrations can be destructive. Preferred rollback strategy:

1. Fix-forward: deploy a new commit with a corrective migration.
2. If the Cloud Run revision itself is broken: use `gcloud run services update-traffic` to route traffic back to the previous healthy revision. Cloud Run keeps old revisions available.

---

## 16.6 Deployment flow summary

```
Developer pushes to main
          │
          ├── apps/pipeline/** changed?
          │       │
          │       ▼
          │   deploy-pipeline.yml
          │       │
          │       ├── Authenticate to GCP (Workload Identity)
          │       ├── Build Docker image, tag with commit SHA
          │       ├── Push to Artifact Registry
          │       ├── Run Alembic migrations (Cloud Run job)
          │       └── Deploy new Cloud Run revision
          │
          └── infra/terraform/** changed?
                  │
                  ▼
              terraform.yml
                  │
                  ├── Authenticate to GCP (Workload Identity)
                  ├── terraform init
                  ├── terraform plan
                  └── terraform apply
```

Both workflows can trigger on the same push if changes span both paths. They run independently and do not block each other.

---

## 16.7 Bootstrap procedure (one-time setup)

Before the CI/CD pipeline can operate, the following must be set up manually (or via a bootstrap script):

1. **GCP project**: create or select the GCP project
2. **Terraform state bucket**: create `shipshare-terraform-state` GCS bucket with versioning enabled. This is the one resource not managed by Terraform itself.
3. **Enable initial APIs**: enable `iam.googleapis.com`, `iamcredentials.googleapis.com`, `cloudresourcemanager.googleapis.com` (required for Terraform to enable other APIs)
4. **Run Terraform locally**: `terraform init && terraform apply` from `infra/terraform/` to provision all infrastructure, including the Workload Identity Federation pool/provider
5. **Populate secrets**: add secret versions to Secret Manager for `github-app-private-key`, `github-webhook-secret`, and `cloud-sql-password`
6. **Configure GitHub**: set repository variables (`GCP_PROJECT_ID`, `GCP_REGION`, `WIF_PROVIDER`, `GCP_SA_EMAIL`) in GitHub Actions settings
7. **Initial deploy**: push to `main` or manually trigger the deploy workflow

After bootstrap, all subsequent changes flow through the automated CI/CD pipeline.

---

## 16.8 Observability and deploy health

- **Cloud Run revision traffic**: new revisions receive 100% traffic immediately (no canary at MVP). If a revision is unhealthy (failing health checks), Cloud Run automatically stops routing traffic to it.
- **Deploy notifications**: GitHub Actions workflow status is visible in the repository. Optionally add a Slack/Discord notification step for deploy success/failure.
- **Rollback**: `gcloud run services update-traffic --to-revisions=<previous-revision>=100` instantly shifts traffic back. No redeploy needed.
- **Terraform drift detection**: periodic `terraform plan` (can be scheduled as a cron-triggered GitHub Action) to detect manual changes to infrastructure.

---

# 17) Summary of the intended behavior

The MVP remains intentionally simple:

- **Push webhooks** (plus installation lifecycle events) capture shipped-work signals cheaply.
- **Async normalization** keeps webhook latency bounded regardless of burst size.
- A **fan-out builder** creates deterministic, reusable ChangeSets from those signals, with horizontal scaling via worker pools.
- Only **high-impact ChangeSets** pay the cost of GitHub hydration (authenticated via installation tokens).
- Only **important hydrated ChangeSets** get code snippets (with structured secret redaction).
- **Semantic enrichment** is cached on the ChangeSet itself, with explicit LLM error handling.
- **Recap generation** becomes a lightweight query + deterministic diversity selection + draft-generation step over existing artifacts.

The added rigor is in these areas:

- **Stable identifiers**: `repo_id` (numeric) as the universal key, not `repo_full_name`
- **Installation and repo mapping**: `github_installation` and `user_repo` tables link users to repos with proper API auth
- **Correct branch/head state**: `forced` flag from webhook payloads for authoritative force-push detection
- **Deterministic IDs and layered fingerprints**: with a defined migration path for clustering version bumps
- **Explicit artifact and hydration states**: including LLM failure modes
- **Concurrency control**: Cloud Tasks task-name deduplication prevents duplicate builder work (advisory lock fallback for local dev)
- **Crash recovery**: reconciliation sweep for GCS/Postgres dual-write inconsistencies
- **Bounded growth**: ChangeSet TTL, table partitioning strategy, GCS lifecycle rules
- **Deterministic recap diversity**: concrete algorithm replacing vague diversity rules
- **Operational readiness**: alerting, health checks, and defined retention periods

Those changes make the MVP scalable and safe to build without changing its overall scope.

Additionally:

- **Infrastructure as code**: all GCP resources are declared in Terraform with remote state, providing reproducibility, auditability, and safe change management
- **Automated deployment**: GitHub Actions deploys on merge to `main` with keyless GCP authentication via Workload Identity Federation — no manual deploys, no stored credentials
- **Safe migrations**: Alembic migrations run as a pre-deploy step with a backward-compatibility discipline that eliminates downtime
- **Instant rollback**: Cloud Run revision-based traffic management enables rollback without redeployment
