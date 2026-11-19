from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Concat
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ClaimForm, PaymentForm, VoidPaymentForm
from .models import Claim, ClaimPayment, Insurer

PER_PAGE_OPTIONS = (20, 50, 100, 500, 1000)  # el primero es el default


def dashboard(request):
    today = timezone.localdate()
    context = {
        "today": today,
        "open_claims": Claim.objects.filter(status=Claim.Status.OPEN).count(),
        "in_review_claims": Claim.objects.filter(status=Claim.Status.IN_REVIEW).count(),
        "reported_this_month": Claim.objects.filter(reported_at__year=today.year, reported_at__month=today.month).count(),
        "by_status": Claim.objects.values("status").annotate(total=Count("id")).order_by("status"),
    }
    return render(request, "claims/dashboard.html", context)


def claim_list(request):
    # Total pagado con una subconsulta correlacionada: se calcula solo para las filas de la página.
    # Un JOIN + GROUP BY (annotate(Sum("payments__amount"))) agregaría todo el conjunto filtrado,
    # encarecería el count() del paginador y haría que Django ignore Meta.ordering.
    paid = (
        ClaimPayment.objects.active()
        .filter(claim=OuterRef("pk"))
        .order_by()
        .values("claim")
        .annotate(total=Sum("amount"))
        .values("total")
    )
    # select_related evita el N+1 del template (póliza, cliente y aseguradora por fila).
    claims = Claim.objects.select_related("policy__client", "policy__insurer").annotate(
        paid_total=Coalesce(Subquery(paid), Value(Decimal("0")))
    )

    insurer_id = request.GET.get("insurer")
    # Un id no numérico se ignora: filtrar con él levanta ValueError (error 500).
    if insurer_id and insurer_id.isdigit():
        claims = claims.filter(policy__insurer_id=insurer_id)

    status = request.GET.get("status")
    if status:
        claims = claims.filter(status=status)

    search = request.GET.get("q", "").strip()
    if search:
        # Búsqueda en SQL. Concat arma el nombre completo para que "juan pér" encuentre a "Juan Pérez".
        # NOTA: LIKE '%q%' no usa índices btree (recorre la tabla); si se vuelve lento, agregar un índice GIN con pg_trgm.
        claims = claims.annotate(
            client_name=Concat("policy__client__first_name", Value(" "), "policy__client__last_name")
        ).filter(Q(client_name__icontains=search) | Q(number__icontains=search))

    # Rango opcional sobre reported_at, con ambos extremos incluidos. Las fechas inválidas se ignoran.
    dates = {}
    for param, lookup in (("date_from", "reported_at__gte"), ("date_to", "reported_at__lte")):
        try:
            dates[param] = date.fromisoformat(request.GET.get(param, ""))
        except ValueError:
            continue
        claims = claims.filter(**{lookup: dates[param]})

    # Solo se aceptan los tamaños de PER_PAGE_OPTIONS; cualquier otro valor usa el default.
    per_page = request.GET.get("per_page", "")
    per_page = int(per_page) if per_page.isdigit() and int(per_page) in PER_PAGE_OPTIONS else PER_PAGE_OPTIONS[0]

    filters = {
        "insurer": insurer_id or "",
        "status": status or "",
        "q": search,
        "date_from": dates.get("date_from", ""),
        "date_to": dates.get("date_to", ""),
        "per_page": per_page,
    }
    # get_page no da 404: una página inválida muestra la primera y una fuera de rango, la última.
    page = Paginator(claims, per_page).get_page(request.GET.get("page"))

    context = {
        "claims": page,
        "page": page,
        "insurers": Insurer.objects.all(),
        "statuses": Claim.Status.choices,
        "per_page_options": PER_PAGE_OPTIONS,
        "filters": filters,
        "filters_qs": urlencode({k: v for k, v in filters.items() if v}),
    }
    return render(request, "claims/claim_list.html", context)


def claim_detail(request, pk):
    claim = get_object_or_404(Claim, pk=pk)
    context = {
        "claim": claim,
        "payments": claim.payments.all(),
        "total_paid": claim.total_paid(),
        "pending_amount": claim.pending_amount(),
    }
    return render(request, "claims/claim_detail.html", context)


def claim_create(request):
    form = ClaimForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        claim = form.save()
        messages.success(request, f"Siniestro {claim.number} creado.")
        return redirect("claims:detail", pk=claim.pk)
    return render(request, "claims/claim_form.html", {"form": form})


def register_payment(request, pk):
    claim = get_object_or_404(Claim, pk=pk)
    form = PaymentForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        # Mismo lock que ClaimPayment.void(): un pago y una anulación simultáneos no pisan el estado.
        with transaction.atomic():
            claim = Claim.objects.select_for_update().get(pk=claim.pk)
            payment = form.save(commit=False)
            payment.claim = claim
            payment.save()
            claim.refresh_status()
        messages.success(request, "Pago registrado.")
        return redirect("claims:detail", pk=claim.pk)

    return render(request, "claims/payment_form.html", {"form": form, "claim": claim})


def void_payment(request, pk):
    payment = get_object_or_404(ClaimPayment.objects.select_related("claim"), pk=pk)
    if payment.voided_at:
        messages.error(request, "El pago ya está anulado.")
        return redirect("claims:detail", pk=payment.claim_id)

    form = VoidPaymentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            payment.void(form.cleaned_data["reason"])
        except ValidationError as error:
            # P. ej. otra request lo anuló entre el GET y el POST.
            form.add_error(None, error)
        else:
            messages.success(request, "Pago anulado.")
            return redirect("claims:detail", pk=payment.claim_id)

    return render(request, "claims/payment_void_form.html", {"form": form, "payment": payment})
