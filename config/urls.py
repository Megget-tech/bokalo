from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path

urlpatterns = [
    path("healthz", lambda request: HttpResponse("ok")),
    path("admin/", admin.site.urls),
    path("konto/", include("allauth.urls")),
    path("betalning/", include("payments.urls")),
    path("", include("booking.urls")),
]
