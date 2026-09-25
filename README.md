# pokeget : alertes de stock Pokémon TCG

pokeget surveille des sites marchands français. Dès qu'un produit Pokémon
correspondant à tes mots-clés devient achetable, il t'envoie une notification
sur ton iPhone. Toucher la notification t'emmène le plus près possible du
paiement, et c'est toi qui finalises l'achat. L'outil est 100 % gratuit
(aucune API payante) et tourne sur ton Mac.

> **État du projet.** Le socle est prêt : configuration, mémoire des produits,
> notifications, boutiques **Shopify**, sites **JSON-LD** génériques,
> bouton « Couper 1 h », résumé quotidien. Les modules dédiés (Fnac,
> Cultura, Amazon…) et le démarrage automatique (launchd) arrivent dans les
> prochaines étapes.

---

## 1. Installation (une seule fois)

Toutes les commandes se tapent dans l'application **Terminal** du Mac
(Cmd + Espace, tape « Terminal », Entrée). Copie-colle chaque ligne puis
appuie sur Entrée.

### 1.1 Installer Python 3

1. Va sur <https://www.python.org/downloads/macos/> et télécharge la
   dernière version « macOS 64-bit universal2 installer » (3.12 ou plus récent).
2. Ouvre le fichier `.pkg` et suis l'installation.
3. Vérifie dans le Terminal :
   ```bash
   python3 --version
   ```
   Le Terminal doit afficher `Python 3.12.x` (ou plus récent).

### 1.2 Récupérer le projet

Le plus simple est de passer par `git`. Si le Mac te propose d'installer les
« outils de ligne de commande », accepte, puis relance la commande.

```bash
cd ~
git clone https://github.com/65czvywbwn-create/pokeget.git
cd pokeget
git checkout claude/pokemon-tcg-stock-monitor-6jal1j
```

Le projet se trouve maintenant dans le dossier `pokeget` de ton dossier
personnel.

### 1.3 Créer l'environnement Python et installer les bibliothèques

```bash
cd ~/pokeget
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

* `python3 -m venv .venv` crée un environnement Python propre au projet, dans
  le dossier caché `.venv`.
* `source .venv/bin/activate` active cet environnement. Ton invite de
  commande commence alors par `(.venv)`. **Refais cette commande à chaque
  nouvelle fenêtre de Terminal.**
* `pip install ...` installe `curl_cffi`, qui imite un vrai navigateur, et
  `PyYAML`, qui lit la configuration.

Pour vérifier que tout est en place :
```bash
python3 -m unittest discover -s tests
```
Le Terminal doit afficher `OK` à la fin.

### 1.4 Créer ta configuration

```bash
python3 -m pokeget init
```

Cette commande crée `config.yaml` avec deux noms de topic ntfy longs et
aléatoires, puis affiche le topic auquel t'abonner sur l'iPhone (du genre
`pokeget-3f9a…`). Garde-le secret : quiconque le connaît peut lire tes
alertes.

---

## 2. Recevoir les alertes sur l'iPhone (ntfy)

1. Sur l'iPhone, installe l'app gratuite **ntfy** depuis l'App Store
   (éditeur : Philipp Heckel).
2. Ouvre-la et **autorise les notifications** quand elle le demande.
3. Touche **+** (en haut à droite) et colle le topic affiché par
   `python3 -m pokeget init`. Laisse le serveur par défaut (`ntfy.sh`), puis
   touche **Subscribe**.
4. Dans **Réglages iPhone → Notifications → ntfy**, active
   **Notifications urgentes** (Time Sensitive). Les alertes passeront ainsi
   même en mode Concentration.
5. Sur le Mac, envoie une fausse alerte :
   ```bash
   python3 -m pokeget test
   ```
   En quelques secondes, tu dois recevoir « 🟢 [TEST] ETB Pokémon 30e
   Anniversaire (FAUSSE ALERTE), 59,99 € ».
   * **Toucher** la notification ouvre le lien d'achat (pour le test, une page
     de ntfy).
   * **Appuyer longuement** dessus affiche les deux boutons : « Fiche
     produit » et « Couper ce produit 1 h ».

---

## 3. Utilisation au quotidien

| Je veux…                                       | Commande                                   |
|------------------------------------------------|--------------------------------------------|
| lancer la surveillance                         | `python3 -m pokeget`                       |
| l'arrêter                                      | `Ctrl + C` dans la fenêtre du Terminal     |
| tout vérifier une fois et voir un tableau      | `python3 -m pokeget --once`                |
| envoyer une fausse alerte                      | `python3 -m pokeget --test`                |
| savoir si une boutique est sur Shopify / lisible | `python3 -m pokeget verifier https://boutique.fr/...` |
| plus de détails à l'écran                      | ajoute `-v` à la fin de la commande        |

Pense à `cd ~/pokeget` puis `source .venv/bin/activate` avant ces
commandes.

Pendant la surveillance, le Mac ne se met pas en veille : le programme
lance `caffeinate`. Sur un MacBook, **l'écran rabattu met quand même le
Mac en veille**, sauf s'il est branché sur secteur et relié à un écran
externe. Laisse-le ouvert.

