// Rapports : au survol (ou au toucher, ou au clavier) d'une colonne, le détail du jour par service.
(function () {
  "use strict";

  var bulle = document.getElementById("infobulle");
  if (!bulle) { return; }
  var actuelle = null;

  function montrer(colonne) {
    actuelle = colonne;
    bulle.innerHTML = "";
    var titre = document.createElement("strong");
    titre.textContent = colonne.getAttribute("data-titre");
    bulle.appendChild(titre);
    (colonne.getAttribute("data-parts") || "").split(";").reverse().forEach(function (morceau) {
      var p = morceau.split("|");
      if (p.length < 3 || !parseInt(p[2], 10)) { return; }
      var ligne = document.createElement("div");
      ligne.className = "ligne-bulle";
      ligne.innerHTML = '<span class="cle-couleur serie-' + p[0] + '"></span><span></span><b></b>';
      ligne.children[1].textContent = p[1];
      ligne.children[2].textContent = parseInt(p[2], 10).toLocaleString("fr-FR");
      bulle.appendChild(ligne);
    });
    var total = document.createElement("div");
    total.className = "ligne-bulle total";
    total.innerHTML = "<span></span><span>Total</span><b></b>";
    total.children[2].textContent = parseInt(colonne.getAttribute("data-total"), 10).toLocaleString("fr-FR") + " " +
      (colonne.getAttribute("data-unite") || "FCFA");
    if (colonne.hasAttribute("data-unite")) { total.children[1].textContent = "En stock"; }
    bulle.appendChild(total);
    bulle.hidden = false;
    var r = colonne.getBoundingClientRect(), b = bulle.getBoundingClientRect();
    var gauche = Math.min(Math.max(8, r.left + r.width / 2 - b.width / 2), window.innerWidth - b.width - 8);
    var haut = r.top + window.pageYOffset - b.height - 8;
    if (haut < window.pageYOffset + 8) { haut = r.bottom + window.pageYOffset + 8; }
    bulle.style.left = gauche + window.pageXOffset + "px";
    bulle.style.top = haut + "px";
    document.querySelectorAll(".graphe-colonne.survol").forEach(function (c) { c.classList.remove("survol"); });
    colonne.classList.add("survol");
  }
  function cacher() {
    bulle.hidden = true;
    if (actuelle) { actuelle.classList.remove("survol"); }
    actuelle = null;
  }
  document.querySelectorAll(".graphe-colonne").forEach(function (c) {
    c.addEventListener("mouseenter", function () { montrer(c); });
    c.addEventListener("focus", function () { montrer(c); });
    c.addEventListener("click", function () { montrer(c); });
    c.addEventListener("mouseleave", cacher);
    c.addEventListener("blur", cacher);
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { cacher(); } });
})();
