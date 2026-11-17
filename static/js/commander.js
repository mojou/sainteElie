// Commander des plats : « − » et « + » sur chaque plat, total qui se met à jour, numéro de chambre seulement
// quand on mange dans sa chambre. Sans JavaScript, on tape les quantités et le formulaire marche pareil.
(function () {
  "use strict";

  var form = document.getElementById("commande-plats");
  if (!form) { return; }
  var max = parseInt(form.getAttribute("data-quantite-max"), 10) || 20;
  var total = document.getElementById("commande-total");
  var blocChambre = document.getElementById("bloc-chambre");

  function enFcfa(n) { return n.toLocaleString("fr-FR") + " FCFA"; }

  function lire(champ) { return Math.min(Math.max(parseInt(champ.value, 10) || 0, 0), max); }

  function majTotal() {
    var nombre = 0, somme = 0;
    form.querySelectorAll("[data-plat]").forEach(function (plat) {
      var q = lire(plat.querySelector("input"));
      plat.classList.toggle("choisi", q > 0);
      nombre += q;
      somme += q * (parseInt(plat.getAttribute("data-prix"), 10) || 0);
    });
    total.textContent = nombre ? nombre + " plat" + (nombre > 1 ? "s" : "") + " · " + enFcfa(somme) : "Aucun plat choisi";
  }

  form.querySelectorAll("[data-plat]").forEach(function (plat) {
    var champ = plat.querySelector("input");
    plat.querySelector("[data-plus]").addEventListener("click", function () {
      champ.value = Math.min(lire(champ) + 1, max);
      majTotal();
    });
    plat.querySelector("[data-moins]").addEventListener("click", function () {
      var q = Math.max(lire(champ) - 1, 0);
      champ.value = q ? q : "";
      majTotal();
    });
    champ.addEventListener("input", majTotal);
  });

  function majChambre() {
    var choix = form.querySelector('input[name="service"]:checked');
    if (blocChambre) { blocChambre.hidden = !(choix && choix.value === "EN_CHAMBRE"); }
  }
  form.querySelectorAll('input[name="service"]').forEach(function (r) { r.addEventListener("change", majChambre); });

  form.addEventListener("submit", function (e) {
    majTotal();
    total.classList.remove("erreur");
    if (total.textContent === "Aucun plat choisi") {
      e.preventDefault();
      total.textContent = "Choisissez au moins un plat (touchez « + »)";
      total.classList.add("erreur");
      var premier = form.querySelector("[data-plat] [data-plus]");
      if (premier) { premier.focus(); }
      return;
    }
    // Plats choisis mais pas encore le nom ou le téléphone : on y amène le client au lieu d'envoyer.
    var vide = [form.elements.nom, form.elements.telephone].filter(function (c) { return c && !c.value.trim(); })[0];
    if (vide) {
      e.preventDefault();
      var resume = total.textContent;
      total.textContent = resume + " · il manque votre nom et votre téléphone";
      vide.scrollIntoView({ behavior: "smooth", block: "center" });
      window.setTimeout(function () { vide.focus(); }, 400);
    }
  });

  majTotal();
  majChambre();
})();