### Comment une alerte est décidée

Un produit déclenche une alerte quand toutes ces conditions sont réunies :

1. son nom contient un mot-clé de `inclure` ;
2. il ne contient aucun mot de `exclure` ;
3. il contient un mot de `doit_contenir` (par défaut « pokemon ») ;
4. il est **disponible**, ou **en précommande** si `precommande: true` ;
5. son prix ne dépasse pas le `prix_max` du mot-clé.

L'alerte part **une seule fois**, au passage « indisponible → disponible » ou
à l'apparition d'une nouvelle fiche disponible. Si un site hésite entre
« dispo » et « rupture », deux alertes pour un même produit sont espacées
d'au moins 10 minutes (réglable).

---

## 4. Modifier la configuration (`config.yaml`)

Ouvre le fichier avec TextEdit : `open -e config.yaml`. Après chaque
modification, **enregistre puis redémarre** le script (Ctrl + C, puis
`python3 -m pokeget`).

### Ajouter un mot-clé

Dans la section `produits:` → `inclure:`, ajoute deux lignes en respectant
l'alignement :

```yaml
    - mot: "flammes obsidiennes"
      prix_max: 60
```

Majuscules, accents, apostrophes et « 30ème / 30e / 30ᵉ » n'ont pas
d'importance. La recherche porte sur des mots entiers (« 30 ans » ne
correspond pas à « 130 ans »).

### Exclure un type de produit

Ajoute une ligne dans `exclure:`, par exemple `- "pin's"`.

### Ajouter une boutique Shopify

1. Vérifie que la boutique utilise Shopify :
   ```bash
   python3 -m pokeget verifier https://www.la-boutique.fr
   ```
2. Si la réponse est « ✅ Oui », copie dans `sites:` le bloc proposé :
   ```yaml
     - nom: "La Boutique"
       type: shopify
       domaine: "www.la-boutique.fr"
       actif: true
   ```

La config contient déjà trois boutiques candidates, désactivées
(`actif: false`) : Monpokestore, Blazing Tail et Shop TCG. **Vérifie chacune
avec la commande ci-dessus** avant de passer `actif: true`.

### Surveiller une fiche produit précise (site JSON-LD)

Ce mode convient à beaucoup de sites qui décrivent leurs produits au format
schema.org. Vérifie d'abord la page :
`python3 -m pokeget verifier https://site.fr/fiche-produit`. Ensuite :

```yaml
  - nom: "Mon site"
    type: jsonld
    actif: true
    intervalle: 60
    fiches:
      - "https://site.fr/fiche-produit"
```

### Mettre un site en pause

Passe `actif: true` à `actif: false`.

---

## 5. Lire les logs

Le programme note tout dans `logs/pokeget.log`. Quand le fichier dépasse
2 Mo, il est renommé en `pokeget.log.1`, et ainsi de suite jusqu'à 5
fichiers.

```bash
tail -f logs/pokeget.log        # suivre en direct (Ctrl + C pour quitter)
grep ALERTE logs/pokeget.log    # retrouver toutes les alertes envoyées
grep bloqué logs/pokeget.log    # voir les sites qui ont bloqué
```

Exemple de ligne : `2026-09-25 18:06:21 | INFO | [Boutique] ETB 30e Anniversaire : rupture -> disponible (54,99 €, ALERTE)`

---

## 6. Blocages et bonnes pratiques

* Chaque site est vérifié à intervalle régulier, avec ±20 % d'aléatoire, et
  jamais plus d'une requête à la fois par site.
* En cas de refus (erreur 403 ou 429, page captcha), le programme met ce site
  en pause, en doublant la pause à chaque nouveau refus (1 min, 2 min,
  4 min… jusqu'à 30 min). Si le blocage dure plus de 15 minutes, tu reçois
  « ⚠️ site bloqué ».
* L'outil ne se connecte jamais à tes comptes marchands.
* Chaque jour à 9 h, tu reçois « ✅ pokeget toujours actif » avec, pour
  chaque site, le nombre de vérifications et d'erreurs.

---

## 7. Organisation du projet

```
pokeget/
├── config.example.yaml     modèle de configuration (config.yaml est créé par « init »)
├── requirements.txt        bibliothèques Python
├── pokeget/
│   ├── cli.py              commandes (init, test, once, verifier, run)
│   ├── config.py           lecture de config.yaml
│   ├── matching.py         comparaison des noms avec les mots-clés
│   ├── db.py               mémoire SQLite (data/pokeget.db)
│   ├── http.py             requêtes « navigateur », pauses, blocages
│   ├── notifier.py         notifications ntfy
│   ├── engine.py           boucles par site, bouton 1 h, résumé de 9 h
│   └── adapters/           un module par type de site
│       ├── base.py         interface commune (discover / check)
│       ├── shopify.py      boutiques Shopify
│       └── jsonld.py       sites schema.org génériques
└── tests/                  tests automatiques (sans Internet)
```
