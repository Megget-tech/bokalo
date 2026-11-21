from django.core.management.base import BaseCommand

from access.reconcile import reconcile


class Command(BaseCommand):
    help = "Stäm av dörrbehörigheter mot bokningarna en gång."

    def handle(self, *args, **opts):
        self.stdout.write(str(reconcile()))
