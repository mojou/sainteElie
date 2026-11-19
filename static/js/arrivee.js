// Arrivée d'un client, une question par écran : qui, combien de nuits, combien il paie, puis on vérifie tout.
// Sans JavaScript, les quatre étapes s'affichent l'une sous l'autre et le formulaire marche pareil.
(function () {
  "use strict";

  var form = document.getElementById("assistant");
  if (!form) { return; }
  form.classList.add("par-etapes");

  var pas = Array.prototype.slice.call(form.querySelectorAll(".pas"));
  var reperes = form.querySelectorAll(".pas-indicateur li");
  var tarifs = {};
  try { tarifs = JSON.parse(document.getElementById("tarifs-chambres").textContent) || {}; } catch (e) { tarifs = {}; }
  var photos = {};
  try { photos = JSON.parse(document.getElementById("photos-chambres").textContent) || {}; } catch (e) { photos = {}; }
  var champChambre = form.elements.chambre;
  var champNom = form.elements.nom, champTel = form.elements.telephone;
  var champNuits = form.elements.nuits, champMontant = form.elements.montant;
  var enChiffres = window.enChiffres || function (n) { return n + " FCFA"; };
  var enLettres = window.enLettres || function () { return ""; };
  var aujourdhui = new Date(form.getAttribute("data-aujourdhui") + "T12:00:00");
  var courant = 0;

  function tarif() { return parseInt(tarifs[champChambre ? champChambre.value : ""] || "0", 10) || 0; }

  // Le client voit la chambre avant de payer : ses photos s'affichent dès qu'elle est choisie.
  var blocPhotos = document.getElementById("montrer-chambre");
  var montree = null;
  function montrerChambre() {
    if (!blocPhotos || !champChambre) { return; }
    var choisie = champChambre.value || "";
    if (choisie === montree) { return; }
    montree = choisie;
    var liste = photos[choisie] || [];
    var ancienne = blocPhotos.querySelector("[data-galerie]");
    var galerie = document.createElement("div");
    galerie.className = "galerie";
    galerie.setAttribute("data-galerie", "");
    var piste = document.createElement("div");
    piste.className = "galerie-piste";
    piste.tabIndex = 0;
    piste.setAttribute("aria-label", "Photos de la chambre");
    liste.forEach(function (url, i) {
      var img = document.createElement("img");
      img.src = url;
      img.alt = "Photo " + (i + 1) + " sur " + liste.length;
      piste.appendChild(img);
    });
    galerie.appendChild(piste);
    if (liste.length > 1) {
      [["precedente", -1, "‹", "Photo précédente"], ["suivante", 1, "›", "Photo suivante"]].forEach(function (f) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "galerie-fleche " + f[0];
        b.setAttribute("data-galerie-pas", f[1]);
        b.setAttribute("aria-label", f[3]);
        b.textContent = f[2];
        galerie.appendChild(b);
      });
    }
    ancienne.parentNode.replaceChild(galerie, ancienne);
    blocPhotos.hidden = !liste.length;
    if (window.activerGalerie) { window.activerGalerie(galerie); }
  }
  if (champChambre) {
    champChambre.addEventListener("change", montrerChambre);
    form.addEventListener("click", function () { window.setTimeout(montrerChambre, 0); });
    montrerChambre();
  }
  function nuits() { return Math.max(parseInt(champNuits.value, 10) || 0, 0); }
  function total() { return tarif() * nuits(); }
  function montant() { return Math.max(parseInt(champMontant.value, 10) || 0, 0); }
  function moyen() {
    var r = form.querySelector('input[name="moyen"]:checked');
    return r ? r.parentNode.textContent.trim() : "";
  }
  function depart() {
    var d = new Date(aujourdhui.getTime());
    d.setDate(d.getDate() + nuits());
    return d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
  }
  function numeroChambre() {
    if (!champChambre) { return ""; }
    if (champChambre.tagName === "SELECT") {
      var o = champChambre.options[champChambre.selectedIndex];
      return o && o.value ? o.text.split(" ")[0] : "";
    }
    var titre = form.querySelector("h1").textContent.match(/chambre (\S+)/);
    return titre ? titre[1] : "";
  }

  function erreur(champ, texte) {
    var bloc = champ.closest(".champ") || champ.parentNode;
    var ancien = bloc.querySelector(".erreur.js");
    if (ancien) { ancien.remove(); }
    bloc.classList.toggle("en-erreur", !!texte);
    if (texte) {
      var div = document.createElement("div");
      div.className = "erreur js";
      div.textContent = texte;
      bloc.appendChild(div);
      champ.focus();
    }
    return !texte;
  }

  function verifier(i) {
    if (i === 0) {
      if (champChambre && champChambre.tagName === "SELECT" && !champChambre.value) {
        var saisie = form.querySelector(".combo-saisie") || champChambre;
        return erreur(saisie, "Choisissez la chambre.");
      }
      if (!champNom.value.trim()) { return erreur(champNom, "Écrivez le nom du client."); }
      erreur(champNom, "");
      if (!champTel.value.trim()) { return erreur(champTel, "Écrivez son numéro de téléphone."); }
      erreur(champTel, "");
      var champHeure = form.elements.heure;
      if (champHeure && !champHeure.value) { return erreur(champHeure, "Écrivez l'heure d'arrivée du client."); }
      return champHeure ? erreur(champHeure, "") : true;
    }
    if (i === 1) {
      if (nuits() < 1 || nuits() > 90) { return erreur(champNuits, "Entre 1 et 90 nuits."); }
      return erreur(champNuits, "");
    }
    return true;
  }

  function majCalculs() {
    var t = total(), n = nuits();
    var calcul = document.getElementById("calcul-nuits");
    calcul.textContent = n && tarif() ? n + " nuit" + (n > 1 ? "s" : "") + " × " + enChiffres(tarif()) + " = " +
      enChiffres(t) + ". Départ le " + depart() + "." : "";
    form.querySelectorAll("[data-nuits]").forEach(function (b) {
      b.classList.toggle("choisi", parseInt(b.getAttribute("data-nuits"), 10) === n);
    });
    var tout = form.querySelector('[data-montant-rapide="total"] span');
    var nuit = form.querySelector('[data-montant-rapide="nuit"] span');
    if (tout) { tout.textContent = t ? "\u00a0: " + enChiffres(t) : ""; }
    if (nuit) { nuit.textContent = tarif() ? "\u00a0: " + enChiffres(tarif()) : ""; }
    champMontant.setAttribute("data-montant-max", t || "");

    var recap = document.getElementById("recapitulatif");
    var m = montant(), lignes = [
      ["Chambre", numeroChambre() + (tarif() ? " · " + enChiffres(tarif()) + " la nuit" : "")],
      ["Client", champNom.value.trim() + " · " + champTel.value.trim()],
      ["Arrivé à", form.elements.heure ? form.elements.heure.value.replace(":", " h ") : ""],
      ["Nuits", n + " · départ le " + depart()],
      ["Prix du séjour", enChiffres(t)],
      ["Payé maintenant", m ? enChiffres(m) + " (" + enLettres(m) + ") en " + moyen() : "Rien pour l'instant"],
      ["Restera à payer", enChiffres(Math.max(t - m, 0))]
    ];
    recap.innerHTML = "";
    lignes.forEach(function (l) {
      var dt = document.createElement("dt"), dd = document.createElement("dd");
      dt.textContent = l[0];
      dd.textContent = l[1];
      recap.appendChild(dt);
      recap.appendChild(dd);
    });
  }

  function montrer(i) {
    courant = Math.max(0, Math.min(pas.length - 1, i));
    pas.forEach(function (p, j) { p.classList.toggle("actif", j === courant); });
    reperes.forEach(function (li, j) {
      li.classList.toggle("actif", j === courant);
      li.classList.toggle("fait", j < courant);
    });
    majCalculs();
    var haut = form.getBoundingClientRect().top + window.pageYOffset - 70;
    if (window.pageYOffset > haut) { window.scrollTo(0, haut); }
    var premier = pas[courant].querySelector("input[type=text], input[type=tel], input[type=number], .combo-saisie");
    if (premier && courant < 3 && !premier.value) { premier.focus(); }
  }

  form.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) { return; }
    if (b.hasAttribute("data-suivant")) {
      if (verifier(courant)) { montrer(courant + 1); }
    } else if (b.hasAttribute("data-precedent")) {
      montrer(courant - 1);
    } else if (b.hasAttribute("data-nuits")) {
      champNuits.value = b.getAttribute("data-nuits");
      majCalculs();
    } else if (b.hasAttribute("data-montant-rapide")) {
      var quoi = b.getAttribute("data-montant-rapide");
      champMontant.value = quoi === "total" ? total() : quoi === "nuit" ? tarif() : "";
      champMontant.dispatchEvent(new Event("input", { bubbles: true }));
      majCalculs();
    }
  });
  // Entrée dans un champ : on passe à l'étape suivante au lieu d'envoyer le formulaire trop tôt.
  form.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && courant < pas.length - 1 && e.target.tagName === "INPUT" &&
        !e.target.classList.contains("combo-saisie")) {
      e.preventDefault();
      if (verifier(courant)) { montrer(courant + 1); }
    }
  });
  form.addEventListener("input", majCalculs);
  form.addEventListener("change", majCalculs);

  // Après une erreur du serveur, on ouvre l'étape où se trouve la première erreur.
  var depart0 = 0;
  for (var i = 0; i < pas.length; i += 1) {
    if (pas[i].querySelector(".en-erreur, .erreur")) { depart0 = i; break; }
  }
  montrer(depart0);
})();
