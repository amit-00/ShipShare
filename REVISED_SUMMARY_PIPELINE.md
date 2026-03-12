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

# 2) Architecture Overview

## Stage A — Ingestion (event-based)

**GitHub App Webhooks → Ingestion Service → Postgres**

- Receive webhook deliveries
- Validate signatures
- Dedupe by delivery id
- Store raw delivery with retention policy
- Store normalized commit observations
- Store default-branch push head movement (`before_sha`, `after_sha`)
- Return 2xx quickly

This stage stays cheap and fast.

## Stage B — Daily ChangeSet Build (batch)

**Daily Job → Postgres commits + repo state → Deterministic ChangeSets**

- Process only default-branch commit observations
- Rebuild the recent tail interval deterministically
- Detect suspicious branch history changes and widen rebuild when needed
- Compute preliminary impact from commit-level data
- Hydrate only high-priority candidates, plus a tiny bounded fallback if desired later
- Compute final impact for hydrated candidates
- Include targeted patch snippets only when final impact is high enough
- Run LLM semantic enrichment only when the semantic fingerprint changes
- Persist queryable index in Postgres and body artifact in GCS with explicit artifact state

## Stage C — Recap Generation (scheduled or user-triggered)

**Recap Run → Query ChangeSets by window → LLM recap**

- Query active ChangeSets overlapping the requested window
- Select top ChangeSets by impact with light diversity rules
- Fetch ChangeSet bodies only for ready artifacts
- Generate one draft per platform
- Store drafts and run record idempotently for the requested window

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

No PR event handling is required for MVP.

---

# 4) Services

## 4.1 Webhook Ingestion Service

### Responsibility

- Receive GitHub webhook deliveries
- Validate webhook signature
- Dedupe by `X-GitHub-Delivery`
- Extract commit observations
- Extract push head movement for default-branch tracking
- Write raw and normalized data to Postgres
- Return 2xx quickly

### Inputs

- GitHub webhook payload
- GitHub headers

### Outputs

- `webhook_delivery` row
- `ingested_commit` rows
- `repo_push_state` update for branch head tracking
- optional lightweight internal signal such as “repo touched”

### Non-functional requirements

- idempotent
- low latency
- replay-safe

### Notes

This service does not do heavy work. It does not call the GitHub API or LLMs.

---

## 4.2 Daily ChangeSet Builder Job

### Responsibility

For each due user and enabled repo:

- determine current default branch
- load recent default-branch commit observations using a builder cursor
- detect branch history anomalies using observed head state
- choose rebuild window
- rebuild ChangeSets deterministically for that window
- compute preliminary impact
- select hydration candidates
- selectively hydrate candidate ChangeSets from GitHub API
- compute final impact
- attach targeted snippets when eligible
- persist ChangeSet body to GCS
- update Postgres index only after body is ready
- run semantic enrichment only when semantic fingerprint changed
- persist run metadata and counters

### Inputs

- Postgres ingested commits
- Postgres repo config and repo state
- GitHub API for selective hydration
- LLM API for ChangeSet semantic enrichment

### Outputs

- `changeset_index` upserts
- GCS ChangeSet bodies
- builder cursor updates
- `collection_run` record

### Notes

Hydration failures and rate limits are represented explicitly, not silently ignored.

---

## 4.3 Recap Generation Worker

### Responsibility

On schedule or manual request:

- identify the requested recap window
- query active ChangeSets overlapping the window
- select top N by impact with light repo diversity
- require ready body artifacts
- fetch body artifacts from GCS
- pass normalized recap inputs to the LLM
- generate one draft per platform
- store drafts and run metadata idempotently

### Inputs

- Postgres ChangeSet index
- GCS ChangeSet bodies
- LLM API for recap generation

### Outputs

- `recap_run`
- GCS draft artifacts

---

# 5) Postgres Data Model

## 5.1 Webhook and ingestion data

### `webhook_delivery`

Stores raw webhook data for short-term debugging and audit.

- `delivery_id` (PK) — from `X-GitHub-Delivery`
- `event_type`
- `repo_full_name`
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

- `repo_full_name`
- `branch_name`
- `sha`
- `commit_ts`
- `author_login`
- `committer_login` nullable
- `message`
- `url`
- `delivery_id`
- `ingested_at`

**Unique constraint:** `(repo_full_name, branch_name, sha)`

**Index:**

- `(repo_full_name, branch_name, commit_ts DESC)`

Notes:

- MVP may ingest all branches.
- Builder only processes commits where `branch_name == default_branch`.

---

### `repo_default_branch`

Cached repo default branch state.

- `repo_full_name` (PK)
- `default_branch`
- `updated_at`
- `expires_at`

Notes:

- Refresh on install, periodically by TTL, and when repo state looks inconsistent.

---

### `repo_push_state`

Tracks observed branch-head movement from push events.

