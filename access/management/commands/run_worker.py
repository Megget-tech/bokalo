"""Bakgrundsworker: släpper obetalda reservationer, stämmer av dörrbehörigheter
varje minut och synkar medlemmar en gång per natt."""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from access.reconcile import reconcile
from access.sync import sync_members
from booking.services import release_expired_holds

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Kör bakgrundsjobben i en evig loop."

    def handle(self, *args, **opts):
        last_sync_date = None
        log.info("Worker startad (intervall %ss)", settings.WORKER_INTERVAL_SECONDS)
        while True:
            close_old_connections()
            try:
                released = release_expired_holds()
                if released:
                    log.info("Släppte %s obetalda reservationer", released)
                result = reconcile()
                if result.granted or result.revoked or result.errors:
                    log.info("Avstämning: %s", result)
                now = timezone.localtime()
                if now.hour == settings.MEMBER_SYNC_HOUR and last_sync_date != now.date():
                    sync_members()
                    last_sync_date = now.date()
            except Exception:  # workern får aldrig dö; felet loggas och vi försöker igen
                log.exception("Fel i worker-loopen")
            time.sleep(settings.WORKER_INTERVAL_SECONDS)
