from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from accounts.models import User


class IsLandlord(BasePermission):
    """Grants access only to an authenticated user with the landlord
    role.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.LANDLORD
        )
