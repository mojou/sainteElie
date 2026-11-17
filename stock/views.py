from datetime import date, timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from core.forms import Formulaire, FormulaireModele
from core.permissions import acces_requis, stock
from core.utils import aujourd_hui, journaliser

from . import recit, services
from .models import Article, MouvementStock


class ArticleForm(FormulaireModele):
    class Meta:
        model = Article
        fields = ["nom", "code", "categorie", "rubrique", "description", "ordre", "unite", "seuil_alerte", "prix_achat",
                  "prix_vente", "suivi_stock", "photo", "actif"]
        labels = {"prix_achat": "Prix d'achat unitaire (coût moyen, FCFA)"}

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "content_type"):  # nouvelle photo envoyée
            from core.images import photo_allegee

            return photo_allegee(photo, nom="article", taille=900)
        return photo


class MouvementForm(Formulaire):
    type = forms.ChoiceField(choices=[c for c in MouvementStock.Type.choices if c[0] not in ("VENTE", "RETOUR")],
                             help_text="Les ventes se saisissent dans la main courante (Vente bar / boutique).")
    quantite = forms.IntegerField(label="Quantité", min_value=0,
                                  help_text="Entrée ou sortie : la quantité qui bouge. Inventaire : la quantité comptée.")
    cout_unitaire = forms.IntegerField(label="Coût unitaire (FCFA, pour une entrée)", min_value=0, required=False)
    motif = forms.CharField(max_length=200, required=False)
    journee = forms.DateField(label="Journée de la fiche", initial=aujourd_hui,
                              help_text="Jour de la fiche de stock où le mouvement apparaît.")


FILTRES_ETAT = [("", "Tous"), ("commander", "À commander"), ("rupture", "En rupture"), ("dort", "Ne se vendent pas")]


@acces_requis(stock)
def articles(request):
    """Le stock en mots : chaque article dit s'il faut le commander, combien de jours de vente il reste, s'il dort."""
    categorie = request.GET.get("categorie", "")
    q = request.GET.get("q", "").strip()
    filtre = request.GET.get("etat", "")
    qs = Article.objects.filter(actif=True)
    if categorie:
        qs = qs.filter(categorie=categorie)
    if q:
        qs = qs.filter(Q(nom__icontains=q) | Q(code__icontains=q))
    liste = list(qs)
    vites, dernieres, premiers = recit.vitesses(liste)
    for a in liste:
        a.vitesse = vites.get(a.pk, 0)
        a.etat = recit.etat(a, a.vitesse, dernieres.get(a.pk), premiers.get(a.pk))
    compte = {
        "rupture": sum(1 for a in liste if a.etat["code"] == "danger"),
        "commander": sum(1 for a in liste if a.etat["code"] in ("danger", "alerte")),
        "dort": sum(1 for a in liste if a.etat["code"] == "dort"),
    }
    valeur_dort = sum(a.valeur for a in liste if a.etat["code"] == "dort")
    if filtre == "commander":
        liste = [a for a in liste if a.etat["code"] in ("danger", "alerte")]
    elif filtre == "rupture":
        liste = [a for a in liste if a.etat["code"] == "danger"]
    elif filtre == "dort":
        liste = [a for a in liste if a.etat["code"] == "dort"]
    if request.GET.get("bas"):  # ancien lien « stock bas »
        liste = [a for a in liste if a.est_bas]
    return render(request, "stock/articles.html", {
        "articles": liste, "categories": Article.Categorie.choices, "categorie": categorie, "q": q, "filtre": filtre,
        "filtres": FILTRES_ETAT, "compte": compte, "valeur_dort": valeur_dort,
        "valeur_totale": sum(a.valeur for a in Article.objects.filter(actif=True)),
        "sans_cout": Article.objects.filter(actif=True, suivi_stock=True, prix_achat=0).count(),
    })


