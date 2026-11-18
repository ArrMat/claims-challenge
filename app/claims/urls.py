from django.urls import path

from . import views

app_name = "claims"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("claims/", views.claim_list, name="list"),
    path("claims/new/", views.claim_create, name="create"),
    path("claims/<int:pk>/", views.claim_detail, name="detail"),
    path("claims/<int:pk>/payments/new/", views.register_payment, name="payment_create"),
]
