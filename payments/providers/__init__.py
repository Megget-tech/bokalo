from django.conf import settings
from django.utils.module_loading import import_string


def get_payment_provider():
    return import_string(settings.PAYMENT_PROVIDER)()