@acces_requis(stock)
def article_form(request, pk=None):
    article = get_object_or_404(Article, pk=pk) if pk else None
    form = ArticleForm(request.POST or None, request.FILES or None, instance=article)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if "photo" in form.changed_data:
            obj.oublier_credit()
        obj.save()
        journaliser(request.user, "Article modifié" if article else "Article créé", obj)
        messages.success(request, f"{obj} enregistré.")
        return redirect("stock:article", pk=obj.pk)
    return render(request, "form_page.html", {"form": form, "titre": f"Modifier {article}" if article else "Nouvel article",
                                              "retour": "stock:articles"})


@acces_requis(stock)
def photos(request):
    """Photographier les produits un par un : on touche « Prendre la photo », le téléphone ouvre l'appareil photo,
    la photo remplace le dessin partout (caisse, stock, page d'accueil)."""
    if request.method == "POST":
        article = get_object_or_404(Article, pk=request.POST.get("article"))
        fichier = request.FILES.get("photo")
        if request.POST.get("action") == "retirer":
            article.photo = ""
            article.oublier_credit()
            article.save(update_fields=["photo", "photo_credit", "photo_source", "photo_licence_url"])
            journaliser(request.user, "Photo d'article retirée", article)
            messages.success(request, f"Photo de {article} retirée : le dessin revient.")
        elif fichier:
            from core.images import photo_allegee

            try:
                article.photo = photo_allegee(fichier, nom="article", taille=900)
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                article.oublier_credit()
                article.save(update_fields=["photo", "photo_credit", "photo_source", "photo_licence_url"])
                journaliser(request.user, "Photo d'article ajoutée", article)
                messages.success(request, f"Photo de {article} enregistrée.")
        return redirect(f"{request.path}?categorie={request.POST.get('categorie', '')}#article-{article.pk}")
    categorie = request.GET.get("categorie", "")
    qs = Article.objects.filter(actif=True).exclude(categorie=Article.Categorie.MAGASIN)
    if categorie:
        qs = qs.filter(categorie=categorie)
    articles = list(qs.order_by("categorie", "ordre", "nom"))
    return render(request, "stock/photos.html", {
        "articles": articles, "categorie": categorie, "sans_photo": sum(1 for a in articles if not a.photo),
        "categories": [c for c in Article.Categorie.choices if c[0] != Article.Categorie.MAGASIN],
    })


@acces_requis(stock)
def article_detail(request, pk):
    article = get_object_or_404(Article, pk=pk)
    form = MouvementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            m = services.enregistrer_mouvement(article, request.user, d["type"], d["quantite"], d.get("motif", ""),
                                               d.get("cout_unitaire") or 0, journee=d["journee"])
            messages.success(request, recit.raconter(m)["titre"] + ".")
            return redirect("stock:article", pk=article.pk)
        except ValidationError as exc:
            form.add_error(None, exc.messages[0])
    vites, dernieres, premiers = recit.vitesses([article])
    article.vitesse = vites.get(article.pk, 0)
    etat = recit.etat(article, article.vitesse, dernieres.get(article.pk), premiers.get(article.pk))
    depuis = aujourd_hui() - timedelta(days=recit.JOURS_OBSERVES - 1)
    recents = article.mouvements.filter(journee__gte=depuis)

    def total(type_):
        return abs(recents.filter(type=type_).aggregate(s=Sum("quantite"))["s"] or 0)

    resume = {"recu": total(MouvementStock.Type.ENTREE), "vendu": total(MouvementStock.Type.VENTE)
              - total(MouvementStock.Type.RETOUR), "perdu": total(MouvementStock.Type.AVARIE),
              "sorti": total(MouvementStock.Type.SORTIE),
              # le premier comptage (stock de départ à zéro) n'est pas un écart
              "ecart": recents.filter(type=MouvementStock.Type.INVENTAIRE).exclude(quantite=F("quantite_apres"))
              .aggregate(s=Sum("quantite"))["s"] or 0}
    historique = recit.raconter_tous(article.mouvements.select_related("saisi_par", "article")[:120])
    return render(request, "stock/article_detail.html", {
        "article": article, "form": form, "etat": etat, "resume": resume, "jours": recit.JOURS_OBSERVES,
        "courbe": _courbe_stock(article, depuis), "groupes": _par_jour(historique),
    })


