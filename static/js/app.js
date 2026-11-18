// Gestion Saint-Élie — comportements légers, sans dépendance.
(function () {
  "use strict";

  // Menu latéral sur mobile
  var bouton = document.querySelector(".bouton-menu");
  var menu = document.querySelector("nav.menu");
  if (bouton && menu) {
    bouton.addEventListener("click", function () { menu.classList.toggle("ouvert"); });
  }

  // --- Montants en toutes lettres (même règle que core/utils.py) -------------------------------
  var UNITES = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
    "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf"];
  var DIZAINES = { 2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante" };

  function moinsDeCent(n, final) {
    if (n < 20) { return UNITES[n]; }
    var d = Math.floor(n / 10), u = n % 10;
    if (d === 7) { return u === 1 ? "soixante et onze" : "soixante-" + UNITES[10 + u]; }
    if (d === 8) { return u === 0 ? (final ? "quatre-vingts" : "quatre-vingt") : "quatre-vingt-" + UNITES[u]; }
    if (d === 9) { return "quatre-vingt-" + UNITES[10 + u]; }
    if (u === 0) { return DIZAINES[d]; }
    return u === 1 ? DIZAINES[d] + " et un" : DIZAINES[d] + "-" + UNITES[u];
  }

  function moinsDeMille(n, final) {
    var c = Math.floor(n / 100), r = n % 100, morceaux = [];
    if (c === 1) { morceaux.push("cent"); }
    else if (c > 1) { morceaux.push(UNITES[c] + " cent" + (r === 0 && final ? "s" : "")); }
    if (r) { morceaux.push(moinsDeCent(r, final)); }
    return morceaux.join(" ");
  }

  function enLettres(n) {
    if (n === 0) { return "zéro"; }
    var milliards = Math.floor(n / 1e9), millions = Math.floor(n / 1e6) % 1000;
    var milliers = Math.floor(n / 1000) % 1000, unites = n % 1000, morceaux = [];
    if (milliards) { morceaux.push(enLettres(milliards) + " milliard" + (milliards > 1 ? "s" : "")); }
    if (millions) { morceaux.push(moinsDeMille(millions, true) + " million" + (millions > 1 ? "s" : "")); }
    if (milliers) { morceaux.push(milliers === 1 ? "mille" : moinsDeMille(milliers, false) + " mille"); }
    if (unites) { morceaux.push(moinsDeMille(unites, true)); }
    return morceaux.join(" ");
  }

  function francsEnLettres(n) { return enLettres(n) + (n > 1 ? " francs" : " franc"); }
  function enChiffres(n) { return n.toLocaleString("fr-FR") + " FCFA"; }
  window.enLettres = francsEnLettres;
  window.enChiffres = enChiffres;

  // Sous chaque champ de montant, le montant en toutes lettres : « 250000 » → deux cent cinquante mille francs.
  function lireMontant(champ) {
    var n = parseInt(String(champ.value).replace(/[\s  ]/g, ""), 10);
    return isNaN(n) || n <= 0 ? 0 : n;
  }
  document.querySelectorAll("input[data-montant]").forEach(function (champ) {
    var ligne = document.createElement("span");
    ligne.className = "en-lettres";
    ligne.setAttribute("aria-live", "polite");
    champ.insertAdjacentElement("afterend", ligne);
    var maj = function () {
      var n = lireMontant(champ);
      ligne.textContent = n ? francsEnLettres(n) : "";
    };
    champ.addEventListener("input", maj);
    maj();
  });

  // --- Fenêtre « C'est bien ça ? » : gros boutons, « Non » choisi par défaut ----------------------
  var dialogue = null;
  function confirmer(options, siOui, siNon) {
    var texte = options.texte || "";
    if (typeof HTMLDialogElement !== "function") {
      var phrase = texte + (options.montant ? "\n\n" + enChiffres(options.montant) + "\n(" + francsEnLettres(options.montant) + ")" : "");
      if (window.confirm(phrase)) { siOui(); } else if (siNon) { siNon(); }
      return;
    }
    if (!dialogue) {
      dialogue = document.createElement("dialog");
      dialogue.className = "confirmation";
      dialogue.innerHTML = '<form method="dialog"><h2></h2><p class="texte"></p>' +
        '<p class="montant"><strong></strong><span></span></p>' +
        '<div class="boutons"><button class="btn secondaire grand" value="non"></button>' +
        '<button class="btn ok grand" value="oui"></button></div></form>';
      document.body.appendChild(dialogue);
    }
    dialogue.querySelector("h2").textContent = options.titre || "Vous êtes sûr ?";
    dialogue.querySelector(".texte").textContent = texte;
    var blocMontant = dialogue.querySelector(".montant");
    blocMontant.hidden = !options.montant;
    if (options.montant) {
      blocMontant.querySelector("strong").textContent = enChiffres(options.montant);
      blocMontant.querySelector("span").textContent = francsEnLettres(options.montant);
    }
    var non = dialogue.querySelector("[value=non]"), oui = dialogue.querySelector("[value=oui]");
    non.textContent = options.non || "Non";
    oui.textContent = options.oui || "Oui";
    dialogue.onclose = function () {
      if (dialogue.returnValue === "oui") { siOui(); } else if (siNon) { siNon(); }
    };
    dialogue.returnValue = "";
    dialogue.showModal();
    non.focus();
  }
  window.confirmer = confirmer;

  // Confirmation avant une action irréversible : <button data-confirmer="Texte">
  document.addEventListener("click", function (e) {
    var cible = e.target.closest("[data-confirmer]");
    if (!cible) { return; }
    if (cible.dataset.confirme === "1") { cible.dataset.confirme = ""; return; }
    e.preventDefault();
    confirmer({ texte: cible.getAttribute("data-confirmer"), oui: cible.getAttribute("data-oui") || "Oui",
                non: cible.getAttribute("data-non") || "Non, retour" },
      function () { cible.dataset.confirme = "1"; cible.click(); });
  });

  // Argent reçu : au-delà du montant dû (data-montant-max) ou du seuil réglé, on fait relire le montant.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.method === "dialog") { return; }
    if (form.dataset.montantsConfirmes === "1") { form.dataset.montantsConfirmes = ""; return; }
    var seuil = parseInt(document.body.getAttribute("data-montant-eleve") || "0", 10);
    var aRelire = null;
    form.querySelectorAll("input[data-confirmer-montant]").forEach(function (champ) {
      if (aRelire || champ.disabled) { return; }
      var n = lireMontant(champ), max = parseInt(champ.getAttribute("data-montant-max") || "", 10);
      if (!n) { return; }
      if (max > 0 && n > max) {
        aRelire = { champ: champ, n: n, texte: (champ.getAttribute("data-montant-max-texte") || "Le montant dû est de") +
          " " + enChiffres(max) + ". Vous avez tapé :" };
      } else if (seuil && n >= seuil) {
        aRelire = { champ: champ, n: n, texte: "C'est un gros montant. Vérifiez les zéros. Vous avez tapé :" };
      }
    });
    if (!aRelire) { return; }
    e.preventDefault();
    var bouton = e.submitter;
    confirmer({ titre: "C'est bien ça ?", texte: aRelire.texte, montant: aRelire.n,
                oui: "Oui, c'est bien ça", non: "Non, je corrige" },
      function () {
        form.dataset.montantsConfirmes = "1";
        if (form.requestSubmit) { form.requestSubmit(bouton || undefined); } else { form.submit(); }
      },
      function () { aRelire.champ.focus(); aRelire.champ.select(); });
  });

  // --- Petits « ? » : l'explication d'un mot en une phrase -------------------------------------
  document.addEventListener("click", function (e) {
    var bouton = e.target.closest(".aide-bouton");
    document.querySelectorAll(".aide-bulle:not([hidden])").forEach(function (bulle) {
      if (!bouton || bulle.previousElementSibling !== bouton) {
        bulle.hidden = true;
        bulle.previousElementSibling.setAttribute("aria-expanded", "false");
      }
    });
    if (bouton) {
      e.preventDefault();
      var bulle = bouton.nextElementSibling;
      bulle.hidden = !bulle.hidden;
      bouton.setAttribute("aria-expanded", bulle.hidden ? "false" : "true");
    }
  });

  // --- Listes déroulantes avec recherche -------------------------------------------------------
  // Chaque <select> devient un champ où l'on tape quelques lettres pour filtrer les choix
  // (sans tenir compte des accents ni des majuscules). Le <select> d'origine reste dans le
  // formulaire, caché : c'est lui qui est envoyé, et son événement « change » est déclenché.
  function sansAccent(texte) {
    return (texte || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function rendreCherchable(select) {
    var options = Array.prototype.slice.call(select.options);
    var boite = document.createElement("div");
    boite.className = "combo";
    var saisie = document.createElement("input");
    saisie.type = "text";
    saisie.className = "combo-saisie";
    saisie.autocomplete = "off";
    saisie.placeholder = "Tapez pour chercher…";
    saisie.setAttribute("role", "combobox");
    saisie.setAttribute("aria-expanded", "false");
    var liste = document.createElement("ul");
    liste.className = "combo-liste";
    liste.setAttribute("role", "listbox");
    liste.hidden = true;

    select.parentNode.insertBefore(boite, select);
    boite.appendChild(saisie);
    boite.appendChild(liste);
    boite.appendChild(select);
    select.classList.add("combo-select");
    select.tabIndex = -1;
    select.required = false;  // le serveur valide ; un champ caché obligatoire bloquerait l'envoi
    if (select.id) {
      saisie.id = select.id + "_recherche";
      var etiquette = document.querySelector('label[for="' + select.id + '"]');
      if (etiquette) { etiquette.setAttribute("for", saisie.id); }
    }
    if (select.disabled) { saisie.disabled = true; }

    var visibles = [];
    var actif = -1;

    function texteChoisi() {
      var o = select.options[select.selectedIndex];
      return o && o.value !== "" ? o.text : "";
    }

    function fermer() {
      liste.hidden = true;
      saisie.setAttribute("aria-expanded", "false");
    }

    function choisir(option) {
      select.value = option.value;
      saisie.value = option.value === "" ? "" : option.text;
      fermer();
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function marquer(index) {
      var items = liste.querySelectorAll("li[role=option]");
      actif = Math.max(0, Math.min(items.length - 1, index));
      items.forEach(function (li, i) { li.classList.toggle("actif", i === actif); });
      if (items[actif]) { items[actif].scrollIntoView({ block: "nearest" }); }
    }

    function afficher(filtre) {
      var recherche = sansAccent(filtre).trim();
      var mots = recherche ? recherche.split(/\s+/) : [];
      liste.innerHTML = "";
      visibles = options.filter(function (o) {
        if (o.disabled) { return false; }
        var texte = sansAccent(o.text);
        return mots.every(function (mot) { return texte.indexOf(mot) !== -1; });
      });
      visibles.slice(0, 300).forEach(function (o) {
        var li = document.createElement("li");
        if (o.dataset && o.dataset.image) {
          var image = document.createElement("img");
          image.src = o.dataset.image;
          image.alt = "";
          image.loading = "lazy";
          li.appendChild(image);
          li.appendChild(document.createTextNode(o.text || "—"));
        } else {
          li.textContent = o.text || "—";
        }
        li.setAttribute("role", "option");
        if (o.value === select.value && o.value !== "") { li.classList.add("choisi"); }
        li.addEventListener("mousedown", function (e) { e.preventDefault(); choisir(o); });
        liste.appendChild(li);
      });
      if (!visibles.length) {
        var vide = document.createElement("li");
        vide.className = "vide";
        vide.textContent = "Aucun résultat";
        liste.appendChild(vide);
      }
      actif = -1;
      liste.hidden = false;
      saisie.setAttribute("aria-expanded", "true");
    }

    saisie.value = texteChoisi();
    saisie.addEventListener("focus", function () { saisie.select(); afficher(""); });
    saisie.addEventListener("click", function () { if (liste.hidden) { afficher(""); } });
    saisie.addEventListener("input", function () { afficher(saisie.value); });
    saisie.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (liste.hidden) { afficher(""); }
        marquer(actif + (e.key === "ArrowDown" ? 1 : -1));
      } else if (e.key === "Enter" && !liste.hidden) {
        e.preventDefault();
        if (visibles.length) { choisir(visibles[Math.max(actif, 0)]); }
      } else if (e.key === "Escape") {
        saisie.value = texteChoisi();
        fermer();
      }
    });
    saisie.addEventListener("blur", function () {
      window.setTimeout(function () { saisie.value = texteChoisi(); fermer(); }, 120);
    });
  }

  document.querySelectorAll("select:not([multiple]):not([data-sans-recherche])").forEach(rendreCherchable);

  // --- Galerie de photos (chambres) : glisser du doigt, flèches, vignettes ---------------------
  function activerGalerie(galerie) {
    var piste = galerie.querySelector(".galerie-piste");
    if (!piste || galerie.getAttribute("data-galerie-active")) { return; }
    galerie.setAttribute("data-galerie-active", "1");
    var vignettes = galerie.querySelectorAll("[data-galerie-index]");
    function rang() { return piste.clientWidth ? Math.round(piste.scrollLeft / piste.clientWidth) : 0; }
    function aller(i) {
      var n = piste.children.length;
      if (!n) { return; }
      i = (i + n) % n;
      piste.scrollTo({ left: i * piste.clientWidth, behavior: "smooth" });
    }
    function marquer() {
      var i = rang();
      Array.prototype.forEach.call(vignettes, function (b, k) { b.classList.toggle("actif", k === i); });
    }
    galerie.querySelectorAll("[data-galerie-pas]").forEach(function (b) {
      b.addEventListener("click", function () { aller(rang() + parseInt(b.getAttribute("data-galerie-pas"), 10)); });
    });
    Array.prototype.forEach.call(vignettes, function (b) {
      b.addEventListener("click", function () { aller(parseInt(b.getAttribute("data-galerie-index"), 10)); });
    });
    piste.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight") { e.preventDefault(); aller(rang() + 1); }
      if (e.key === "ArrowLeft") { e.preventDefault(); aller(rang() - 1); }
    });
    var minuterie = null;
    piste.addEventListener("scroll", function () { window.clearTimeout(minuterie); minuterie = window.setTimeout(marquer, 80); });
    marquer();
  }
  window.activerGalerie = activerGalerie;
  document.querySelectorAll("[data-galerie]").forEach(activerGalerie);

  // Menu du site (téléphone, tablette) : il se referme quand on choisit un lien, touche ailleurs ou appuie sur Échap.
  document.querySelectorAll("details.v-menu-site").forEach(function (menu) {
    menu.addEventListener("click", function (e) { if (e.target.closest("a")) { menu.open = false; } });
    document.addEventListener("click", function (e) { if (menu.open && !menu.contains(e.target)) { menu.open = false; } });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { menu.open = false; } });
  });

  // Photo prise : elle part tout de suite, sans bouton de plus à toucher.
  document.querySelectorAll("input[type=file][data-envoi-auto]").forEach(function (champ) {
    champ.addEventListener("change", function () {
      if (!champ.files.length) { return; }
      var etiquette = champ.closest("label");
      var n = champ.files.length;
      if (etiquette) { etiquette.firstChild.textContent = n > 1 ? "Envoi de " + n + " photos… " : "Envoi de la photo… "; }
      champ.form.submit();
    });
  });

  // --- Billetage : total des espèces à partir des billets et pièces --------------------------
  // Toucher l'image d'un billet ajoute 1 ; « − » enlève 1 ; le nombre peut aussi se taper.
  document.querySelectorAll(".billet").forEach(function (billet) {
    var champ = billet.querySelector("input");
    var total = billet.querySelector(".billet-total");
    var valeur = parseInt(billet.getAttribute("data-valeur"), 10);
    var maj = function () {
      var n = Math.max(parseInt(champ.value, 10) || 0, 0);
      total.textContent = n ? n + " × " + valeur.toLocaleString("fr-FR") + " = " + (n * valeur).toLocaleString("fr-FR") : "";
      billet.classList.toggle("compte", n > 0);
    };
    billet.addEventListener("click", function (e) {
      var b = e.target.closest("[data-plus], [data-moins]");
      if (!b) { return; }
      var n = Math.max((parseInt(champ.value, 10) || 0) + (b.hasAttribute("data-plus") ? 1 : -1), 0);
      champ.value = n || "";
      champ.dispatchEvent(new Event("input", { bubbles: true }));
      if (b.classList.contains("billet-image")) {
        b.classList.remove("touche");
        void b.offsetWidth;  // relance la petite animation à chaque toucher
        b.classList.add("touche");
      }
    });
    champ.addEventListener("input", maj);
    maj();
  });

  var grille = document.querySelector("[data-billetage]");
  if (grille) {
    var total = document.getElementById(grille.getAttribute("data-billetage"));
    grille.addEventListener("input", function () {
      var somme = 0, saisi = false;
      grille.querySelectorAll("input[data-valeur]").forEach(function (champ) {
        var n = parseInt(champ.value, 10);
        if (!isNaN(n) && n > 0) { somme += n * parseInt(champ.getAttribute("data-valeur"), 10); saisi = true; }
      });
      if (saisi && total) { total.value = somme; total.dispatchEvent(new Event("input", { bubbles: true })); }
    });
  }

  // --- Remise : Orange Money, MTN MoMo — « 10000+5000 », le total s'affiche en dessous ----------
  document.querySelectorAll("[data-total-de]").forEach(function (total) {
    var champ = document.getElementById(total.getAttribute("data-total-de"));
    if (!champ) { return; }
    var recalculer = function () {
      var somme = 0;
      champ.value.split("+").forEach(function (terme) {
        var n = parseInt(terme.replace(/\s/g, ""), 10);
        if (!isNaN(n) && n > 0) { somme += n; }
      });
      total.textContent = somme.toLocaleString("fr-FR");
      var lettres = total.parentNode.querySelector(".en-lettres");
      if (!lettres) {
        lettres = document.createElement("span");
        lettres.className = "en-lettres";
        total.parentNode.appendChild(lettres);
      }
      lettres.textContent = somme ? francsEnLettres(somme) : "";
    };
    champ.addEventListener("input", recalculer);
    recalculer();
  });

  // --- Moyen de paiement : la référence n'est demandée que pour une carte ou un chèque ---------
  var moyen = document.getElementById("id_moyen");
  var blocReference = document.getElementById("bloc-reference");
  if (moyen && blocReference) {
    var majReference = function () {
      blocReference.style.display = (moyen.value === "CARTE" || moyen.value === "CHEQUE") ? "" : "none";
    };
    moyen.addEventListener("change", majReference);
    majReference();
  }

  // --- Vente comptoir : n'afficher que les champs utiles au règlement (cash, crédit, offre) ----
  var reglement = document.getElementById("id_reglement");
  if (reglement) {
    var blocs = document.querySelectorAll("[data-si-reglement]");
    var afficherBlocs = function () {
      blocs.forEach(function (bloc) {
        bloc.style.display = bloc.getAttribute("data-si-reglement") === reglement.value ? "" : "none";
      });
    };
    reglement.addEventListener("change", afficherBlocs);
    afficherBlocs();
  }

  // --- Remise : bouton actif seulement quand le motif exigé est saisi -------------------------
  var motif = document.querySelector("[data-motif-obligatoire]");
  var remettre = document.getElementById("bouton-remettre");
  if (motif && remettre) {
    var etat = function () { remettre.disabled = motif.value.trim().length === 0; };
    motif.addEventListener("input", etat);
    etat();
  }

  // --- Écran verrouillé après quelques minutes sans activité (voir accounts/verrouillage.py) -------
  var minutesVerrou = parseInt(document.body.getAttribute("data-verrouillage") || "0", 10);
  var urlVerrou = document.body.getAttribute("data-url-verrouille");
  var urlPresence = document.body.getAttribute("data-url-presence");
  if (minutesVerrou > 0 && urlVerrou) {
    var delaiVerrou = minutesVerrou * 60000;
    var derniereActivite = Date.now(), dernierSignal = Date.now();
    var CLE_COMMUNE = "st-elie-activite";  // partagée entre les onglets : un onglet actif garde les autres ouverts
    var lireCommune = function () {
      try { return parseInt(window.localStorage.getItem(CLE_COMMUNE) || "0", 10) || 0; } catch (err) { return 0; }
    };
    var verrouiller = function () {
      window.location.href = urlVerrou + "?suite=" + encodeURIComponent(window.location.pathname + window.location.search);
    };
    var signaler = function () {
      var jeton = document.querySelector('meta[name="csrf-token"]');
      if (!window.fetch || !urlPresence) { return; }
      window.fetch(urlPresence, { method: "POST", credentials: "same-origin",
                                  headers: { "X-CSRFToken": jeton ? jeton.getAttribute("content") : "" } })
        .then(function (r) { return r.status === 200 ? r.json() : null; })
        .then(function (d) { if (d && d.verrouille) { verrouiller(); } })
        .catch(function () {});
    };
    var noterActivite = function () {
      derniereActivite = Date.now();
      try { window.localStorage.setItem(CLE_COMMUNE, String(derniereActivite)); } catch (err) { /* navigation privée */ }
      if (derniereActivite - dernierSignal > 120000) { dernierSignal = derniereActivite; signaler(); }
    };
    ["pointerdown", "keydown", "wheel", "touchstart"].forEach(function (ev) {
      document.addEventListener(ev, noterActivite, { passive: true });
    });
    window.setInterval(function () {
      if (Date.now() - Math.max(derniereActivite, lireCommune()) > delaiVerrou) { verrouiller(); }
    }, 15000);
  }

  // --- Un envoi par formulaire : un double appui ne compte pas deux fois -----------------------
  // Chaque formulaire reçoit un numéro d'envoi (vérifié par le serveur, core/envois.py) ; après le premier
  // envoi, ses boutons se grisent le temps que la page suivante arrive.
  function numeroEnvoi() {
    var aleatoire = window.crypto && window.crypto.getRandomValues ? window.crypto.getRandomValues(new Uint32Array(4)) : null;
    return aleatoire ? Array.prototype.map.call(aleatoire, function (n) { return n.toString(36); }).join("")
      : String(Date.now()) + Math.random().toString(36).slice(2);
  }
  document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(function (form) {
    var champ = document.createElement("input");
    champ.type = "hidden";
    champ.name = "_envoi";
    champ.value = numeroEnvoi();
    form.appendChild(champ);
  });
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (e.defaultPrevented || (form.getAttribute("method") || "").toLowerCase() !== "post") { return; }
    if (form.dataset.envoye === "1") { e.preventDefault(); return; }
    form.dataset.envoye = "1";
    window.setTimeout(function () {
      form.querySelectorAll('button:not([type="button"]), input[type="submit"]').forEach(function (b) {
        b.disabled = true;
        b.classList.add("en-cours");
      });
    }, 0);
  });
  // Retour arrière vers une page déjà envoyée : on peut de nouveau s'en servir.
  window.addEventListener("pageshow", function (e) {
    if (!e.persisted) { return; }
    document.querySelectorAll("form[data-envoye]").forEach(function (form) {
      delete form.dataset.envoye;
      form.querySelectorAll(".en-cours").forEach(function (b) { b.disabled = false; b.classList.remove("en-cours"); });
    });
  });

  // --- Une autre personne se connecte sur ce navigateur (autre onglet) : cette page n'est plus valable ----
  var moi = document.body.getAttribute("data-utilisateur");
  if (moi) {
    var CLE_PERSONNE = "st-elie-utilisateur";
    try { window.localStorage.setItem(CLE_PERSONNE, moi + "|" + document.body.getAttribute("data-utilisateur-nom")); } catch (err) { /* privé */ }
    var avertir = function (nom) {
      if (document.getElementById("autre-personne")) { return; }
      var bandeau = document.createElement("div");
      bandeau.id = "autre-personne";
      bandeau.className = "autre-personne";
      bandeau.setAttribute("role", "alert");
      bandeau.innerHTML = "<p></p><button type=\"button\" class=\"btn ok grand\">Recharger la page</button>";
      bandeau.querySelector("p").textContent = (nom || "Une autre personne") + " s'est connecté(e) sur ce navigateur, " +
        "dans un autre onglet. Cette page n'est plus valable : rechargez-la avant de continuer.";
      bandeau.querySelector("button").addEventListener("click", function () { window.location.reload(); });
      document.body.appendChild(bandeau);
    };
    window.addEventListener("storage", function (e) {
      if (e.key !== CLE_PERSONNE || !e.newValue) { return; }
      var morceaux = e.newValue.split("|");
      if (morceaux[0] !== moi) { avertir(morceaux[1]); }
    });
  }

  // --- Page d'accueil : diaporama, galerie qui défile, apparition des blocs ---------------------
  var calme = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var diaporama = document.querySelector("[data-diaporama]");
  if (diaporama && !calme) {
    var diapos = diaporama.querySelectorAll(".v-diapo");
    var courante = 0;
    if (diapos.length > 1) {
      window.setInterval(function () {
        diapos[courante].classList.remove("active");
        courante = (courante + 1) % diapos.length;
        diapos[courante].classList.add("active");
      }, 6000);
    }
  }

  var ruban = document.querySelector("[data-defile]");
  if (ruban && !calme) {
    var pauseJusqua = 0;
    var pause = function () { pauseJusqua = Date.now() + 8000; };
    ["touchstart", "mouseenter", "wheel"].forEach(function (ev) { ruban.addEventListener(ev, pause, { passive: true }); });
    window.setInterval(function () {
      if (Date.now() < pauseJusqua || ruban.scrollWidth <= ruban.clientWidth + 4) { return; }
      var tuile = ruban.querySelector(".v-tuile");
      var pas = tuile ? tuile.getBoundingClientRect().width + 12 : ruban.clientWidth;
      if (ruban.scrollLeft + ruban.clientWidth >= ruban.scrollWidth - 8) {
        ruban.scrollTo({ left: 0, behavior: "smooth" });
      } else {
        ruban.scrollBy({ left: pas, behavior: "smooth" });
      }
    }, 4500);
  }

  var aMontrer = document.querySelectorAll(".v-apparait");
  if (aMontrer.length) {
    if (calme || !("IntersectionObserver" in window)) {
      aMontrer.forEach(function (el) { el.classList.add("visible"); });
    } else {
      var observateur = new IntersectionObserver(function (entrees) {
        entrees.forEach(function (entree) {
          if (entree.isIntersecting) {
            entree.target.classList.add("visible");
            observateur.unobserve(entree.target);
          }
        });
      }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
      aMontrer.forEach(function (el) {
        var rang = Array.prototype.indexOf.call(el.parentNode.children, el);
        el.style.transitionDelay = Math.min(rang, 5) * 90 + "ms";
        observateur.observe(el);
      });
    }
  }
})();
