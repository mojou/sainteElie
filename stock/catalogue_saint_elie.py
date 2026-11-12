"""
Données de référence relevées sur les fiches papier du Saint-Élie Palace (photos du 10/11/2026).

Les contenances et prix du bar ont été lus sur une photo prise de côté : à vérifier dans
l'application (Stock → article → Modifier). Les prix « CONSO » sont des prix au verre.
"""

ETABLISSEMENT = "Complexe St Élie Palace"  # nom de l'en-tête du menu
ANCIENS_NOMS = ("", "Saint-Élie", "Saint-Élie Palace")  # noms provisoires remplacés au chargement

# Chambres, dans l'ordre de la fiche « Recette chambres ». « 102/103 », « 106/107 », « 109/110 » : suites.
CHAMBRES = (
    ["101", "102/103", "104", "105", "106/107", "108", "109/110"]
    + [str(n) for n in range(111, 119)]
    + [str(n) for n in range(201, 212)]
    + [str(n) for n in range(301, 313)]
)

# Suites : deux chambres réunies.
SUITES = {
    "102/103": "Suite : les chambres 102 et 103 réunies",
    "106/107": "Suite : les chambres 106 et 107 réunies",
    "109/110": "Suite : les chambres 109 et 110 réunies",
}

# Prix par nuit (FCFA) donnés par la direction le 11/11/2026.
# 105 : la liste reçue disait deux fois « 205 » (205 à 20 000, puis 205-207 à 20 000) ; 105 à 20 000 est À CONFIRMER.
TARIFS = {
    "101": 15000, "102/103": 40000, "104": 12000, "105": 20000, "106/107": 40000, "108": 20000, "109/110": 40000,
    **{str(n): 10000 for n in range(111, 119)},
    **{str(n): 15000 for n in range(201, 205)},
    "205": 20000, "206": 20000, "207": 20000, "208": 15000, "209": 20000, "210": 15000, "211": 20000,
    "301": 15000, "302": 55000, "303": 15000, "304": 20000, "305": 35000,
    "306": 25000, "307": 25000, "308": 25000, "309": 35000, "310": 20000, "311": 35000, "312": 20000,
}

# (nom, code, prix de vente) — fiche « STOCK BAR SAINT ELIE PALACE », page 1 puis page 2.
BAR = [
    ("33 EXPORT", "65CL", 1000), ("BEAUFORT LIGHT", "50CL", 1000), ("BEAUFORT ORDINAIRE", "65CL", 1000),
    ("BOOSTER COLA", "50CL", 1000), ("BOOSTER GIN", "50CL", 1000), ("CHILL", "50CL", 1000), ("CASTEL", "65CL", 1000),
    ("COCA-COLA B. Cassable", "60CL", 1000), ("COCA-COLA B. Plastique", "1L", 1000),
    ("DJINO B. Cassable", "60CL", 1000), ("DJINO B. Plastique", "1L", 1000), ("DOPPEL", "65CL", 1000),
    ("TOP GRENADINE Cassable", "60CL", 1000), ("TOP GRENADINE Plastique", "1L", 1000), ("ISENBECK", "65CL", 1000),
    ("MUTZIG", "65CL", 1000), ("ORANGINA Cassable", "60CL", 1000), ("ORANGINA Plastique", "1L", 1000),
    ("SODA", "65CL", 1000), ("TONIC", "33CL", 1000), ("TOP ORANGE Plastique", "1L", 1000),
    ("TOP ANANAS Plastique", "1L", 1000), ("TOP PAMPLEMOUSSE Cassable", "60CL", 1000),
    ("TOP PAMPLEMOUSSE Plastique", "1L", 1000), ("XXL", "60CL", 1000), ("VIMTO B. Plastique", "1L", 1000),
    ("SPRITE", "65CL", 1000), ("GUINNESS G", "65CL", 1000), ("GUINNESS P", "33CL", 1000), ("HARP", "65CL", 1000),
    ("ICE ANANAS", "33CL", 1000), ("ICE BLACK", "33CL", 1000), ("MALTA GUINNESS", "33CL", 1000),
    ("ORIGIN", "65CL", 1000), ("GUINNESS SMOOTH", "50CL", 1000), ("HEINEKEN Cassable", "33CL", 1000),
    ("KADJI", "65CL", 1000), ("3X Canette", "50CL", 1000),
    ("AMARULA CONSO", "75CL", 2000), ("AMARULA", "75CL", 15000), ("BAILEYS", "75CL", 16000),
    ("BAILEYS CONSO", "75CL", 2000), ("WHITE HORSE CONSO", "75CL", 1500), ("WHITE HORSE", "75CL", 15000),
    ("BLACK & WHITE CONSO", "75CL", 1500), ("BLACK & WHITE", "75CL", 15000), ("BLACK LABEL", "75CL", 30000),
    ("BLACK LABEL CONSO", "75CL", 4000), ("BORDEAUX", "75CL", 10000), ("CAMPARI", "1L", 20000),
    # Page 2
    ("CAMPARI CONSO", "1L", 1500), ("CHÂTEAU DU LAC", "75CL", 10000), ("CHIVAS CONSO", "75CL", 4500),
    ("CHIVAS", "75CL", 35000), ("COOKS", "1L", 25000), ("COOKS", "2L", 40000), ("COOKS", "750ML", 15000),
    ("GORDON GIN", "75CL", 15000), ("GORDON GIN CONSO", "75CL", 1500), ("GRANTS", "75CL", 15000),
    ("GRANTS CONSO", "75CL", 1500), ("J & B", "65CL", 15000), ("J & B CONSO", "65CL", 1500),
    ("JACK DANIEL", "75CL", 30000), ("JACK DANIEL CONSO", "75CL", 4000), ("JACK DANIEL", "1L", 35000),
    ("NIGHTS CONSO", "75CL", 1500), ("NIGHTS VODKA", "75CL", 18000), ("OLD WHISKEY", "75CL", 13000),
    ("PAUL BERNARD", "65CL", 10000), ("POL REMY", "65CL", 10000), ("RED LABEL", "65CL", 18000),
    ("RED LABEL CONSO", "65CL", 2000), ("RUSSIAN CHAMPAIGN", "65CL", 10000), ("SUPERMONT", "1,5L", 1000),
    ("TANGUI", "1,5L", 1000), ("FLORIDA", "75CL", 10000), ("VERMOUTI", "75CL", 10000), ("LORDSON", "70CL", 15000),
    ("LORDSON CONSO", "70CL", 1500), ("MARTINI ROUGE", "75CL", 15000), ("MARTINI ROUGE CONSO", "75CL", 1500),
    ("MARTINI BIANCO", "75CL", 15000), ("MARTINI BIANCO CONSO", "75CL", 1500), ("MARTINI ROSE", "1L", 15000),
    ("MARTINI ROSE CONSO", "1L", 1500), ("LOUIS ESCHENEAU", "75CL", 10000), ("PASTIS", "75CL", 10000),
    ("BALLENTINE", "75CL", 18000), ("BALLENTINE CONSO", "75CL", 2000), ("ISABELLE DE FRANCE", "75CL", 10000),
    ("VIEUX MOULIN", "75CL", 5000), ("MUSCATO", "33CL", 15000), ("JP CHENET", "75CL", 15000),
    ("PITAR", "75CL", 10000), ("PROSPERITY", "75CL", 10000),
]

