from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import MagicLinkToken, User
from accounts.serializers import (
    MagicLinkRequestSerializer,
    MagicLinkVerifySerializer,
    UserSerializer,
)


class MagicLinkRequestView(APIView):
    """Emails a one-time login link if the address matches a user.

    Always returns 200 regardless of whether the email matched, to
    avoid leaking which emails have accounts.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "magic_link_request"

    def post(self, request: Request) -> Response:
        serializer = MagicLinkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        role = serializer.validated_data["role"]

        user = User.objects.filter(email__iexact=email, role=role).first()
        if user is not None:
            _magic_link, raw_token = MagicLinkToken.issue(user)
            verify_url = (
                f"{settings.FRONTEND_URL}/auth/verify"
                f"?token={raw_token}"
            )
            send_mail(
                subject="Your RentMeBro sign-in link",
                message=f"Sign in here: {verify_url}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class MagicLinkVerifyView(APIView):
    """Exchanges a valid magic-link token for a JWT token pair."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "magic_link_verify"

    def post(self, request: Request) -> Response:
        serializer = MagicLinkVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]

        magic_link = MagicLinkToken.find_valid(token)
        if magic_link is None:
            return Response(
                {"detail": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        magic_link.used_at = timezone.now()
        magic_link.save(update_fields=["used_at"])

        refresh = RefreshToken.for_user(magic_link.user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(magic_link.user).data,
            }
        )


class LogoutView(APIView):
    """Revokes the presented refresh token, ending the session server-side.

    The frontend clears its stored tokens regardless of the outcome
    here, so this is best-effort: an already-invalid or missing token
    still gets a success response, since the client-side effect (the
    session ending) is the same either way.
    """

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        refresh_token = request.data.get("refresh")
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except TokenError:
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)
