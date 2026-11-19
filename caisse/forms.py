from functools import partial

from django import forms

from core.forms import (Formulaire, FormulaireModele, SelectAvecImages, champ_pin, champ_signataire, controler_signature, gerants)
from hotel.models import Client, Sejour
from stock.models import Article

from .models import (Encaissement, FondCaisse, RemiseCaisse, ParametreCaisse, SessionCaisse, Shift, SortieCaisse,
                     Tiroir, VenteComptoir, Virement)


def choix_moyens(carte_cheque=False):
    """Espèces, Orange Money, MTN MoMo — trois moyens simples, rien d'autre à saisir — puis carte et chèque."""
    choix = [(m, libelle) for m, libelle in Encaissement.Mode.choices if m in Encaissement.MODES_COMPTOIR]
    if carte_cheque:
        choix += [("CARTE", "Carte bancaire"), ("CHEQUE", "Chèque")]
    return choix


class MoyenPaiementForm(forms.Form):
    """Ajoute le champ « Payé en » et remplit `mode` dans cleaned_data."""

    carte_cheque = False
    ordre_champs = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["moyen"] = forms.ChoiceField(label="Payé en", choices=partial(choix_moyens, self.carte_cheque))
        self.order_fields(self.ordre_champs)
        if "reference" in self.fields:
            self.fields["reference"].help_text = "Carte ou chèque seulement : n° de transaction ou de chèque."

    def clean(self):
        d = super().clean()
        if d.get("moyen"):
            d["mode"] = d["moyen"]
        return d


BILLETAGE = [("b10000", 10000, "Billets de 10 000"), ("b5000", 5000, "Billets de 5 000"),
             ("b2000", 2000, "Billets de 2 000"), ("b1000", 1000, "Billets de 1 000"), ("b500", 500, "Billets de 500"),
             ("p500", 500, "Pièces de 500"), ("p100", 100, "Pièces de 100"), ("p50", 50, "Pièces de 50"),
             ("p25", 25, "Pièces de 25"), ("p10", 10, "Pièces de 10"), ("p5", 5, "Pièces de 5")]


class OuvertureForm(Formulaire):
    tiroir = forms.ModelChoiceField(label="Caisse", queryset=Tiroir.objects.filter(actif=True), empty_label=None)
    shift = forms.ChoiceField(label="Votre service", choices=Shift.choices)
    especes_comptees = forms.IntegerField(label="Argent compté dans la caisse (FCFA)", min_value=0,
                                          help_text="Billets et pièces, avant de commencer.")
    consignes_lues = forms.BooleanField(label="J'ai lu les messages de la personne d'avant", required=False)


class SortieForm(Formulaire):
    type = forms.ChoiceField(label="Pour quoi ?", choices=SortieCaisse.Type.choices)
    montant = forms.IntegerField(label="Montant (FCFA)", min_value=1)
    motif = forms.CharField(label="Ce qui a été acheté, ou pourquoi", max_length=300)
    justificatif = forms.FileField(label="Photo du reçu ou de la facture", required=False)
    gerant = champ_signataire("Gérant qui prend l'argent", gerants(), required=False)
    gerant_pin = champ_pin("Code PIN du gérant", required=False)

    def clean_justificatif(self):
        from core.images import valider_justificatif

        return valider_justificatif(self.cleaned_data.get("justificatif"))

    def clean(self):
        d = super().clean()
        d["_valideur"] = None
        if d.get("type") == SortieCaisse.Type.PRELEVEMENT:
            d["_valideur"] = controler_signature(self, "gerant", "gerant_pin")
        return d


class ChampMontants(forms.CharField):
    """Un ou plusieurs montants séparés par « + » : « 10000+5000 » → [10000, 5000] (espaces permis)."""

    def __init__(self, **kwargs):
        super().__init__(required=False, **kwargs)
        self.widget.attrs.update({"placeholder": "Ex. : 10000+5000", "autocomplete": "off", "maxlength": 300})

    def to_python(self, value):
        montants = []
        for terme in (super().to_python(value) or "").split("+"):
            terme = terme.replace(" ", "").replace("\u202f", "").replace("\xa0", "")
            if not terme:
                continue
            if not terme.isdigit():
                raise forms.ValidationError(f"« {terme} » n'est pas un montant : tapez des chiffres, avec + entre "
                                            "deux montants (ex. 10000+5000).")
            montants.append(int(terme))
        return montants


