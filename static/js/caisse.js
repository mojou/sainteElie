// Point de vente (boutique de la réception, ou restaurant · bar) : la commande et son pavé à gauche, les articles à
// droite ; « Paiement » ouvre l'écran de paiement ; après « Valider », un écran de fin : imprimer le reçu, nouvelle
// commande. La commande est gardée dans l'onglet (sessionStorage) : un écran verrouillé ne la perd pas.
(function () {
  "use strict";

  var form = document.getElementById("caisse");
  if (!form) { return; }

  var cle = form.getAttribute("data-cle");
  var tuiles = Array.prototype.slice.call(form.querySelectorAll(".tuile-article"));
  var parId = {};
  tuiles.forEach(function (t) {
    var id = t.getAttribute("data-id");
    if (!parId[id]) {
      parId[id] = { nom: t.getAttribute("data-nom"), prix: parseInt(t.getAttribute("data-prix"), 10),
                    stock: t.hasAttribute("data-stock") ? parseInt(t.getAttribute("data-stock"), 10) : null, tuiles: [] };
    }
    parId[id].tuiles.push(t);
  });

  var $ = function (id) { return document.getElementById(id); };
  var lignes = $("lignes-commande"), champs = document.createElement("div");
  form.appendChild(champs);
  var enChiffres = window.enChiffres || function (n) { return n + " FCFA"; };
  var enLettres = window.enLettres || function () { return ""; };
  var details = Array.prototype.slice.call(form.querySelectorAll("[data-pour]"));

  // --- La commande -----------------------------------------------------------------------------------------------
  var panier = {}, ordre = [], choisie = null, saisieNeuve = true;

  function garder() {
    try { window.sessionStorage.setItem(cle, JSON.stringify({ panier: panier, ordre: ordre })); } catch (e) { /* privé */ }
  }
  function oublier() {
    try { window.sessionStorage.removeItem(cle); } catch (e) { /* privé */ }
  }

  var initial = {};
  try { initial = JSON.parse($("panier-initial").textContent) || {}; } catch (e) { initial = {}; }
  if (Object.keys(initial).length) {
    panier = initial;                         // la page revient avec une erreur : on remet la commande
  } else {
    try {
      var garde = JSON.parse(window.sessionStorage.getItem(cle) || "null");
      if (garde && garde.panier) { panier = garde.panier; ordre = garde.ordre || []; }
    } catch (e) { panier = {}; }
  }
  Object.keys(panier).forEach(function (id) { if (!parId[id] || !(panier[id] > 0)) { delete panier[id]; } });
  ordre = ordre.filter(function (id) { return panier[id]; });
  Object.keys(panier).forEach(function (id) { if (ordre.indexOf(id) === -1) { ordre.push(id); } });
  choisie = ordre.length ? ordre[ordre.length - 1] : null;

  function total() { return ordre.reduce(function (s, id) { return s + panier[id] * parId[id].prix; }, 0); }
  function nombre() { return ordre.reduce(function (s, id) { return s + panier[id]; }, 0); }

  function fixer(id, q) {
    var article = parId[id];
    if (article.stock !== null && q > article.stock) {
      window.confirmer({ titre: "Pas assez en stock", texte: "Il ne reste que " + article.stock + " « " + article.nom +
                         " ». Comptez le stock avec le gérant si c'est faux.", oui: "Compris", non: "Fermer" },
                       function () {});
      return false;
    }
    if (q <= 0) {
      delete panier[id];
      ordre = ordre.filter(function (x) { return x !== id; });
      if (choisie === id) { choisie = ordre.length ? ordre[ordre.length - 1] : null; saisieNeuve = true; }
    } else {
      if (!panier[id]) { ordre.push(id); }
      panier[id] = Math.min(q, 999);
    }
    afficher();
    return true;
  }

  function ajouter(id) {
    if (fixer(id, (panier[id] || 0) + 1)) { choisie = id; saisieNeuve = true; afficher(); }
  }

  function afficher() {
    lignes.innerHTML = "";
    champs.innerHTML = "";
    if (!ordre.length) {
      var vide = document.createElement("li");
      vide.className = "vide";
      vide.textContent = "La commande est vide.";
      lignes.appendChild(vide);
    }
    ordre.forEach(function (id) {
      var article = parId[id], q = panier[id];
      var li = document.createElement("li");
      li.className = "pdv-ligne" + (id === choisie ? " choisie" : "");
      li.setAttribute("role", "button");
      li.setAttribute("tabindex", "0");
      li.setAttribute("aria-label", q + " " + article.nom + ", touchez pour changer la quantité");
      li.innerHTML = '<span class="ligne-nom"></span><span class="ligne-montant"></span><span class="ligne-detail"></span>';
      li.querySelector(".ligne-nom").textContent = article.nom;
      li.querySelector(".ligne-montant").textContent = (q * article.prix).toLocaleString("fr-FR");
      li.querySelector(".ligne-detail").textContent = q + " × " + article.prix.toLocaleString("fr-FR") + " F";
      li.addEventListener("click", function () { choisie = id; saisieNeuve = true; afficher(); });
      li.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); li.click(); } });
      lignes.appendChild(li);

      var champ = document.createElement("input");
      champ.type = "hidden";
      champ.name = "q_" + id;
      champ.value = q;
      champs.appendChild(champ);
    });
    var ligneChoisie = lignes.querySelector(".choisie");
    if (ligneChoisie && ligneChoisie.scrollIntoView) { ligneChoisie.scrollIntoView({ block: "nearest" }); }

    Object.keys(parId).forEach(function (id) {
      parId[id].tuiles.forEach(function (t) {
        var compteur = t.querySelector(".compteur");
        compteur.hidden = !panier[id];
        compteur.textContent = panier[id] || "";
        t.classList.toggle("choisi", !!panier[id]);
      });
    });
    var somme = total(), n = nombre();
    $("total-commande").textContent = enChiffres(somme);
    $("total-lettres").textContent = somme ? enLettres(somme) : "";
    $("a-payer").textContent = enChiffres(somme);
    $("a-payer-lettres").textContent = somme ? enLettres(somme) : "";
    $("astuce").textContent = n ? "Touchez une ligne, puis tapez sa quantité sur le pavé." :
      "Touchez un article à droite pour l'ajouter.";
    $("aller-paiement").disabled = !n;
    $("aller-paiement").textContent = n ? "Paiement · " + enChiffres(somme) : "Paiement";
    $("vider-commande").disabled = !n;
    $("barre-commande").hidden = !n;
    $("barre-resume").textContent = n + (n > 1 ? " articles · " : " article · ") + enChiffres(somme);
    form.querySelectorAll(".pdv-touches button").forEach(function (b) { b.disabled = !choisie; });
    calculerMonnaie();
    majValider();
    garder();
  }

  tuiles.forEach(function (t) {
    t.addEventListener("click", function () { if (!t.disabled) { ajouter(t.getAttribute("data-id")); } });
  });

  // Pavé : la quantité de la ligne choisie. Le premier chiffre remplace la quantité, les suivants s'ajoutent.
  form.querySelector(".pdv-touches").addEventListener("click", function (e) {
    var b = e.target.closest("[data-touche]");
    if (!b || !choisie) { return; }
    var touche = b.getAttribute("data-touche"), q = panier[choisie] || 0;
    if (touche === "moins") { fixer(choisie, q - 1); return; }
    if (touche === "efface") {
      saisieNeuve = false;
      fixer(choisie, Math.floor(q / 10));
      return;
    }
    var chiffre = parseInt(touche, 10);
    var nouveau = saisieNeuve ? chiffre : q * 10 + chiffre;
    saisieNeuve = false;
    fixer(choisie, nouveau);
  });

  $("vider-commande").addEventListener("click", function () {
    window.confirmer({ titre: "Vider la commande ?", texte: "Tous les articles touchés seront retirés.",
                       oui: "Oui, vider", non: "Non, garder" }, function () {
      panier = {}; ordre = []; choisie = null; afficher();
    });
  });

  // --- Vues : articles, commande (téléphone), paiement ----------------------------------------------------------
  function vue(nom) {
    form.classList.toggle("vue-commande", nom === "commande");
    form.classList.toggle("vue-paiement", nom === "paiement");
    $("ecran-paiement").hidden = nom !== "paiement";
    if (nom === "paiement") {
      var choix = form.querySelector('input[name="paiement"]:checked') || form.querySelector('input[name="paiement"]');
      if (choix) { choix.focus(); }
    }
    window.scrollTo(0, 0);
  }
  form.addEventListener("click", function (e) {
    var b = e.target.closest("[data-vue]");
    if (b) { vue(b.getAttribute("data-vue")); }
  });
  $("aller-paiement").addEventListener("click", function () { if (ordre.length) { vue("paiement"); } });
  $("retour-commande").addEventListener("click", function () {
    vue(window.matchMedia("(max-width: 899px)").matches ? "commande" : "articles");
  });

  // --- Paiement ------------------------------------------------------------------------------------------------
  var LIBELLES = { ESPECES: "en espèces", ORANGE_MONEY: "par Orange Money", MTN_MOMO: "par MTN MoMo" };
  var donne = $("donne"), monnaie = $("monnaie");

  function paiement() {
    var r = form.querySelector('input[name="paiement"]:checked');
    return r ? r.value : "";
  }
  function majDetails() {
    var p = paiement();
    details.forEach(function (d) { d.hidden = d.getAttribute("data-pour") !== p; });
  }
  function pret() {
    var p = paiement();
    if (!ordre.length || !p) { return false; }
    if (p === "CHAMBRE") { return !!form.querySelector('input[name="sejour"]:checked'); }
    if (p === "CREDIT") {
      return !!(form.elements.client.value || (form.elements.nouveau_client.value.trim() && form.elements.telephone.value.trim()));
    }
    if (p === "OFFERT") { return !!form.elements.observation.value.trim(); }
    return true;
  }
  function majValider() {
    var p = paiement(), somme = enChiffres(total()), bouton = $("bouton-encaisser");
    bouton.disabled = !pret();
    if (!p) { bouton.textContent = "Valider"; return; }
    if (LIBELLES[p]) { bouton.textContent = "Valider : " + somme + " " + LIBELLES[p]; }
    else if (p === "CHAMBRE") {
      var ch = form.querySelector('input[name="sejour"]:checked');
      bouton.textContent = ch ? "Valider : " + somme + " sur la chambre " + ch.parentNode.querySelector("strong").textContent
        : "Touchez la chambre du client";
    } else if (p === "CREDIT") { bouton.textContent = pret() ? "Valider : " + somme + " à crédit" : "Choisissez le client"; }
    else if (p === "OFFERT") { bouton.textContent = pret() ? "Valider : offert (" + somme + ")" : "Écrivez à qui et pourquoi"; }
  }
  function calculerMonnaie() {
    if (!donne) { return; }
    var recu = parseInt(donne.value, 10), somme = total();
    if (isNaN(recu) || !recu || !somme) { monnaie.textContent = ""; monnaie.className = "monnaie"; return; }
    if (recu < somme) {
      monnaie.textContent = "Il manque " + enChiffres(somme - recu) + ".";
      monnaie.className = "monnaie manque";
    } else {
      monnaie.textContent = "Monnaie à rendre : " + enChiffres(recu - somme);
      monnaie.className = "monnaie rendre";
    }
  }
  form.addEventListener("change", function () { majDetails(); majValider(); });
  form.addEventListener("input", function (e) { if (e.target !== $("recherche-article")) { majValider(); } });
  donne.addEventListener("input", calculerMonnaie);
  form.querySelectorAll("[data-donne]").forEach(function (b) {
    b.addEventListener("click", function () {
      var v = b.getAttribute("data-donne");
      donne.value = v === "juste" ? total() : (parseInt(donne.value, 10) || 0) + parseInt(v, 10);
      calculerMonnaie();
    });
  });

  // --- Chercher, familles ------------------------------------------------------------------------------------
  var recherche = $("recherche-article"), familleActive = "";
  function sansAccent(t) { return (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function filtrer() {
    var mots = sansAccent(recherche.value).trim().split(/\s+/).filter(Boolean), visibles = 0;
    form.querySelectorAll(".groupe-articles").forEach(function (g) {
      var cache = mots.length ? g.hasAttribute("data-doublons")
        : !!familleActive && g.getAttribute("data-famille") !== familleActive;
      var n = 0;
      g.querySelectorAll(".tuile-article").forEach(function (t) {
        var ok = !cache && mots.every(function (m) { return sansAccent(t.getAttribute("data-nom")).indexOf(m) !== -1; });
        t.hidden = !ok;
        if (ok) { n += 1; }
      });
      g.hidden = !n;
      visibles += n;
    });
    $("aucun-article").hidden = visibles > 0;
  }
  recherche.addEventListener("input", filtrer);
  recherche.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") { return; }
    e.preventDefault();                       // Entrée : ajoute l'article s'il est le seul trouvé
    var ids = tuiles.filter(function (t) { return !t.hidden && !t.closest(".groupe-articles").hidden && !t.disabled; })
      .map(function (t) { return t.getAttribute("data-id"); })
      .filter(function (v, i, a) { return a.indexOf(v) === i; });
    if (ids.length === 1) { ajouter(ids[0]); recherche.select(); }
  });
  form.querySelectorAll(".famille").forEach(function (b) {
    b.addEventListener("click", function () {
      familleActive = b.getAttribute("data-famille");
      form.querySelectorAll(".famille").forEach(function (x) { x.classList.toggle("active", x === b); });
      filtrer();
    });
  });

  // --- Mes ventes (fenêtre) -------------------------------------------------------------------------------------
  document.querySelectorAll("[data-ouvrir]").forEach(function (b) {
    b.addEventListener("click", function () {
      var d = $(b.getAttribute("data-ouvrir"));
      if (d && d.showModal) { d.showModal(); } else if (d) { d.setAttribute("open", ""); }
    });
  });

  // --- Valider, puis écran de fin ---------------------------------------------------------------------------------
  form.addEventListener("submit", function (e) {
    if (e.defaultPrevented) { return; }
    if (!pret()) { e.preventDefault(); majValider(); return; }
    var recu = parseInt(donne.value, 10), somme = total();
    try {
      window.sessionStorage.setItem("monnaie-rendue", paiement() === "ESPECES" && recu > somme ? String(recu - somme) : "");
    } catch (err) { /* privé */ }
    window.setTimeout(function () { $("bouton-encaisser").disabled = true; $("bouton-encaisser").textContent = "Enregistrement…"; }, 0);
  });

  var fin = $("pdv-termine");
  if (fin) {
    var rendue = "";
    try { rendue = window.sessionStorage.getItem("monnaie-rendue") || ""; window.sessionStorage.removeItem("monnaie-rendue"); } catch (e) { rendue = ""; }
    if (rendue) {
      $("monnaie-rendue").hidden = false;
      $("monnaie-rendue").textContent = "Monnaie rendue : " + enChiffres(parseInt(rendue, 10));
    }
    panier = {}; ordre = []; choisie = null;
    oublier();
    var fermer = function () { fin.remove(); recherche.focus(); };
    $("nouvelle-commande").addEventListener("click", fermer);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && document.body.contains(fin)) { fermer(); } });
    $("nouvelle-commande").focus();
  }

  majDetails();
  afficher();
  filtrer();
  if (form.hasAttribute("data-ouvrir-paiement") && ordre.length) { vue("paiement"); }
})();
