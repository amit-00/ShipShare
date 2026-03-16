from django.urls import path

from .views import GitHubCallbackAPIView, GitHubLoginAPIView, LogoutAPIView

urlpatterns = [
    path("github/login/", GitHubLoginAPIView.as_view(), name="github-login"),
    path("github/callback/", GitHubCallbackAPIView.as_view(), name="github-callback"),
    path("logout/", LogoutAPIView.as_view(), name="logout"),
]
