"""CSV-import av medlemmar (reserv om VAKA saknar e-postadresser).

Format (semikolon eller komma, rubrikrad krävs):
    lagenhet;namn;epost[;vaka_id]
"""

import csv
import io
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.core.validators import validate_email
from django.db import transaction

from .models import Apartment, Member


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)


HEADER_ALIASES = {
    "lagenhet": "apartment", "lägenhet": "apartment", "lgh": "apartment",
    "namn": "name", "epost": "email", "e-post": "email", "email": "email",
    "vaka_id": "vaka", "vaka-id": "vaka", "vaka": "vaka",
}


def import_members_csv(text: str) -> ImportResult:
    text = text.lstrip("﻿")
    dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=";,")
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    reader.fieldnames = [HEADER_ALIASES.get(h.strip().lower(), h) for h in reader.fieldnames or []]
    missing = {"apartment", "name", "email"} - set(reader.fieldnames)
    if missing:
        names = {"apartment": "lagenhet", "name": "namn", "email": "epost"}
        return ImportResult(errors=[f"Saknade kolumner: {', '.join(sorted(names[m] for m in missing))}"])

    User = get_user_model()
    result = ImportResult()
    with transaction.atomic():
        for lineno, row in enumerate(reader, start=2):
            apt = (row.get("apartment") or "").strip()
            name = (row.get("name") or "").strip()
            email = (row.get("email") or "").strip().lower()
            vaka = (row.get("vaka") or "").strip() or None
            try:
                validate_email(email)
            except Exception:
                result.errors.append(f"Rad {lineno}: ogiltig e-post '{email}'")
                continue
            if not apt or not name:
                result.errors.append(f"Rad {lineno}: lägenhet och namn krävs")
                continue
            if vaka and Member.objects.filter(vaka_user_ref=vaka).exclude(user__email__iexact=email).exists():
                result.errors.append(f"Rad {lineno}: VAKA-id {vaka} används redan av en annan medlem")
                continue
            apartment, _ = Apartment.objects.get_or_create(number=apt)
            member = Member.objects.filter(user__email__iexact=email).first()
            if member:
                member.apartment, member.name, member.active = apartment, name, True
                if vaka:
                    member.vaka_user_ref = vaka
                member.save()
                result.updated += 1
            else:
                user, _ = User.objects.get_or_create(username=email, defaults={"email": email})
                Member.objects.create(
                    user=user, apartment=apartment, name=name, vaka_user_ref=vaka,
                    source=Member.Source.MANUAL,
                )
                result.created += 1
    return result
