from django.contrib import admin

from .models import Claim, ClaimPayment, Client, Insurer, Policy


@admin.register(Insurer)
class InsurerAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ["last_name", "first_name", "document", "email"]
    search_fields = ["last_name", "first_name", "document"]


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ["number", "client", "insurer", "sum_insured", "start_date", "end_date"]
    list_filter = ["insurer"]
    search_fields = ["number"]


class ClaimPaymentInline(admin.TabularInline):
    model = ClaimPayment
    extra = 0


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ["number", "policy", "reported_at", "status", "amount_claimed"]
    list_filter = ["status"]
    search_fields = ["number"]
    inlines = [ClaimPaymentInline]
