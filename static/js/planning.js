// Planning : « + » ajoute un créneau dans la case, toucher un créneau l'ouvre pour le changer ou le retirer,
// et à la souris on le glisse vers un autre jour ou une autre personne.
(function () {
  "use strict";

  var dialogue = document.getElementById("dialogue-shift");
  if (!dialogue) { return; }
  var form = dialogue.querySelector("form");
  var champs = form.elements;

  function ouvrir(o) {
    document.getElementById("shift-action").value = o.pk ? "modifier" : "ajouter";
    champs.pk.value = o.pk || "";
    champs.employe.value = o.employe;
    champs.date.value = o.date;
    champs.note.value = o.note || "";
    var radio = o.creneau ? form.querySelector('input[name="creneau"][value="' + o.creneau + '"]') : null;
    (radio || form.querySelector('input[name="creneau"]')).checked = true;
    document.getElementById("titre-shift").textContent = o.pk ? "Changer ce créneau" : "Ajouter un créneau";
    document.getElementById("shift-supprimer").hidden = !o.pk;
    document.getElementById("shift-enregistrer").textContent = o.pk ? "Enregistrer" : "Ajouter";
    if (dialogue.showModal) { dialogue.showModal(); } else { dialogue.setAttribute("open", ""); }
  }

  document.addEventListener("click", function (e) {
    var plus = e.target.closest(".gantt-ajouter");
    if (plus) { ouvrir({ employe: plus.dataset.employe, date: plus.dataset.date }); return; }
    var shift = e.target.closest(".gantt-shift");
    if (shift) {
      ouvrir({ pk: shift.dataset.id, employe: shift.dataset.employe, date: shift.dataset.date,
               creneau: shift.dataset.creneau, note: shift.dataset.note });
    }
  });
  dialogue.querySelector("[data-fermer]").addEventListener("click", function () { dialogue.close(); });
  dialogue.addEventListener("click", function (e) { if (e.target === dialogue) { dialogue.close(); } });

  // Glisser-déposer (souris) : le créneau change de jour ou de personne.
  var deplacer = document.getElementById("form-deplacer");
  var enCours = null;
  document.querySelectorAll(".gantt-shift").forEach(function (shift) {
    shift.addEventListener("dragstart", function (e) {
      enCours = shift;
      shift.classList.add("deplace");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", shift.dataset.id);
    });
    shift.addEventListener("dragend", function () {
      shift.classList.remove("deplace");
      document.querySelectorAll(".gantt-case.survol").forEach(function (c) { c.classList.remove("survol"); });
    });
  });
  document.querySelectorAll(".gantt-case").forEach(function (cas) {
    cas.addEventListener("dragover", function (e) {
      if (!enCours) { return; }
      e.preventDefault();
      cas.classList.add("survol");
    });
    cas.addEventListener("dragleave", function () { cas.classList.remove("survol"); });
    cas.addEventListener("drop", function (e) {
      e.preventDefault();
      cas.classList.remove("survol");
      if (!enCours) { return; }
      if (cas.dataset.employe === enCours.dataset.employe && cas.dataset.date === enCours.dataset.date) { return; }
      deplacer.elements.pk.value = enCours.dataset.id;
      deplacer.elements.employe.value = cas.dataset.employe;
      deplacer.elements.date.value = cas.dataset.date;
      cas.classList.add("en-attente");
      deplacer.submit();
    });
  });
})();
