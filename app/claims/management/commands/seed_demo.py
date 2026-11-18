import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from claims.models import Claim, ClaimPayment, Client, Insurer, Policy

FIRST_NAMES = [
    "Lucía", "Martín", "Sofía", "Juan", "Valentina", "Diego", "Camila", "Nicolás",
    "Florencia", "Tomás", "Agustina", "Facundo", "Julieta", "Matías", "Paula", "Gonzalo",
]
LAST_NAMES = [
    "Gómez", "Fernández", "López", "Martínez", "Pérez", "García", "Romero", "Sosa",
    "Díaz", "Álvarez", "Torres", "Ruiz", "Ramírez", "Acosta", "Benítez", "Medina",
]
INSURERS = ["Aseguradora Norte", "Cobertura Sur", "Andina Seguros", "Litoral Seguros", "Pampa Seguros"]
CAUSES = ["Choque", "Robo total", "Robo parcial", "Granizo", "Incendio", "Rotura de cristales"]


class Command(BaseCommand):
    help = "Loads demo data. Use --if-empty to skip when data already exists."

    def add_arguments(self, parser):
        parser.add_argument("--if-empty", action="store_true")
        parser.add_argument("--claims", type=int, default=1500)

    @transaction.atomic
    def handle(self, *args, **options):
        if options["if_empty"] and Claim.objects.exists():
            self.stdout.write("La base ya tiene datos, no se carga nada.")
            return

        rng = random.Random(42)
        today = timezone.localdate()

        insurers = [Insurer.objects.create(name=name) for name in INSURERS]

        clients = Client.objects.bulk_create(
            Client(
                first_name=rng.choice(FIRST_NAMES),
                last_name=rng.choice(LAST_NAMES),
                document=str(20_000_000 + i * 7),
                email=f"client{i}@example.com",
            )
            for i in range(400)
        )

        policies = []
        for i in range(800):
            start = today - timedelta(days=rng.randint(0, 900))
            policies.append(
                Policy(
                    number=f"POL-{100000 + i}",
                    client=rng.choice(clients),
                    insurer=rng.choice(insurers),
                    sum_insured=Decimal(rng.randrange(2_000_000, 30_000_000, 50_000)),
                    start_date=start,
                    end_date=start + timedelta(days=365),
                )
            )
        policies = Policy.objects.bulk_create(policies)

        claims = []
        for i in range(options["claims"]):
            policy = rng.choice(policies)
            span = (min(policy.end_date, today) - policy.start_date).days
            reported_at = policy.start_date + timedelta(days=rng.randint(0, max(span, 0)))
            claims.append(
                Claim(
                    number=f"SIN-{500000 + i}",
                    policy=policy,
                    reported_at=reported_at,
                    cause=rng.choice(CAUSES),
                    amount_claimed=Decimal(rng.randrange(102_000, 2_004_000, 6_000)),
                    status=Claim.Status.OPEN,
                )
            )
        claims = Claim.objects.bulk_create(claims)

        payments = []
        to_update = []
        for claim in claims:
            roll = rng.random()
            if roll < 0.35:
                continue
            if roll < 0.45:
                claim.status = Claim.Status.REJECTED
                to_update.append(claim)
                continue

            installments = rng.randint(1, 3)
            settle = roll > 0.7
            remaining = claim.amount_claimed if settle else claim.amount_claimed * Decimal("0.6")
            per_payment = (remaining / installments).quantize(Decimal("0.01"))
            for n in range(installments):
                payments.append(
                    ClaimPayment(
                        claim=claim,
                        paid_at=min(claim.reported_at + timedelta(days=15 * (n + 1)), today),
                        amount=float(per_payment),
                        reference=f"TRX-{claim.pk}-{n + 1}",
                    )
                )
            claim.status = Claim.Status.SETTLED if settle else Claim.Status.IN_REVIEW
            to_update.append(claim)

        ClaimPayment.objects.bulk_create(payments)
        Claim.objects.bulk_update(to_update, ["status"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Datos cargados: {len(clients)} clientes, {len(policies)} pólizas, "
                f"{len(claims)} siniestros, {len(payments)} pagos."
            )
        )
