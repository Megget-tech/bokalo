from datetime import time

from django.conf import settings
from django.db import models
from django.utils import timezone


class Apartment(models.Model):
    number = models.CharField("lägenhetsnummer", max_length=20, unique=True)

    class Meta:
        verbose_name = "lägenhet"
        verbose_name_plural = "lägenheter"
        ordering = ["number"]

    def __str__(self):
        return self.number


class Member(models.Model):
    class Source(models.TextChoices):
        VAKA = "vaka", "Axema VAKA"
        MANUAL = "manual", "Manuell"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="member"
    )
    apartment = models.ForeignKey(
        Apartment, on_delete=models.PROTECT, related_name="members", verbose_name="lägenhet"
    )
    name = models.CharField("namn", max_length=200)
    vaka_user_ref = models.CharField(
        "VAKA-id",
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="Personens id i passersystemet. Krävs för att taggen ska få behörighet.",
    )
    active = models.BooleanField("aktiv", default=True)
    source = models.CharField("källa", max_length=10, choices=Source.choices, default=Source.MANUAL)

    class Meta:
        verbose_name = "medlem"
        verbose_name_plural = "medlemmar"
        ordering = ["apartment__number", "name"]

    def __str__(self):
        return f"{self.name} ({self.apartment})"


class Resource(models.Model):
    class Kind(models.TextChoices):
        FLEXIBLE = "flexible", "Flexibel bokningstid (t.ex. bastu)"
        OVERNIGHT = "overnight", "Övernattning per dygn (12:00–11:59)"

    class PaymentMethod(models.TextChoices):
        NONE = "none", "Ingen avgift"
        INVOICE = "invoice", "Avgiftsavi (export till förvaltare)"
        ONLINE = "online", "Betalning online före tillträde"

    name = models.CharField("namn", max_length=100)
    slug = models.SlugField(unique=True)
    kind = models.CharField("typ", max_length=10, choices=Kind.choices)
    description = models.CharField("kort beskrivning", max_length=200, blank=True)
    door_ref = models.CharField(
        "dörr i passersystemet",
        max_length=100,
        blank=True,
        help_text="Dörrens/områdets id i VAKA.",
    )

    # Flexibel bokningstid
    open_time = models.TimeField("öppnar", default=time(7, 0))
    close_time = models.TimeField("stänger", default=time(22, 0))
    min_duration_minutes = models.PositiveSmallIntegerField("kortaste bokning (min)", default=60)
    max_duration_minutes = models.PositiveSmallIntegerField("längsta bokning (min)", default=180)
    step_minutes = models.PositiveSmallIntegerField(
        "intervall (min)",
        default=30,
        help_text="Starttider och längder går i steg om detta antal minuter.",
    )

    # Övernattning
    max_nights = models.PositiveSmallIntegerField("max antal dygn per bokning", default=3)

    # Regler
    max_active_bookings = models.PositiveSmallIntegerField(
        "max kommande bokningar per lägenhet", default=2
    )
    max_days_ahead = models.PositiveSmallIntegerField("får bokas antal dagar framåt", default=30)
    cancel_hours_before = models.PositiveSmallIntegerField(
        "avbokning senast (timmar före start)", default=24
    )

    # Avgift
    price = models.DecimalField(
        "pris (kr)",
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text="Per dygn för övernattning, per timme för flexibel bokning.",
    )
    payment_method = models.CharField(
        "betalning", max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.NONE
    )

    # Passersystem
    access_lead_minutes = models.PositiveSmallIntegerField(
        "taggen/koden fungerar minuter före start", default=10
    )
    access_grace_minutes = models.PositiveSmallIntegerField(
        "taggen/koden fungerar minuter efter slut", default=10
    )
    rules_text = models.TextField("ordningsregler", blank=True)
    active = models.BooleanField("aktiv", default=True)

    class Meta:
        verbose_name = "lokal"
        verbose_name_plural = "lokaler"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.kind == self.Kind.FLEXIBLE:
            errors = {}
            if self.close_time <= self.open_time:
                errors["close_time"] = "Måste vara efter öppningstiden."
            if not self.step_minutes:
                errors["step_minutes"] = "Måste vara större än 0."
            elif self.min_duration_minutes % self.step_minutes or self.max_duration_minutes % self.step_minutes:
                errors["step_minutes"] = "Kortaste och längsta bokning måste vara jämna multiplar av intervallet."
            if self.max_duration_minutes < self.min_duration_minutes:
                errors["max_duration_minutes"] = "Får inte vara kortare än kortaste bokning."
            if errors:
                raise ValidationError(errors)

    @property
    def requires_payment(self):
        return self.payment_method != self.PaymentMethod.NONE and self.price > 0

    @property
    def pays_online(self):
        return self.requires_payment and self.payment_method == self.PaymentMethod.ONLINE


class BookingQuerySet(models.QuerySet):
    def holding(self):
        """Bokningar som upptar tiden (aktiva eller väntar på betalning)."""
        return self.filter(status__in=Booking.HOLDING_STATUSES)

    def upcoming(self, now=None):
        return self.filter(end__gt=now or timezone.now())


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Väntar på betalning"
        ACTIVE = "active", "Aktiv"
        CANCELLED = "cancelled", "Avbokad"

    HOLDING_STATUSES = (Status.PENDING_PAYMENT, Status.ACTIVE)

    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="bookings")
    member = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, related_name="bookings", verbose_name="medlem"
    )
    apartment = models.ForeignKey(
        Apartment, on_delete=models.PROTECT, related_name="bookings", verbose_name="lägenhet"
    )
    start = models.DateTimeField("start")
    end = models.DateTimeField("slut")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    hold_expires_at = models.DateTimeField(
        "betalas senast", null=True, blank=True,
        help_text="Obetalda bokningar avbryts vid den här tiden.",
    )
    reminder_sent_at = models.DateTimeField("påminnelse skickad", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        verbose_name = "bokning"
        verbose_name_plural = "bokningar"
        ordering = ["start"]
        indexes = [models.Index(fields=["resource", "start", "end"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end__gt=models.F("start")), name="booking_end_after_start"
            )
        ]

    def __str__(self):
        local = timezone.localtime(self.start)
        return f"{self.resource} {local:%Y-%m-%d %H:%M} ({self.apartment})"

    @property
    def duration_minutes(self):
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def nights(self):
        if self.resource.kind != Resource.Kind.OVERNIGHT:
            return 0
        return (timezone.localtime(self.end).date() - timezone.localtime(self.start).date()).days
