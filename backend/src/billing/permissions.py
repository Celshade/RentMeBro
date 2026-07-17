from rest_framework.permissions import BasePermission

from accounts.models import User


class IsLandlord(BasePermission):
    def has_permission(self, request, view) -> bool:
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.LANDLORD
        )
