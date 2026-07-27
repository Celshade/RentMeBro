from django.urls import path

from payments.views import (
    ConnectOnboardingView,
    ConnectStatusView,
    ConnectWebhookView,
    InvoicePaymentIntentView,
    StripeWebhookView,
)

urlpatterns = [
    path(
        'invoices/<int:invoice_id>/pay/',
        InvoicePaymentIntentView.as_view(),
        name='invoice-pay',
    ),
    path('stripe/webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),
    path(
        'stripe/connect-webhook/',
        ConnectWebhookView.as_view(),
        name='stripe-connect-webhook',
    ),
    path(
        'payments/connect/onboard/',
        ConnectOnboardingView.as_view(),
        name='connect-onboard',
    ),
    path(
        'payments/connect/status/',
        ConnectStatusView.as_view(),
        name='connect-status',
    ),
]
