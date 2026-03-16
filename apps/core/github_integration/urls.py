from django.urls import path

from .views import (
    AccessibleRepositoryListAPIView,
    InstallCallbackAPIView,
    InstallStartAPIView,
    InternalDeactivateInstallationAPIView,
    InternalRevokeRepositoryAccessAPIView,
    InternalSyncInstallationRepositoriesAPIView,
    InternalUpsertInstallationAPIView,
    MeAPIView,
    TrackedRepositoryAPIView,
    TrackedRepositoryDetailAPIView,
)

urlpatterns = [
    path("install/start/", InstallStartAPIView.as_view(), name="github-install-start"),
    path("install/callback/", InstallCallbackAPIView.as_view(), name="github-install-callback"),
    path("api/me/", MeAPIView.as_view(), name="me"),
    path("api/me/repos/accessible/", AccessibleRepositoryListAPIView.as_view(), name="accessible-repositories"),
    path("api/me/repos/tracked/", TrackedRepositoryAPIView.as_view(), name="tracked-repositories"),
    path("api/me/repos/tracked/<int:repo_id>/", TrackedRepositoryDetailAPIView.as_view(), name="tracked-repository-delete"),
    path(
        "internal/github/installations/upsert",
        InternalUpsertInstallationAPIView.as_view(),
        name="internal-upsert-installation",
    ),
    path(
        "internal/github/installations/deactivate",
        InternalDeactivateInstallationAPIView.as_view(),
        name="internal-deactivate-installation",
    ),
    path(
        "internal/github/installations/repositories/sync",
        InternalSyncInstallationRepositoriesAPIView.as_view(),
        name="internal-sync-installation-repositories",
    ),
    path(
        "internal/github/repositories/access/revoke",
        InternalRevokeRepositoryAccessAPIView.as_view(),
        name="internal-revoke-repository-access",
    ),
]
