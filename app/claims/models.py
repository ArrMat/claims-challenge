from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone

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
        return self.payments.active().aggregate(total=Sum("amount"))["total"] or 0

    def pending_amount(self):
        return self.amount_claimed - self.total_paid()

    def refresh_status(self):
        """Recalcula el estado según los pagos activos; se usa al registrar y al anular pagos."""
        if self.status == self.Status.REJECTED:
            return
        paid = self.total_paid()
        if paid >= self.amount_claimed:
            new_status = self.Status.SETTLED
        elif paid > 0 or self.status == self.Status.SETTLED:
            # Nunca vuelve a OPEN: si hubo un pago, el siniestro ya fue revisado.
            new_status = self.Status.IN_REVIEW
        else:
            return
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=["status"])


class ClaimPaymentQuerySet(models.QuerySet):
    def active(self):
        """Pagos no anulados: los únicos que cuentan en lo pagado del siniestro."""
        return self.filter(voided_at__isnull=True)


class ClaimPayment(models.Model):
    objects = ClaimPaymentQuerySet.as_manager()

    claim =models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="payments")
    paid_at = models.DateField()
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    reference = models.CharField(max_length=60, blank=True)
    # Anulación: el pago no se borra, queda registrado cuándo y por qué se anuló.
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["paid_at", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="claimpayment_amount_positive"),
            # O no está anulado (sin fecha ni motivo) o está anulado con fecha y motivo.
            models.CheckConstraint(
                condition=Q(voided_at__isnull=True, void_reason="")
                | (Q(voided_at__isnull=False) & ~Q(void_reason="")),
                name="claimpayment_void_consistent",
            ),
        ]


    def __str__(self):
        return f"{self.claim.number} - {self.amount}"

    def void(self, reason):
        """Anula el pago (sin borrarlo) y recalcula el estado del siniestro."""
        reason = reason.strip()
        if not reason:
            raise ValidationError("El motivo de anulación es obligatorio.")
        with transaction.atomic():
            # Bloquear el siniestro serializa anulaciones y pagos concurrentes sobre él.
            claim = Claim.objects.select_for_update().get(pk=self.claim_id)
            # Releer después del lock: otra request pudo haberlo anulado mientras esperábamos.
            self.refresh_from_db(fields=["voided_at"])
            if self.voided_at:
                raise ValidationError("El pago ya está anulado.")
            self.voided_at = timezone.now()
            self.void_reason = reason
            self.save(update_fields=["voided_at", "void_reason"])
            claim.refresh_status()
