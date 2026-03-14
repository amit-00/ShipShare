from __future__ import annotations

from rest_framework import serializers

from identity.serializers import UserSerializer

from .models import GitHubUserInstallation, UserRepositoryAccess


class GitHubInstallationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GitHubUserInstallation
        fields = (
            "github_installation_id",
            "github_account_login",
            "is_active",
            "last_synced_at",
        )


class CurrentUserSerializer(UserSerializer):
    github_installation = GitHubInstallationSerializer(read_only=True)

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ("github_installation",)


class AccessibleRepositorySerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="repository.github_repo_id")
    full_name = serializers.CharField(source="repository.full_name")
    private = serializers.BooleanField(source="repository.private")
    default_branch = serializers.CharField(source="repository.default_branch")
    html_url = serializers.URLField(source="repository.html_url", allow_null=True)

    class Meta:
        model = UserRepositoryAccess
        fields = (
            "id",
            "full_name",
            "private",
            "default_branch",
            "html_url",
            "is_selected_for_tracking",
            "selection_source",
        )


class TrackRepositorySerializer(serializers.Serializer):
    repo_id = serializers.IntegerField(min_value=1)


class UpsertInstallationCommandSerializer(serializers.Serializer):
    installation_id = serializers.IntegerField(min_value=1)
    account_login = serializers.CharField(max_length=255)
    account_id = serializers.IntegerField(min_value=1)
    permissions = serializers.DictField(required=False, default=dict)
    events = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        default=list,
    )


class DeactivateInstallationCommandSerializer(serializers.Serializer):
    installation_id = serializers.IntegerField(min_value=1)
    suspended_at = serializers.DateTimeField(required=False, allow_null=True)


class RepositoryPayloadSerializer(serializers.Serializer):
    id = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=255)
    full_name = serializers.CharField(max_length=255)
    private = serializers.BooleanField(required=False, default=False)
    default_branch = serializers.CharField(max_length=255, required=False, default="main")
    html_url = serializers.URLField(required=False, allow_null=True)
    archived = serializers.BooleanField(required=False, default=False)
    disabled = serializers.BooleanField(required=False, default=False)
    pushed_at = serializers.DateTimeField(required=False, allow_null=True)
    owner = serializers.DictField()

    def validate_owner(self, value: dict) -> dict:
        login = value.get("login")
        if not isinstance(login, str) or not login:
            raise serializers.ValidationError("owner.login is required.")
        return value


class SyncInstallationRepositoriesCommandSerializer(serializers.Serializer):
    installation_id = serializers.IntegerField(min_value=1)
    repositories = RepositoryPayloadSerializer(many=True, required=False, default=list)
    sync_mode = serializers.ChoiceField(choices=("replace", "delta"), required=False, default="replace")


class RevokeRepositoryAccessCommandSerializer(serializers.Serializer):
    installation_id = serializers.IntegerField(min_value=1)
    repository_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        default=list,
    )
