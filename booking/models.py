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
        SLOTS = "slots", "Fasta pass (t.ex. bastu)"
        OVERNIGHT = "overnight", "Övernattning (12:00–11:59)"

    class PaymentMethod(models.TextChoices):
        NONE = "none", "Ingen avgift"
        INVOICE = "invoice", "Avgiftsavi (export till förvaltare)"
        ONLINE = "online", "Betalning online"

    name = models.CharField("namn", max_length=100)
    slug = models.SlugField(unique=True)
    kind = models.CharField("typ", max_length=10, choices=Kind.choices)
    door_ref = models.CharField(
        "dörr i passersystemet",
        max_length=100,
        blank=True,
        help_text="Dörrens/områdets id i VAKA.",
    )
    max_active_bookings = models.PositiveSmallIntegerField(
        "max aktiva bokningar per lägenhet", default=2
    )
    max_days_ahead = models.PositiveSmallIntegerField("får bokas antal dagar framåt", default=30)
    cancel_hours_before = models.PositiveSmallIntegerField(
        "avbokning senast (timmar före start)", default=24
    )
    max_nights = models.PositiveSmallIntegerField(
        "max nätter per bokning", default=3, help_text="Gäller bara övernattning."
    )
    price_per_night = models.DecimalField(
        "pris (kr)",
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text="Per natt för övernattning, per pass för fasta pass.",
    )
    payment_method = models.CharField(
        "betalning", max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.NONE
    )
    access_lead_minutes = models.PositiveSmallIntegerField(
        "taggen fungerar minuter före start", default=10
    )
    access_grace_minutes = models.PositiveSmallIntegerField(
        "taggen fungerar minuter efter slut", default=10
    )
    rules_text = models.TextField("ordningsregler", blank=True)
    active = models.BooleanField("aktiv", default=True)

    class Meta:
        verbose_name = "lokal"
        verbose_name_plural = "lokaler"
        ordering = ["name"]

    def __str__(self):
        return self.name


class SlotTemplate(models.Model):
    WEEKDAYS = [
        (0, "Måndag"),
        (1, "Tisdag"),
        (2, "Onsdag"),
        (3, "Torsdag"),
        (4, "Fredag"),
        (5, "Lördag"),
        (6, "Söndag"),
    ]

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="slot_templates")
    weekday = models.PositiveSmallIntegerField("veckodag", choices=WEEKDAYS)
    start_time = models.TimeField("start")
    end_time = models.TimeField("slut")

    class Meta:
        verbose_name = "pass"
        verbose_name_plural = "pass"
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="slot_end_after_start",
            )
        ]

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}"


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
    hold_expires_at = models.DateTimeField(null=True, blank=True)
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
    def nights(self):
        if self.resource.kind != Resource.Kind.OVERNIGHT:
            return 0
        return (timezone.localtime(self.end).date() - timezone.localtime(self.start).date()).days
