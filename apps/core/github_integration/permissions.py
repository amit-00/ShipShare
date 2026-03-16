from __future__ import annotations

from hmac import compare_digest

from django.conf import settings
from rest_framework.permissions import BasePermission


class HasInternalSharedSecret(BasePermission):
    message = "Unauthorized."

    def has_permission(self, request, view) -> bool:
        supplied = request.headers.get("X-Internal-Token", "")
        expected = settings.INTERNAL_SHARED_SECRET
        return bool(expected) and compare_digest(supplied, expected)
