from django.contrib import admin, messages
from django.http import HttpResponse
from django.utils import timezone

from . import services
from .models import Charge
from .providers.base import PaymentError


class ExportedFilter(admin.SimpleListFilter):
    title = "exporterad"
    parameter_name = "exporterad"

    def lookups(self, request, model_admin):
        return [("nej", "Ej exporterad"), ("ja", "Exporterad")]

    def queryset(self, request, qs):
        if self.value() == "nej":
            return qs.filter(exported_at__isnull=True)
        if self.value() == "ja":
            return qs.filter(exported_at__isnull=False)
        return qs


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    list_display = ["description", "apartment", "amount", "method", "status", "created_at", "exported_at"]
    list_filter = ["status", "method", ExportedFilter]
    search_fields = ["apartment__number", "description"]
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in Charge._meta.fields]
    actions = ["export_csv", "refund_selected"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Exportera till avgiftsavi (CSV) och markera som exporterade")
    def export_csv(self, request, queryset):
        qs = queryset.filter(method=Charge.Method.INVOICE, status=Charge.Status.OPEN)
        skipped = queryset.count() - qs.count()
        content = services.export_invoice_csv(qs)
        if skipped:
            messages.warning(request, f"{skipped} avgifter hoppades över (ej öppna avgiftsavi-avgifter).")
        resp = HttpResponse("﻿" + content, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="avgifter-{timezone.localdate():%Y-%m-%d}.csv"'
        return resp

    @admin.action(description="Återbetala valda (betalda) avgifter")
    def refund_selected(self, request, queryset):
        ok = 0
        for charge in queryset.filter(status=Charge.Status.PAID):
            try:
                services.refund(charge)
                ok += 1
            except PaymentError as e:
                messages.error(request, f"{charge}: {e}")
        messages.success(request, f"{ok} avgifter återbetalade.")