class ComptageForm(Formulaire):
    """Comptage à l'aveugle : aucun montant attendu n'est affiché sur ce formulaire."""

    especes = forms.IntegerField(label="Total des espèces comptées (FCFA)", min_value=0,
                                 help_text="Calculé tout seul si vous remplissez les billets et pièces ci-dessus.")
    cheques_nombre = forms.IntegerField(label="Nombre de chèques", min_value=0, initial=0)
    cheques_total = forms.IntegerField(label="Total des chèques (FCFA)", min_value=0, initial=0)
    orange_money = ChampMontants(label="Orange Money reçu (FCFA)")
    mtn_momo = ChampMontants(label="MTN MoMo reçu (FCFA)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.billets = []
        for cle, valeur, libelle in BILLETAGE:
            self.fields[cle] = forms.IntegerField(label=libelle, min_value=0, required=False)
            self.fields[cle].widget.attrs.update({"data-valeur": valeur, "inputmode": "numeric"})
            self.billets.append(self[cle])
        self.champs_mobiles = [self[champ] for _, _, champ in RemiseCaisse.MOBILES]

    def clean(self):
        d = super().clean()
        d["mobile"] = {cle: d.get(champ) or [] for cle, _, champ in RemiseCaisse.MOBILES}
        return d

    def billetage(self):
        return {cle: self.cleaned_data[cle] for cle, _, _ in BILLETAGE if self.cleaned_data.get(cle)}


class FinalisationForm(Formulaire):
    motif = forms.CharField(label="Expliquez la différence", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    entrant = champ_signataire("Personne qui prend la suite (si elle est là)", required=False)
    entrant_pin = champ_pin("Son code PIN", required=False)
    pin = champ_pin("Votre code PIN (signature)")
    consigne = forms.CharField(label="Message pour la personne suivante", required=False,
                               widget=forms.Textarea(attrs={"rows": 3}),
                               help_text="Ex. : « chambre 204 signale une fuite », « M. Kamga règle demain matin ».")

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        from accounts.models import Role, User

        self.fields["entrant"].queryset = User.objects.filter(
            is_active=True,
            role__in=[Role.RECEPTIONNISTE, Role.CHEF_RECEPTION, Role.BAR_RESTAURANT, Role.ADJOINT, Role.ADMIN]
        ).exclude(pk=user.pk)

    def clean(self):
        d = super().clean()
        from accounts.forms import verifier_pin

        try:
            verifier_pin(self.user, d.get("pin"))
        except forms.ValidationError as exc:
            self.add_error("pin", exc)
        d["_entrant"] = None
        if d.get("entrant"):
            d["_entrant"] = controler_signature(self, "entrant", "entrant_pin")
        return d


def _libelle_article(a):
    prix = f"{a.prix_vente:,}".replace(",", " ")
    stock = f" (stock {a.quantite})" if a.suivi_stock else ""
    rayon = (a.rubrique or "Plat") if a.categorie == Article.Categorie.RESTAURANT else a.get_categorie_display()
    return f"{rayon} · {a.nom} {a.code}".rstrip() + f" — {prix} FCFA{stock}"


class CommandeForm(Formulaire):
    """La caisse tactile : les articles touchés (champs q_<id> = quantité), puis une seule question,
    « Comment le client paie ? ». Un seul paiement, donc un seul reçu, pour toute la commande."""

    MODES = ("ESPECES", "ORANGE_MONEY", "MTN_MOMO")
    PAIEMENTS = [("ESPECES", "Espèces"), ("ORANGE_MONEY", "Orange Money"), ("MTN_MOMO", "MTN MoMo"),
                 ("CHAMBRE", "Sur sa chambre"), ("CREDIT", "À crédit"), ("OFFERT", "Offert")]
    QUANTITE_MAX = 999

    paiement = forms.ChoiceField(label="Comment le client paie ?", choices=PAIEMENTS,
                                 error_messages={"required": "Touchez comment le client paie."})
    sejour = forms.ModelChoiceField(label="Chambre du client", queryset=Sejour.objects.none(), required=False)
    client = forms.ModelChoiceField(label="Client qui a déjà un compte", queryset=Client.objects.all(), required=False)
    nouveau_client = forms.CharField(label="… ou nouveau client : son nom", max_length=120, required=False)
    telephone = forms.CharField(label="Téléphone du nouveau client", max_length=30, required=False)
    observation = forms.CharField(label="À qui et pourquoi c'est offert ?", max_length=200, required=False)

    def __init__(self, *args, articles=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.articles = articles if articles is not None else Article.objects.none()
        self.fields["sejour"].queryset = Sejour.objects.filter(statut=Sejour.Statut.EN_COURS).select_related(
            "chambre", "client").order_by("chambre__numero")
        self.fields["sejour"].label_from_instance = lambda s: f"Ch. {s.chambre.numero} - {s.client}"

    def quantites(self):
        """{id article: quantité} tel que tapé, pour remettre la commande à l'écran après une erreur."""
        resultat = {}
        for cle, valeur in (self.data or {}).items():
            if cle.startswith("q_") and cle[2:].isdigit() and str(valeur).isdigit() and int(valeur) > 0:
                resultat[int(cle[2:])] = min(int(valeur), self.QUANTITE_MAX)
        return resultat

    def clean(self):
        d = super().clean()
        for cle, valeur in self.data.items():
            if cle.startswith("q_") and not (cle[2:].isdigit() and str(valeur).isdigit()
                                              and int(valeur) <= self.QUANTITE_MAX):
                raise forms.ValidationError("Une quantité est illisible : videz la commande et recommencez.")
        quantites = self.quantites()
        articles = {a.pk: a for a in self.articles.filter(pk__in=quantites)}
        if set(quantites) - set(articles):
            raise forms.ValidationError("Un article n'est plus en vente à cette caisse : videz la commande et recommencez.")
        if not quantites:
            raise forms.ValidationError("La commande est vide : touchez au moins un article.")
        d["lignes"] = [(articles[pk], quantite) for pk, quantite in quantites.items()]
        paiement = d.get("paiement")
        d["mode"] = "ESPECES"
        if paiement in self.MODES:
            d["reglement"], d["mode"] = VenteComptoir.Reglement.COMPTANT, paiement
            d["sejour"] = d["client"] = None
        elif paiement == "CHAMBRE":
            d["reglement"], d["client"] = VenteComptoir.Reglement.CREDIT, None
            if not d.get("sejour"):
                self.add_error("sejour", "Touchez la chambre du client.")
        elif paiement == "CREDIT":
            d["reglement"], d["sejour"] = VenteComptoir.Reglement.CREDIT, None
            if not d.get("client"):
                if not d.get("nouveau_client"):
                    self.add_error("client", "Choisissez le client, ou écrivez le nom d'un nouveau client.")
                elif not d.get("telephone"):
                    self.add_error("telephone", "Le téléphone est obligatoire pour ouvrir un compte client.")
        elif paiement == "OFFERT":
            d["reglement"] = VenteComptoir.Reglement.OFFERT
            d["sejour"] = d["client"] = None
            if not d.get("observation", "").strip():
                self.add_error("observation", "Écrivez à qui c'est offert, et pourquoi.")
        return d


class AvarieForm(Formulaire):
    article = forms.ModelChoiceField(queryset=Article.objects.filter(actif=True, categorie__in=Article.VENDUS_AU_COMPTOIR))
    quantite = forms.IntegerField(label="Quantité", min_value=1)
    motif = forms.CharField(label="Motif (bouteille cassée, produit périmé…)", max_length=200)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["article"].label_from_instance = _libelle_article


class ReglementCreditForm(MoyenPaiementForm, Formulaire):
    ordre_champs = ["montant", "moyen"]
    montant = forms.IntegerField(label="Montant réglé (FCFA)", min_value=1)


class ValidationForm(Formulaire):
    imputation = forms.ChoiceField(label="Décision", choices=[("", "---")] + list(SessionCaisse.Imputation.choices),
                                   required=False)
    decision = forms.CharField(label="Explication de la décision", required=False,
                               widget=forms.Textarea(attrs={"rows": 3}))


class VirementForm(FormulaireModele):
    class Meta:
        model = Virement
        fields = ["sejour", "montant", "reference_bancaire", "date_valeur"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sejour"].queryset = Sejour.objects.exclude(
            statut__in=[Sejour.Statut.ANNULE, Sejour.Statut.NO_SHOW]).select_related("client", "chambre").order_by(
            "-date_arrivee")


class ParametreCaisseForm(FormulaireModele):
    class Meta:
        model = ParametreCaisse
        exclude = ["cree_par", "cree_le"]


class FondForm(FormulaireModele):
    class Meta:
        model = FondCaisse
        fields = ["tiroir", "montant", "date_effet"]


class TiroirForm(FormulaireModele):
    class Meta:
        model = Tiroir
        fields = ["nom", "poste", "actif"]


# --- Saisie après coup d'un jour passé (direction) : voir caisse/passe.py -------------------------------------------
def _titulaires():
    from accounts.models import Role, User

    return User.objects.filter(is_active=True, role__in=[Role.ADMIN, Role.ADJOINT, Role.CHEF_RECEPTION,
                                                         Role.RECEPTIONNISTE, Role.BAR_RESTAURANT]).order_by("first_name")


def _libelle_session(s):
    from django.utils import timezone

    return (f"{s.tiroir} · {s.receptionniste} ({s.get_shift_display().lower()}, "
            f"ouverte à {timezone.localtime(s.ouverte_le):%H:%M})")


def _libelle_sejour(s):
    return f"Ch. {s.chambre.numero} · {s.client} ({s.date_arrivee:%d/%m} → {s.date_depart:%d/%m})"


class CaissePasseeForm(Formulaire):
    tiroir = forms.ModelChoiceField(label="Caisse", queryset=Tiroir.objects.all())
    titulaire = forms.ModelChoiceField(label="Qui tenait la caisse", queryset=None)
    shift = forms.ChoiceField(label="Service", choices=Shift.choices)
    heure_ouverture = forms.TimeField(label="Heure d'ouverture")
    ouverture = forms.IntegerField(label="Montant d'ouverture (FCFA, espèces)", min_value=0)
    heure_fermeture = forms.TimeField(label="Heure de fermeture",
                                      help_text="Plus tôt que l'ouverture : la caisse a fermé le lendemain matin.")
    fermeture = forms.IntegerField(label="Montant de fermeture (FCFA, espèces comptées)", min_value=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["titulaire"].queryset = _titulaires()


class SejourPasseForm(Formulaire):
    nom = forms.CharField(label="Nom du client", max_length=120)
    telephone = forms.CharField(label="Téléphone", max_length=30)
    chambre = forms.ModelChoiceField(label="Chambre", queryset=None)
    date_arrivee = forms.DateField(label="Date d'arrivée")
    heure_arrivee = forms.TimeField(label="Heure d'arrivée")
    nuits = forms.IntegerField(label="Nombre de nuits", min_value=1, max_value=90, initial=1)
    heure_depart = forms.TimeField(label="Heure de départ", required=False,
                                   help_text="Obligatoire si le client est déjà parti.")
    tarif_nuit = forms.IntegerField(label="Prix de la nuit (FCFA)", min_value=0, required=False,
                                    help_text="Vide : le prix de la chambre.")
    motif_tarif = forms.CharField(label="Pourquoi un autre prix ?", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        from hotel.models import Chambre

        super().__init__(*args, **kwargs)
        self.fields["chambre"].queryset = Chambre.objects.filter(active=True).order_by("numero")
        self.fields["chambre"].label_from_instance = (
            lambda c: f"{c.numero} — {c.tarif_nuit:,} FCFA la nuit".replace(",", " "))


class PaiementPasseForm(MoyenPaiementForm, Formulaire):
    carte_cheque = True
    ordre_champs = ["sejour", "nature", "montant", "moyen", "reference", "session", "heure"]
    sejour = forms.ModelChoiceField(label="Client (chambre)", queryset=Sejour.objects.none())
    nature = forms.ChoiceField(label="C'est", choices=[("ACOMPTE", "Un acompte (avant ou pendant le séjour)"),
                                                     ("REGLEMENT", "Le règlement (au départ)")])
    montant = forms.IntegerField(label="Montant (FCFA)", min_value=1)
    reference = forms.CharField(label="Référence (carte, chèque)", required=False, max_length=80)
    session = forms.ModelChoiceField(label="Payé à la caisse de", queryset=SessionCaisse.objects.none())
    heure = forms.TimeField(label="Heure du paiement")

    def __init__(self, *args, sejours=None, sessions=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sejour"].queryset = sejours if sejours is not None else Sejour.objects.none()
        self.fields["sejour"].label_from_instance = _libelle_sejour
        self.fields["session"].queryset = sessions if sessions is not None else SessionCaisse.objects.none()
        self.fields["session"].label_from_instance = _libelle_session


class VentePasseeForm(Formulaire):
    session = forms.ModelChoiceField(label="Caisse", queryset=SessionCaisse.objects.none())
    article = forms.ModelChoiceField(label="Boisson ou plat", queryset=Article.objects.none())
    quantite = forms.IntegerField(label="Quantité", min_value=1, max_value=500, initial=1)
    paiement = forms.ChoiceField(label="Payé comment")
    sejour = forms.ModelChoiceField(label="Chambre (si « sur la chambre »)", queryset=Sejour.objects.none(),
                                    required=False)
    motif = forms.CharField(label="Pourquoi (si offert)", max_length=200, required=False)
    heure = forms.TimeField(label="Heure de la vente")

    def __init__(self, *args, sejours=None, sessions=None, **kwargs):
        from .passe import PAIEMENTS_VENTE

        super().__init__(*args, **kwargs)
        self.fields["paiement"].choices = PAIEMENTS_VENTE
        self.fields["session"].queryset = sessions if sessions is not None else SessionCaisse.objects.none()
        self.fields["session"].label_from_instance = _libelle_session
        self.fields["sejour"].queryset = sejours if sejours is not None else Sejour.objects.none()
        self.fields["sejour"].label_from_instance = _libelle_sejour
        self.fields["article"].queryset = Article.objects.filter(
            actif=True, categorie__in=[Article.Categorie.BAR, Article.Categorie.RESTAURANT]).order_by("categorie", "nom")
        self.fields["article"].label_from_instance = (
            lambda a: f"{a.nom}{' ' + a.code if a.code else ''} — {a.prix_vente:,} FCFA".replace(",", " "))
