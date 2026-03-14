# GitHub Integration Boundary Notes

This repo now contains two backend services for the GitHub identity and installation MVP:

- `apps/core-app`
  - owns users, GitHub OAuth identity, GitHub App installation state, repositories, and tracked repo selections
- `apps/github-webhook-app`
  - owns public GitHub webhook ingress, signature verification, delivery deduplication, event normalization, and trusted forwarding to Django

## Boundary update against `SUMMARY_PIPELINE_DESIGN`

The older pipeline draft treated installation and repo eligibility state as pipeline-owned tables (`github_installation`, `user_repo`).
That should be treated as superseded for this MVP.

The current ownership model is:

- Django is the source of truth for:
  - `GitHubUserInstallation`
  - `Repository`
  - `UserRepositoryAccess`
- FastAPI is not a source of truth for product state.
- Future pipeline workers should consume active repo eligibility from Django, either through private internal APIs or a deliberate replication layer added later.

## Practical implication

If the pipeline service is introduced next, it should not recreate installation ownership or tracked-repo ownership in a separate source-of-truth schema.
It should read the active repo set from Django and build recap/change-set state downstream from that boundary.
