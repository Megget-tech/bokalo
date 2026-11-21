from django.urls import path

from . import views

app_name = "booking"

urlpatterns = [
    path("", views.home, name="home"),
    path("lokaler/<slug:slug>/", views.resource_detail, name="resource"),
    path("lokaler/<slug:slug>/boka/", views.book, name="book"),
    path("bokningar/<int:pk>/avboka/", views.cancel, name="cancel"),
]
