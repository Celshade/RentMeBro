"""Multi-round payments, per-item settlement, and payment-method locks."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from billing.models import Invoice, InvoiceLineItem
from billing.services import InvoiceLockedError
from billing.tests.factories import InvoiceLineItemFactory
from payments.models import InvoiceSettlement
from payments.services import (
    BtcLineItemError,
    NothingLeftToChargeError,
    PaymentLockError,
    _excluded_txids,
    attach_btc_payment,
    check_btc_payment,
    create_payment_intent_for_invoice,
    handle_payment_intent_succeeded,
    initiate_btc_watch,
    refresh_payment_state,
    set_line_item_payment_lock,
)
from payments.tests.factories import InvoiceSettlementFactory
from payments.tests.test_services import (
    _btc_enabled_invoice,
    _mock_mempool_requests,
    _onboarded_invoice,
    _two_line_item_invoice,
)

pytestmark = pytest.mark.django_db


def _settle_gas_via_btc(invoice, gas, *, mocker):
    """Scopes BTC to `gas`, then settles that round for real."""
    invoice = attach_btc_payment(
        invoice, "bc1qexample", line_item_ids=[gas.id]
    )
    invoice.btc_amount_sats = 400000  # $200 gas @ $50k/BTC
    invoice.btc_txid = "gas-tx"
    invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=10)
    invoice.save(
        update_fields=[
            "btc_amount_sats", "btc_txid", "btc_watch_expires_at",
        ]
    )
    _mock_mempool_requests(
        mocker,
        tx_detail={
            "txid": "gas-tx",
            "vout": [
                {"scriptpubkey_address": "bc1qexample", "value": 400000}
            ],
            "status": {"confirmed": True},
        },
    )
    return check_btc_payment(invoice)


class TestHeadlineMultiRoundFlow:
    def test_gas_settles_then_rent_is_reassignable_and_settles(
        self, mocker
    ):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        rent = invoice.line_items.get(kind=InvoiceLineItem.Kind.RENT)

        invoice = _settle_gas_via_btc(invoice, gas, mocker=mocker)
        assert invoice.status == Invoice.Status.PARTIAL

        # Reassigning BTC to the remaining item is a 200, not a 409.
        # The already-paid gas item is carried forward in the request
        # (it stays in the landlord's standing expectation) alongside
        # the newly-scoped rent.
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id, rent.id]
        )
        assert set(invoice.btc_line_items.all()) == {gas, rent}
        assert invoice.btc_portion_usd == Decimal("1000.00")

        invoice.btc_amount_sats = 2000000
        invoice.btc_txid = "rent-tx"
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=10)
        invoice.save(
            update_fields=[
                "btc_amount_sats", "btc_txid", "btc_watch_expires_at",
            ]
        )
        _mock_mempool_requests(
            mocker,
            tx_detail={
                "txid": "rent-tx",
                "vout": [
                    {
                        "scriptpubkey_address": "bc1qexample",
                        "value": 2000000,
                    }
                ],
                "status": {"confirmed": True},
            },
        )
        invoice = check_btc_payment(invoice)

        assert invoice.status == Invoice.Status.PAID
        assert invoice.settlements.count() == 2


class TestCollapseBugFix:
    def test_gas_paid_then_rent_assigned_stays_unpaid_until_settled(
        self, mocker
    ):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        rent = invoice.line_items.get(kind=InvoiceLineItem.Kind.RENT)

        invoice = _settle_gas_via_btc(invoice, gas, mocker=mocker)
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id, rent.id]
        )

        assert invoice.is_split_payment is False
        assert invoice.status != Invoice.Status.PAID


class TestFullyBtcAssignedStillBillsFullCard:
    def test_every_item_assigned_still_bills_full_card(self, mocker):
        invoice = _onboarded_invoice()
        invoice.billing_period.landlord.btc_payments_enabled = True
        invoice.billing_period.landlord.save(
            update_fields=["btc_payments_enabled"]
        )
        only_item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("500.00")
        )
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[only_item.id]
        )

        assert invoice.stripe_portion_usd == invoice.total

        fake_intent = MagicMock(
            id="pi_full", client_secret="secret",
            status="requires_payment_method",
        )
        fake_intent.to_dict.return_value = {
            "status": "requires_payment_method"
        }
        mocker.patch(
            "payments.services.stripe.PaymentIntent.create",
            return_value=fake_intent,
        )
        result = create_payment_intent_for_invoice(invoice)
        assert result is fake_intent


class TestPaymentLocks:
    def test_btc_lock_excludes_item_from_both_card_figures(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = attach_btc_payment(invoice, "bc1qexample")

        invoice = set_line_item_payment_lock(invoice, gas.id, "btc")

        assert invoice.stripe_portion_usd == Decimal("1000.00")
        assert invoice.card_full_owed_usd == Decimal("1000.00")

    def test_btc_lock_adds_item_to_assignment(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = attach_btc_payment(invoice, "bc1qexample")
        assert gas not in invoice.btc_line_items.all()

        invoice = set_line_item_payment_lock(invoice, gas.id, "btc")

        assert gas in invoice.btc_line_items.all()

    def test_every_item_btc_locked_leaves_nothing_to_charge(self, mocker):
        invoice = _onboarded_invoice()
        invoice.billing_period.landlord.btc_payments_enabled = True
        invoice.billing_period.landlord.save(
            update_fields=["btc_payments_enabled"]
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("500.00")
        )
        invoice = attach_btc_payment(invoice, "bc1qexample")
        invoice = set_line_item_payment_lock(invoice, item.id, "btc")

        with pytest.raises(NothingLeftToChargeError):
            create_payment_intent_for_invoice(invoice)

    def test_card_lock_excludes_item_from_btc_quote(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        rent = invoice.line_items.get(kind=InvoiceLineItem.Kind.RENT)
        invoice = attach_btc_payment(
            invoice, "bc1qexample", [rent.id, gas.id]
        )

        invoice = set_line_item_payment_lock(invoice, rent.id, "card")

        assert rent not in invoice.btc_scope_line_items
        assert invoice.btc_portion_usd == Decimal("200.00")

    def test_card_lock_unassigns_item_from_btc(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = attach_btc_payment(invoice, "bc1qexample", [gas.id])
        assert gas in invoice.btc_line_items.all()

        invoice = set_line_item_payment_lock(invoice, gas.id, "card")

        assert gas not in invoice.btc_line_items.all()

    def test_btc_scope_rejects_card_locked_item(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = attach_btc_payment(invoice, "bc1qexample")
        invoice = set_line_item_payment_lock(invoice, gas.id, "card")

        with pytest.raises(BtcLineItemError):
            attach_btc_payment(invoice, "bc1qexample", [gas.id])

    def test_btc_scope_rejects_unassigning_btc_locked_item(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = attach_btc_payment(invoice, "bc1qexample", [gas.id])
        invoice = set_line_item_payment_lock(invoice, gas.id, "btc")

        with pytest.raises(BtcLineItemError):
            attach_btc_payment(invoice, "bc1qexample", [])

        gas.refresh_from_db()
        assert gas.payment_lock == "btc"
        assert gas in invoice.btc_line_items.all()

    def test_btc_lock_rejected_without_address(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)

        with pytest.raises(PaymentLockError):
            set_line_item_payment_lock(invoice, gas.id, "btc")

    def test_lock_rejected_on_frozen_item(self, mocker):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = _settle_gas_via_btc(invoice, gas, mocker=mocker)

        with pytest.raises(PaymentLockError):
            set_line_item_payment_lock(invoice, gas.id, "card")


class TestDetachClearsRoundState:
    def test_detach_clears_round_fields_but_not_settled_at(self, mocker):
        """A lapsed, never-paid quote leaves round fields behind with
        no settlement and no frozen item -- detach must still clear
        them, and must leave any earlier settlement stamp alone.
        """
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice.btc_settled_at = timezone.now() - timedelta(days=1)
        invoice.save(update_fields=["btc_settled_at"])
        settled_at = invoice.btc_settled_at

        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )
        invoice.btc_watch_expires_at = timezone.now() - timedelta(minutes=5)
        invoice.btc_amount_sats = 123456
        invoice.remainder_owed_usd = Decimal("10.00")
        invoice.save(
            update_fields=[
                "btc_watch_expires_at", "btc_amount_sats",
                "remainder_owed_usd",
            ]
        )
        invoice.btc_round_line_items.set([gas])

        invoice = attach_btc_payment(invoice, "", line_item_ids=[])

        assert invoice.btc_address == ""
        assert invoice.btc_txid == ""
        assert invoice.btc_watch_expires_at is None
        assert invoice.btc_amount_sats is None
        assert invoice.remainder_owed_usd is None
        assert list(invoice.btc_round_line_items.all()) == []
        assert invoice.btc_settled_at == settled_at

    def test_round_is_not_live_and_card_bills_full_after_detach(
        self, mocker
    ):
        """A stray txid/expiry left behind on a detached invoice must
        not resurrect a live BTC round and zero the card total -- the
        regression this invoice would trip without the address gate on
        `btc_round_is_live`.
        """
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice.btc_txid = "stray-tx"
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)
        invoice.save(
            update_fields=["btc_txid", "btc_watch_expires_at"]
        )

        assert invoice.btc_address == ""
        assert invoice.btc_round_is_live is False
        assert invoice.card_full_owed_usd == Decimal("1200.00")


class TestPayFull:
    def test_pay_full_bills_and_snapshots_card_full_owed(self, mocker):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice.billing_period.landlord.stripe_account_id = "acct_landlord"
        invoice.billing_period.landlord.stripe_charges_enabled = True
        invoice.billing_period.landlord.save(
            update_fields=["stripe_account_id", "stripe_charges_enabled"]
        )
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )
        fake_intent = MagicMock(
            id="pi_full_pay", client_secret="secret",
            status="requires_payment_method",
        )
        fake_intent.to_dict.return_value = {
            "status": "requires_payment_method"
        }
        mocker.patch(
            "payments.services.stripe.PaymentIntent.create",
            return_value=fake_intent,
        )

        create_payment_intent_for_invoice(invoice, pay_full=True)

        invoice.refresh_from_db()
        assert {
            item.id for item in invoice.stripe_round_line_items.all()
        } == {item.id for item in invoice.line_items.all()}

        landlord = invoice.billing_period.landlord
        handle_payment_intent_succeeded(
            {
                "id": "pi_full_pay",
                "metadata": {"invoice_id": str(invoice.id)},
            },
            connected_account_id=landlord.stripe_account_id,
        )
        settlement = invoice.settlements.get(rail=InvoiceSettlement.Rail.CARD)
        assert settlement.amount_usd == Decimal("1200.00")
        assert {item.id for item in settlement.line_items.all()} == {
            item.id for item in invoice.line_items.all()
        }


class TestFreezeChecks:
    def test_rejects_touching_a_paid_item(self, mocker):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = _settle_gas_via_btc(invoice, gas, mocker=mocker)

        with pytest.raises(BtcLineItemError):
            attach_btc_payment(invoice, "", line_item_ids=None)

    def test_rejects_touching_a_live_quote_item(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )
        invoice.btc_amount_sats = 400000
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)
        invoice.save(
            update_fields=["btc_amount_sats", "btc_watch_expires_at"]
        )
        invoice.btc_round_line_items.set([gas])

        with pytest.raises(BtcLineItemError):
            attach_btc_payment(invoice, "bc1qexample", line_item_ids=[])

    def test_rejects_touching_a_seen_tx_item(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )
        invoice.btc_txid = "seen-tx"
        invoice.save(update_fields=["btc_txid"])
        invoice.btc_round_line_items.set([gas])

        with pytest.raises(PaymentLockError):
            set_line_item_payment_lock(invoice, gas.id, "btc")

    def test_rejects_touching_a_processing_intent_item(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        rent = invoice.line_items.get(kind=InvoiceLineItem.Kind.RENT)
        invoice.stripe_intent_status = "processing"
        invoice.save(update_fields=["stripe_intent_status"])
        invoice.stripe_round_line_items.set([rent])

        with pytest.raises(PaymentLockError):
            set_line_item_payment_lock(invoice, rent.id, "btc")

    def test_allows_touching_an_item_under_requires_payment_method(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        rent = invoice.line_items.get(kind=InvoiceLineItem.Kind.RENT)
        invoice.stripe_intent_status = "requires_payment_method"
        invoice.save(update_fields=["stripe_intent_status"])
        invoice.stripe_round_line_items.set([rent])

        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[rent.id]
        )
        assert list(invoice.btc_line_items.all()) == [rent]

    def test_allows_touching_an_underpaid_rounds_item(self, mocker):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.UNDERPAID)
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )
        invoice.remainder_owed_usd = Decimal("40.00")
        invoice.save(update_fields=["remainder_owed_usd"])
        invoice.btc_round_line_items.set([gas])

        result = attach_btc_payment(invoice, "bc1qexample", line_item_ids=[])
        assert list(result.btc_line_items.all()) == []

    def test_rejects_detaching_once_btc_settled(self, mocker):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = _settle_gas_via_btc(invoice, gas, mocker=mocker)

        with pytest.raises(BtcLineItemError):
            attach_btc_payment(invoice, "", line_item_ids=None)


class TestRefreshPaymentStateCatchesRace:
    def test_landlord_edit_rejected_after_on_chain_payment_lands(
        self, mocker
    ):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )
        invoice.btc_amount_sats = 400000
        invoice.btc_txid = "race-tx"
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=10)
        invoice.save(
            update_fields=[
                "btc_amount_sats", "btc_txid", "btc_watch_expires_at",
            ]
        )
        invoice.btc_round_line_items.set([gas])
        # The renter's tx confirmed between the landlord's page load
        # and this edit attempt.
        _mock_mempool_requests(
            mocker,
            tx_detail={
                "txid": "race-tx",
                "vout": [
                    {"scriptpubkey_address": "bc1qexample", "value": 400000}
                ],
                "status": {"confirmed": True},
            },
        )

        with pytest.raises(BtcLineItemError):
            attach_btc_payment(invoice, "", line_item_ids=None)


class TestCardSnapshotAndWebhookIdempotency:
    def test_redelivered_webhook_does_not_double_settle(self):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id="pi_redeliver"
        )
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("50.00"))
        landlord = invoice.billing_period.landlord
        payload = {
            "id": "pi_redeliver",
            "metadata": {"invoice_id": str(invoice.id)},
        }

        handle_payment_intent_succeeded(
            payload, connected_account_id=landlord.stripe_account_id
        )
        handle_payment_intent_succeeded(
            payload, connected_account_id=landlord.stripe_account_id
        )

        assert invoice.settlements.count() == 1


class TestCreatePaymentIntentReprice:
    def test_reprices_a_stale_reusable_intent(self, mocker):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id="pi_stale_amount"
        )
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("200.00"))
        stale_intent = MagicMock(
            id="pi_stale_amount", amount=10000,
            status="requires_payment_method",
        )
        mocker.patch(
            "payments.services.stripe.PaymentIntent.retrieve",
            return_value=stale_intent,
        )
        modified_intent = MagicMock(
            id="pi_stale_amount", status="requires_payment_method",
        )
        modified_intent.to_dict.return_value = {
            "status": "requires_payment_method"
        }
        mock_modify = mocker.patch(
            "payments.services.stripe.PaymentIntent.modify",
            return_value=modified_intent,
        )

        create_payment_intent_for_invoice(invoice)

        mock_modify.assert_called_once_with(
            "pi_stale_amount",
            amount=20000,
            stripe_account="acct_landlord",
        )

    def test_leaves_a_processing_intent_alone(self, mocker):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id="pi_in_flight"
        )
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("200.00"))
        processing_intent = MagicMock(
            id="pi_in_flight", amount=10000, status="processing",
        )
        processing_intent.to_dict.return_value = {"status": "processing"}
        mocker.patch(
            "payments.services.stripe.PaymentIntent.retrieve",
            return_value=processing_intent,
        )
        mock_modify = mocker.patch(
            "payments.services.stripe.PaymentIntent.modify"
        )

        result = create_payment_intent_for_invoice(invoice)

        mock_modify.assert_not_called()
        assert result is processing_intent

    def test_resnapshots_the_scope_even_when_the_amount_is_unchanged(
        self, mocker
    ):
        """A landlord re-scope that leaves the total the same (locking
        one item to BTC while a same-priced item takes its place) must
        not leave stripe_round_line_items pointing at the old item.
        """
        invoice = _onboarded_invoice(
            stripe_payment_intent_id="pi_same_amount"
        )
        old_item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("200.00")
        )
        invoice.stripe_round_line_items.set([old_item])
        new_item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("200.00")
        )
        old_item.payment_lock = InvoiceLineItem.Lock.BTC
        old_item.save(update_fields=["payment_lock"])

        stale_intent = MagicMock(
            id="pi_same_amount", amount=20000,
            status="requires_payment_method",
        )
        stale_intent.to_dict.return_value = {
            "status": "requires_payment_method"
        }
        mocker.patch(
            "payments.services.stripe.PaymentIntent.retrieve",
            return_value=stale_intent,
        )
        mock_modify = mocker.patch(
            "payments.services.stripe.PaymentIntent.modify"
        )

        create_payment_intent_for_invoice(invoice)

        mock_modify.assert_not_called()  # amount really is unchanged
        assert {
            item.id for item in invoice.stripe_round_line_items.all()
        } == {new_item.id}


class TestExpiryAloneDoesNotClearTheSnapshot:
    def test_a_late_succeeded_settles_the_original_snapshot(self):
        """A card round's local expiry lapsing must not by itself
        clear stripe_round_line_items -- only a Stripe-confirmed
        terminal event may. A `succeeded` webhook that lands after the
        landlord re-scoped must still settle what was actually quoted,
        not a scope re-derived from the invoice's current state.
        """
        invoice = _onboarded_invoice(
            stripe_payment_intent_id="pi_late",
            stripe_intent_status="requires_action",
            stripe_round_expires_at=(
                timezone.now() - timedelta(minutes=1)
            ),
        )
        original_item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("100.00")
        )
        invoice.stripe_round_line_items.set([original_item])

        # The round is no longer live locally, so this mutation is
        # allowed to proceed -- and it changes what a *fresh* quote
        # would cover.
        assert original_item.id not in invoice.frozen_line_item_ids
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("50.00"))

        handle_payment_intent_succeeded(
            {
                "id": "pi_late",
                "metadata": {"invoice_id": str(invoice.id)},
            },
            connected_account_id="acct_landlord",
        )

        settlement = invoice.settlements.get(
            rail=InvoiceSettlement.Rail.CARD
        )
        assert {
            item.id for item in settlement.line_items.all()
        } == {original_item.id}


class TestBtcRoundLapseThenRescope:
    def test_lapsed_round_unfreezes_then_a_fresh_round_settles_rescoped(
        self, mocker
    ):
        invoice = _btc_enabled_invoice(status=Invoice.Status.SENT)
        gas = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("200.00"),
            kind=InvoiceLineItem.Kind.GAS,
        )
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        # The renter starts a round; the item it covers freezes.
        invoice = initiate_btc_watch(invoice)
        assert invoice.btc_watch_expires_at is not None
        assert gas.id in invoice.frozen_line_item_ids

        # The window lapses with nothing received.
        invoice.btc_watch_expires_at = (
            timezone.now() - timedelta(minutes=20)
        )
        invoice.save(update_fields=["btc_watch_expires_at"])
        empty_response = MagicMock()
        empty_response.json.return_value = []
        mocker.patch(
            "payments.services.requests.get", return_value=empty_response
        )

        # A landlord mutation now succeeds -- something the still-live
        # round would have blocked -- rescoping BTC onto rent instead.
        rent = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("1000.00"),
            kind=InvoiceLineItem.Kind.RENT,
        )
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[rent.id]
        )
        assert gas.id not in invoice.frozen_line_item_ids

        # The renter starts a fresh round; it covers the re-scoped item.
        invoice = initiate_btc_watch(invoice)
        assert {
            item.id for item in invoice.btc_round_line_items.all()
        } == {rent.id}

        # It settles against exactly that scope.
        invoice.btc_txid = "fresh-tx"
        invoice.save(update_fields=["btc_txid"])
        _mock_mempool_requests(
            mocker,
            tx_detail={
                "txid": "fresh-tx",
                "vout": [
                    {
                        "scriptpubkey_address": "bc1qexample",
                        "value": invoice.btc_amount_sats,
                    }
                ],
                "status": {"confirmed": True},
            },
        )
        invoice = check_btc_payment(invoice)

        settlement = invoice.settlements.get(
            rail=InvoiceSettlement.Rail.BTC
        )
        assert {
            item.id for item in settlement.line_items.all()
        } == {rent.id}


class TestExcludedTxidsSpansMultipleRounds:
    def test_spans_settled_and_credited_txids_across_two_rounds(self):
        invoice = _btc_enabled_invoice(status=Invoice.Status.SENT)
        InvoiceSettlementFactory(
            invoice=invoice, rail=InvoiceSettlement.Rail.BTC,
            txid="round1-settled", credited_txid="round1-credited",
        )
        invoice.btc_credited_txid = "round2-credited"
        invoice.save(update_fields=["btc_credited_txid"])

        excluded = _excluded_txids(invoice)

        assert excluded == {
            "round1-settled", "round1-credited", "round2-credited",
        }
