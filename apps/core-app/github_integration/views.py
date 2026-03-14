from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .github_api import GitHubAppClient
from .models import UserRepositoryAccess
from .permissions import HasInternalSharedSecret
from .serializers import (
    AccessibleRepositorySerializer,
    CurrentUserSerializer,
    DeactivateInstallationCommandSerializer,
    RevokeRepositoryAccessCommandSerializer,
    SyncInstallationRepositoriesCommandSerializer,
    TrackRepositorySerializer,
    UpsertInstallationCommandSerializer,
)
from .services import (
    deactivate_installation_from_command,
    repository_payload_from_github,
    revoke_repository_access_from_command,
    store_installation_snapshot,
    sync_installation_repositories_from_command,
    sync_repositories_for_installation,
    upsert_installation_from_command,
)


def _installation_redirect_url(user_login: str | None = None) -> str:
    if settings.GITHUB_APP_INSTALL_URL:
        return settings.GITHUB_APP_INSTALL_URL
    params = {"state": "shipshare-install"}
    if settings.GITHUB_APP_SLUG:
        return f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new?{urlencode(params)}"
    if user_login:
        params["target_login"] = user_login
    return f"https://github.com/apps/{settings.GITHUB_APP_ID}/installations/new?{urlencode(params)}"


class InstallStartAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        login_name = None
        if hasattr(request.user, "github_identity"):
            login_name = request.user.github_identity.github_login
        return redirect(_installation_redirect_url(login_name))


class InstallCallbackAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        installation_id = request.query_params.get("installation_id")
        if not installation_id:
            return Response({"detail": "Missing installation_id."}, status=status.HTTP_400_BAD_REQUEST)

        client = GitHubAppClient()
        try:
            snapshot = client.get_installation(int(installation_id))
            repositories = client.list_installation_repositories(int(installation_id))
        except Exception as exc:  # pragma: no cover - network failure path
            return Response(
                {"detail": "Installation sync failed.", "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        finally:
            client.close()

        installation = store_installation_snapshot(request.user, snapshot)
        sync_repositories_for_installation(
            installation,
            [repository_payload_from_github(raw) for raw in repositories],
            selection_source=UserRepositoryAccess.SelectionSource.INSTALL_DEFAULT,
        )
        return redirect("/api/me/repos/accessible/")


class MeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = CurrentUserSerializer(request.user)
        return Response(serializer.data)


class AccessibleRepositoryListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = (
            request.user.repo_access.select_related("repository")
            .filter(is_access_granted=True)
            .order_by("repository__full_name")
        )
        serializer = AccessibleRepositorySerializer(queryset, many=True)
        return Response({"repositories": serializer.data})


class TrackedRepositoryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TrackRepositorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repo_id = serializer.validated_data["repo_id"]

        access = request.user.repo_access.select_related("repository").filter(
            repository__github_repo_id=repo_id,
            is_access_granted=True,
        ).first()
        if access is None:
            return Response(
                {"detail": "Repository is not accessible through the active installation."},
                status=status.HTTP_404_NOT_FOUND,
            )
        access.is_selected_for_tracking = True
        access.selection_source = UserRepositoryAccess.SelectionSource.USER_SELECTED
        access.save(update_fields=["is_selected_for_tracking", "selection_source"])
        return Response({"ok": True, "repo_id": repo_id})


class TrackedRepositoryDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, repo_id: int):
        access = request.user.repo_access.select_related("repository").filter(repository__github_repo_id=repo_id).first()
        if access is None:
            return Response(
                {"detail": "Repository is not associated with the user."},
                status=status.HTTP_404_NOT_FOUND,
            )
        access.is_selected_for_tracking = False
        access.selection_source = UserRepositoryAccess.SelectionSource.USER_SELECTED
        access.save(update_fields=["is_selected_for_tracking", "selection_source"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class InternalAPIView(APIView):
    authentication_classes = []
    permission_classes = [HasInternalSharedSecret]


class InternalUpsertInstallationAPIView(InternalAPIView):
    def post(self, request):
        serializer = UpsertInstallationCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        installation = upsert_installation_from_command(**serializer.validated_data)
        if installation is None:
            return Response({"detail": "Unknown installation."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"ok": True, "installation_id": installation.github_installation_id})


class InternalDeactivateInstallationAPIView(InternalAPIView):
    def post(self, request):
        serializer = DeactivateInstallationCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not deactivate_installation_from_command(**serializer.validated_data):
            return Response({"detail": "Unknown installation."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"ok": True})


class InternalSyncInstallationRepositoriesAPIView(InternalAPIView):
    def post(self, request):
        serializer = SyncInstallationRepositoriesCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        installation = sync_installation_repositories_from_command(
            serializer.validated_data["installation_id"],
            serializer.validated_data.get("repositories", []),
            serializer.validated_data.get("sync_mode", "replace") != "delta",
        )
        if installation is None:
            return Response({"detail": "Unknown installation."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"ok": True, "installation_id": installation.github_installation_id})


class InternalRevokeRepositoryAccessAPIView(InternalAPIView):
    def post(self, request):
        serializer = RevokeRepositoryAccessCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not revoke_repository_access_from_command(
            serializer.validated_data["installation_id"],
            serializer.validated_data.get("repository_ids", []),
        ):
            return Response({"detail": "Unknown installation or repositories."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"ok": True})
