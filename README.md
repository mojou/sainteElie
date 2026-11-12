# Gestion du Complexe St Élie Palace

Application de gestion d'un hôtel : réception et séjours, caisse par réceptionniste avec remise de caisse,
personnel (planning, pointage, congés), paie, stock, dépenses et bilan, projets internes.

Pile : **Python 3.12 + Django 5.2**, gabarits serveur, CSS/JS sans dépendance (mobile d'abord), PDF avec reportlab.
SQLite en développement, PostgreSQL ou MySQL en production. Montants en entiers FCFA.

## Démarrage (Windows / PowerShell)

```powershell
C:\Python312\python.exe -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env          # DJANGO_DEBUG=true pour le développement local
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py seed_demo --sejours   # données de démonstration (pas en production)
.\.venv\Scripts\python manage.py runserver
```

### Mise en service réelle (sans données de démonstration)

```powershell
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py charger_saint_elie     # 38 chambres + catalogue bar (96) et boutique (24) des fiches
.\.venv\Scripts\python manage.py creer_equipe           # les 10 comptes du personnel, noms provisoires
```

Base déjà remplie par la démonstration ou par des essais : `manage.py effacer_donnees_test` montre ce qui sera
effacé, `manage.py effacer_donnees_test --oui` l'efface. Restent l'établissement, les chambres et leurs prix, le
catalogue (bar, boutique, carte), les caisses et leurs réglages, les horaires du planning, le personnel. Le stock
repart de 0, les reçus du numéro 1, les salaires fictifs de la démonstration sont remis à 0, et chaque compte qui
avait encore `Demo1234!` reçoit un mot de passe provisoire (affiché à la fin). Copier `db.sqlite3` avant.

Puis, connecté en gérant (`ducart`) : renommer chacun (Administration → Utilisateurs, Personnel → Employés) et lui
faire changer mot de passe et code PIN (Mon compte) ; vérifier les prix des chambres (menu Chambres, chargés depuis la
grille de la direction) ; deux caisses dans
Paramètres → Caisse (« Réception » au poste Réception, « Cuisine / Bar » au poste Cuisine / Bar), chacune avec son
fond ; la carte des plats (Stock → Nouvel article, catégorie « Cuisine (carte des plats) ») ; et **inventaire de
départ** (Stock → Inventaire / livraison groupée) : c'est le S.I. des premières fiches.

- Application : http://127.0.0.1:8000
- Tests : `.\.venv\Scripts\python manage.py test tests`
- `creer_equipe` accepte `--mot-de-passe` et `--pin` pour choisir le mot de passe et le code PIN provisoires.

### Les comptes du personnel (démonstration comme mise en service)

Démonstration (`seed_demo`) : mot de passe `Demo1234!`, code PIN `1234` pour tous. En service : chacun reçoit un
mot de passe provisoire (affiché par `effacer_donnees_test`, ou choisi avec `creer_equipe --mot-de-passe`) et choisit
le sien et son code PIN à sa première connexion. Le gérant peut redonner un mot de passe provisoire à quelqu'un
(Administration → Utilisateurs).

| Identifiants | Équipe | Rôle |
|---|---|---|
| `ducart` | Administration | M. Ducart, gérant : tout, y compris paie, finances, paramètres, utilisateurs |
| `julio`, `germain` | Administration | M. Julio et M. Germain, adjoints de direction : valident les caisses, suivent toute l'activité (réception, stock, planning, rapports, alertes) ; pas la paie, les finances ni les paramètres |
| `adelaide` | Gouvernante | Mme Adélaïde : encadre la réception / boutique, la cuisine / bar et les chambres / blanchisserie (planning, pointages, congés), le stock, les chambres et séjours ; valide les caisses ; pas de caisse à elle, ni paie, finances ou paramètres |
| `carine`, `nina`, `junior` | Réception / boutique | Carine, Nina, Junior : réceptionnistes (R1, R2, R3 sur les fiches, dans l'ordre de prise de service) : chambres, boutique, extras, caisse « Réception » |
| `aurelle`, `merveille`, `liliane` | Cuisine / bar | Aurelle, Merveille, Liliane : boissons et plats sur la caisse « Cuisine / Bar » (celle d'Aurelle est ouverte en démo) |

Les gestionnaires de chambre / blanchisserie (Carine, Benedite, Blondelle) et le gardien **n'ont pas de compte** : ils figurent seulement dans les salaires
(Personnel → Employés, Paie). La réception relaie leurs informations : elle touche « Faite » quand le ménage lui dit
qu'une chambre est prête (écran Réception, « Chambres à nettoyer ») et tient la **main courante du gardien**. Pas de
compte maintenance non plus : la réception signale les pannes, la direction les suit et note qu'elles sont réparées.

## Modules

| Module | Contenu |
|---|---|
| Réception (`hotel`) | Chambres et tarifs, clients, séjours (réservé → en cours → terminé / annulé / no-show), disponibilité en temps réel, check-in/out, nuitées, extras sur la note, ménage |
| Caisse (`caisse`) | Session par réceptionniste et par shift, encaissements avec reçu numéroté, sorties de caisse, remise à l'aveugle, validation, rapport quotidien PDF, virements |
| Personnel (`personnel`) | Employés, créneaux, planning de la semaine, pointage, congés, échanges de shift |
| Paie (`paie`) | Fiches de paie mensuelles, acomptes déduits, bulletins PDF |
| Vente comptoir (`caisse`) | Main courante bar et boutique tenue par le réceptionniste : cash (espèces, Orange Money ou MTN MoMo), crédit sur la note d'une chambre ou au compte d'un client, offre motivée ; avaries ; règlement des dettes clients |
| Fiches du jour (`fiches`) | Les fiches papier, remplies automatiquement et imprimables en PDF : main courante bar, stock bar, stock et main courante boutique (R1/R2/R3), recette chambres |
| Stock (`stock`) | Articles bar / boutique / restaurant / magasin avec contenance (code) et prix de vente, approvisionnements, avaries, inventaire, saisie groupée, alerte de stock bas |
| Finances (`finances`) | Dépenses générales avec justificatif, bilan du mois (recettes, charges, taux d'occupation) |
| Projets (`projets`) | Projets internes et tâches assignées |
| Socle (`core`, `accounts`) | Rôles, code PIN de signature, alertes, journal d'activité, paramètres |

## Une page de saisie par département

À la connexion, chacun arrive sur la page de son département : c'est l'écran qui reste ouvert sur son poste toute la
journée (même en-tête partout : département, date, état de la caisse, « Signaler une panne »).

| Département | Page de saisie | Ce qu'on y fait |
|---|---|---|
| Réception · chambres | `/poste/reception/` | **Le plan des chambres** (une case de couleur par chambre : libre en vert, occupée en bleu, à nettoyer en orange, hors service en rouge), arrivées attendues (« Il est arrivé »), chambres à nettoyer (« Faite »). On touche une chambre : seules ses actions s'affichent (voir plus bas) |
| Boutique | Point de vente « Boutique » | Ventes de la réception |
| Cuisine / Bar | Point de vente « Restaurant · Bar » | Boissons et plats : payés sur place, ou à crédit sur la chambre (payés à la réception) |
| Ménage et nettoyage | — (pas de compte) | La réception note les chambres faites ; fiche employé pour la paie |
| Maintenance | `/poste/maintenance/` | Problèmes de chambre signalés par la réception ; la maintenance clique « Je m'en occupe », « Réparé » ; chambre hors service le temps des travaux |
| Gardiennage | `/poste/securite/` (réception) | Pas de compte : la réception note rondes, visiteurs, livraisons, incidents ; fiche employé pour la paie |

Le département vient de la fiche employé (Personnel → Employés) pour la maintenance et la sécurité. Le gérant et les
chefs retrouvent toutes ces pages dans « Saisies des départements ».

## Pour des opérateurs peu à l'aise avec l'informatique

Analyse du 11/11/2026 : chaque écran du personnel suit « une question à la fois, de gros boutons, des mots du
quotidien ».

**Réception : le plan des chambres.** On touche une chambre et seules les actions possibles s'affichent :
- libre : « Un client arrive », en 4 étapes, une question par écran : qui est le client (nom, téléphone), combien de
  nuits (boutons 1, 2, 3, 4, 5, 7 ; prix et date de départ calculés), combien il paie maintenant (« Tout », « Une
  nuit », « Rien maintenant », payé en Espèces / Orange Money / MTN MoMo), puis un récapitulatif à vérifier avant
  « Installer le client » ;
- réservée pour aujourd'hui : « Il est arrivé » ;
- occupée : reste à payer en gros, « Encaisser » (montant proposé, moyen en un toucher), « Ajouter un repas ou une
  boisson », « Le client part » ;
- à nettoyer : « Chambre faite » ; hors service : les pannes en cours.

**Le point de vente : « Boutique » pour la réception, « Restaurant · Bar » pour la cuisine et le bar.** Chacun voit
celui de sa caisse : un réceptionniste ne vend que la boutique (avec un bouton « Chambres » pour revenir au plan ; la
« Boutique » est aussi un gros bouton en haut du plan des chambres et dans le menu), l'équipe cuisine / bar vend boissons
et plats. L'écran prend toute la page, comme une caisse enregistreuse :
- à gauche, **la commande** : chaque ligne avec quantité et montant ; on touche une ligne puis on tape sa quantité sur le
  **pavé** (1 à 9, 0, −1, ⌫) ; le total en chiffres et en lettres ; « Vider » et « Paiement » ;
- à droite, **les articles** en tuiles (photo, prix en pastille, stock restant), une recherche et les familles (« Les
  plus vendus » des 30 derniers jours, puis chaque rubrique ; une boisson du bar sans rubrique est sous « Bar » : le
  gérant peut lui en donner une dans Stock pour créer « Bières », « Sucreries »…) ;
- **Paiement** ouvre un écran à part : à gauche **Espèces, Orange Money, MTN MoMo, Sur sa chambre, À crédit ou Offert**,
  à droite le montant à payer en gros ; en espèces, « Le client donne » (le compte juste, + 500, + 1 000… ou tapé) calcule
  la monnaie à rendre. « Valider » dit exactement ce qui sera enregistré ;
- après « Valider », un **écran de fin** : « C'est enregistré », la monnaie rendue, « Imprimer le reçu », « Nouvelle
  commande ». « Mes ventes » liste les ventes de la caisse, avec « Annuler ».

Sur téléphone, les articles d'abord ; une barre en bas montre la commande en cours (« Voir la commande »). Payée tout de
suite, la commande entière fait **un seul reçu**. Tout ou rien : s'il manque un article en stock, rien n'est enregistré.
**Annuler une ligne d'un reçu annule toute la commande** (chaque article revient en stock), puis on ressaisit la bonne.
La commande en cours survit à un écran verrouillé ou à une page quittée.

**Fermer ma caisse : on touche les billets.** Chaque billet et chaque pièce a son image : un toucher = un de plus,
« − » pour corriger ; le nombre peut aussi se taper. Le total des espèces se calcule tout seul.

**Montants en toutes lettres.** Sous chaque montant tapé : « deux cent cinquante mille francs ». Pour l'argent reçu ou
compté, au-delà de 100 000 FCFA (`MONTANT_A_CONFIRMER`) ou au-delà de ce que le client doit, une fenêtre demande
« C'est bien ça ? » avec le montant en chiffres et en lettres ; « Non, je corrige » est choisi par défaut. Le reçu
imprimé porte aussi le montant en lettres.

**Mots du quotidien et petits « ? ».** « Fermer ma caisse » (pas « remise »), « Votre service » (pas « shift »),
« Casse ou périmé » (pas « avarie »), « Différence » (pas « écart »), « Sortir de l'argent », « Message pour la
personne suivante »… Les mots qui restent (fond de caisse, extras, crédit, offert, reste à payer, main courante, code
PIN…) ont un « ? » qui les explique en une phrase ; toutes ces phrases sont dans `core/aides.py`.

**Écran verrouillé et relève par code PIN.** Après 10 minutes sans toucher l'écran ni le clavier
(`VERROUILLAGE_MINUTES`, 0 pour désactiver), l'écran se verrouille : la personne reprend avec son code PIN, là où elle
était. À la relève, la collègue touche son prénom et tape son propre code PIN : c'est alors elle qui travaille sur
l'écran (bouton « ⇄ Changer de personne » en haut pour le faire tout de suite). Seul le personnel de la même équipe
(réception, ou cuisine / bar) peut prendre l'écran ainsi ; la direction et les chefs passent par leur mot de passe, et un
code PIN provisoire ne marche pas. 5 codes faux bloquent ce code PIN 15 minutes, comme ailleurs ; chaque prise d'écran est
notée au journal. Les clients, sur leur propre téléphone, ne sont jamais verrouillés.

**Fiches papier imprimées par l'application** (Fiches du jour) : « Chambres à faire » (chaque chambre et quoi y faire :
ménage complet après un départ, recouche, départ prévu, arrivée à préparer ; colonnes Faite, Par qui, Heure,
Remarques), que le personnel des chambres rapporte cochée à la réception ; « Main courante du gardien », feuille vierge
pour la nuit (heure, ronde, visiteur, livraison, incident), recopiée le matin par la réception.

**Mises à jour visibles tout de suite.** Les adresses des styles et des scripts portent un numéro de version : après une
mise à jour, les navigateurs rechargent les nouveaux fichiers au lieu de garder les anciens.

## Planning, projets, rapports et stock (refonte du 11/11/2026)

**Planning** (Personnel → Planning), comme un tableau de planification : une ligne par personne, rangée par
département, une colonne par jour (vue Semaine ou Mois), chaque créneau en pastille de couleur avec ses heures. On
touche « + » dans une case pour ajouter un créneau, un créneau pour le changer ou le retirer ; à la souris, on le glisse
vers un autre jour ou une autre personne. Les congés accordés sont barrés ; chaque ligne affiche ses heures, chaque jour
le nombre de présents par créneau. « Copier la semaine précédente » recopie tout d'un coup. Le serveur refuse un créneau
pendant un congé, réservé à un autre département, ou qui chevauche un autre créneau de la même personne (la nuit
23 h → 7 h compte jusqu'au lendemain matin). Imprimable pour l'affichage.

**Projets** (Projets internes) : les projets en cartes (avancement, échéance en rouge si dépassée, tâches en cours ou
bloquées) ; dans un projet, les tâches en colonnes **À faire, En cours, Bloquée, Faite**, qu'on fait glisser d'une
colonne à l'autre ; une ligne « + Nouvelle tâche » en haut de chaque colonne ; l'étoile marque une tâche prioritaire.
Chaque tâche a sa fiche avec une **discussion** : les messages de l'équipe, et chaque changement d'étape ou de personne
noté tout seul. La personne chargée d'une tâche la voit dans « Mes tâches » et change son étape ; seule l'encadrement
modifie la fiche.

**Rapports** (Pilotage → Rapports) : sur n'importe quelle période (aujourd'hui, hier, cette semaine, la semaine
dernière, ce mois, le mois dernier, cette année, ou du … au …), comparée à la période d'avant de même nature :
recette, argent encaissé, taux d'occupation, prix moyen d'une nuit, recette par chambre disponible, nuits vendues ;
recette jour par jour (mois par mois sur une année) par service — hébergement, restaurant · bar, boutique — avec le
détail au survol et le tableau des chiffres ; encaissements par moyen de paiement ; articles qui rapportent le plus ;
stock (livraisons, ventes, casse, manquants) ; caisses par personne (encaissé, différences). Le gérant voit aussi les
dépenses. Rien n'est compté deux fois : un repas « sur la chambre » est un extra de la note, une seule fois ; l'offert
n'est pas une recette. Téléchargeable pour Excel. Les rapports quotidiens de caisse (contrôle des remises) restent à
part.

**Inventaire et rentabilité** (Stock → Inventaire et rentabilité, ou depuis le rapport d'activité) : sur la période
choisie, à l'écran, **en PDF à imprimer** et en fichier Excel :
- synthèse : chiffre d'affaires, marge brute sur marchandises et taux de marque, pertes et écarts, valeur du stock en fin
  de période (au coût et au prix de vente), charges et résultat (gérant), comparés à la période d'avant ;
- recettes par service (hébergement, restaurant · bar, boutique) et leur part ;
- ventes et marges par catégorie, puis **rentabilité de chaque article** : quantité vendue, prix, coût d'achat, marge
  unitaire, taux de marque, coefficient, chiffre d'affaires, marge, part du chiffre d'affaires ;
- **inventaire article par article** : début + premier comptage + livré − vendu ou offert − casse − sorties ± écart =
  fin, valeur de fin, jours de stock restants ;
- pertes et sorties : casse, écarts d'inventaire, offerts (au prix de vente et au coût), prélèvements du gérant ;
- **charges et résultat** (gérant) : recettes − dépenses par catégorie − salaires bruts (au prorata des jours) =
  résultat de gestion et marge nette, avec la part de chaque charge dans les recettes ;
- tout ce qui s'est passé dans l'application : réservations, arrivées, départs, ventes, annulations, caisses,
  livraisons, inventaires, casse, planning, pointages, congés, pannes, journal.
Règles : chiffre d'affaires d'un article = ventes payées ou à crédit (l'offert n'en fait pas partie) ; coût des ventes =
quantité × coût moyen d'achat actuel ; un article sans prix d'achat n'a pas de marge (jamais 100 %) et il est signalé en
tête du rapport, comme un mois sans fiche de paie validée, une période sans inventaire compté ou sans dépense notée. Le
stock d'un jour se calcule à partir du stock actuel et des mouvements des jours suivants : il ne dépend pas de l'heure de
l'ordinateur. Adjoints, gouvernante et chefs d'équipe voient l'inventaire et les marges ; charges et résultat restent au
gérant. Les plats n'ont pas de stock : leur coût de revient se note, si on le connaît, dans le prix d'achat de l'article.

**Le stock qui parle** : chaque article dit en mots où il en est — « Rupture », « À commander : il en reste 6, sous le
seuil de 10 », « Bientôt épuisé : environ 2 jours de vente », « Ne se vend pas : aucune vente en 30 jours », « Nouveau :
trop tôt pour juger » — avec le nombre vendu par jour (sur les jours réellement suivis, 30 au plus). Les tuiles du haut
mènent aux articles à commander, en rupture ou qui dorment. La fiche d'un article montre le stock jour après jour
(30 jours, avec le seuil) et son histoire. **Chaque mouvement est raconté** : « Vendu : 2 verres · sur la chambre 106/107
(Mme Abena Claire) · par Aurelle · stock 6 → 4 », « Livraison reçue : 24 unités · à 650 FCFA l'unité », « Inventaire :
2 unités manquent · compté 29, l'application attendait 31 · 1 300 FCFA au coût ». Page Mouvements : par période, type,
catégorie ou mot cherché, regroupés par jour avec leur résumé, téléchargeables pour Excel.

**Fiable au doigt** : un formulaire envoyé deux fois (double appui) n'est enregistré qu'une fois (numéro d'envoi vérifié
par le serveur, `core/envois.py`) ; une page expirée ramène simplement à la page avec une phrase claire, au lieu de
l'erreur technique « CSRF » ; si une autre personne se connecte dans un autre onglet du même navigateur, les anciens
onglets le disent et demandent de recharger.

## Page d'accueil publique et espace client

- `/` : page publique de l'hôtel (chambres et prix, restaurant, bar, boutique, moyens de paiement, contact), avec
  « Se connecter » et « Créer un compte ». Slogan, présentation, adresse et téléphone se changent dans Paramètres →
  Établissement.
- Sous le grand bandeau, un **ruban doré fait défiler les prix les plus bas** : chambres et suites « dès … », chaque
  rubrique de la carte, boissons du bar. Il suit les prix de l'application (un prix changé s'y voit aussitôt) et
  s'arrête quand on pose le doigt ou la souris dessus.
- **Réserver en ligne** : dans le grand bandeau (et via « Réserver » dans le menu du site), le visiteur choisit ses
  dates et le nombre de personnes ; il voit les chambres **réellement libres** à ces dates, regroupées par type et par
  prix, avec le prix du séjour (« Plus que 1 libre » quand il en reste peu). Il choisit, donne son nom et son téléphone
  (un mot pour la réception s'il veut), et reçoit un numéro de demande. Rien à payer en ligne.
- La demande arrive à la réception (alerte, pastille « Réservations en ligne » et bandeau sur le plan des chambres). La
  réception appelle le client si besoin, choisit la chambre (celle proposée, ou une autre libre) et touche « Confirmer
  la réservation » : le séjour « Réservé » est créé, sur la fiche du client retrouvée par son numéro ou une nouvelle.
  Ou « Refuser » avec un motif que le client voit. **Pourquoi une demande et pas une réservation immédiate** : sans
  paiement en ligne, n'importe qui pourrait bloquer toutes les chambres avec un faux numéro. La disponibilité est
  revérifiée à la confirmation. Protections : 5 demandes par heure et par appareil, champ piège à robots, 30 nuits et
  un an d'avance au plus, 6 personnes au plus.
- Un client connecté retrouve ses demandes dans son espace (à confirmer, confirmée avec la chambre, refusée avec le
  motif) et peut annuler une demande pas encore traitée.
- Un client crée son compte avec son nom et son numéro de téléphone, qui devient son identifiant. Le compte reste
  **en attente** jusqu'à ce que la réception le relie à la fiche du client (menu « Comptes clients en ligne ») :
  sans cette vérification, quiconque connaît un numéro verrait les séjours d'un autre.
- Une fois relié, le client voit son séjour en cours (total, déjà payé, reste à payer, détail des nuits et des
  extras), ses réservations à venir, ses paiements et ses séjours passés. Il ne voit jamais les écrans du personnel.
- Démonstration : client `699112233` / `Demo1234!` (relié à M. Kamga) ; un second compte attend la réception.
- **Photos** : menu « Site public » → Photos du site (gérant et adjoints), plusieurs photos d'un coup. Cinq rubriques : l'hôtel, les chambres, la réception, nos plats,
  le parking. Chaque photo est tournée dans le bon sens et réduite à 1 600 pixels (page légère sur une connexion lente) ;
  elles défilent en fondu dans le bandeau du haut (celles de « L'hôtel » d'abord). La page est animée : blocs qui
  apparaissent au défilement, galerie qui défile toute seule sur téléphone ; les animations s'arrêtent si le
  téléphone demande moins de mouvement. Une rubrique sans photo montre une illustration
  dessinée, jamais la photo d'un autre hôtel. Le personnel connecté voit la page publique sur `/site/`.

## Postes, rôles et moyens de paiement

| Rôle | Caisse | Ce qu'il fait |
|---|---|---|
| Réceptionniste | Réception | Chambres, boutique ; encaisse les chambres **et leurs extras** |
| Cuisine / Bar | Cuisine / Bar | Vend boissons et plats (payés, sur une chambre, à crédit ou offerts) |
| Adjoint de direction | Toutes | Valide les remises, suit toute l'activité |
| Gérant | Toutes | Tout, y compris paie, finances et paramètres |

**Extras** : saisis à la réception, ou à la cuisine / bar (« Sur sa chambre »), ils figurent sur
la fiche du réceptionniste (colonne « Extras jr » et liste des extras du jour) et se paient à la réception avec la
chambre. Écran en deux gestes : toucher la chambre, choisir le plat (prix calculé) ou écrire autre chose.

**Repas et boissons** : la cuisine et le bar sont une seule équipe avec une seule caisse « Cuisine / Bar ». Un client
qui paie tout de suite (client de passage, ou client de l'hôtel avec son argent) paie à cette caisse ; un client de
l'hôtel à crédit a un **extra** sur sa chambre, payé à la réception. La réception ne vend pas de plats. Fiches : main
courante bar, main courante cuisine, stock bar.

**Simplicité** : le personnel de terrain voit un menu court et un accueil « Que voulez-vous faire ? » à gros boutons ;
la cuisine / bar arrive directement sur son écran de vente. Le gérant et les adjoints gardent le menu complet.

- Partout, « Payé en » propose **Espèces, Orange Money, MTN MoMo** (et Carte, Chèque pour les chambres). Orange Money
  et MTN MoMo sont de simples moyens de paiement : pas de compte à configurer, pas de numéro, pas de référence ni de
  solde à saisir. Écrans, reçus, rapports, bilan et fiches donnent le total de chacun.
- **Toutes les listes déroulantes se filtrent en tapant** quelques lettres (sans souci des accents ni des majuscules) :
  chambre, client, article, personne… Les flèches et Entrée fonctionnent au clavier.

## Règles de gestion appliquées

Réception et caisse suivent la version corrigée du complément au cahier des charges.

- **Disponibilité** : une réservation porte sur des nuits ; un départ le 12 et une arrivée le 12 ne se gênent pas.
  Un chevauchement est refusé avec un message clair (« La chambre 101 est déjà réservée du … au … »).
- **Tarif** : pré-rempli depuis la chambre ; un autre tarif exige un motif, une remise au-delà du plafond (20 % par défaut)
  exige le code PIN du chef de réception ou du gérant.
- **Recette ≠ encaissement** : la recette (nuitées, extras) est constatée nuit par nuit ; l'encaissement est l'argent reçu,
  par personne et par mode. Les écrans et le rapport présentent les deux séparément.
- **Session de caisse** : une seule ouverte par tiroir et par personne. L'entrant compte le fond à l'ouverture ;
  un fond incomplet est signalé et reste à la charge de la session précédente.
- **Sorties de caisse** : petite dépense (validation du chef au-delà du plafond) ou prélèvement du gérant (son code PIN).
  Espèces attendues = ouverture + encaissements espèces − remboursements − sorties.
- **Remise** : comptage à l'aveugle (l'attendu s'affiche après la saisie), un seul recomptage, premier comptage conservé ;
  motif obligatoire au-delà du seuil (1 000 FCFA par défaut) ; versement = compté − fond ; reçu PDF signé (identifiant,
  code PIN, horodatage serveur).
- **Validation** : la remise débloque le shift suivant ; la validation (chef de réception ou gérant, jamais l'auteur)
  peut attendre — alerte au-delà de 24 h. Un écart se valide avec une décision d'arbitrage. Session validée = verrouillée.
- **Rien n'est supprimé** : un encaissement s'annule par une écriture inverse motivée ; après la remise, seule une
  session rectificative (chef ou gérant) peut corriger.
- **Orange Money, MTN MoMo** : à la clôture, la personne tape ce qu'elle a reçu sur le téléphone ; plusieurs
  paiements se tapent avec un + entre eux (10000+5000), le total s'affiche en dessous. L'écran suivant compare au montant enregistré ; un écart au-delà du seuil exige un motif. Pas d'API opérateur.
- **Rapport quotidien** : produit à l'heure de coupure (16 h par défaut) ; une session entre dans le premier rapport qui
  suit sa remise. Il liste encaissements par personne, recettes constatées, écarts, sorties, impayés et chambres faites
  sans séjour enregistré.
- **Alertes** : écart hors seuil, 3 écarts en 30 jours (par personne, par shift), annulation,
  validation en retard, dépense à valider, stock bas, chambre faite sans séjour.

Tous les seuils et plafonds se règlent dans **Paramètres → Caisse**, avec date d'effet.

### Carte de la cuisine

Chargée depuis le menu « Complexe St Élie Palace » (photos du 11/11/2026) par `charger_saint_elie` : 20 plats chauds,
5 garnitures, 1 dessert, petit-déjeuner, salade et boissons chaudes, chacun dans sa **rubrique** avec sa composition.
Elle s'affiche sur la page d'accueil (« Notre carte ») et dans l'écran de vente Cuisine / Bar (« Plats chauds · Poulet
DG — 3 500 FCFA »). Un plat n'a pas de stock. Un prix modifié dans l'application n'est jamais écrasé par un rechargement.

### Stock

- **Coût moyen pondéré** : chaque livraison saisie avec son prix d'achat (Stock → saisie groupée, colonne « Prix
  d'achat unitaire ») recalcule le coût de l'article : le stock restant garde son coût, la livraison apporte le sien.
  La valeur du stock et la **marge par unité** (affichée en rouge si nulle ou négative) en découlent.
- **Écarts d'inventaire** (Stock → Écarts d'inventaire) : chaque manquant au comptage est chiffré au coût et au prix
  de vente, et signalé au gérant. Un manquant répété sur le même article : casse non déclarée, vente non saisie, vol.
- Avaries et sorties (consommation interne) exigent un motif ; le stock ne peut pas devenir négatif ; deux ventes
  simultanées ne faussent pas le compte (verrouillage de la ligne).
- **Chaque article a une image.** Tant qu'il n'a pas sa photo, l'application dessine la sienne d'après son nom
  (`stock/illustrations.py`) : bière, soda en verre ou en plastique aux couleurs du parfum, canette, eau, whisky, vin,
  mousseux, verre « conso », plat, bouillon, tasse, brosse à dents, sac… Jamais de logo ni de photo d'une marque.
  **Stock → Photos des articles** : sur téléphone, « Prendre la photo » ouvre l'appareil photo ; la photo remplace le
  dessin partout (caisse, stock), « Retirer » remet le dessin.
- **Photos** : chaque article (boisson, boutique, plat) et chaque chambre peut avoir sa photo. Elle apparaît dans la
  recherche de l'écran de vente, dans le stock, et sur la page d'accueil (chambres, plats). Toute photo est tournée,
  réduite et réenregistrée en JPEG : légère, et sans contenu caché.

### Sécurité (audit du 11/11/2026)

- 5 mots de passe faux de suite bloquent le compte 15 minutes ; 5 codes PIN faux bloquent la signature 15 minutes ;
  le gérant est prévenu. Codes PIN trop simples (1234, 0000…) refusés.
- Un compte créé avec un mot de passe provisoire (commande `creer_equipe`, ou créé / réinitialisé par le gérant)
  doit choisir son mot de passe et son code PIN à la première connexion, avant tout le reste.
- Justificatifs : photo ou PDF vérifiés (10 Mo au plus). Tout autre fichier n'est jamais affiché dans le navigateur.
- Un reçu client n'est visible que par la réception, la direction ou la personne de la caisse concernée.
- Inscriptions clients limitées à 5 par heure et par appareil ; un compte client ne voit jamais la gestion.

### Fiches du jour (formats des fiches papier)

- **Journée** : celle de l'ouverture de la session de caisse. Le réceptionniste de nuit qui ouvre à 23 h reste sur la
  fiche du jour, même pour une vente après minuit.
- **Main courante bar / boutique** : Désignation, Qté V, Cash, Crédit, Total, Offre, Obs. Total = cash + crédit + offre.
  Par réceptionniste (sa session) ou pour toute la journée.
- **Stock bar** : S.I (stock en début de journée), Appro, Avaries, S.T = S.I + appro − avaries, Qtés vendues, P.V,
  Montant, S.F (stock réel en fin de journée), puis Ventes / Crédits / Offres / Espèces / Orange Money / MTN MoMo.
- **Stock boutique** : Prix, S.I, Approv, R1, R2, R3, S.F, Montant, Cumulé (depuis le 1er du mois), Crédit ; la main
  courante boutique est imprimée dessous. R1, R2, R3 = quantités vendues par chaque réceptionniste du jour, dans l'ordre de
  leur prise de service (noms en tête de fiche) ; une colonne R4 s'ajoute si quatre réceptionnistes se succèdent.
- **Recette chambres** : pour chaque chambre, Recette jr (part de la nuit couverte par les paiements), Imp jr (part
  impayée), Offre jr et Compensation (séjours offerts ou compensés, à la valeur de la grille), Avance (payé au-delà de la
  nuit du jour) ; puis les règlements de dettes du jour et les restes de dettes (chambres et comptoir). Les paiements
  règlent d'abord les dettes des jours précédents.
- **Offre** au comptoir : motif obligatoire, sortie de stock sans recette. **Séjour offert ou en compensation** : nuit à
  0 FCFA, motif et code PIN du chef de réception ou du gérant.

## Production

- `.env` : `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`,
  `DB_ENGINE` et `DB_*`, `ETABLISSEMENT_NOM`.
- `python manage.py migrate`, `python manage.py createcachetable` (cache partagé entre les processus du serveur :
  formulaire envoyé deux fois, limite des réservations en ligne), `python manage.py collectstatic`, serveur WSGI
  (`config.wsgi`), HTTPS obligatoire.
- Planifier toutes les heures : `python manage.py taches_quotidiennes` (nuitées, rapports dus, retards de validation).
  Sans planificateur, ces tâches tournent aussi à l'ouverture du tableau de bord par le gérant ou le chef de réception.
- Sauvegarder la base **et** le dossier `private_media/` (reçus, rapports, bulletins, justificatifs : jamais servis
  directement, uniquement via des vues qui vérifient les droits).
- L'administration technique Django n'est exposée que si `DJANGO_ADMIN_URL` est défini.

## Mise en ligne sur PythonAnywhere

Adresse du site : `https://<nom-d-utilisateur>.pythonanywhere.com`. SQLite suffit pour un hôtel.

**1. Sur l'ordinateur, avant d'envoyer** : `effacer_donnees_test --oui` (voir plus haut), puis un zip du dossier
**sans** `.venv`, `.env`, `staticfiles` ni `__pycache__`, avec `db.sqlite3`.

**2. Envoyer et installer.** Onglet *Files* : envoyer le zip dans le dossier personnel. Onglet *Consoles* → *Bash* :

```bash
unzip gestion_st_elie_pythonanywhere.zip          # crée ~/gestion_st_elie
mkvirtualenv --python=/usr/bin/python3.12 st-elie
cd ~/gestion_st_elie && pip install -r requirements.txt
cat > .env <<EOF
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
DJANGO_ALLOWED_HOSTS=${USER,,}.pythonanywhere.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://${USER,,}.pythonanywhere.com
SECURE_SSL_REDIRECT=false
ETABLISSEMENT_NOM=Complexe St Élie Palace
EOF
python manage.py migrate && python manage.py createcachetable && python manage.py collectstatic --noinput
python manage.py check --deploy                   # seuls W005, W008, W021 restent : normal ici
```

Le bloc `cat > .env` se colle tel quel : il prend le nom d'utilisateur de la console et tire une clé secrète au hasard.
`SECURE_SSL_REDIRECT=false` parce que c'est PythonAnywhere qui force le HTTPS (étape 3).

**3. Onglet *Web*** → *Add a new web app* → *Manual configuration* → *Python 3.12*, puis :
- *Virtualenv* : `/home/<nom-d-utilisateur>/.virtualenvs/st-elie`
- *Source code* : `/home/<nom-d-utilisateur>/gestion_st_elie`
- *Static files* : URL `/static/`, dossier `/home/<nom-d-utilisateur>/gestion_st_elie/staticfiles`
- *Force HTTPS* : activé
- *WSGI configuration file* : remplacer tout le contenu par

```python
import os
import pwd
import sys

projet = os.path.join(pwd.getpwuid(os.getuid()).pw_dir, "gestion_st_elie")
if projet not in sys.path:
    sys.path.insert(0, projet)
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

from django.core.wsgi import get_wsgi_application  # noqa: E402
application = get_wsgi_application()
```

puis *Reload*.

**4. Onglet *Tasks*** : une tâche par jour à 05:00 (heure UTC, 6 h à Douala) :
`cd ~/gestion_st_elie && ~/.virtualenvs/st-elie/bin/python manage.py taches_quotidiennes`.
Le reste du temps, ces tâches tournent aussi quand le gérant ouvre le tableau de bord.

**5. Premier jour** : se connecter en `ducart` avec le mot de passe provisoire, choisir le sien ; donner à chacun le
sien ; vérifier l'adresse et le téléphone (Paramètres → Établissement : « Yaoundé, Cameroun » vient de la
démonstration), le fond de chaque caisse (20 000 F réception, 10 000 F cuisine / bar : valeurs de la démonstration),
les vrais salaires (Personnel → Employés) ; puis **l'inventaire de départ** (Stock → Faire l'inventaire) : tant
qu'il n'est pas fait, le stock est à 0 et le bar ne peut rien vendre (« Stock insuffisant »). Noter les prix
d'achat (marges du rapport d'inventaire), ajouter les vraies photos (Paramètres → Photos du site, Stock → Photos des
articles).

**Ensuite**
- Compte gratuit : cliquer *Run until 3 months from today* (onglet *Web*) au moins tous les 3 mois, sinon le site
  s'arrête.
- Sauvegarde : télécharger régulièrement `db.sqlite3` et le dossier `private_media/` (onglet *Files*).
- Mise à jour du programme : renvoyer **seulement le code** — jamais `db.sqlite3`, `private_media/` ni `.env`, qui
  écraseraient les données réelles — puis `workon st-elie && cd ~/gestion_st_elie && python manage.py migrate &&
  python manage.py collectstatic --noinput`, et *Reload*.

## À vérifier dans les données chargées

- Liste du bar relevée sur une photo prise de côté : contenances (65CL, 50CL…) et prix à contrôler dans Stock, en
  particulier BEAUFORT, BOOSTER, CHILL, SODA, 3X, COOKS (25 000 / 40 000 / 15 000) et MUSCATO 33CL (15 000).
- Prix des chambres : grille donnée par la direction le 11/11/2026 (de 10 000 F pour les 111 à 118 à 55 000 F pour
  la 302 ; suites 102/103, 106/107, 109/110 à 40 000 F). **105 à 20 000 F à confirmer** : la liste reçue citait deux
  fois la 205. `charger_saint_elie --tarifs` réapplique la grille ; les séjours déjà enregistrés gardent leur prix.

## À trancher avec l'exploitant

- Horaires des shifts et heure de coupure ; fond de caisse, seuil, plafonds.
- Destination du versement quand le gérant est absent (coffre, enveloppe, transmission à l'entrant — l'application gère
  les trois : l'excédent non versé est compté par l'entrant).
- Vente de chambres « de passage » (à l'heure) : non gérée, les séjours se comptent en nuits.
- Cotisations CNPS et impôt sur salaire : saisis sur la fiche, pas calculés (à fixer avec le comptable).
- Taxe de séjour éventuelle : à isoler de la recette si l'hôtel la collecte.
- Mode hors ligne : non prévu ; en cas de coupure, carnet de reçus numérotés et ressaisie ensuite.
