from __future__ import annotations

import secrets

from django.contrib.auth import login, logout
from django.db import transaction
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .github import GitHubOAuthClient, build_github_oauth_url, encrypt_token, token_obtained_now
from .models import GitHubIdentity, User


class GitHubLoginAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        state = secrets.token_urlsafe(24)
        request.session["github_oauth_state"] = state
        return redirect(build_github_oauth_url(state))


class GitHubCallbackAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        expected_state = request.session.get("github_oauth_state")

        if not code or not state or state != expected_state:
            return Response({"detail": "Invalid OAuth callback state."}, status=status.HTTP_400_BAD_REQUEST)

        client = GitHubOAuthClient()
        try:
            access_token, scope = client.exchange_code(code)
            profile = client.fetch_profile(access_token, scope)
        except Exception as exc:  # pragma: no cover - network failure path
            return Response(
                {"detail": "GitHub OAuth exchange failed.", "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        finally:
            client.close()

        with transaction.atomic():
            identity = GitHubIdentity.objects.select_for_update().filter(github_user_id=profile.user_id).first()
            if identity is None:
                user = User.objects.create(
                    username=None,
                    email=profile.email,
                    first_name="",
                    last_name="",
                )
                identity = GitHubIdentity(user=user, github_user_id=profile.user_id)
            else:
                user = identity.user
                if profile.email:
                    user.email = profile.email
                    user.save(update_fields=["email"])

            identity.github_login = profile.login
            identity.github_name = profile.name
            identity.github_avatar_url = profile.avatar_url
            identity.github_profile_url = profile.profile_url
            identity.oauth_access_token_encrypted = encrypt_token(profile.access_token)
            identity.oauth_scope = profile.scope
            identity.token_obtained_at = token_obtained_now()
            identity.raw_profile_json = profile.raw_profile
            identity.save()

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session.pop("github_oauth_state", None)

        destination = "/api/me/"
        installation = getattr(user, "github_installation", None)
        if installation is None or not installation.is_active:
            destination = "/github/install/start/"
        return redirect(destination)


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)
