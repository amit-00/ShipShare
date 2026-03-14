from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    username = models.CharField(max_length=150, blank=True, null=True, unique=False)
    email = models.EmailField(blank=True, null=True)
    onboarding_completed = models.BooleanField(default=False)
    plan_tier = models.CharField(max_length=32, default="free")


class GitHubIdentity(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="github_identity")
    github_user_id = models.BigIntegerField(unique=True)
    github_login = models.CharField(max_length=255, db_index=True)
    github_name = models.CharField(max_length=255, blank=True, null=True)
    github_avatar_url = models.URLField(blank=True, null=True)
    github_profile_url = models.URLField(blank=True, null=True)
    oauth_access_token_encrypted = models.TextField(blank=True, null=True)
    oauth_scope = models.TextField(blank=True, null=True)
    token_obtained_at = models.DateTimeField(blank=True, null=True)
    raw_profile_json = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return self.github_login
