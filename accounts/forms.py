from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from . import securite
from .models import Role, User


class ConnexionForm(AuthenticationForm):
    username = forms.CharField(label="Identifiant", widget=forms.TextInput(attrs={"autofocus": True}),
                               help_text="Clients : votre numéro de téléphone.")
    password = forms.CharField(label="Mot de passe", strip=False, widget=forms.PasswordInput)

    def clean_username(self):
        """Un client tape son numéro comme il veut (« 699 11 22 33 », « +237… ») : on garde les chiffres."""
        from core.utils import normaliser_telephone

        identifiant = self.cleaned_data["username"].strip()
        if identifiant and all(c.isdigit() or c in " +.-" for c in identifiant):
            return normaliser_telephone(identifiant)
        return identifiant

    def clean(self):
        identifiant = self.cleaned_data.get("username")
        compte = User.objects.filter(username=identifiant).first() if identifiant else None
        fin = securite.bloque_jusqua(compte.connexion_bloquee_jusqua) if compte else None
        if fin:
            raise forms.ValidationError(
                f"Trop d'essais : ce compte est bloqué jusqu'à {timezone.localtime(fin):%H:%M}. Réessayez ensuite, "
                "ou demandez au gérant.")
        try:
            donnees = super().clean()
        except forms.ValidationError:
            if compte is not None:
                securite.echec_connexion(compte)
            raise
        if compte is not None:
            securite.reussite_connexion(compte)
        return donnees


class PinForm(forms.Form):
    pin = forms.CharField(label="Nouveau code PIN", min_length=4, max_length=6,
                          widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
                          help_text="4 à 6 chiffres. Il vous servira à signer les remises de caisse et les validations.")
    confirmation = forms.CharField(label="Confirmer le code", widget=forms.PasswordInput(attrs={"inputmode": "numeric"}))
    mot_de_passe = forms.CharField(label="Votre mot de passe", widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_pin(self):
        pin = self.cleaned_data["pin"]
        if not pin.isdigit():
            raise forms.ValidationError("Le code ne doit contenir que des chiffres.")
        if securite.pin_trop_simple(pin):
            raise forms.ValidationError("Code trop facile à deviner (1234, 0000…) : choisissez-en un autre.")
        return pin

    def clean(self):
        donnees = super().clean()
        if donnees.get("pin") and donnees.get("pin") != donnees.get("confirmation"):
            self.add_error("confirmation", "Les deux codes ne correspondent pas.")
        if donnees.get("mot_de_passe") and not self.user.check_password(donnees["mot_de_passe"]):
            self.add_error("mot_de_passe", "Mot de passe incorrect.")
        return donnees


class UtilisateurForm(forms.ModelForm):
    mot_de_passe = forms.CharField(label="Mot de passe", required=False, widget=forms.PasswordInput,
                                   help_text="Obligatoire à la création. Laisser vide pour ne pas le changer.")

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "telephone", "role", "is_active"]
        labels = {"username": "Identifiant", "first_name": "Prénom", "last_name": "Nom", "is_active": "Compte actif"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Les clients créent leur compte sur le site : ce formulaire ne sert qu'au personnel.
        self.fields["role"].choices = [c for c in self.fields["role"].choices if c[0] != Role.CLIENT]
        self.fields["mot_de_passe"].help_text = ("Mot de passe provisoire : la personne choisira le sien (et son code PIN) "
                                                 "à sa première connexion. Laisser vide pour ne pas le changer.")

    def clean_mot_de_passe(self):
        mdp = self.cleaned_data.get("mot_de_passe")
        if not self.instance.pk and not mdp:
            raise forms.ValidationError("Le mot de passe est obligatoire à la création.")
        if mdp:
            validate_password(mdp, self.instance)
        return mdp

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("mot_de_passe"):
            user.set_password(self.cleaned_data["mot_de_passe"])
            user.doit_changer_secret = True
        if commit:
            user.save()
        return user


def verifier_pin(user, pin):
    """Lève une erreur de formulaire claire si le PIN est absent ou faux."""
    if user is None:
        raise forms.ValidationError("Choisissez la personne qui signe.")
    if not user.a_un_pin:
        raise forms.ValidationError(f"{user} n'a pas encore défini de code PIN (menu « Mon compte »).")
    fin = securite.bloque_jusqua(user.pin_bloque_jusqua)
    if fin:
        raise forms.ValidationError(f"Code PIN de {user} bloqué jusqu'à {timezone.localtime(fin):%H:%M} "
                                    f"après {securite.ESSAIS_MAX} essais faux.")
    if not user.check_pin(pin):
        securite.echec_pin(user)
        raise forms.ValidationError(f"Code PIN incorrect pour {user}.")
    securite.reussite_pin(user)


class PremiereConnexionForm(forms.Form):
    """Première connexion avec un mot de passe provisoire : la personne choisit son mot de passe et son code PIN."""

    mot_de_passe = forms.CharField(label="Nouveau mot de passe", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                   help_text="8 caractères au moins, pas seulement des chiffres. Gardez-le pour vous.")
    confirmation = forms.CharField(label="Confirmer le mot de passe",
                                   widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    pin = forms.CharField(label="Nouveau code PIN", min_length=4, max_length=6,
                          widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
                          help_text="4 à 6 chiffres : votre signature pour les caisses et les validations.")
    pin_confirmation = forms.CharField(label="Confirmer le code PIN",
                                       widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_pin(self):
        pin = self.cleaned_data["pin"]
        if not pin.isdigit():
            raise forms.ValidationError("Le code ne doit contenir que des chiffres.")
        if securite.pin_trop_simple(pin):
            raise forms.ValidationError("Code trop facile à deviner (1234, 0000…) : choisissez-en un autre.")
        return pin

    def clean(self):
        d = super().clean()
        mot_de_passe = d.get("mot_de_passe")
        if mot_de_passe and mot_de_passe != d.get("confirmation"):
            self.add_error("confirmation", "Les deux mots de passe ne sont pas identiques.")
        elif mot_de_passe:
            if self.user.check_password(mot_de_passe):
                self.add_error("mot_de_passe", "Choisissez un mot de passe différent du mot de passe provisoire.")
            else:
                try:
                    validate_password(mot_de_passe, self.user)
                except forms.ValidationError as exc:
                    self.add_error("mot_de_passe", exc)
        if d.get("pin") and d.get("pin") != d.get("pin_confirmation"):
            self.add_error("pin_confirmation", "Les deux codes ne correspondent pas.")
        return d
