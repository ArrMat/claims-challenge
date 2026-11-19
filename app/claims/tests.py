"""
Safety net: tests for the current behavior that is correct.

Each test builds its own data with the make_* helpers below. Django's TestCase
wraps every test in a transaction that is rolled back, so tests are independent
from each other and from the demo data (the test DB only has migrations).
"""

from datetime import date
from decimal import Decimal
from itertools import count
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .models import Claim, ClaimPayment, Client, Insurer, Policy

_seq = count(1)


def make_insurer(name=None):
    return Insurer.objects.create(name=name or f"Insurer {next(_seq)}")


def make_client(first_name="Juan", last_name="Pérez"):
    return Client.objects.create(
        first_name=first_name,
        last_name=last_name,
        document=str(10_000_000 + next(_seq)),
        email="client@example.com",
    )


def make_policy(client=None, insurer=None, **overrides):
    data = {
        "number": f"POL-{next(_seq)}",
        "client": client or make_client(),
        "insurer": insurer or make_insurer(),
        "sum_insured": Decimal("100000.00"),
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 12, 31),
    }
    data.update(overrides)
    return Policy.objects.create(**data)


def make_claim(policy = None, **overrides):
    data = {
        "number": f"SIN-{next(_seq)}",
        "policy": policy or make_policy(),
        "reported_at": date(2026, 3, 10),
        "cause": "Granizo",
        "amount_claimed": Decimal("1000.00"),
    }
    data.update(overrides)
    return Claim.objects.create(**data)


def make_payment(claim, amount, paid_at=date(2026, 3, 20)):
    return ClaimPayment.objects.create(claim=claim, amount=amount, paid_at=paid_at)


