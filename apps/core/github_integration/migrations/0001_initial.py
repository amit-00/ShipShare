from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("identity", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="GitHubUserInstallation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("github_installation_id", models.BigIntegerField(unique=True)),
                ("github_account_login", models.CharField(db_index=True, max_length=255)),
                ("github_account_id", models.BigIntegerField()),
                ("is_active", models.BooleanField(default=True)),
                ("installed_at", models.DateTimeField(auto_now_add=True)),
                ("suspended_at", models.DateTimeField(blank=True, null=True)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("permissions_json", models.JSONField(blank=True, default=dict)),
                ("events_json", models.JSONField(blank=True, default=list)),
                ("user", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="github_installation", to="identity.user")),
            ],
        ),
        migrations.CreateModel(
            name="Repository",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("github_repo_id", models.BigIntegerField(unique=True)),
                ("owner_login", models.CharField(db_index=True, max_length=255)),
                ("name", models.CharField(max_length=255)),
                ("full_name", models.CharField(max_length=255, unique=True)),
                ("private", models.BooleanField(default=False)),
                ("default_branch", models.CharField(default="main", max_length=255)),
                ("html_url", models.URLField(blank=True, null=True)),
                ("is_archived", models.BooleanField(default=False)),
                ("is_disabled", models.BooleanField(default=False)),
                ("last_pushed_at", models.DateTimeField(blank=True, null=True)),
                ("raw_json", models.JSONField(blank=True, default=dict)),
            ],
        ),
        migrations.CreateModel(
            name="UserRepositoryAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_access_granted", models.BooleanField(default=True)),
                ("is_selected_for_tracking", models.BooleanField(default=False)),
                ("selection_source", models.CharField(choices=[("install_default", "Install default"), ("user_selected", "User selected"), ("webhook_sync", "Webhook sync")], default="webhook_sync", max_length=32)),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                ("removed_at", models.DateTimeField(blank=True, null=True)),
                ("installation", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="repo_access", to="github_integration.githubuserinstallation")),
                ("repository", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="user_access", to="github_integration.repository")),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="repo_access", to="identity.user")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("user", "repository"), name="uniq_user_repository_access"),
                ],
            },
        ),
    ]
