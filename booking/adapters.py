from allauth.account.adapter import DefaultAccountAdapter


class MemberOnlyAccountAdapter(DefaultAccountAdapter):
    """Ingen fri registrering: konton skapas av medlemssynken eller av styrelsen."""

    def is_open_for_signup(self, request):
        return False
