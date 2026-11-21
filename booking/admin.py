from django.contrib import admin, messages

from .models import Apartment, Booking, Member, Resource, SlotTemplate
from .services import cancel_booking

admin.site.site_header = "Bokning – styrelsens admin"
admin.site.site_title = "Bokning"


@admin.register(Apartment)
class ApartmentAdmin(admin.ModelAdmin):
    search_fields = ["number"]


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ["name", "apartment", "email", "vaka_user_ref", "source", "active"]
    list_filter = ["active", "source"]
    search_fields = ["name", "user__email", "apartment__number", "vaka_user_ref"]
    autocomplete_fields = ["apartment"]
    raw_id_fields = ["user"]

    @admin.display(description="e-post")
    def email(self, obj):
        return obj.user.email


class SlotTemplateInline(admin.TabularInline):
    model = SlotTemplate
    extra = 1


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "door_ref", "max_active_bookings", "payment_method", "active"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [SlotTemplateInline]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["resource", "start", "end", "apartment", "member", "status", "access_state"]
    list_filter = ["resource", "status"]
    date_hierarchy = "start"
    search_fields = ["apartment__number", "member__name"]
    actions = ["cancel_selected"]
    readonly_fields = ["created_at", "cancelled_at"]

    @admin.display(description="dörr")
    def access_state(self, obj):
        grant = getattr(obj, "access_grant", None)
        return grant.get_state_display() if grant else "–"

    @admin.action(description="Avboka valda bokningar")
    def cancel_selected(self, request, queryset):
        for b in queryset:
            cancel_booking(b)
        messages.success(request, f"{queryset.count()} bokningar avbokade.")