def _courbe_stock(article, depuis):
    """Le stock en fin de chaque jour, sur 30 jours (le dernier chiffre connu se reporte sur les jours sans mouvement)."""
    from rapports.services import JOURS_COURTS, MOIS, graduations

    jours = [depuis + timedelta(days=i) for i in range(recit.JOURS_OBSERVES)]
    # Stock en fin de journée = stock d'aujourd'hui − ce qui a bougé les jours suivants (sans dépendre de l'heure).
    par_jour = dict(article.mouvements.filter(journee__gte=depuis).values("journee").annotate(s=Sum("quantite"))
                    .values_list("journee", "s"))
    premier = article.mouvements.order_by("journee").values_list("journee", flat=True).first()
    points, niveau = [], article.quantite
    for jour in reversed(jours):
        connu = premier is not None and jour >= premier
        points.append((jour, max(niveau, 0) if connu else None))
        niveau -= par_jour.get(jour, 0)
    points.reverse()
    haut, reperes = graduations(max([v or 0 for _, v in points] + [article.seuil_alerte, 1]))
    return {
        "colonnes": [{"titre": f"{JOURS_COURTS[j.weekday()].capitalize()} {j.day} {MOIS[j.month - 1]}"
                      + ("" if v is not None else " : pas encore suivi"), "valeur": v or 0, "connu": v is not None,
                      "hauteur": round(100 * (v or 0) / haut, 2), "court": str(j.day), "etiquette": i % 5 == 0}
                     for i, (j, v) in enumerate(points)],
        "reperes": [{"texte": str(r), "position": round(100 * r / haut, 2)} for r in reperes],
        "seuil": round(100 * article.seuil_alerte / haut, 2) if article.seuil_alerte else None,
    }


def _par_jour(mouvements):
    from rapports.services import JOURS_COURTS, MOIS

    groupes = []
    for m in mouvements:
        if not groupes or groupes[-1]["jour"] != m.journee:
            j = m.journee
            groupes.append({"jour": j, "titre": f"{JOURS_COURTS[j.weekday()].rstrip('.').capitalize()} {j.day} "
                                                f"{MOIS[j.month - 1]} {j.year}", "mouvements": []})
        groupes[-1]["mouvements"].append(m)
    for g in groupes:
        types = {}
        for m in g["mouvements"]:
            types[m.get_type_display()] = types.get(m.get_type_display(), 0) + 1
        g["resume"] = types
    return groupes


@acces_requis(stock)
def saisie_groupee(request):
    """Inventaire ou approvisionnement de toute une catégorie sur une seule page."""
    categorie = request.POST.get("categorie") or request.GET.get("categorie") or Article.Categorie.BAR
    type_ = request.POST.get("type") or request.GET.get("type") or MouvementStock.Type.INVENTAIRE
    if type_ not in (MouvementStock.Type.INVENTAIRE, MouvementStock.Type.ENTREE):
        type_ = MouvementStock.Type.INVENTAIRE
    articles = Article.objects.filter(actif=True, categorie=categorie).order_by("ordre", "nom")
    try:
        journee = date.fromisoformat(request.POST.get("journee") or request.GET.get("journee") or "")
    except ValueError:
        journee = aujourd_hui()
    erreurs = []
    if request.method == "POST":
        motif = request.POST.get("motif", "").strip() or ("Inventaire" if type_ == "INVENTAIRE" else "Livraison")
        cout = {}
        n = 0
        for a in articles:
            brut = request.POST.get(f"q_{a.pk}", "").strip()
            if not brut:
                continue
            try:
                quantite = int(brut)
                if type_ == MouvementStock.Type.INVENTAIRE and quantite == a.quantite:
                    continue
                if type_ == MouvementStock.Type.ENTREE and quantite == 0:
                    continue
                cout[a.pk] = int(request.POST.get(f"c_{a.pk}", "").strip() or 0)
                if cout[a.pk] < 0:
                    raise ValueError("prix d'achat négatif")
                services.enregistrer_mouvement(a, request.user, type_, quantite, motif, journee=journee,
                                               cout_unitaire=cout[a.pk] if type_ == MouvementStock.Type.ENTREE else 0)
                n += 1
            except (ValueError, ValidationError) as exc:
                erreurs.append(f"{a} : {getattr(exc, 'messages', [str(exc)])[0]}")
        if n:
            messages.success(request, f"{n} article(s) mis à jour.")
        if not erreurs:
            return redirect(f"{request.path}?categorie={categorie}&type={type_}&journee={journee.isoformat()}")
    return render(request, "stock/saisie_groupee.html", {
        "articles": articles, "categorie": categorie, "type": type_, "journee": journee, "erreurs": erreurs,
        "categories": Article.Categorie.choices,
    })


