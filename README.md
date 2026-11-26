# Brf-bokning

Bokning av föreningens gemensamma lokaler (bastu och övernattningsrum) med
automatisk dörrbehörighet i passersystemet Axema VAKA.

- Medlemmar loggar in med engångskod via e-post (eller lösenord) och bokar i mobilen.
- När man bokar får taggen behörighet till lokalens dörr under den bokade tiden.
- Styrelsen sköter lokaler, pass, regler och medlemmar i adminpanelen (`/admin/`).

## Funktioner

- **Bastu (flexibel tid):** styrelsen ställer in öppettider, kortaste och längsta
  bokning samt intervall (t.ex. 1–3 h i steg om 30 min). Pris per timme.
- **Övernattningsrum:** bokas per dygn (12:00–11:59), med ställbart max antal dygn. Pris per dygn.
- **Månadskalender:** medlemmen ser först en månadskalender (ledigt / delvis bokat /
  egen bokning / fullt). Ett klick på en dag visar lediga starttider och längder.
- **Betalning före tillträde (Stripe):** bokningen hålls tills betalning sker, senast
  60 minuter före start. Betallänk skickas i bekräftelsemejlet. Obetalda bokningar
  avbryts automatiskt vid gränsen. Behörigheten i passersystemet läggs in först
  efter betalning.
- **Påminnelse med tillträdeskod** 60 minuter före start (kod från passersystemet;
  om VAKA inte ger någon kod står det att taggen är aktiverad).
- Alternativt betalsätt: avgiftsavi med CSV-export till förvaltaren, eller ingen avgift.
- Inloggning med engångskod via e-post (eller lösenord). Ingen fri registrering.
- Avstämning mot passersystemet varje minut, medlemssynk varje natt, larm till styrelsen vid fel.

| Del | Status |
|---|---|
| Allt ovan | ✅ testat mot fejkad VAKA och fejkad betaltjänst |
| Stripe | ✅ signaturkontroll och anrop testade utan nätverk, ej mot riktigt konto |
| Axema VAKA-koppling (`access/providers/axema.py`) | ⏳ väntar på Axemas dokumentation |

Tider som kan ändras via miljövariabler: `PAYMENT_DEADLINE_MINUTES` (60),
`PAYMENT_MIN_TIME_TO_PAY_MINUTES` (15) och `REMINDER_MINUTES_BEFORE` (60).

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

## Avgifter och betalning

Per lokal väljs betalsätt i admin:

- **Ingen avgift**
- **Avgiftsavi**: bokningen gäller direkt. Styrelsen markerar avgifterna i admin
  (filter "Ej exporterad"), väljer åtgärden "Exportera till avgiftsavi" och skickar
  CSV-filen till förvaltaren. Avbokning före gränsen makulerar avgiften.
- **Betalning online**: bokningen hålls i 30 minuter medan medlemmen betalar via
  Stripe. Obetalda reservationer släpps automatiskt. Betalningar som kommer in
  för sent återaktiverar bokningen om tiden är ledig, annars återbetalas de.
  Avbokning före gränsen återbetalar automatiskt.

Lokalt används en fejkad betalsida. Stripe i drift:

1. Skapa ett Stripe-konto för föreningen och hämta den hemliga nyckeln.
2. Lägg till en webhook till `https://<domän>/betalning/webhook/` med händelserna
   `checkout.session.completed` och `checkout.session.expired`.
3. Sätt `PAYMENT_PROVIDER`, `STRIPE_SECRET_KEY` och `STRIPE_WEBHOOK_SECRET` i `.env`.

Testa först med Stripes testnycklar och `stripe listen --forward-to localhost:8000/betalning/webhook/`.

Fler betaltjänster (t.ex. Swish Handel) läggs till som en ny klass i
`payments/providers/` utan att bokningslogiken behöver ändras.

## Drift på Railway (rekommenderat)

`railway.json` och `Dockerfile` beskriver bygget. Allt körs i en tjänst via
`bin/start.sh`: databasmigrering, bakgrundsworkern och webbservern (en process med
trådar för att hålla nere minnet).

1. Skapa ett projekt på railway.com och välj **Deploy from GitHub repo** → `bokalo`.
2. Lägg till en databas: **+ New → Database → PostgreSQL**.
3. På webbtjänsten, under **Variables**, lägg till:
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
   - `DJANGO_SECRET_KEY` = en lång slumpsträng
   - `DJANGO_DEBUG` = `false`
   - `SITE_NAME` = t.ex. `Brf Solgläntan – bokning`
4. Under **Settings → Networking**, välj **Generate Domain** (eller lägg till egen
   domän, t.ex. `bokning.brfnamn.se`, och peka DNS hos Simply enligt Railways instruktion).
   Med egen domän: sätt även `DJANGO_ALLOWED_HOSTS` och `DJANGO_CSRF_TRUSTED_ORIGINS`
   (`https://bokning.brfnamn.se`) och `SITE_URL` (`https://bokning.brfnamn.se`).
5. Välj region i EU (t.ex. Amsterdam) under **Settings → Region**.
6. När tjänsten är uppe: kör `python manage.py createsuperuser` via
   **railway ssh** (eller Railway CLI) och logga in på `/admin/`.
7. Sätt en **utgiftsgräns** under Workspace → Usage.

För test går det bra att låta e-postvariablerna vara tomma: då skrivs mejlen
(även inloggningskoder) till loggen under **Deployments → Logs**.

## Drift på egen VPS (alternativ)

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
