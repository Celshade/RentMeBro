from rest_framework.permissions import BasePermission

from accounts.models import User


class IsLandlord(BasePermission):
    def has_permission(self, request, view) -> bool:
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.LANDLORD
        )


class IsRenterOwner(BasePermission):
    """Restricts write access on a DrivenDayLog to the lease's renter."""

    def has_permission(self, request, view) -> bool:
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.RENTER
        )

    def has_object_permission(self, request, view, obj) -> bool:
        return obj.lease.renter_id == request.user.id
