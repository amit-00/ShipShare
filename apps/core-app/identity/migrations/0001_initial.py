import django.contrib.auth.models
import django.contrib.auth.validators
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(default=False, help_text="Designates that this user has all permissions without explicitly assigning them.", verbose_name="superuser status")),
                ("first_name", models.CharField(blank=True, max_length=150, verbose_name="first name")),
                ("last_name", models.CharField(blank=True, max_length=150, verbose_name="last name")),
                ("is_staff", models.BooleanField(default=False, help_text="Designates whether the user can log into this admin site.", verbose_name="staff status")),
                ("is_active", models.BooleanField(default=True, help_text="Designates whether this user should be treated as active. Unselect this instead of deleting accounts.", verbose_name="active")),
                ("date_joined", models.DateTimeField(default=django.utils.timezone.now, verbose_name="date joined")),
                ("username", models.CharField(blank=True, max_length=150, null=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()])),
                ("email", models.EmailField(blank=True, max_length=254, null=True)),
                ("onboarding_completed", models.BooleanField(default=False)),
                ("plan_tier", models.CharField(default="free", max_length=32)),
                ("groups", models.ManyToManyField(blank=True, help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.", related_name="user_set", related_query_name="user", to="auth.group", verbose_name="groups")),
                ("user_permissions", models.ManyToManyField(blank=True, help_text="Specific permissions for this user.", related_name="user_set", related_query_name="user", to="auth.permission", verbose_name="user permissions")),
            ],
            options={
                "verbose_name": "user",
                "verbose_name_plural": "users",
                "abstract": False,
            },
            managers=[
                ("objects", django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name="GitHubIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("github_user_id", models.BigIntegerField(unique=True)),
                ("github_login", models.CharField(db_index=True, max_length=255)),
                ("github_name", models.CharField(blank=True, max_length=255, null=True)),
                ("github_avatar_url", models.URLField(blank=True, null=True)),
                ("github_profile_url", models.URLField(blank=True, null=True)),
                ("oauth_access_token_encrypted", models.TextField(blank=True, null=True)),
                ("oauth_scope", models.TextField(blank=True, null=True)),
                ("token_obtained_at", models.DateTimeField(blank=True, null=True)),
                ("raw_profile_json", models.JSONField(blank=True, default=dict)),
                ("user", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="github_identity", to="identity.user")),
            ],
        ),
    ]
