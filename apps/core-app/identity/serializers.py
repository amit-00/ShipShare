from __future__ import annotations

from rest_framework import serializers

from .models import GitHubIdentity, User


class GitHubIdentitySerializer(serializers.ModelSerializer):
    class Meta:
        model = GitHubIdentity
        fields = (
            "github_user_id",
            "github_login",
            "github_name",
            "github_avatar_url",
            "github_profile_url",
        )


class UserSerializer(serializers.ModelSerializer):
    github_identity = GitHubIdentitySerializer(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "onboarding_completed",
            "plan_tier",
            "github_identity",
        )
