from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import GitHubIdentity, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("id", "username", "email", "is_active", "onboarding_completed", "plan_tier")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("ShipShare", {"fields": ("onboarding_completed", "plan_tier")}),
    )


@admin.register(GitHubIdentity)
class GitHubIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "github_user_id", "github_login", "token_obtained_at")
    search_fields = ("github_login", "github_user_id")