@acces_requis(stock)
def mouvements(request):
    """Tous les mouvements, racontés : qui a reçu, vendu, cassé, compté quoi, et quand. Par période, par type."""
    def _d(cle):
        try:
            return date.fromisoformat(request.GET.get(cle, ""))
        except ValueError:
            return None

    au = _d("au") or aujourd_hui()
    du = _d("du") or au - timedelta(days=6)
    if du > au:
        du, au = au, du
    type_ = request.GET.get("type", "")
    categorie = request.GET.get("categorie", "")
    q = request.GET.get("q", "").strip()
    qs = MouvementStock.objects.filter(journee__gte=du, journee__lte=au).select_related("article", "saisi_par")
    if type_ in MouvementStock.Type.values:
        qs = qs.filter(type=type_)
    if categorie:
        qs = qs.filter(article__categorie=categorie)
    if q:
        qs = qs.filter(Q(article__nom__icontains=q) | Q(motif__icontains=q))
    resume = []
    for v, l in MouvementStock.Type.choices:
        sous = qs.filter(type=v)
        n = sous.count()
        if n:
            resume.append({"type": v, "libelle": l, "nombre": n, "quantite": abs(sous.aggregate(s=Sum("quantite"))["s"] or 0)})
    liste = recit.raconter_tous(qs.order_by("-journee", "-date", "-id")[:500])
    if request.GET.get("format") == "csv":
        return _csv_mouvements(liste, du, au)
    return render(request, "stock/mouvements.html", {
        "groupes": _par_jour(liste), "resume": resume, "du": du, "au": au, "type": type_, "categorie": categorie, "q": q,
        "types": MouvementStock.Type.choices, "categories": Article.Categorie.choices, "total": qs.count(),
        "tronque": qs.count() > 500,
    })


def _csv_mouvements(liste, du, au):
    import csv

    from django.http import HttpResponse

    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    reponse["Content-Disposition"] = f'attachment; filename="mouvements-{du}-{au}.csv"'
    reponse.write("\ufeff")
    ecrivain = csv.writer(reponse, delimiter=";")
    ecrivain.writerow(["Journée", "Heure", "Article", "Ce qui s'est passé", "Détail", "Variation", "Stock après", "Par"])
    for m in liste:
        ecrivain.writerow([m.journee.strftime("%d/%m/%Y"), m.date.astimezone().strftime("%H:%M"), str(m.article),
                           m.recit["titre"], m.recit["detail"], m.quantite, m.quantite_apres, str(m.saisi_par)])
    return reponse


@acces_requis(stock)
def ecarts(request):
    """Écarts d'inventaire du mois : ce qui manque au comptage, chiffré. Au bar, c'est le premier signe de pertes."""
    from core.utils import mois_suivant, premier_du_mois

    try:
        mois = date.fromisoformat(request.GET.get("mois", "") + "-01") if request.GET.get("mois") else premier_du_mois()
    except ValueError:
        mois = premier_du_mois()
    fin = mois_suivant(mois) - timedelta(days=1)
    return render(request, "stock/ecarts.html", {
        "d": services.ecarts_inventaire(mois, fin), "mois": mois,
        "precedent": (mois - timedelta(days=1)).strftime("%Y-%m"), "suivant": mois_suivant(mois).strftime("%Y-%m")})