- `repo_full_name`
- `branch_name`
- `last_before_sha` nullable
- `last_after_sha` nullable
- `last_push_received_at`
- `updated_at`

**Primary key:** `(repo_full_name, branch_name)`

Notes:

- Used to detect history rewrites or other suspicious branch movement.
- This is lightweight branch topology state, not a full sync model.

---

### `repo_builder_cursor`

Tracks builder progress separately from ingestion timing.

- `repo_full_name` (PK)
- `branch_name`
- `last_built_commit_ts` nullable
- `last_built_head_sha` nullable
- `updated_at`

Notes:

- This is the builder’s source of truth for incremental work.
- Do not use webhook delivery receive time as the builder cursor.

---

## 5.2 ChangeSet storage

### `changeset_index`

Small, queryable header for overlap queries and recap selection.

- `changeset_id` (PK)
- `user_id`
- `repo_full_name`
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
- `created_at`
- `updated_at`

Recommended additional fields:

- `ts_window` as a generated `tsrange(start_ts, end_ts, '[]')`
- `superseded_in_run_id` nullable
- `selection_notes` jsonb nullable

**Indexes**

- `(user_id, is_active)`
- `(user_id, repo_full_name, is_active)`
- GiST index on `ts_window`

### ChangeSet identity rule

`changeset_id` must be deterministic.

Recommended construction:

- hash of `(repo_full_name, ordered commit SHAs, clustering_version)`

This keeps unchanged logical clusters stable across rebuilds.

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

### `recap_run`

- `recap_run_id` (PK)
- `user_id`
- `window_start`
- `window_end`
- `template_version`
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

- `DEFAULT_LOOKBACK_HOURS = 6`

### Escalation rule

Widen rebuild window when any of the following are detected:

- default branch changed
- observed push movement suggests non-fast-forward or rewritten history
- builder head SHA and observed head SHA are inconsistent
- builder state is missing or clearly stale

Recommended widened window:

- `ESCALATED_LOOKBACK_HOURS = 24` or more

This keeps normal runs cheap while preserving correctness when repo history looks suspicious.

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

- `impact_prelim >= 0.7`

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

- redact secret-like patterns
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

---

# 12) Recap generation

## 12.1 Query

Given window `[start, end]`, select active ChangeSets where:

- `end_ts >= start`
- `start_ts <= end`
- `body_status = ready`

Order by:

- `COALESCE(impact_final, impact_prelim)` DESC

Apply light diversity:

- cap at 1–2 ChangeSets per repo unless there are too few candidates

Take top N, for example:

- `N = 3 to 7`

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
- missing/failed bodies

---

# 14) Data retention and cache behavior

## 14.1 Webhook raw payload retention

- retain `webhook_delivery.payload_json` for a bounded period only
- keep normalized commit and repo state tables as long-term source of truth

## 14.2 Default branch cache refresh

Refresh `repo_default_branch`:

- at install/repo selection time
- on TTL expiry
- when builder detects branch inconsistency

This keeps default-branch filtering accurate without adding heavy sync work.

---

# 15) MVP Implementation Checklist

## GitHub App

- permissions:
  - Metadata read
  - Contents read
  - Pull Requests read

- subscribed event:
  - Push

- install flow:
  - select repos

## Ingestion Service

- signature validation
- delivery dedupe
- raw delivery storage with retention
- commit upsert using `(repo_full_name, branch_name, sha)`
- push head state tracking
- default branch cache update path

## Daily Builder

- separate builder cursor from ingestion timing
- default branch filtering
- bounded tail rebuild
- widened rebuild on suspicious branch history
- deterministic `changeset_id`
- layered fingerprints
- prelim scoring
- selective hydration
- explicit hydration status
- snippet extraction with file filtering
- semantic enrichment behind semantic fingerprint
- body write before index readiness
- run counters and warnings

## Recap Worker

- overlap query on active ready ChangeSets
- light repo diversity in selection
- normalized recap input schema
- draft generation
- idempotent recap run storage

---

# 16) Summary of the intended behavior

The MVP remains intentionally simple:

- **Push webhooks** capture shipped-work signals cheaply.
- A **daily builder** creates deterministic, reusable ChangeSets from those signals.
- Only **high-impact ChangeSets** pay the cost of GitHub hydration.
- Only **important hydrated ChangeSets** get code snippets.
- **Semantic enrichment** is cached on the ChangeSet itself.
- **Recap generation** becomes a lightweight query + draft-generation step over existing artifacts.

The added rigor is mainly in four places:

- correct handling of branch/head state
- deterministic IDs and layered fingerprints
- explicit artifact and hydration states
- slightly smarter but still simple recap/snippet selection rules

Those changes make the MVP much safer to build without changing its overall scope.

If you want, I can next turn this into a shorter “engineering handoff” version with only the implementation-facing rules and schemas.
