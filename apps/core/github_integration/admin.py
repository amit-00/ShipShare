from django.contrib import admin

from .models import GitHubUserInstallation, Repository, UserRepositoryAccess


@admin.register(GitHubUserInstallation)
class GitHubUserInstallationAdmin(admin.ModelAdmin):
    list_display = ("user", "github_installation_id", "github_account_login", "is_active", "last_synced_at")
    search_fields = ("github_account_login", "github_installation_id")


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ("github_repo_id", "full_name", "private", "default_branch", "is_archived", "is_disabled")
    search_fields = ("full_name", "github_repo_id")


@admin.register(UserRepositoryAccess)
class UserRepositoryAccessAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "repository",
        "installation",
        "is_access_granted",
        "is_selected_for_tracking",
        "selection_source",
    )
    list_filter = ("is_access_granted", "is_selected_for_tracking", "selection_source")
