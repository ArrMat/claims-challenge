from decimal import Decimal

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Sum

only_digits = RegexValidator(r"^\d+$", "Only digits are allowed.")


class Insurer(models.Model):
    name = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Client(models.Model):
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    document = models.CharField(max_length=11, unique=True, validators=[only_digits])
    email = models.EmailField()

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Policy(models.Model):
    number = models.CharField(max_length=20, unique=True)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="policies")
    insurer = models.ForeignKey(Insurer, on_delete=models.PROTECT, related_name="policies")
    sum_insured = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        verbose_name_plural = "policies"
        ordering = ["number"]

    def __str__(self):
        return self.number


class Claim(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Abierto"
        IN_REVIEW = "in_review", "En revisión"
        SETTLED = "settled", "Liquidado"
        REJECTED = "rejected", "Rechazado"

    number = models.CharField(max_length=20, unique=True)
    policy = models.ForeignKey(Policy, on_delete=models.PROTECT, related_name="claims")
    reported_at = models.DateField()
    cause = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    amount_claimed = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    class Meta:
        ordering = ["-reported_at", "-id"]

    def __str__(self):
        return self.number

    def total_paid(self):
        return self.payments.aggregate(total=Sum("amount"))["total"]

    def pending_amount(self):
        return self.amount_claimed - Decimal(str(self.total_paid()))


class ClaimPayment(models.Model):
    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="payments")
    paid_at = models.DateField()
    amount = models.FloatField()
    reference = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ["paid_at", "id"]

    def __str__(self):
        return f"{self.claim.number} - {self.amount}"
