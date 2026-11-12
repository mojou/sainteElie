from django.shortcuts import redirect


class SecretProvisoireMiddleware:
    """Tant qu'un compte garde son mot de passe provisoire, la personne ne peut que choisir ses propres codes."""

    AUTORISES = ("/comptes/premiere-connexion/", "/comptes/deconnexion/", "/static/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (user is not None and user.is_authenticated and user.doit_changer_secret
                and not request.path.startswith(self.AUTORISES)):
            return redirect("accounts:premiere_connexion")
        return self.get_response(request)
