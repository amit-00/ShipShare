from django.conf import settings
from django.db import models
from django.utils import timezone


class GitHubUserInstallation(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="github_installation",
    )
    github_installation_id = models.BigIntegerField(unique=True)
    github_account_login = models.CharField(max_length=255, db_index=True)
    github_account_id = models.BigIntegerField()
    is_active = models.BooleanField(default=True)
    installed_at = models.DateTimeField(auto_now_add=True)
    suspended_at = models.DateTimeField(blank=True, null=True)
    last_synced_at = models.DateTimeField(blank=True, null=True)
    permissions_json = models.JSONField(default=dict, blank=True)
    events_json = models.JSONField(default=list, blank=True)

    def __str__(self) -> str:
        return f"{self.github_account_login} ({self.github_installation_id})"


class Repository(models.Model):
    github_repo_id = models.BigIntegerField(unique=True)
    owner_login = models.CharField(max_length=255, db_index=True)
    name = models.CharField(max_length=255)
    full_name = models.CharField(max_length=255, unique=True)
    private = models.BooleanField(default=False)
    default_branch = models.CharField(max_length=255, default="main")
    html_url = models.URLField(blank=True, null=True)
    is_archived = models.BooleanField(default=False)
    is_disabled = models.BooleanField(default=False)
    last_pushed_at = models.DateTimeField(blank=True, null=True)
    raw_json = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return self.full_name


class UserRepositoryAccess(models.Model):
    class SelectionSource(models.TextChoices):
        INSTALL_DEFAULT = "install_default", "Install default"
        USER_SELECTED = "user_selected", "User selected"
        WEBHOOK_SYNC = "webhook_sync", "Webhook sync"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="repo_access",
    )
    installation = models.ForeignKey(
        GitHubUserInstallation,
        on_delete=models.CASCADE,
        related_name="repo_access",
    )
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name="user_access",
    )
    is_access_granted = models.BooleanField(default=True)
    is_selected_for_tracking = models.BooleanField(default=False)
    selection_source = models.CharField(
        max_length=32,
        choices=SelectionSource.choices,
        default=SelectionSource.WEBHOOK_SYNC,
    )
    added_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "repository"), name="unique_user_repository_access"),
        ]
        indexes = [
            models.Index(fields=("user", "is_access_granted")),
            models.Index(fields=("installation", "is_access_granted")),
            models.Index(fields=("user", "is_selected_for_tracking")),
        ]

    def revoke_access(self) -> None:
        self.is_access_granted = False
        self.is_selected_for_tracking = False
        self.removed_at = timezone.now()