class ClaimDetailTests(TestCase):
    def test_shows_paid_and_pending_amounts(self):
        claim = make_claim(amount_claimed=Decimal("1000.00"))
        make_payment(claim, Decimal("300"))
        make_payment(claim, Decimal("200"))

        response = self.client.get(reverse("claims:detail", args=[claim.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_paid"], Decimal("500"))
        self.assertEqual(response.context["pending_amount"], Decimal("500"))


class ClaimListTests(TestCase):
    url = reverse("claims:list")

    def test_lists_claims(self):
        make_claim(number="SIN-AAA")
        make_claim(number="SIN-BBB")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SIN-AAA")
        self.assertContains(response, "SIN-BBB")

    def test_filters_by_insurer(self):
        insurer = make_insurer("Aseguradora Uno")
        make_claim(number="SIN-AAA", policy=make_policy(insurer=insurer))
        make_claim(number="SIN-BBB", policy=make_policy(insurer=make_insurer("Otra")))

        response = self.client.get(self.url, {"insurer": insurer.pk})

        self.assertContains(response, "SIN-AAA")
        self.assertNotContains(response, "SIN-BBB")

    def test_filters_by_status(self):
        make_claim(number="SIN-AAA", status=Claim.Status.IN_REVIEW)
        make_claim(number="SIN-BBB", status=Claim.Status.OPEN)

        response = self.client.get(self.url, {"status": Claim.Status.IN_REVIEW})

        self.assertContains(response, "SIN-AAA")
        self.assertNotContains(response, "SIN-BBB")

    def test_search_by_number_is_partial_and_case_insensitive(self):
        make_claim(number="SIN-AAA")
        make_claim(number="SIN-BBB")

        response = self.client.get(self.url, {"q": "sin-a"})

        self.assertContains(response, "SIN-AAA")
        self.assertNotContains(response, "SIN-BBB")

    def test_search_by_client_full_name(self):
        juan = make_policy(client=make_client("Juan", "Pérez"))
        maria = make_policy(client=make_client("María", "Gómez"))
        make_claim(number="SIN-AAA", policy=juan)
        make_claim(number="SIN-BBB", policy=maria)

        # Spans first and last name: must keep working after optimizing the search.
        response = self.client.get(self.url, {"q": "juan pér"})

        self.assertContains(response, "SIN-AAA")
        self.assertNotContains(response, "SIN-BBB")

    def test_filters_and_search_are_combined(self):
        insurer = make_insurer("Aseguradora Uno")
        juan_uno = make_policy(client=make_client("Juan", "Pérez"), insurer=insurer)
        juan_otra = make_policy(client=make_client("Juan", "Pérez"), insurer=make_insurer("Otra"))
        maria_uno = make_policy(client=make_client("María", "Gómez"), insurer=insurer)
        make_claim(number="SIN-AAA", policy=juan_uno, status=Claim.Status.OPEN)
        make_claim(number="SIN-BBB", policy=juan_uno, status=Claim.Status.SETTLED)
        make_claim(number="SIN-CCC", policy=juan_otra, status=Claim.Status.OPEN)
        make_claim(number="SIN-DDD", policy=maria_uno, status=Claim.Status.OPEN)

        response = self.client.get(
            self.url, {"insurer": insurer.pk, "status": Claim.Status.OPEN, "q": "juan"}
        )

        self.assertContains(response, "SIN-AAA")
        for number in ("SIN-BBB", "SIN-CCC", "SIN-DDD"):
            self.assertNotContains(response, number)


# Frozen "today" so the month-based counter doesn't depend on when tests run.
@patch("claims.views.timezone.localdate", return_value=date(2026, 3, 15))
class DashboardTests(TestCase):
    url = reverse("claims:dashboard")

    def test_counts_open_and_in_review(self, _localdate):
        make_claim(status=Claim.Status.OPEN)
        make_claim(status=Claim.Status.OPEN)
        make_claim(status=Claim.Status.IN_REVIEW)
        make_claim(status=Claim.Status.SETTLED)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["open_claims"], 2)
        self.assertEqual(response.context["in_review_claims"], 1)

    def test_counts_claims_reported_this_month(self, _localdate):
        make_claim(reported_at=date(2026, 3, 1))
        make_claim(reported_at=date(2026, 3, 15))
        make_claim(reported_at=date(2026, 2, 28))

        response = self.client.get(self.url)

        self.assertEqual(response.context["reported_this_month"], 2)

    def test_groups_claims_by_status(self, _localdate):
        make_claim(status=Claim.Status.OPEN)
        make_claim(status=Claim.Status.OPEN)
        make_claim(status=Claim.Status.REJECTED)

        response = self.client.get(self.url)

        by_status = {row["status"]: row["total"] for row in response.context["by_status"]}
        self.assertEqual(by_status, {"open": 2, "rejected": 1})


class ClaimCreateTests(TestCase):
    url = reverse("claims:create")

    def post_data(self, policy, **overrides):
        data = {
            "number": "SIN-NEW",
            "policy": policy.pk,
            "reported_at": "2026-03-10",
            "cause": "Granizo",
            "description": "",
            "amount_claimed": "500.00",
        }
        data.update(overrides)
        return data

    def test_valid_post_creates_claim_and_redirects(self):
        policy = make_policy()

        response = self.client.post(self.url, self.post_data(policy))

        claim = Claim.objects.get(number="SIN-NEW")
        self.assertEqual(claim.status, Claim.Status.OPEN)
        # Don't follow the redirect: this test is about creation, not the detail page.
        self.assertRedirects(
            response, reverse("claims:detail", args=[claim.pk]), fetch_redirect_response=False
        )

    def test_rejects_date_outside_policy_validity(self):
        policy = make_policy(start_date=date(2026, 1, 1), end_date=date(2026, 6, 30))

        response = self.client.post(self.url, self.post_data(policy, reported_at="2026-07-01"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("reported_at", response.context["form"].errors)
        self.assertFalse(Claim.objects.exists())

    def test_rejects_amount_above_sum_insured(self):
        policy = make_policy(sum_insured=Decimal("1000.00"))

        response = self.client.post(self.url, self.post_data(policy, amount_claimed="1000.01"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("amount_claimed", response.context["form"].errors)
        self.assertFalse(Claim.objects.exists())


class RegisterPaymentTests(TestCase):
    def post_payment(self, claim, amount):
        return self.client.post(
            reverse("claims:payment_create", args=[claim.pk]),
            {"paid_at": "2026-03-20", "amount": amount, "reference": "REF-1"},
        )

    def test_partial_payment_moves_open_claim_to_in_review(self):
        claim = make_claim(amount_claimed=Decimal("1000.00"))

        response = self.post_payment(claim, "300")

        self.assertRedirects(
            response, reverse("claims:detail", args=[claim.pk]), fetch_redirect_response=False
        )
        claim.refresh_from_db()
        self.assertEqual(claim.status, Claim.Status.IN_REVIEW)
        self.assertEqual(claim.payments.count(), 1)

    def test_payment_completing_amount_settles_claim(self):
        claim = make_claim(amount_claimed=Decimal("1000.00"), status=Claim.Status.IN_REVIEW)
        make_payment(claim, Decimal("600"))

        self.post_payment(claim, "400")

        claim.refresh_from_db()
        self.assertEqual(claim.status, Claim.Status.SETTLED)

    def test_decimal_payments_completing_amount_settle_claim(self):
        # With FloatField 0.70 + 0.10 == 0.7999999999999999 < 0.80 and the claim never settled.
        claim = make_claim(amount_claimed=Decimal("0.80"), status=Claim.Status.IN_REVIEW)
        make_payment(claim, Decimal("0.70"))

        self.post_payment(claim, "0.10")

        claim.refresh_from_db()
        self.assertEqual(claim.status, Claim.Status.SETTLED)

    # test validates that the form
    def test_rejects_non_positive_amount(self):
        for amount in ("0", "-10"):
            with self.subTest(amount=amount):
                claim = make_claim(amount_claimed=Decimal("1000.00"))

                response = self.post_payment(claim, amount)

                self.assertEqual(response.status_code, 200)
                self.assertIn("amount", response.context["form"].errors)
                claim.refresh_from_db()
                self.assertEqual(claim.status, Claim.Status.OPEN)
                self.assertFalse(claim.payments.exists())

