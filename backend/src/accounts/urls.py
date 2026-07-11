from django.urls import path

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
]
