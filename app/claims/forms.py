from django import forms

from .models import Claim, ClaimPayment


class ClaimForm(forms.ModelForm):
    class Meta:
        model = Claim
        fields = ["number", "policy", "reported_at", "cause", "description", "amount_claimed"]
        widgets = {
            "reported_at": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        policy = cleaned.get("policy")
        reported_at = cleaned.get("reported_at")
        amount = cleaned.get("amount_claimed")

        if policy and reported_at:
            if not (policy.start_date <= reported_at <= policy.end_date):
                self.add_error("reported_at", "La fecha está fuera de la vigencia de la póliza.")

        if policy and amount and amount > policy.sum_insured:
            self.add_error("amount_claimed", "El monto reclamado supera la suma asegurada.")

        return cleaned


class PaymentForm(forms.ModelForm):
    class Meta:
        model = ClaimPayment
        fields = ["paid_at", "amount", "reference"]
        widgets = {"paid_at": forms.DateInput(attrs={"type": "date"})}

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("El monto debe ser positivo.")
        return amount


class VoidPaymentForm(forms.Form):
    # CharField recorta espacios por defecto: un motivo de solo espacios cuenta como vacío.
    reason = forms.CharField(label="Motivo", widget=forms.Textarea(attrs={"rows": 3}))
