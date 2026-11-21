from django.conf import settings


def site(request):
    member = getattr(request.user, "member", None) if request.user.is_authenticated else None
    return {"SITE_NAME": settings.SITE_NAME, "current_member": member}
