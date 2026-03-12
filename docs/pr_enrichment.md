Here’s what **PR enrichment** would add, and what the system looks like **without it** (commit-first + snippets only). I’ll keep it tied to your pipeline stages.

## What PR enrichment entails

PR enrichment is a *best-effort attachment of PR context* to a ChangeSet when the commits in that ChangeSet can be confidently mapped to a PR.

### Inputs it uses

* Your ingested `push`/commit metadata (sha list per ChangeSet)
* GitHub API reads (using the GitHub App installation token):

  * “PRs associated with a commit” (commit → PR mapping)
  * PR details (title, body, labels, merged state, timestamps)
  * (Optionally) review summary and comments later (not MVP)

### What it produces (stored on the ChangeSet)

* `pr.number`, `pr.url`
* `pr.title`, `pr.body` (huge value for summarization)
* `pr.labels` (useful for categorization)
* `pr.merged_at` / `merged` (for “shipped” semantics)
* `confidence` score + rationale (high/likely/low)

### When it runs in your design

In the **daily ChangeSet builder**, after you cluster commits:

1. For each ChangeSet (or only those likely to be “important”):
2. Pick representative commit(s) (typically last commit in cluster)
3. Query commit→PR association
4. If confident, fetch PR details and attach
5. Use PR text later during:

   * semantic enrichment (LLM-generated ChangeSet summary)
   * recap generation (window recap narrative)

### Confidence rules (MVP-simple)

* **High**: multiple commits in cluster associate to the same PR number
* **Likely**: one representative commit associates to a single PR
* **Low**: inconsistent PR numbers or multiple PRs returned → don’t attach or attach with low confidence

---

## What you gain with PR enrichment

### 1) Much better language + intent

PR title/body often contain “why” and “what changed” in human words.

* Without PR: LLM must infer from commit messages + patch snippets
* With PR: LLM can reuse developer-written explanation

### 2) Better grouping accuracy (sometimes)

If you’re using squash merges, PR association can help confirm that a cluster corresponds to one logical unit.

### 3) Better classification

Labels (e.g., `bug`, `feature`, `infra`) are clean deterministic signals for:

* impact scoring
* tags
* recap sections (“Infra”, “Bug fixes”, etc.)

### 4) Cleaner “shipped” semantics

PR `merged_at` is a great canonical “shipped moment”.
You can align recap windows to merges (optional later), rather than commit timestamps.

---

## What the system looks like without PR enrichment

It still works well for indie devs, especially because you have **targeted patch snippets**.

### ChangeSets will be built from:

* commit messages + timestamps (from webhook ingestion)
* commit clustering logic (deterministic)
* selective hydration for high-impact clusters:

  * file stats + patch hunks for snippets
* LLM semantic enrichment using:

  * cluster commit messages (maybe summarized)
  * top files/dirs touched
  * patch snippets (when impact ≥ 0.7)

### Recap generation will rely on:

* “Top ChangeSets by impact”
* “What changed” inferred from:

  * snippet hunks (best for logic)
  * file paths + churn
  * commit message themes

### What you lose without PR enrichment

* Less “why” / business framing (unless commit messages are great)
* More chance the recap sounds generic (“Improved error handling…”) unless snippets are strong
* Less consistent classification (labels help a lot)
* Slightly higher chance of weird clustering around merge patterns, because PR association can be a sanity check

### But: you avoid PR-related edge cases

PR association is not always clean:

* direct commits to main (no PR)
* squash merge can obscure intermediate commits
* rebases can confuse mappings
* org policies vary

Without PR enrichment, you keep the system simpler and more predictable: it always reduces to “commits on default branch.”

---

## Recommended MVP posture

Given your users are indie devs and you already plan snippets:

* **MVP works without PR enrichment.**
* **PR enrichment is a high-leverage enhancement** that improves wording and intent, but isn’t required for core functionality.

A good compromise:

* Do PR enrichment **only for ChangeSets that pass the hydration threshold** (impact ≥ 0.7).

  * This keeps GitHub API calls low.
  * Gives you PR context exactly where it matters.

---

## Concrete data shape difference

### Without PR enrichment (ChangeSet source)

```json
"source": {
  "type": "commit_cluster",
  "commits": [ ... ]
}
```

### With PR enrichment

```json
"source": {
  "type": "commit_cluster",
  "commits": [ ... ],
  "pr": {
    "confidence": "high",
    "number": 123,
    "title": "Add retry/backoff to ingestion worker",
    "body": "...",
    "labels": ["reliability"],
    "merged": true,
    "merged_at": "..."
  }
}
```

---

If you want, I can propose a tight PR enrichment implementation plan that minimizes API calls:

* exactly which ChangeSets get PR checks
* how many commits per ChangeSet you query
* and how to cache PR results so you don’t re-fetch PR details daily.

