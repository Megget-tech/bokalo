# Brf-bokning

Bokning av föreningens gemensamma lokaler (bastu och övernattningsrum) med
automatisk dörrbehörighet i passersystemet Axema VAKA.

- Medlemmar loggar in med engångskod via e-post (eller lösenord) och bokar i mobilen.
- När man bokar får taggen behörighet till lokalens dörr under den bokade tiden.
- Styrelsen sköter lokaler, pass, regler och medlemmar i adminpanelen (`/admin/`).

## Status

| Del | Status |
|---|---|
| Bokning av fasta pass (bastu) och övernattning 12:00–11:59 | ✅ |
| Regler: max aktiva bokningar per lägenhet, hur långt fram, avbokningsgräns, max nätter | ✅ |
| Inloggning (kod via e-post / lösenord), ingen fri registrering | ✅ |
| Avstämning av dörrbehörigheter (idempotent, tål fel och omstarter) | ✅ mot fejkad VAKA |
| Medlemssynk från VAKA (nattlig) | ✅ mot fejkad VAKA |
| Axema VAKA-koppling (`access/providers/axema.py`) | ⏳ väntar på Axemas dokumentation |
| Avgifter, CSV-export till förvaltare, Stripe, e-postbekräftelser | ⏳ fas 2 |

## Kom igång lokalt

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py seed_demo          # två lokaler + tre demomedlemmar
python manage.py createsuperuser    # styrelsens adminkonto
python manage.py runserver
```

Öppna http://localhost:8000, välj "Skicka en inloggningskod" och använd
t.ex. `anna@example.se`. Koden skrivs ut i terminalen (ingen riktig e-post lokalt).

Kör avstämningen mot den fejkade VAKA:n och se behörigheterna i admin under
"Fejkade VAKA-behörigheter":

```bash
python manage.py reconcile_access
```

Tester:

```bash
pytest
```

## Hur det hänger ihop

```
booking/rules.py        Bokningsregler som ren logik (lätt att testa)
booking/services.py     Skapa/avboka bokningar under lås
booking/views.py        Medlemmarnas sidor
access/providers/       Gränssnittet mot passersystemet
  base.py               AccessProvider: list_users, grant, revoke, list_grants
  fake.py               Fejkad VAKA (utveckling/test)
  axema.py              Riktiga kopplingen (att bygga)
access/reconcile.py     Avstämning: bokningar → behörigheter i VAKA
access/sync.py          Medlemsimport från VAKA
access/management/commands/run_worker.py   Bakgrundsjobb (varje minut + nattlig synk)
```

**Avstämningen** räknar varje minut ut vilka behörigheter som borde finnas och
rättar skillnaden: lägger in saknade, tar bort avbokade och passerade, lägger in
igen sådant som tagits bort direkt i VAKA och tar bort okända behörigheter som
systemet skapat. Fel syns i admin under "Dörrbehörigheter".

Taggen fungerar en inställbar marginal före och efter bokningen (per lokal).
För övernattningsrummet är marginalen 0 så att två gäster aldrig har behörighet
samtidigt.

## Drift

En liten VPS (t.ex. Hetzner, ca 50–100 kr/mån) med Docker:

```bash
cp .env.example .env   # fyll i
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Caddy ordnar HTTPS automatiskt för domänen i `DOMAIN`. Säkerhetskopiera databasen
nattligen, t.ex. `docker compose exec db pg_dump -U bokning bokning > backup.sql`
via cron till extern lagring.

I PostgreSQL finns dessutom en databasregel som gör dubbelbokning omöjlig
(`booking/migrations/0002_no_overlap_constraint.py`).
