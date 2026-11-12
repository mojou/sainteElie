from django.utils import timezone

from core.pdf import DocumentPDF, montant_pdf


def _date(dt):
    return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M") if dt else "-"


def recu_remise_pdf(session):
    remise = session.remise
    moyens = [m for m in session.totaux_par_moyen() if m["montant"] or m["cle"] not in ("CARTE", "CHEQUE")]
    doc = DocumentPDF(f"Reçu de remise de caisse - session n°{session.pk}",
                      f"{session.receptionniste} - shift {session.get_shift_display()} - tiroir {session.tiroir}")
    doc.cles_valeurs([
        ("Caisse", f"{session.tiroir} ({session.tiroir.get_poste_display()})"),
        ("Sortant", str(session.receptionniste)),
        ("Entrant", str(remise.entrant) if remise.entrant else "Aucun (remise au chef ou au gérant)"),
        ("Compté par", str(remise.compte_par) + (" (clôture d'office)" if session.cloture_office else "")),
        ("Ouverture", _date(session.ouverte_le)),
        ("Remise", _date(session.remise_le)),
        ("Espèces d'ouverture (prévues / comptées)",
         f"{montant_pdf(session.especes_ouverture_prevues)} / {montant_pdf(session.especes_ouverture_comptees)}"),
    ])
    doc.section("Encaissements du shift (ce n'est pas la recette)")
    doc.tableau(["Payé en", "Montant"], [[m["libelle"], montant_pdf(m["montant"])] for m in moyens],
                total=["Total encaissé", montant_pdf(session.total_encaisse)])
    sorties = list(session.sorties.all())
    if sorties:
        doc.section("Sorties de caisse")
        doc.tableau(["Type", "Motif", "Statut", "Montant"],
                    [[s.get_type_display(), s.motif, s.get_statut_display(), montant_pdf(s.montant)] for s in sorties])
    doc.section("Comptage de fin de shift")
    doc.cles_valeurs([
        ("Espèces attendues", montant_pdf(remise.especes_attendues)),
        ("Espèces comptées", montant_pdf(remise.especes_comptees)
         + (f" (premier comptage : {montant_pdf(remise.premier_comptage)})" if remise.recompte_fait else "")),
        ("Écart espèces", montant_pdf(remise.ecart)),
        ("Chèques (attendus / comptés)",
         f"{montant_pdf(remise.cheques_attendus_total)} / {montant_pdf(remise.cheques_total)} "
         f"({remise.cheques_nombre} chèque(s))"),
        *[(f"{m['libelle']} (attendu / déclaré)",
           f"{montant_pdf(m['attendu'])} / {montant_pdf(m['declare'])} (écart {montant_pdf(m['ecart'])})")
          for m in remise.lignes_mobile()],
        ("Versement au gérant ou au coffre", montant_pdf(remise.versement)),
        ("Espèces laissées dans le tiroir", montant_pdf(remise.especes_transmises)),
    ])
    doc.section("Motif")
    doc.paragraphe(remise.motif or "Aucun écart au-delà du seuil de " + montant_pdf(session.seuil_ecart) + ".")
    doc.signatures(["Sortant", "Entrant", "Chef de réception / gérant"],
                   titre="Signatures")
    doc.paragraphe(f"Signature électronique du sortant ({remise.compte_par}) : {_date(remise.signe_sortant_le)}. "
                   + (f"Signature électronique de l'entrant ({remise.entrant}) : {_date(remise.signe_entrant_le)}."
                      if remise.entrant else ""), petit=True)
    return doc.rendre()


def rapport_pdf(rapport):
    from .services import donnees_rapport

    d = donnees_rapport(rapport)
    doc = DocumentPDF(f"Rapport quotidien de caisse - {timezone.localtime(rapport.coupure):%d/%m/%Y}",
                      f"Sessions remises du {_date(rapport.debut)} au {_date(rapport.coupure)}", paysage=True)
    doc.section("Encaissements par caisse et par personne")
    lignes = []
    for ligne in d["lignes"]:
        s = ligne["session"]
        nom = f"{s.receptionniste}" + (" (rectification)" if s.est_rectificative else "")
        lignes.append([nom, f"{s.tiroir} · {s.get_shift_display()} {timezone.localtime(s.ouverte_le):%d/%m}"]
                      + [montant_pdf(v) for v in ligne["moyens"]]
                      + [montant_pdf(ligne["total"]), montant_pdf(ligne["sorties"]), montant_pdf(ligne["attendues"]),
                         montant_pdf(ligne["ecart"]), montant_pdf(ligne["ecart_mobile"]), s.get_statut_display()])
    t = d["totaux"]
    doc.tableau(["Titulaire", "Caisse · shift"] + [m["libelle"] for m in d["moyens"]]
                + ["Total encaissé", "Sorties", "Espèces attendues", "Écart espèces", "Écart OM + MoMo", "Statut"], lignes,
                total=["Total", ""] + [montant_pdf(v) for v in t["moyens"]]
                + [montant_pdf(t["total"]), montant_pdf(t["sorties"]), "", montant_pdf(t["ecart"]),
                   montant_pdf(t["ecart_mobile"]), ""], compact=True)
    doc.section("Recettes constatées (ce que l'hôtel a gagné)")
    doc.cles_valeurs([
        ("Nuitées", f"{montant_pdf(d['total_nuitees'])} ({len(d['nuitees'])} nuit(s))"),
        ("Extras sur les notes (restaurant, bar, boutique)", f"{montant_pdf(d['total_extras'])} ({len(d['extras'])} ligne(s))"),
        ("Bar et boutique (cash et crédits clients)", montant_pdf(d["comptoir"]["recette"])),
        ("Total recettes", montant_pdf(d["total_recettes"])),
    ])
    c = d["comptoir"]
    doc.section("Bar et boutique (main courante)")
    doc.cles_valeurs([("Ventes", montant_pdf(c["ventes"])), ("Crédits", montant_pdf(c["credits"])),
                      ("Offres", montant_pdf(c["offres"])), ("Cash encaissé", montant_pdf(c["comptant"]))])
    if d["ecarts"]:
        doc.section("Écarts et motifs")
        doc.tableau(["Session", "Écart espèces", "Statut", "Motif / contestation"],
                    [[str(s), montant_pdf(s.remise.ecart if hasattr(s, "remise") else 0), s.get_statut_display(),
                      " ".join(x for x in [getattr(getattr(s, "remise", None), "motif", ""), s.motif_contestation] if x)]
                     for s in d["ecarts"]])
    if d["sorties"]:
        doc.section("Sorties de caisse")
        doc.tableau(["Réceptionniste", "Type", "Motif", "Statut", "Montant"],
                    [[str(s.session.receptionniste), s.get_type_display(), s.motif, s.get_statut_display(),
                      montant_pdf(s.montant)] for s in d["sorties"]])
    if d["impayes"]:
        doc.section("Séjours terminés non soldés")
        doc.tableau(["Client", "Chambre", "Départ", "Reste à payer"],
                    [[str(s.client), s.chambre.numero, s.date_depart.strftime("%d/%m/%Y"), montant_pdf(s.reste_a_payer)]
                     for s in d["impayes"]])
    if d["menage_sans_sejour"]:
        doc.section("Chambres faites sans séjour enregistré")
        doc.tableau(["Chambre", "Faite le", "Par"],
                    [[n.chambre.numero, _date(n.fait_le), str(n.fait_par)] for n in d["menage_sans_sejour"]])
    return doc.rendre()
