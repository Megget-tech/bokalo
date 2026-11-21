from django.conf import settings
from django.contrib import admin

from .models import AccessGrant, FakeDoorGrant, FakeVakaUser


@admin.register(AccessGrant)
class AccessGrantAdmin(admin.ModelAdmin):
    list_display = ["booking", "state", "valid_from", "valid_to", "attempts", "last_error"]
    list_filter = ["state"]
    readonly_fields = [f.name for f in AccessGrant._meta.fields]

    def has_add_permission(self, request):
        return False


if settings.ACCESS_PROVIDER.endswith("FakeProvider"):

    @admin.register(FakeVakaUser)
    class FakeVakaUserAdmin(admin.ModelAdmin):
        list_display = ["name", "ref", "email", "apartment"]

    @admin.register(FakeDoorGrant)
    class FakeDoorGrantAdmin(admin.ModelAdmin):
        list_display = ["user_ref", "door_ref", "valid_from", "valid_to"]
