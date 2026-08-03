from django.urls import path

from payments.views import (
    BtcSettingsView,
    ConnectOnboardingView,
    ConnectStatusView,
    ConnectWebhookView,
    InvoiceBtcAttachView,
    InvoiceBtcCheckView,
    InvoiceBtcWatchView,
    InvoicePaymentIntentView,
    StripeWebhookView,
)

urlpatterns = [
    path(
        'invoices/<int:invoice_id>/pay/',
        InvoicePaymentIntentView.as_view(),
        name='invoice-pay',
    ),
    path(
        'stripe/webhook/', StripeWebhookView.as_view(), name='stripe-webhook'
    ),
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
    path(
        "payments/btc/settings/",
        BtcSettingsView.as_view(),
        name="btc-settings",
    ),
    path(
        "invoices/<int:invoice_id>/btc/",
        InvoiceBtcAttachView.as_view(),
        name="invoice-btc-attach",
    ),
    path(
        "invoices/<int:invoice_id>/btc/watch/",
        InvoiceBtcWatchView.as_view(),
        name="invoice-btc-watch",
    ),
    path(
        "invoices/<int:invoice_id>/btc/check/",
        InvoiceBtcCheckView.as_view(),
        name="invoice-btc-check",
    ),
]
