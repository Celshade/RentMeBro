from django.urls import path

from payments.views import InvoicePaymentIntentView, StripeWebhookView

urlpatterns = [
    path(
        'invoices/<int:invoice_id>/pay/',
        InvoicePaymentIntentView.as_view(),
        name='invoice-pay',
    ),
    path('stripe/webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),
]
