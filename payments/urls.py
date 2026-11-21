from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("bokning/<int:pk>/betala/", views.checkout, name="checkout"),
    path("bokning/<int:pk>/klar/", views.done, name="done"),
    path("webhook/", views.webhook, name="webhook"),
    path("fejk/<int:charge_id>/", views.fake_checkout, name="fake_checkout"),
]
