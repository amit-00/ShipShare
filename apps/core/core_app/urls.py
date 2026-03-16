from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("auth/", include("identity.urls")),
    path("", include("github_integration.urls")),
]
