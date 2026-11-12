from django.shortcuts import redirect


class EspaceClientMiddleware:
    """Un client connecté ne voit que son espace, jamais les écrans du personnel (même en tapant l'adresse)."""

    AUTORISES = ("/espace-client/", "/comptes/deconnexion/", "/static/", "/reserver/", "/site/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (user is not None and user.is_authenticated and user.est_client and request.path != "/"
                and not request.path.startswith(self.AUTORISES)):
            return redirect("vitrine:espace")
        return self.get_response(request)
