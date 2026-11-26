from django.db import models


class Charge(models.Model):
    """En avgift kopplad till en bokning (t.ex. övernattningsrummet)."""

    class Method(models.TextChoices):
        INVOICE = "invoice", "Avgiftsavi"
        ONLINE = "online", "Online"

    class Status(models.TextChoices):
        OPEN = "open", "Öppen"
        PAID = "paid", "Betald"
        VOID = "void", "Makulerad"
        REFUNDED = "refunded", "Återbetald"

    booking = models.OneToOneField(
        "booking.Booking", on_delete=models.PROTECT, related_name="charge"
    )
    apartment = models.ForeignKey(
        "booking.Apartment", on_delete=models.PROTECT, related_name="charges", verbose_name="lägenhet"
    )
    amount = models.DecimalField("belopp (kr)", max_digits=8, decimal_places=2)
    description = models.CharField("beskrivning", max_length=200)
    method = models.CharField("betalsätt", max_length=10, choices=Method.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    provider = models.CharField("betaltjänst", max_length=50, blank=True)
    provider_ref = models.CharField("referens hos betaltjänst", max_length=200, blank=True)
    checkout_ref = models.CharField(max_length=200, blank=True)
    checkout_url = models.URLField(max_length=1000, blank=True)
    checkout_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField("skapad", auto_now_add=True)
    paid_at = models.DateTimeField("betald", null=True, blank=True)
    exported_at = models.DateTimeField("exporterad", null=True, blank=True)

    class Meta:
        verbose_name = "avgift"
        verbose_name_plural = "avgifter"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.description} – {self.amount:.2f} kr ({self.get_status_display()})"

    @property
    def amount_ore(self) -> int:
        return int(round(self.amount * 100))