# (nom, prix de vente) — fiche « STOCK BOUTIQUE ».
BOUTIQUE = [
    ("Brosse à dent", 500), ("Serviette hygiénique", 1000), ("Colgate 15g", 500), ("Colgate 30g", 1000),
    ("Cirage", 500), ("Santex 90g", 500), ("Santex 180g", 1000), ("Herboderm", 1000), ("Omo", 200),
    ("Brosse à cirage", 500), ("Boucle d'oreille", 500), ("Chaîne collier", 1000), ("Sac à dos", 5000),
    ("Sac à main", 25000), ("Ballerine", 5000), ("Chaussure montante", 10000), ("Rasoir bic", 500),
    ("Casque", 2500), ("Arachides 1,5L", 2500), ("Caramelles 1,5L", 2000), ("Croquettes 1,5L", 2000),
    ("Maïs/Arachide 1,5L", 2000), ("Cacahuète", 2500), ("Coconut", 4000),
]


# Carte de la cuisine — menu « Complexe St Élie Palace » (photos du 11/11/2026).
# (rubrique, nom, prix de vente en FCFA, composition)
CARTE = [
    ("Plats chauds", "Poulet rôti", 3000, ""),
    ("Plats chauds", "Poulet DG", 3500, ""),
    ("Plats chauds", "Poulet aux arachides à la camerounaise", 3500, ""),
    ("Plats chauds", "Bar à la poêle / braisé", 4000, ""),
    ("Plats chauds", "Maquereau grillé / braisé / à la poêle", 3000, ""),
    ("Plats chauds", "Carpe braisée / grillée / à la poêle", 3000, ""),
    ("Plats chauds", "Côtes de porc rôties aux épices", 3500, ""),
    ("Plats chauds", "Viande hachée", 2000, ""),
    ("Plats chauds", "Brochettes de bœuf", 1000, ""),
    ("Plats chauds", "Boulette de viande", 2000, ""),
    ("Plats chauds", "Rognons sautés", 3000, ""),
    ("Plats chauds", "Émincés de bœuf", 2000, ""),
    ("Plats chauds", "Ndolé viande de bœuf ou poisson fumé", 2500, ""),
    ("Plats chauds", "Folong sauté au poisson fumé", 2000, ""),
    ("Plats chauds", "Tripes sautées", 2000, ""),
    ("Plats chauds", "Bouillon de viande de bœuf", 2000, ""),
    ("Plats chauds", "Bouillon de poisson carpe / maquereau", 3000, ""),
    ("Plats chauds", "Bouillon de poisson bar", 4000, ""),
    ("Plats chauds", "Spaghetti sauté simple", 1000, ""),
    ("Plats chauds", "Spaghetti garni sardine / saucisson", 1500, ""),
    ("Garnitures", "Riz", 500, ""),
    ("Garnitures", "Spaghetti", 500, ""),
    ("Garnitures", "Bâton de manioc", 500, ""),
    ("Garnitures", "Pommes vapeur / frites", 500, ""),
    ("Garnitures", "Plantains vapeur / frites", 500, ""),
    ("Desserts", "Salade de fruits", 500, "Ananas, papaye, pastèque"),
    ("Petit-déjeuner", "Omelette nature", 1000, "Pain et micro beurre"),
    ("Petit-déjeuner", "Omelette garnie + spaghetti", 1500, ""),
    ("Petit-déjeuner", "Omelette garnie + pommes", 1500, ""),
    ("Petit-déjeuner", "Omelette garnie + plantain", 1500, ""),
    ("Petit-déjeuner", "Petit-déjeuner complet", 2000, "Omelette garnie, pain, cake, micro beurre, jus de fruits"),
    ("Salades", "Salade de crudités", 1500, "Laitue, tomate, carotte, oignon, œuf, sauce vinaigrette, pain"),
    ("Boissons chaudes", "Chocolat chaud", 500, ""),
    ("Boissons chaudes", "Lait chaud", 500, ""),
    ("Boissons chaudes", "Café noir / au lait", 500, ""),
    ("Boissons chaudes", "Thé", 500, "Citron, gingembre, menthe ou simple"),
]
