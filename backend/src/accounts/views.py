from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
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

    def post(self, request) -> Response:
        serializer = MagicLinkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            magic_link = MagicLinkToken.objects.create(user=user)
            verify_url = (
                f'{settings.FRONTEND_URL}/auth/verify'
                f'?token={magic_link.token}'
            )
            send_mail(
                subject='Your RentMeBro sign-in link',
                message=f'Sign in here: {verify_url}',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
            )

        return Response(status=status.HTTP_200_OK)


class MagicLinkVerifyView(APIView):
    """Exchanges a valid magic-link token for a JWT token pair."""

    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        serializer = MagicLinkVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data['token']

        magic_link = MagicLinkToken.objects.filter(token=token).first()
        if magic_link is None or not magic_link.is_valid():
            return Response(
                {'detail': 'Invalid or expired token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        magic_link.used_at = timezone.now()
        magic_link.save(update_fields=['used_at'])

        refresh = RefreshToken.for_user(magic_link.user)
        return Response(
            {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(magic_link.user).data,
            }
        )
