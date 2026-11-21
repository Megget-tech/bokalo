from django.db import models


class AccessGrant(models.Model):
    """Vår bild av en dörrbehörighet som skapats i passersystemet för en bokning."""

    class State(models.TextChoices):
        GRANTED = "granted", "Aktiv i passersystemet"
        REVOKED = "revoked", "Borttagen"
        FAILED = "failed", "Misslyckades"

    booking = models.OneToOneField(
        "booking.Booking", on_delete=models.CASCADE, related_name="access_grant"
    )
    provider_ref = models.CharField(max_length=200, blank=True)
    state = models.CharField(max_length=10, choices=State.choices)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "dörrbehörighet"
        verbose_name_plural = "dörrbehörigheter"

    def __str__(self):
        return f"{self.booking} – {self.get_state_display()}"


# --- Endast för den fejkade leverantören (utveckling, test, demo) ----------------


class FakeVakaUser(models.Model):
    """Simulerar personer i VAKA tills den riktiga kopplingen finns."""

    ref = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    apartment = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = "fejkad VAKA-person"
        verbose_name_plural = "fejkade VAKA-personer"

    def __str__(self):
        return f"{self.name} ({self.ref})"


class FakeDoorGrant(models.Model):
    """Simulerar behörigheter som ligger i VAKA."""

    user_ref = models.CharField(max_length=100)
    door_ref = models.CharField(max_length=100)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "fejkad VAKA-behörighet"
        verbose_name_plural = "fejkade VAKA-behörigheter"

    def __str__(self):
        return f"{self.user_ref} → {self.door_ref} {self.valid_from:%Y-%m-%d %H:%M}–{self.valid_to:%H:%M}"
