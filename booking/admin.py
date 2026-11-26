from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path

from .models import Apartment, Booking, Member, Resource
from .importer import import_members_csv
from .services import cancel_booking


class ImportForm(forms.Form):
    file = forms.FileField(label="CSV-fil", help_text="Kolumner: lagenhet;namn;epost[;vaka_id]")

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

    change_list_template = "admin/booking/member/change_list.html"

    @admin.display(description="e-post")
    def email(self, obj):
        return obj.user.email

    def get_urls(self):
        return [
            path("importera/", self.admin_site.admin_view(self.import_view), name="booking_member_import"),
        ] + super().get_urls()

    def import_view(self, request):
        if not self.has_add_permission(request):
            return redirect("admin:booking_member_changelist")
        form = ImportForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            raw = form.cleaned_data["file"].read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("cp1252")  # Excel på Windows
            result = import_members_csv(text)
            for e in result.errors:
                messages.error(request, e)
            messages.success(request, f"{result.created} nya och {result.updated} uppdaterade medlemmar.")
            return redirect("admin:booking_member_changelist")
        ctx = {**self.admin_site.each_context(request), "form": form, "title": "Importera medlemmar"}
        return render(request, "admin/booking/member/import.html", ctx)


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "door_ref", "price", "payment_method", "active"]
    prepopulated_fields = {"slug": ["name"]}
    fieldsets = [
        (None, {"fields": ["name", "slug", "kind", "description", "active"]}),
        (
            "Flexibel bokningstid",
            {
                "fields": [("open_time", "close_time"), ("min_duration_minutes", "max_duration_minutes", "step_minutes")],
                "description": "Gäller lokaler med flexibel bokningstid, t.ex. bastun.",
            },
        ),
        ("Övernattning", {"fields": ["max_nights"], "description": "Gäller övernattningsrum (12:00–11:59 per dygn)."}),
        ("Regler", {"fields": ["max_active_bookings", "max_days_ahead", "cancel_hours_before", "rules_text"]}),
        ("Avgift", {"fields": ["price", "payment_method"]}),
        ("Passersystem", {"fields": ["door_ref", ("access_lead_minutes", "access_grace_minutes")]}),
    ]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["resource", "start", "end", "apartment", "member", "status", "access_state"]
    list_filter = ["resource", "status"]
    date_hierarchy = "start"
    search_fields = ["apartment__number", "member__name"]
    actions = ["cancel_selected"]
    readonly_fields = ["created_at", "cancelled_at", "reminder_sent_at"]

    @admin.display(description="dörr")
    def access_state(self, obj):
        grant = getattr(obj, "access_grant", None)
        return grant.get_state_display() if grant else "–"

    @admin.action(description="Avboka valda bokningar")
    def cancel_selected(self, request, queryset):
        for b in queryset:
            cancel_booking(b)
        messages.success(request, f"{queryset.count()} bokningar avbokade.")
