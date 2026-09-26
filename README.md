# pokeget : alertes de stock Pokémon TCG

pokeget surveille des sites marchands français. Dès qu'un produit Pokémon
correspondant à tes mots-clés devient achetable, il t'envoie une notification
sur ton iPhone. Toucher la notification t'emmène le plus près possible du
paiement, et c'est toi qui finalises l'achat. L'outil est 100 % gratuit
(aucune API payante) et tourne sur ton Mac, tout seul, en arrière-plan.

---

## Sommaire

1. [Installation (une seule fois)](#1-installation-une-seule-fois)
2. [Recevoir les alertes sur l'iPhone (ntfy)](#2-recevoir-les-alertes-sur-liphone-ntfy)
3. [Lancer la surveillance](#3-lancer-la-surveillance)
4. [Démarrage automatique (recommandé)](#4-démarrage-automatique-recommandé)
   * [4 bis. Faire tourner pokeget quand le Mac est éteint (serveur gratuit Oracle)](#4-bis-faire-tourner-pokeget-quand-le-mac-est-éteint-serveur-gratuit-oracle)
5. [Les sites surveillés](#5-les-sites-surveillés)
6. [Modifier la configuration](#6-modifier-la-configuration-configyaml)
7. [Mettre à jour pokeget](#7-mettre-à-jour-pokeget)
8. [Lire les logs](#8-lire-les-logs)
9. [Blocages et bonnes pratiques](#9-blocages-et-bonnes-pratiques)
10. [Dépannage](#10-dépannage)
11. [Organisation du projet](#11-organisation-du-projet)

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
git checkout claude/upbeat-brahmagupta-6txm4m
```

Le projet se trouve maintenant dans le dossier `pokeget` de ton dossier
personnel. **Laisse-le à cet endroit** : macOS interdit au démarrage
automatique de lire les dossiers Bureau, Documents et Téléchargements.

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

### Les notifications que tu peux recevoir

| Notification | Signification |
|---|---|
| 🟢 `[Site] Produit, prix` | Un produit recherché est achetable : fonce ! |
| 🟢 `… (précommande)` | Une précommande vient d'ouvrir. |
| 🚀 pokeget démarré | pokeget vient de (re)démarrer (au plus une par heure). |
| ✅ pokeget toujours actif | Résumé quotidien de 9 h : vérifications et erreurs par site. |
| ⚠️ `[Site] site bloqué` | Le site refuse les vérifications depuis 15 min. |
| ✅ `[Site] de nouveau accessible` | Le blocage est terminé. |
| 🔕 `[Site] Produit` | Tu as coupé les alertes de ce produit pendant 1 h. |

**Si tu ne reçois plus le résumé de 9 h, c'est que pokeget ne tourne plus**
(Mac éteint ou en veille) : voir [Dépannage](#10-dépannage).

---

## 3. Lancer la surveillance

Pense à `cd ~/pokeget` puis `source .venv/bin/activate` avant ces
commandes.

| Je veux…                                          | Commande                                      |
|---------------------------------------------------|-----------------------------------------------|
| tout vérifier une fois et voir un tableau         | `python3 -m pokeget once`                     |
| lancer la surveillance dans cette fenêtre         | `python3 -m pokeget`                          |
| l'arrêter                                         | `Ctrl + C` dans la fenêtre du Terminal        |
| la faire tourner en arrière-plan, toujours        | `python3 -m pokeget installer` (voir §4)      |
| savoir si pokeget tourne                          | `python3 -m pokeget statut`                   |
| relancer après une modification de `config.yaml` | `python3 -m pokeget redemarrer`               |
| envoyer une fausse alerte                         | `python3 -m pokeget test`                     |
| savoir si une boutique est sur Shopify / lisible  | `python3 -m pokeget verifier https://boutique.fr/...` |
| examiner des sites (anti-robot, données)          | `python3 -m pokeget sonde`                    |
| plus de détails à l'écran                         | ajoute `-v` à la fin de la commande           |

**Commence toujours par `python3 -m pokeget once`** après une modification :
il affiche, pour chaque site, les produits trouvés, leur statut, leur prix et
la décision (« ALERTE », « trop cher », « vendeur tiers », « rupture »…),
sans rien enregistrer ni envoyer.

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
5. son prix ne dépasse pas le `prix_max` du mot-clé ;
6. sur une marketplace (Auchan, Leclerc, Cultura, Carrefour), il est
   **vendu par l'enseigne elle-même** et non par un revendeur (réglable avec
   `vendeur_officiel_uniquement`).

L'alerte part **une seule fois**, au passage « indisponible → disponible » ou
à l'apparition d'une nouvelle fiche disponible. Si un site hésite entre
« dispo » et « rupture », deux alertes pour un même produit sont espacées
d'au moins 10 minutes (réglable).

> Au tout premier lancement, tu reçois une alerte pour chaque produit
> **déjà** disponible qui correspond à tes critères : c'est normal.

---

## 4. Démarrage automatique (recommandé)

Plutôt que de laisser une fenêtre de Terminal ouverte, tu peux confier
pokeget à **launchd**, le gestionnaire de services du Mac. pokeget tourne
alors en arrière-plan, démarre tout seul quand tu ouvres ta session, et
**redémarre automatiquement s'il s'arrête** (plantage, coupure réseau…).

```bash
cd ~/pokeget
source .venv/bin/activate
python3 -m pokeget installer
```

Tu reçois « 🚀 pokeget démarré » sur l'iPhone. Tu peux fermer le Terminal.

| Je veux…                                 | Commande                          |
|------------------------------------------|-----------------------------------|
| vérifier que tout tourne                 | `python3 -m pokeget statut`       |
| appliquer une modification de config     | `python3 -m pokeget redemarrer`   |
| arrêter et retirer le démarrage auto     | `python3 -m pokeget desinstaller` |

Exemple de `statut` :

```
Démarrage automatique (launchd) : installé, pokeget en cours (processus 4321)
Surveillance : ✅ en cours
Dernier signe de vie : il y a 18 s

Sites actifs (depuis le dernier résumé quotidien) :
  - Monpokestore : dernier tour réussi il y a 12 s, 214 vérif., 0 erreur(s)
  - Monoprix : dernier tour réussi il y a 21 s, 96 vérif., 0 erreur(s)
  ...
```

À savoir :
* Deux pokeget ne peuvent pas tourner en même temps (sinon alertes en
  double). Si tu tapes `python3 -m pokeget` alors qu'il tourne déjà en
  arrière-plan, il te le dit et s'arrête.
* launchd ne fonctionne que lorsque ta session Mac est ouverte. Pour une
  surveillance Mac éteint, voir la [section 4 bis](#4-bis-faire-tourner-pokeget-quand-le-mac-est-éteint-serveur-gratuit-oracle).
* Les erreurs graves (plantage, config illisible) vont dans
  `logs/launchd.log` ; tout le reste est dans `logs/pokeget.log`.

---

## 4 bis. Faire tourner pokeget quand le Mac est éteint (serveur gratuit Oracle)

Oracle Cloud propose gratuitement et sans limite de durée (offre
« Always Free ») une petite machine Linux allumée 24 h/24. pokeget peut y
tourner comme sur le Mac, avec la même commande `installer` : sur Linux,
c'est **systemd** (l'équivalent de launchd) qui le démarre avec la machine
et le relance s'il s'arrête.

### Ce qu'il faut savoir avant de commencer

* **Carte bancaire demandée à l'inscription**, uniquement pour vérifier ton
  identité : Oracle bloque 1 € environ puis l'annule. Tu ne paies rien tant
  que tu restes en offre gratuite. **Ne clique jamais sur « Upgrade » /
  « Pay As You Go »** : c'est ce qui rendrait le compte payant. Les cartes
  prépayées ou virtuelles sont souvent refusées.
* **La région choisie à l'inscription est définitive** : prends « France
  Central (Paris) » ou « France South (Marseille) ».
* **Certains sites bloquent les serveurs** (ils acceptent une connexion de
  particulier mais pas celle d'un centre de données). C'est le cas de
  Carrefour (Cloudflare) ; Cultura sera aussi gardé sur le Mac par prudence.
  Tu vérifies site par site avec `once` (étape 7) : un site bloqué depuis le
  serveur reste surveillé par le Mac.
* **Oracle peut récupérer une machine gratuite qu'il juge inutilisée.** Si
  ça arrive, tu reçois un e-mail, et le résumé « ✅ pokeget toujours actif
  (Serveur Oracle) » de 9 h n'arrive plus : il suffit de recréer la machine
  (étapes 3 à 8, une vingtaine de minutes).

### Qui surveille quoi (pas d'alertes en double)

Chaque machine a **sa propre `config.yaml`**, avec **les mêmes topics
ntfy** (tu reçois tout sur le même iPhone) mais **des sites différents** :

| Machine | Sites actifs | `machine:` |
|---|---|---|
| Serveur Oracle (24 h/24) | Monpokestore, Monoprix, Auchan, Leclerc, Philibert, UltraJeux | `"Serveur Oracle"` |
| Mac (quand il est allumé) | Carrefour, Cultura | `"Mac"` |

Un même site n'est jamais surveillé par les deux : pas de doublon. Le bouton
« Couper ce produit 1 h » marche dans les deux cas (chaque machine écoute le
topic de contrôle et ne réagit qu'aux produits qu'elle connaît).

### Étape 1 : créer le compte Oracle

1. Va sur <https://www.oracle.com/fr/cloud/free/> et clique sur
   « Commencer gratuitement ».
2. Pays : France. Saisis ton e-mail, puis clique sur le lien reçu par mail.
3. Remplis le formulaire. **Région d'origine** : France Central (Paris) ou
   France South (Marseille).
4. Vérification de la carte bancaire (et éventuellement validation 3D Secure
   sur l'appli de ta banque).
5. Attends le mail « Your account is ready » (de quelques minutes à
   quelques heures), puis connecte-toi sur <https://cloud.oracle.com>.

Si l'inscription échoue, voir [Dépannage de l'inscription](#dépannage-de-linscription-oracle)
plus bas.

### Étape 2 : créer une clé SSH sur le Mac

SSH est le moyen de piloter le serveur depuis le Terminal du Mac. La « clé »
remplace le mot de passe : un fichier secret reste sur ton Mac
(`~/.ssh/oracle_pokeget`), et sa moitié publique (`.pub`) est donnée à
Oracle. Dans le Terminal du Mac :

```bash
ssh-keygen -t ed25519 -f ~/.ssh/oracle_pokeget -C pokeget
```

Appuie deux fois sur Entrée (pas de phrase secrète). Puis affiche la clé
publique, que tu copieras à l'étape 3 :

```bash
cat ~/.ssh/oracle_pokeget.pub
```

### Étape 3 : créer la machine

Dans la console Oracle : menu ☰ → **Compute** → **Instances** →
**Create instance**.

1. **Name** : `pokeget`.
2. **Image and shape** → **Edit** :
   * Image : **Canonical Ubuntu 24.04** ;
   * Shape : **VM.Standard.E2.1.Micro** (AMD, marqué « Always Free
     eligible »), largement suffisant. L'autre choix gratuit,
     **VM.Standard.A1.Flex** (ARM, plus puissant), marche aussi mais est
     souvent indisponible (« Out of capacity »).
3. **Networking** : laisse les valeurs par défaut, en vérifiant que
   « Assign a public IPv4 address » est coché.
4. **Add SSH keys** → **Paste public keys** : colle la ligne affichée à
   l'étape 2 (elle commence par `ssh-ed25519`).
5. **Create**. Au bout d'une minute ou deux, l'instance passe à
   « Running ». Note son **Public IP address** (par ex. `140.238.12.34`).

Tant que tout ce que tu crées porte la mention « Always Free », rien n'est
facturé.

### Étape 4 : se connecter au serveur depuis le Mac

Pour ne pas retaper l'adresse à chaque fois, on donne un surnom au serveur.
Dans le Terminal du Mac, ouvre (ou crée) le fichier de réglages SSH :

```bash
nano ~/.ssh/config
```

Ajoute ces lignes en remplaçant l'adresse par la tienne, puis Ctrl + O,
Entrée, Ctrl + X pour enregistrer et quitter :

```
Host pokeget
  HostName 140.238.12.34
  User ubuntu
  IdentityFile ~/.ssh/oracle_pokeget
```

Connexion :

```bash
ssh pokeget
```

La première fois, réponds `yes` à la question « Are you sure you want to
continue connecting ». L'invite devient `ubuntu@pokeget:~$` : **les commandes
que tu tapes s'exécutent maintenant sur le serveur**. Pour revenir au Mac :
`exit`.

### Étape 5 : installer pokeget sur le serveur

Toujours connecté au serveur (`ssh pokeget`) :

```bash
# mettre le système à jour et installer git et l'outil d'environnement Python
sudo apt update && sudo apt install -y git python3-venv
# mettre l'heure de Paris (pour le résumé de 9 h)
sudo timedatectl set-timezone Europe/Paris
# récupérer pokeget
cd ~
git clone https://github.com/65czvywbwn-create/pokeget.git
cd pokeget
git checkout claude/upbeat-brahmagupta-6txm4m
# créer l'environnement Python et installer les bibliothèques
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# vérifier que tout marche
python3 -m unittest discover -s tests
```

La dernière commande doit finir par `OK`. Tape `exit` pour revenir au Mac.

### Étape 6 : préparer la config du serveur (sur le Mac)

On part de ta `config.yaml` (mêmes topics, mêmes mots-clés) :

```bash
cd ~/pokeget
cp config.yaml config.serveur.yaml
open -e config.serveur.yaml
```

Dans `config.serveur.yaml` :
* mets `machine: "Serveur Oracle"` (ligne à ajouter en haut du fichier si
  elle n'y est pas, sans espace au début) ;
* mets `actif: false` sur **Carrefour** et **Cultura** ;
* laisse les autres sites comme ils sont.

`config.serveur.yaml` contient tes topics secrets : comme `config.yaml`, il
n'est jamais envoyé sur GitHub.

### Étape 7 : copier la config et vérifier les sites depuis le serveur

Sur le Mac, on arrête pokeget le temps de copier sa mémoire (la liste des
produits déjà vus et des alertes déjà envoyées), pour que le serveur ne
renvoie pas d'anciennes alertes :

```bash
cd ~/pokeget
source .venv/bin/activate
python3 -m pokeget desinstaller
ssh pokeget "mkdir -p ~/pokeget/data"
scp config.serveur.yaml pokeget:pokeget/config.yaml
scp data/pokeget.db pokeget:pokeget/data/pokeget.db
```

(`scp` copie un fichier du Mac vers le serveur ; `pokeget:` désigne le
serveur.) Puis, sur le serveur :

```bash
ssh pokeget
cd ~/pokeget
source .venv/bin/activate
python3 -m pokeget once
```

Un site dont la ligne affiche **ERREUR** dans la colonne « Statut » (la
raison est écrite à côté, par ex. « bloqué ») ne fonctionne pas depuis le
serveur. Pour chacun d'eux, mets `actif: false`
dans `config.serveur.yaml` sur le Mac (et laisse-le actif sur le Mac à
l'étape 9), recopie avec `scp`, et relance `once`.

### Étape 8 : démarrage automatique sur le serveur

Toujours sur le serveur :

```bash
python3 -m pokeget installer
python3 -m pokeget statut
```

`installer` crée le service `/etc/systemd/system/pokeget.service` (il
utilise `sudo`, déjà autorisé pour l'utilisateur `ubuntu`). Tu reçois
« 🚀 pokeget démarré (Serveur Oracle) » sur l'iPhone. Tu peux taper `exit` :
pokeget continue de tourner, même Mac éteint.

### Étape 9 : le Mac ne surveille plus que Carrefour et Cultura

Sur le Mac, ouvre ta config habituelle :

```bash
cd ~/pokeget
open -e config.yaml
```

* ajoute `machine: "Mac"` ;
* mets `actif: false` sur tous les sites **sauf Carrefour et Cultura** (et
  les éventuels sites bloqués depuis le serveur à l'étape 7).

Puis :

```bash
source .venv/bin/activate
python3 -m pokeget once
python3 -m pokeget installer
```

Tu reçois « 🚀 pokeget démarré (Mac) ». Chaque matin à 9 h, tu reçois deux
résumés « ✅ pokeget toujours actif » : un « (Serveur Oracle) », et un
« (Mac) » si le Mac est allumé.

### Au quotidien

| Je veux…                                   | Commandes (depuis le Terminal du Mac)                                                        |
|--------------------------------------------|----------------------------------------------------------------------------------------------|
| voir si le serveur tourne                  | `ssh pokeget "cd pokeget && .venv/bin/python3 -m pokeget statut"`                            |
| lire ses logs                              | `ssh pokeget "tail -50 pokeget/logs/pokeget.log"`                                            |
| modifier sa config                         | modifier `config.serveur.yaml` sur le Mac, puis les deux commandes ci-dessous               |
|                                            | `scp config.serveur.yaml pokeget:pokeget/config.yaml`                                        |
|                                            | `ssh pokeget "cd pokeget && .venv/bin/python3 -m pokeget redemarrer"`                        |

Les erreurs graves du service vont dans `logs/service.log` sur le serveur.

### Mettre à jour pokeget sur le serveur

```bash
ssh pokeget
cd ~/pokeget
source .venv/bin/activate
git pull
pip install -r requirements.txt
python3 -m unittest discover -s tests
python3 -m pokeget redemarrer
exit
```

Et la même chose sur le Mac (voir [section 7](#7-mettre-à-jour-pokeget)).

### Revenir à tout sur le Mac

Sur le serveur : `python3 -m pokeget desinstaller`. Sur le Mac : remets
`actif: true` sur les sites voulus dans `config.yaml`, puis
`python3 -m pokeget redemarrer`.

### Dépannage de l'inscription Oracle

* **Carte refusée** : utilise une vraie carte bancaire (pas prépayée, pas
  virtuelle), au nom et à l'adresse saisis dans le formulaire ; valide la
  demande 3D Secure dans l'appli de ta banque ; désactive un éventuel VPN.
* **« Erreur lors du traitement de la transaction »** : réessaie le
  lendemain, sans VPN, depuis un autre navigateur (Safari ou Chrome, sans
  bloqueur de publicité) ; ne multiplie pas les essais le même jour.
* **Le compte reste « en attente de validation »** : attends le mail (il
  peut mettre jusqu'à 24 h).
* **« Out of capacity » à la création de la machine** : choisis la forme
  VM.Standard.E2.1.Micro plutôt que A1.Flex, ou réessaie plus tard.
* **`ssh pokeget` ne répond pas** : vérifie l'adresse dans `~/.ssh/config`
  et que l'instance est « Running ». « Permission denied » : la clé collée à
  l'étape 3 n'est pas celle de `~/.ssh/oracle_pokeget.pub` ; recrée la
  machine avec la bonne.
* **`installer` dit « systemd introuvable »** : l'image n'est pas Ubuntu ;
  recrée la machine avec Canonical Ubuntu 24.04.

Si Oracle refuse l'inscription malgré tout, garde pokeget sur le Mac
(section 4) : il suffit de ne pas faire les étapes ci-dessus.

---

## 5. Les sites surveillés

| Site | Type | Comment pokeget le lit | À savoir |
|---|---|---|---|
| Monpokestore | `shopify` | catalogue Shopify public | lien direct vers le panier pré-rempli |
| Monoprix | `monoprix` | recherche « pokemon » (une dizaine de produits) | livraison seulement dans certaines villes : vérifie ton adresse sur courses.monoprix.fr |
| Auchan | `auchan` | recherche par mot-clé | marketplace ; offres « retrait magasin » ignorées par défaut (`retrait_magasin: true` pour les inclure) |
| Leclerc | `leclerc` | recherche par mot-clé | marketplace ; « Vérifier la disponibilité » = magasin seulement |
| Philibert | `philibert` | recherche + petite requête de stock par produit | |
| UltraJeux | `ultrajeux` | catégorie « ETB Coffret Dresseur d'Elite » | lien qui ajoute directement l'article au panier |
| Cultura | `cultura` | recherche par mot-clé, via l'API publique de la boutique | marketplace ; le stock des magasins (retrait) est ignoré |
| Carrefour | `carrefour` | recherche par mot-clé | marketplace ; protégé par Cloudflare : répond par moments seulement, d'où un tour toutes les 5 min |
| Play-In, JouéClub, La Grande Récré | `jsonld` | fiches produit que tu listes | Play-In interdit aux robots sa recherche : fiches uniquement |

**Pas surveillés, volontairement** : Fnac et King Jouet (protection
DataDome), Amazon (AWS WAF), Cdiscount (Baleen), Micromania et Pokémon
Center (Imperva). Ces sites bloquent les programmes automatiques et pokeget
ne cherche pas à contourner leurs protections.

Pour les grandes enseignes, pokeget cherche par défaut « pokemon + mot-clé »
pour chacun de tes mots-clés (ex. « pokemon dresseur d'élite »), puis
revérifie la fiche des produits suivis qui disparaissent des résultats.

---

## 6. Modifier la configuration (`config.yaml`)

Ouvre le fichier avec TextEdit : `open -e config.yaml`. Après chaque
modification, **enregistre**, vérifie avec `python3 -m pokeget once`, puis
applique avec `python3 -m pokeget redemarrer` (ou Ctrl + C puis
`python3 -m pokeget` si tu n'utilises pas le démarrage automatique).

Règles YAML : l'indentation (les espaces en début de ligne) compte, jamais
de tabulation, et les textes entre guillemets `"comme ceci"`.

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

Ajoute une ligne dans `exclure:`, par exemple `- "poster"` ou `- "pin's"`.
Le modèle exclut déjà « occasion », « descellée », « abîmée », les
protège-cartes, classeurs et portfolios.

### Mettre un site en pause

Passe `actif: true` à `actif: false`.

### Options des grandes enseignes

```yaml
  - nom: "Leclerc"
    type: leclerc
    domaine: "www.e.leclerc"
    actif: true
    intervalle: 60                  # secondes entre deux tours (±20 %)
    recherches:                     # remplace les recherches par défaut
      - "pokemon coffret dresseur d'elite"
    fiches:                         # fiches toujours surveillées, même sans mot-clé
      - "https://www.e.leclerc/fp/pokemon-me04-coffret-dresseur-d-elite-0196214139961"
```

Autres options : `retrait_magasin: true` (Auchan), `pages:` (UltraJeux,
adresses de catégories copiées depuis le site), `verifs_par_tour: 3`
(Shopify : nombre de fiches revérifiées une à une à chaque tour).

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

La config contient déjà Monpokestore (vérifiée : c'est bien Shopify).

### Surveiller une fiche produit précise (site JSON-LD)

Ce mode convient à beaucoup de sites qui décrivent leurs produits au format
schema.org (Play-In, JouéClub, La Grande Récré…). Vérifie d'abord la page :
`python3 -m pokeget verifier https://site.fr/fiche-produit`. Ensuite :

```yaml
  - nom: "Play-In"
    type: jsonld
    actif: true
    intervalle: 60
    fiches:
      - "https://www.play-in.com/fr/produit/670423/booster-pokemon-30-ans-30th-celebration-m6a-cn"
```

---

## 7. Mettre à jour pokeget

```bash
cd ~/pokeget
source .venv/bin/activate
git fetch origin
git checkout claude/upbeat-brahmagupta-6txm4m
git pull
pip install -r requirements.txt
python3 -m unittest discover -s tests
```

`config.yaml` n'est jamais modifié par une mise à jour (il contient tes
topics secrets). **Les nouveaux sites n'y apparaissent donc pas tout
seuls** : ouvre `config.example.yaml`, copie les blocs des sites qui
t'intéressent (de `- nom:` jusqu'à la ligne vide suivante) et colle-les à la
fin de la section `sites:` de ton `config.yaml`. Vérifie avec
`python3 -m pokeget once`, puis `python3 -m pokeget redemarrer`.

---

## 8. Lire les logs

Le programme note tout dans `logs/pokeget.log`. Quand le fichier dépasse
2 Mo, il est renommé en `pokeget.log.1`, et ainsi de suite jusqu'à 5
fichiers.

```bash
tail -f logs/pokeget.log        # suivre en direct (Ctrl + C pour quitter)
grep ALERTE logs/pokeget.log    # retrouver toutes les alertes envoyées
grep bloqué logs/pokeget.log    # voir les sites qui ont bloqué
cat logs/launchd.log            # erreurs au démarrage automatique (logs/service.log sur Linux)
```

Exemple de ligne : `2026-09-25 18:06:21 | INFO | [Monoprix] Coffret Dresseur d'Élite Pokémon 30e Anniversaire ETB : rupture -> disponible (59,99 €, ALERTE)`

---

## 9. Blocages et bonnes pratiques

* Chaque site est vérifié à intervalle régulier, avec ±20 % d'aléatoire, et
  jamais plus d'une requête à la fois par site, espacées d'environ 1,5 s.
* En cas de refus (erreur 403 ou 429, page captcha ou page de défi
  anti-robot, y compris quand elle se cache derrière un code « normal »
  200 ou 202), le programme met ce site en pause, en doublant la pause à
  chaque nouveau refus (1 min, 2 min, 4 min… jusqu'à 30 min). Si le blocage
  dure plus de 15 minutes, tu reçois « ⚠️ site bloqué ».
* L'outil ne se connecte jamais à tes comptes marchands et ne contourne pas
  les protections anti-robot.
* Chaque jour à 9 h, tu reçois « ✅ pokeget toujours actif » avec, pour
  chaque site, le nombre de vérifications et d'erreurs.

---

## 10. Dépannage

**Je ne reçois plus rien, même pas le résumé de 9 h.**
Tape `python3 -m pokeget statut`. Si la surveillance est arrêtée, regarde
`logs/launchd.log` et la fin de `logs/pokeget.log`, puis relance avec
`python3 -m pokeget installer`. Vérifie aussi que le Mac n'était pas en
veille (capot fermé).

**« pokeget tourne déjà ».**
Il tourne en arrière-plan grâce au démarrage automatique : c'est normal.
Utilise `statut`, `redemarrer` ou `desinstaller`.

**Un site affiche « ⛔ bloqué » ou beaucoup d'erreurs.**
Laisse faire : pokeget espace ses essais tout seul. Si ça dure des heures,
augmente son `intervalle` (par exemple 120) ou mets-le en pause
(`actif: false`).

**Un site renvoie « page de recherche illisible ».**
Le site a probablement changé sa présentation : l'adapter doit être mis à
jour. Lance `python3 -m pokeget sonde https://adresse-de-la-recherche` : la
page est enregistrée dans le dossier `sondes/`, ce qui permet de corriger.

**Carrefour est souvent « bloqué ».**
Carrefour est protégé par Cloudflare. Depuis une connexion de particulier,
il répond une partie du temps et affiche parfois une page de défi. pokeget
ne la contourne pas : il fait une pause, puis réessaie. Tu reçois alors
« ⚠️ Carrefour bloqué », puis « ✅ de nouveau accessible ». Si ces messages
te gênent, augmente son `intervalle` (par exemple 600) ou mets-le en pause
(`actif: false`). Depuis un serveur (hébergeur, cloud), Carrefour est
bloqué presque tout le temps.

---

## 11. Organisation du projet

```
pokeget/
├── config.example.yaml     modèle de configuration (config.yaml est créé par « init »)
├── requirements.txt        bibliothèques Python
├── pokeget/
│   ├── cli.py              commandes (init, test, once, run, installer, statut…)
│   ├── config.py           lecture de config.yaml
│   ├── matching.py         comparaison des noms avec les mots-clés
│   ├── db.py               mémoire SQLite (data/pokeget.db)
│   ├── http.py             requêtes « navigateur », pauses, détection des blocages
│   ├── notifier.py         notifications ntfy
│   ├── engine.py           boucles par site, bouton 1 h, résumé de 9 h, signe de vie
│   ├── service.py          démarrage automatique (launchd / systemd) et verrou « une seule instance »
│   ├── probe.py            commande « sonde »
│   └── adapters/           un module par type de site
│       ├── base.py         interface commune (discover / check / poll)
│       ├── retail.py       base commune des grandes enseignes (recherche + fiches)
│       ├── shopify.py      boutiques Shopify
│       ├── jsonld.py       sites schema.org génériques
│       ├── monoprix.py     Monoprix
│       ├── auchan.py       Auchan
│       ├── leclerc.py      E.Leclerc
│       ├── philibert.py    Philibert
│       ├── ultrajeux.py    UltraJeux
│       ├── cultura.py      Cultura (API GraphQL publique de la boutique)
│       └── carrefour.py    Carrefour
└── tests/                  tests automatiques (sans Internet)
    └── fixtures/           extraits réels des pages des sites, pour les tests
```
