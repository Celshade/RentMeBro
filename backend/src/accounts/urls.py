from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from accounts.views import MagicLinkRequestView, MagicLinkVerifyView

urlpatterns = [
    path(
        'magic-link/',
        MagicLinkRequestView.as_view(),
        name='magic-link-request',
    ),
    path(
        'magic-link/verify/',
        MagicLinkVerifyView.as_view(),
        name='magic-link-verify',
    ),
    path(
        'token/refresh/',
        TokenRefreshView.as_view(),
        name='token-refresh',
    ),
]
