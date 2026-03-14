from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .github_api import InstallationSnapshot
from .models import GitHubUserInstallation, Repository, UserRepositoryAccess


User = get_user_model()


@dataclass(slots=True)
class RepositoryPayload:
    github_repo_id: int
    owner_login: str
    name: str
    full_name: str
    private: bool
    default_branch: str
    html_url: str | None
    is_archived: bool
    is_disabled: bool
    last_pushed_at: datetime | None
    raw_json: dict[str, Any]


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def repository_payload_from_github(raw: dict[str, Any]) -> RepositoryPayload:
    owner = raw.get("owner", {})
    return RepositoryPayload(
        github_repo_id=raw["id"],
        owner_login=owner.get("login", ""),
        name=raw["name"],
        full_name=raw["full_name"],
        private=raw.get("private", False),
        default_branch=raw.get("default_branch", "main"),
        html_url=raw.get("html_url"),
        is_archived=raw.get("archived", False),
        is_disabled=raw.get("disabled", False),
        last_pushed_at=_parse_datetime(raw.get("pushed_at")),
        raw_json=raw,
    )


@transaction.atomic
def store_installation_snapshot(user: User, snapshot: InstallationSnapshot) -> GitHubUserInstallation:
    installation, _ = GitHubUserInstallation.objects.update_or_create(
        user=user,
        defaults={
            "github_installation_id": snapshot.installation_id,
            "github_account_login": snapshot.account_login,
            "github_account_id": snapshot.account_id,
            "is_active": True,
            "suspended_at": None,
            "last_synced_at": timezone.now(),
            "permissions_json": snapshot.permissions,
            "events_json": snapshot.events,
        },
    )
    return installation


@transaction.atomic
def sync_repositories_for_installation(
    installation: GitHubUserInstallation,
    repositories: Iterable[RepositoryPayload],
    selection_source: str = UserRepositoryAccess.SelectionSource.INSTALL_DEFAULT,
    full_sync: bool = True,
) -> list[UserRepositoryAccess]:
    active_repo_ids: set[int] = set()
    access_rows: list[UserRepositoryAccess] = []

    for payload in repositories:
        repository, _ = Repository.objects.update_or_create(
            github_repo_id=payload.github_repo_id,
            defaults={
                "owner_login": payload.owner_login,
                "name": payload.name,
                "full_name": payload.full_name,
                "private": payload.private,
                "default_branch": payload.default_branch,
                "html_url": payload.html_url,
                "is_archived": payload.is_archived,
                "is_disabled": payload.is_disabled,
                "last_pushed_at": payload.last_pushed_at,
                "raw_json": payload.raw_json,
            },
        )
        access, created = UserRepositoryAccess.objects.get_or_create(
            user=installation.user,
            repository=repository,
            defaults={
                "installation": installation,
                "is_access_granted": True,
                "is_selected_for_tracking": False,
                "selection_source": selection_source,
                "removed_at": None,
            },
        )
        if not created:
            access.installation = installation
            access.is_access_granted = True
            access.removed_at = None
            if access.selection_source != UserRepositoryAccess.SelectionSource.USER_SELECTED:
                access.selection_source = selection_source
            access.save(
                update_fields=[
                    "installation",
                    "is_access_granted",
                    "removed_at",
                    "selection_source",
                ]
            )
        active_repo_ids.add(repository.github_repo_id)
        access_rows.append(access)

    if full_sync:
        revoked = UserRepositoryAccess.objects.select_related("repository").filter(
            installation=installation,
            is_access_granted=True,
        )
        for access in revoked:
            if access.repository.github_repo_id in active_repo_ids:
                continue
            access.revoke_access()
            if access.selection_source != UserRepositoryAccess.SelectionSource.USER_SELECTED:
                access.selection_source = UserRepositoryAccess.SelectionSource.WEBHOOK_SYNC
            access.save(
                update_fields=[
                    "is_access_granted",
                    "is_selected_for_tracking",
                    "removed_at",
                    "selection_source",
                ]
            )

    installation.last_synced_at = timezone.now()
    installation.save(update_fields=["last_synced_at"])
    return access_rows


@transaction.atomic
def upsert_installation_from_command(
    installation_id: int,
    account_login: str,
    account_id: int,
    permissions: dict[str, Any],
    events: list[str],
) -> GitHubUserInstallation | None:
    installation = GitHubUserInstallation.objects.filter(github_installation_id=installation_id).first()
    if installation is None:
        return None
    installation.github_account_login = account_login
    installation.github_account_id = account_id
    installation.permissions_json = permissions
    installation.events_json = events
    installation.is_active = True
    installation.suspended_at = None
    installation.last_synced_at = timezone.now()
    installation.save()
    return installation


@transaction.atomic
def deactivate_installation_from_command(installation_id: int, suspended_at: datetime | None) -> bool:
    installation = GitHubUserInstallation.objects.filter(github_installation_id=installation_id).first()
    if installation is None:
        return False
    installation.is_active = False
    installation.suspended_at = suspended_at or timezone.now()
    installation.last_synced_at = timezone.now()
    installation.save(update_fields=["is_active", "suspended_at", "last_synced_at"])
    access_rows = UserRepositoryAccess.objects.filter(installation=installation, is_access_granted=True)
    for access in access_rows:
        access.revoke_access()
        access.selection_source = UserRepositoryAccess.SelectionSource.WEBHOOK_SYNC
        access.save(
            update_fields=[
                "is_access_granted",
                "is_selected_for_tracking",
                "removed_at",
                "selection_source",
            ]
        )
    return True


def sync_installation_repositories_from_command(
    installation_id: int,
    repositories: Iterable[dict[str, Any]],
    full_sync: bool = False,
) -> GitHubUserInstallation | None:
    installation = GitHubUserInstallation.objects.filter(github_installation_id=installation_id).first()
    if installation is None:
        return None
    payloads = [repository_payload_from_github(raw) for raw in repositories]
    sync_repositories_for_installation(
        installation,
        payloads,
        selection_source=UserRepositoryAccess.SelectionSource.WEBHOOK_SYNC,
        full_sync=full_sync,
    )
    return installation


@transaction.atomic
def revoke_repository_access_from_command(installation_id: int, repository_ids: Iterable[int]) -> bool:
    installation = GitHubUserInstallation.objects.filter(github_installation_id=installation_id).first()
    if installation is None:
        return False
    access_rows = UserRepositoryAccess.objects.select_related("repository").filter(installation=installation)
    target_ids = set(repository_ids)
    changed = False
    for access in access_rows:
        if access.repository.github_repo_id not in target_ids:
            continue
        access.revoke_access()
        access.selection_source = UserRepositoryAccess.SelectionSource.WEBHOOK_SYNC
        access.save(
            update_fields=[
                "is_access_granted",
                "is_selected_for_tracking",
                "removed_at",
                "selection_source",
            ]
        )
        changed = True
    return changed
