// Tâches en colonnes : glisser une carte (souris) dans une autre colonne change son étape ; l'étoile la rend prioritaire.
(function () {
  "use strict";

  var tableau = document.querySelector("[data-kanban]");
  if (!tableau) { return; }
  function jeton() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute("content") : "";
  }
  function envoyer(url, donnees) {
    var corps = new FormData();
    Object.keys(donnees).forEach(function (k) { corps.append(k, donnees[k]); });
    return window.fetch(url, { method: "POST", body: corps, credentials: "same-origin",
                               headers: { "X-CSRFToken": jeton(), "X-Requested-With": "fetch" } })
      .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); });
  }
  function recompter() {
    tableau.querySelectorAll(".kanban-colonne").forEach(function (col) {
      col.querySelector(".kanban-nombre").textContent = col.querySelectorAll(".carte-tache").length;
    });
  }

  var enCours = null;
  tableau.addEventListener("dragstart", function (e) {
    var carte = e.target.closest(".carte-tache");
    if (!carte) { return; }
    enCours = carte;
    carte.classList.add("deplace");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", carte.dataset.id);
  });
  tableau.addEventListener("dragend", function () {
    if (enCours) { enCours.classList.remove("deplace"); }
    tableau.querySelectorAll(".survol").forEach(function (c) { c.classList.remove("survol"); });
  });
  tableau.querySelectorAll(".kanban-colonne").forEach(function (col) {
    col.addEventListener("dragover", function (e) { if (enCours) { e.preventDefault(); col.classList.add("survol"); } });
    col.addEventListener("dragleave", function (e) { if (!col.contains(e.relatedTarget)) { col.classList.remove("survol"); } });
    col.addEventListener("drop", function (e) {
      e.preventDefault();
      col.classList.remove("survol");
      if (!enCours || enCours.closest(".kanban-colonne") === col) { return; }
      var carte = enCours, avant = carte.parentNode;
      col.querySelector(".kanban-cartes").prepend(carte);
      recompter();
      envoyer(carte.dataset.urlStatut, { statut: col.dataset.statut }).catch(function () {
        avant.prepend(carte);
        recompter();
        window.alert("L'étape n'a pas pu changer. Rechargez la page et réessayez.");
      });
    });
  });

  tableau.addEventListener("click", function (e) {
    var etoile = e.target.closest("button.etoile");
    if (!etoile) { return; }
    e.preventDefault();
    envoyer(etoile.dataset.url, {}).then(function (d) {
      etoile.classList.toggle("active", d.haute);
      etoile.setAttribute("aria-pressed", d.haute ? "true" : "false");
      etoile.closest(".carte-tache").classList.toggle("prioritaire", d.haute);
    }).catch(function () { window.location.reload(); });
  });
})();
