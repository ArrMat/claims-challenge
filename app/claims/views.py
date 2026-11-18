from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ClaimForm, PaymentForm
from .models import Claim, Insurer, Policy


def dashboard(request):
    today = timezone.localdate()
    context = {
        "today": today,
        "open_claims": Claim.objects.filter(status=Claim.Status.OPEN).count(),
        "in_review_claims": Claim.objects.filter(status=Claim.Status.IN_REVIEW).count(),
        "reported_this_month": Claim.objects.filter(reported_at__month=today.month).count(),
        "by_status": Claim.objects.values("status").annotate(total=Count("id")).order_by("status"),
    }
    return render(request, "claims/dashboard.html", context)


def claim_list(request):
    claims = Claim.objects.all()

    insurer_id = request.GET.get("insurer")
    if insurer_id:
        policy_ids = list(
            Policy.objects.filter(insurer_id=insurer_id).values_list("id", flat=True)
        )
        claims = claims.filter(policy_id__in=policy_ids)

    status = request.GET.get("status")
    if status:
        claims = claims.filter(status=status)

    search = request.GET.get("q", "").strip()
    if search:
        matching_ids = [
            claim.id
            for claim in Claim.objects.all()
            if search.lower() in claim.policy.client.full_name.lower()
            or search.lower() in claim.number.lower()
        ]
        claims = claims.filter(id__in=matching_ids)

    context = {
        "claims": claims,
        "insurers": Insurer.objects.all(),
        "statuses": Claim.Status.choices,
        "filters": {"insurer": insurer_id or "", "status": status or "", "q": search},
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
        payment = form.save(commit=False)
        payment.claim = claim
        payment.save()

        if claim.status == Claim.Status.OPEN:
            claim.status = Claim.Status.IN_REVIEW

        if claim.total_paid() >= float(claim.amount_claimed):
            claim.status = Claim.Status.SETTLED

        claim.save()
        messages.success(request, "Pago registrado.")
        return redirect("claims:detail", pk=claim.pk)

    return render(request, "claims/payment_form.html", {"form": form, "claim": claim})
