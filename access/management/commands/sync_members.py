from django.core.management.base import BaseCommand

from access.sync import sync_members


class Command(BaseCommand):
    help = "Importera/uppdatera medlemmar från passersystemet."

    def handle(self, *args, **opts):
        self.stdout.write(str(sync_members()))
