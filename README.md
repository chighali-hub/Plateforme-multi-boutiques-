# Plateforme multi-boutiques

Marketplace **web** (aucune application mobile) où chaque commerçant crée sa **boutique en ligne** personnalisée, où les **clients achètent sans créer de compte**, et où un **administrateur** valide les boutiques et gère leur durée d'utilisation.

> **État actuel :** le socle backend est prêt et dockerisé (Django + DRF + PostgreSQL + Redis + Celery). Les fonctionnalités sont développées en 8 phases décrites dans [docs/Documentation-API/02-phases.md](docs/Documentation-API/02-phases.md). Le front (React + Vite + Tailwind CSS) sera réalisé après le backend.

---

## Sommaire

1. [Le projet](#1-le-projet)
2. [Acteurs et interfaces](#2-acteurs-et-interfaces)
3. [Fonctionnalités](#3-fonctionnalités)
4. [Règles métier essentielles](#4-règles-métier-essentielles)
5. [Technologies](#5-technologies)
6. [Démarrage rapide (Docker)](#6-démarrage-rapide-docker)
7. [Structure du dépôt](#7-structure-du-dépôt)
8. [Documentation](#8-documentation)
9. [Organisation du travail](#9-organisation-du-travail)
10. [Scénarios de fonctionnement](#10-scénarios-de-fonctionnement)

---

## 1. Le projet

Beaucoup de commerçants veulent vendre en ligne sans savoir créer un site. La plateforme leur permet :

- de **créer leur boutique** en quelques minutes : nom, logo, description, coordonnées, design et couleurs ;
- de **publier leurs produits** un par un ou **en masse** (fichier Excel + dossier ZIP de photos) ;
- de **recevoir des commandes** : le client paie hors du site (Bankily, Sedad, Click…), envoie la capture de son paiement, et la boutique le contacte sur WhatsApp pour la livraison.

**Modèle économique :** chaque boutique validée par l'administrateur bénéficie d'**un mois gratuit**. Ensuite, elle paie l'administrateur (hors du site, via WhatsApp) et l'administrateur **recharge** sa durée d'utilisation (1 mois, 1 an, 5 ans…).

---

## 2. Acteurs et interfaces

| Acteur | Compte | Interface |
|---|---|---|
| **Client** | Aucun : il entre sur le site et achète directement | **Site public** |
| **Boutique** | E-mail + mot de passe, connexion depuis le bouton « Se connecter » du site public | **Dashboard boutique** |
| **Administrateur** | E-mail + mot de passe, sur une **page de connexion dédiée** (lien privé) | **Dashboard admin** |

Les trois interfaces proposent le **mode sombre** et deux langues : **français** et **arabe** (affichage de droite à gauche). Quand le site est en arabe, les descriptions des boutiques et la recherche passent aussi en arabe.

---

## 3. Fonctionnalités

### 3.1 Site public (client, sans compte)
- Page d'accueil : **cartes des boutiques** (logo, nom, description) avec une **barre de recherche** en haut ; boutons « Créer votre boutique » et « Se connecter ».
- **Recherche professionnelle** : insensible aux majuscules, aux accents et aux fautes de frappe (« melehfa » trouve « Melhfa »), en français ou en arabe selon la langue du site.
- **Page boutique** aux couleurs et au design choisis par la boutique : produits, filtres par **catégorie** (affichés seulement s'il y a plusieurs catégories) et par **prix** (ex. de 1 000 à 100 000 MRU), recherche de produit.
- **Panier propre à chaque boutique**, conservé dans le navigateur : le client le retrouve s'il quitte la boutique et y revient.
- **Paiement** : banques de la boutique avec leurs codes, total, **acompte minimum de 30 % déjà calculé**, envoi de la capture, du nom et du téléphone, puis confirmation avec le numéro de commande et le contact WhatsApp de la boutique.
- **Suivi des commandes** sans compte : le client est prévenu si sa commande est confirmée, livrée ou **refusée** (avec le motif).

### 3.2 Dashboard boutique
| Menu | Contenu |
|---|---|
| Tableau de bord | **Revenu du mois** (commandes livrées), carte de la **date d'expiration** du compte, commandes à traiter |
| Commandes | Commandes reçues, capture du paiement, nom et téléphone du client, bouton WhatsApp, statuts : confirmer, livrer, refuser |
| Produits | CRUD complet avec recherche et filtres ; catégories ; **import Excel + ZIP** avec liste des brouillons (« Publier la sélection ») et liste des erreurs à corriger (« Publier cette collection ») |
| Charger mon compte | Numéro WhatsApp de l'administrateur avec un lien direct, historique des recharges |
| Profil | Logo, nom, descriptions FR/AR, adresse, téléphones, **banques** (nom de la banque + code de paiement, plusieurs possibles) |
| Paramètres | **Design** de la boutique (même galerie qu'à l'inscription), mot de passe, e-mail |
| En-tête | Notifications, langue, mode sombre, déconnexion avec confirmation |

### 3.3 Dashboard admin
| Menu | Contenu |
|---|---|
| Tableau de bord | Nombre de boutiques par état, boutiques qui expirent dans les 7 jours, recharges du mois |
| Boutiques | Liste avec **recherche** et **filtre** (en attente, validées, expirées, bloquées, refusées) ; fiche complète avec la **carte d'identité** ; valider, refuser (avec motif), bloquer, débloquer, **charger le compte**, modérer les produits |
| Recharges | Historique de toutes les recharges |
| Journal d'audit | Toutes les actions sensibles (qui, quoi, quand) |
| Paramètres | Numéro WhatsApp de l'admin, durée de l'essai gratuit, pourcentage d'acompte, e-mail et mot de passe de l'admin |
| En-tête | Notifications, langue, mode sombre, déconnexion avec confirmation |

---

## 4. Règles métier essentielles

Liste complète et numérotée (RG-01 à RG-50) : [docs/Documentation-API/01-vue-d-ensemble.md](docs/Documentation-API/01-vue-d-ensemble.md#5-règles-métier-rg).

**États d'une boutique**

| État | Signification | Ce que la boutique peut faire | Visible par les clients |
|---|---|---|---|
| `ONBOARDING` | Inscription en cours (code e-mail, design, conditions) | Terminer l'inscription | Non |
| `PENDING` | En attente de validation | Rien (lecture seule : design choisi + message d'attente) | Non |
| `REJECTED` | Refusée avec un motif | Modifier son profil (dont la carte d'identité) et **renvoyer la demande** | Non |
| `ACTIVE` | Validée et non expirée | Tout | Oui (si au moins une banque) |
| `EXPIRED` | Date d'expiration dépassée | Ne peut plus se connecter : page « compte expiré » avec le lien WhatsApp de l'admin | Non |
| `BLOCKED` | Bloquée par l'admin | Ne peut plus se connecter | Non |

**Autres règles clés**
- Le mois gratuit commence le jour de la **validation**.
- Une recharge s'ajoute à la date d'expiration actuelle si la boutique est encore active, sinon à la date du jour. L'expiration ne supprime **aucune** donnée.
- Commande : `SUBMITTED` (nouvelle) → `CONFIRMED` → `DELIVERED`, ou `REJECTED` avec motif.
- **Revenu du mois** = somme des **totaux** des commandes **livrées** dans le mois (même si le client n'avait versé que l'acompte au départ).
- Acompte affiché = arrondi supérieur de 30 % du total ; si le client paie moins, la boutique le contacte sur WhatsApp.

---

## 5. Technologies

| Couche | Technologie |
|---|---|
| Backend | Python 3.12, **Django 5.2**, **Django REST Framework 3.16** |
| ORM | ORM Django |
| Base de données | **PostgreSQL 16** (`pg_trgm`, `unaccent`, `fuzzystrmatch` pour la recherche) |
| Authentification | JWT (simplejwt), Argon2id, codes OTP par e-mail |
| Tâches asynchrones | Celery 5 + Redis 7 |
| Images / Excel | Pillow (WebP), openpyxl |
| Documentation API | drf-spectacular (OpenAPI 3, Swagger) |
| Tests / qualité | pytest, pytest-django, factory-boy, pytest-cov, ruff |
| Conteneurs | Docker, Docker Compose |
| Frontend (après le backend) | React + Vite + Tailwind CSS |

---

## 6. Démarrage rapide (Docker)

### Prérequis
- Docker et Docker Compose (v2)
- Git

Aucune installation de Python, PostgreSQL ou Redis n'est nécessaire sur la machine.

### Lancement

```bash
git clone <url-du-depot>
cd Plateforme-multi-boutiques-
cp .env.example .env
docker compose up --build
```

Au démarrage, le service `backend` attend PostgreSQL puis applique les migrations automatiquement.

### Adresses

| Service | Adresse |
|---|---|
| API | http://localhost:8000/api/v1/ |
| Santé de l'API | http://localhost:8000/api/v1/health/ → `{"status": "ok"}` |
| Documentation Swagger | http://localhost:8000/api/docs/ |
| Schéma OpenAPI | http://localhost:8000/api/schema/ |
| Mailpit (e-mails et codes OTP de développement) | http://localhost:8025/ |
| PostgreSQL (depuis la machine) | `localhost:5433`, base / utilisateur / mot de passe : `plateforme` |
| Admin technique Django | http://localhost:8000/django-admin/ |

> Si le port 5433 est déjà pris sur votre machine, changez `POSTGRES_HOST_PORT` dans `.env`.

### Services Docker

| Service | Rôle |
|---|---|
| `backend` | API Django (rechargement automatique du code) |
| `worker` | Exécute les tâches Celery (e-mails, import Excel + ZIP) |
| `beat` | Planifie les tâches récurrentes (rappels d'expiration) |
| `db` | PostgreSQL 16 (données conservées dans le volume `postgres_data`) |
| `redis` | Cache, limitation de débit, file Celery |
| `mailpit` | Serveur e-mail de test |

### Commandes courantes

```bash
docker compose exec backend pytest                                   # tests
docker compose exec backend pytest --cov --cov-report=term-missing   # tests + couverture
docker compose exec backend ruff check .                             # lint
docker compose exec backend python manage.py makemigrations <app>    # nouvelle migration
docker compose exec backend python manage.py migrate                 # appliquer les migrations
docker compose exec backend python manage.py shell                   # shell Django
docker compose logs -f backend worker                                # journaux
docker compose down                                                  # arrêter
docker compose down -v                                               # arrêter et effacer la base
```

---

## 7. Structure du dépôt

```
.
├── README.md
├── docker-compose.yml          services de développement
├── .env.example                variables d'environnement (copier en .env)
├── docs/
│   └── Documentation-API/      documentation technique du backend (8 fichiers)
└── backend/
    ├── Dockerfile · entrypoint.sh
    ├── requirements.txt · requirements-dev.txt
    ├── manage.py · pytest.ini · pyproject.toml · conftest.py
    ├── config/                 paramètres (base, dev, test, prod), routes, Celery
    └── apps/
        ├── core/               outils communs, paramètres plateforme, audit
        ├── accounts/           utilisateurs, OTP, authentification
        ├── shops/              boutiques, designs, banques, profil
        ├── catalog/            catégories, produits, import Excel + ZIP
        ├── orders/             commandes, suivi public
        ├── notifications/      notifications in-app
        └── administration/     actions admin, recharges
```

---

## 8. Documentation

| Fichier | Contenu |
|---|---|
| [01-vue-d-ensemble.md](docs/Documentation-API/01-vue-d-ensemble.md) | Acteurs, cycle de vie d'une boutique, **règles métier RG-01 à RG-50**, architecture |
| [02-phases.md](docs/Documentation-API/02-phases.md) | Les **8 phases** du backend, branche, tâches et tests de chacune, répartition de l'équipe |
| [03-reference-api.md](docs/Documentation-API/03-reference-api.md) | **Tous les endpoints** : requêtes, réponses, erreurs, permissions |
| [04-schema-base-de-donnees.md](docs/Documentation-API/04-schema-base-de-donnees.md) | Tables, colonnes, contraintes, index, relations |
| [05-aspects-transversaux.md](docs/Documentation-API/05-aspects-transversaux.md) | Conventions de code, erreurs, permissions, fichiers, langues, **algorithme de recherche** |
| [06-strategie-de-tests.md](docs/Documentation-API/06-strategie-de-tests.md) | Quoi tester et comment, par phase |
| [07-securite.md](docs/Documentation-API/07-securite.md) | Protection de l'application et des données |
| [08-regles-du-travail.md](docs/Documentation-API/08-regles-du-travail.md) | Git, commits, demandes de fusion, revues |

---

## 9. Organisation du travail

| # | Phase | Branche |
|---|---|---|
| 1 | Socle commun et modèles de données | `feat/phase-1-socle-et-modeles` |
| 2 | Authentification et comptes | `feat/phase-2-authentification` |
| 3 | Espace boutique : onboarding, profil, banques, notifications | `feat/phase-3-espace-boutique` |
| 4 | Administration des boutiques | `feat/phase-4-administration` |
| 5 | Catalogue : catégories et produits | `feat/phase-5-catalogue` |
| 6 | Import en masse Excel + ZIP | `feat/phase-6-import-produits` |
| 7 | Site public et recherche | `feat/phase-7-site-public` |
| 8 | Commandes, paiement et tableau de bord boutique | `feat/phase-8-commandes` |

Chaque branche part de `dev` et revient dans `dev` par une demande de fusion (PR), fusionnable dès que la CI est verte. Personne ne pousse directement sur `main` ni sur `dev`. Règles complètes : [08-regles-du-travail.md](docs/Documentation-API/08-regles-du-travail.md).

---

## 10. Scénarios de fonctionnement

Les scénarios ci-dessous décrivent le déroulement de la plateforme du point de vue de chaque interface. Les endpoints indiqués entre crochets sont détaillés dans la [référence de l'API](docs/Documentation-API/03-reference-api.md) (préfixe `/api/v1`).

Personnages : **Aïcha** (boutique « Aïcha Mode », melhfas et parfums), **Mohamed** (client), **l'administrateur**.

### 10.1 Site public (client)

#### Scénario P1 — Trouver une boutique
1. Mohamed ouvre le site. Il arrive directement sur la liste des boutiques, présentées en cartes (logo, nom, description), sans créer de compte. [`GET /public/shops/`]
2. Le site est en français. Il tape « melehfa » dans la barre de recherche ; des suggestions apparaissent pendant la frappe. [`GET /public/shops/suggest/?q=mele&lang=fr`]
3. Malgré la faute, la recherche affiche « Aïcha Mode » (qui vend des « melhfas »), puis les autres boutiques qui en parlent dans leur description. [`GET /public/shops/?search=melehfa&lang=fr`]
4. Il passe le site en arabe et tape « ملحفة » : la recherche se fait maintenant dans les descriptions arabes. [`GET /public/shops/?search=ملحفة&lang=ar`]
5. Une boutique expirée, bloquée, en attente ou sans banque n'apparaît jamais.

#### Scénario P2 — Parcourir une boutique et remplir son panier
1. Mohamed clique sur la carte « Aïcha Mode ». La page s'affiche avec le design et les couleurs choisis par Aïcha. [`GET /public/shops/aicha-mode/`]
2. La boutique a deux catégories (« Melhfas » et « Parfums ») : les filtres de catégorie s'affichent. Une boutique avec une seule catégorie afficherait directement tous ses produits.
3. Il choisit « Melhfas » et un prix entre 1 000 et 5 000 MRU. [`GET /public/shops/aicha-mode/products/?category=4&min_price=1000&max_price=5000`]
4. Il ajoute deux melhfas au panier, en haut de la page. Ce panier appartient **uniquement** à Aïcha Mode.
5. Il visite une autre boutique, puis revient : son panier chez Aïcha Mode est **toujours rempli** (conservé dans le navigateur).

#### Scénario P3 — Payer et envoyer la capture
1. Mohamed ouvre son panier et clique sur « Effectuer le paiement ». Le serveur recalcule tout. [`POST /public/shops/aicha-mode/cart/quote/`]
2. Il voit : total **6 000 MRU**, message « Payez au minimum **1 800 MRU** (30 %) », et les banques d'Aïcha : *Bankily : 22334455*, *Sedad : 44556677*.
3. Il paie 1 800 MRU avec son application Bankily, hors du site, et fait une capture d'écran.
4. Il remplit le formulaire : capture (obligatoire), nom, téléphone, montant payé, banque utilisée. Il clique sur « Soumettre le paiement ». [`POST /public/shops/aicha-mode/orders/`]
5. Message : « Votre paiement a été envoyé avec succès. La boutique va le vérifier et vous contacter », avec la référence **CMD-2026-000042**, le numéro d'Aïcha et un bouton WhatsApp. Le panier d'Aïcha Mode est vidé.
6. Si un produit est devenu indisponible entre-temps, le site affiche le nouveau total au lieu d'enregistrer la commande. [`409 CART_CHANGED`]

#### Scénario P4 — Être prévenu d'un refus
1. Le site garde dans le navigateur les références des commandes de Mohamed et interroge régulièrement l'API. [`POST /public/orders/track/`]
2. Aïcha refuse une commande dont la capture est invalide. Au prochain passage de Mohamed, une notification s'affiche : « Commande CMD-2026-000051 refusée : capture invalide, aucun virement reçu », avec le bouton WhatsApp de la boutique.

#### Scénario P5 — Un commerçant découvre la plateforme
Sur la page d'accueil, Aïcha clique sur « Créer votre boutique » (scénario B1). Plus tard, elle utilise le bouton « Se connecter » (scénario B2).

### 10.2 Dashboard boutique

#### Scénario B1 — Inscription jusqu'à l'attente de validation
1. Aïcha remplit le formulaire : nom de la boutique, logo, description en français et en arabe, adresse, téléphone, WhatsApp, e-mail, mot de passe, nom complet, carte d'identité recto et verso. [`POST /auth/shop/register/`]
2. Elle reçoit un code à 6 chiffres par e-mail et le saisit. Elle est connectée automatiquement. [`POST /auth/shop/verify-email/`]
3. Page « Bienvenue Aïcha Mode ! » puis galerie des designs. Elle choisit « Élégant » et ses couleurs. [`GET /public/themes/`, `POST /shop/onboarding/design/`]
4. Message : « Votre compte est en attente de validation par l'administrateur. Après validation, il sera activé gratuitement pendant un mois ; ensuite vous devrez payer pour continuer à utiliser votre boutique. » Elle clique sur « J'accepte ». [`POST /shop/onboarding/accept-terms/`]
5. Elle arrive dans son dashboard en **lecture seule** : elle voit son design et le message « Compte en attente de validation ». Les menus sont désactivés. [`GET /shop/me/` → `state: PENDING`]

#### Scénario B2 — Connexion selon l'état du compte
Aïcha se connecte avec son e-mail et son mot de passe. [`POST /auth/shop/login/`]

| Situation | Ce qu'elle voit |
|---|---|
| Inscription non terminée | L'étape suivante (code e-mail, design ou conditions) |
| En attente | Dashboard en lecture seule avec le message d'attente |
| Refusée | Notification avec le motif, profil modifiable, bouton « Renvoyer la demande » |
| Active | Dashboard complet |
| Expirée | Page blanche : « Ce compte a expiré. Pour le recharger, contactez le +222 22 33 44 55 » (lien WhatsApp vers l'admin) |
| Bloquée | Message « Votre compte a été bloqué, contactez l'administration » |

#### Scénario B3 — Demande refusée puis renvoyée
1. L'administrateur refuse la demande avec le motif « Votre carte d'identité n'est pas lisible ». Aïcha reçoit une notification avec ce motif. [`GET /notifications/`]
2. Son dashboard passe en écriture **pour le profil uniquement**. Elle remplace la photo de sa carte d'identité. [`PUT /shop/me/id-card/`]
3. Elle clique sur « Renvoyer la demande de validation ». Sa boutique repasse en attente et l'administrateur est notifié. [`POST /shop/me/resubmit/`]

#### Scénario B4 — Préparer sa boutique après la validation
1. La boutique est validée le 20/11/2026. Le tableau de bord affiche : revenu du mois 0 MRU, et la carte « Votre compte expire le **20/12/2026** ». [`GET /shop/dashboard/`]
2. Profil → « Ajouter une banque » : *Bankily, 22334455*, puis *Sedad, 44556677*. Sa boutique devient visible sur le site public. [`POST /shop/banks/`]
3. Elle modifie son logo ; la nouvelle image apparaît sur sa carte publique. [`PATCH /shop/me/`]
4. Elle crée les catégories « Melhfas » et « Parfums » et ajoute un produit : nom, description, prix en MRU, image. [`POST /shop/categories/`, `POST /shop/products/`]

#### Scénario B5 — Ajouter 300 produits d'un coup
1. Produits → « Import en masse » → « Télécharger le modèle Excel ». [`GET /shop/products/import/template/`]
2. Elle remplit une ligne par produit : nom, description, prix, catégorie (facultative), nom du fichier photo (ex. `melhfa1.jpg`). Elle met ses 300 photos dans un dossier et le compresse en ZIP.
3. Elle envoie l'Excel et le ZIP. Le site vérifie immédiatement la structure, puis traite les lignes en arrière-plan avec une barre de progression. [`POST /shop/products/import/`, `GET /shop/products/import/jobs/12/`]
4. Notification : « Import terminé : 296 produits prêts, 4 lignes en erreur ».
5. **Liste 1 — brouillons réussis** : elle coche les produits voulus et clique sur « Publier la sélection ». [`POST /shop/products/bulk-publish/`]
6. **Liste 2 — erreurs** : ligne 42, « prix invalide » et « photo absente du ZIP ». Elle corrige le prix et ajoute la photo. [`PATCH /shop/products/import/errors/301/`]
7. Elle clique sur « Publier cette collection » : les lignes corrigées deviennent des produits publiés, les autres restent dans la liste avec leurs erreurs. [`POST /shop/products/import/errors/publish/`]

#### Scénario B6 — Traiter une commande
1. La cloche affiche « 1 ». Nouvelle commande CMD-2026-000042 de Mohamed. [`GET /notifications/unread-count/`, `GET /shop/orders/?status=SUBMITTED`]
2. Le détail montre les produits achetés, le total de 6 000 MRU, 1 800 MRU payés, **4 200 MRU restants**, la capture, le nom et le téléphone de Mohamed. [`GET /shop/orders/42/`, `GET /shop/orders/42/payment-proof/`]
3. Elle vérifie la réception de l'argent sur Bankily, puis clique sur « Confirmer ». [`POST /shop/orders/42/confirm/`]
4. Elle clique sur le bouton WhatsApp pour fixer la livraison avec Mohamed.
5. À la livraison, Mohamed paie les 4 200 MRU restants en main propre. Aïcha clique sur « Livrée ». [`POST /shop/orders/42/deliver/`]
6. Le **revenu du mois** passe à **6 000 MRU** (le total de la commande, compté au moment de la livraison). [`GET /shop/dashboard/`]
7. Pour une capture fausse, elle clique sur « Refuser » avec un motif ; la commande ne compte jamais dans le revenu et le client voit le refus. [`POST /shop/orders/51/reject/`]

#### Scénario B7 — Expiration puis recharge
1. À partir du 13/12/2026, Aïcha voit un bandeau d'alerte et reçoit des rappels (7, 3 et 1 jour avant l'expiration).
2. Menu « Charger mon compte » : « Pour recharger votre compte, contactez le +222 22 33 44 55 » avec un lien qui ouvre WhatsApp et un message pré-rempli. [`GET /shop/recharge-info/`]
3. Elle ne fait rien : le 20/12/2026, sa boutique disparaît du site public et, à sa connexion suivante, elle voit la page « Ce compte a expiré » avec le lien WhatsApp. [`403 SHOP_EXPIRED`]
4. Elle paie l'administrateur pour un an. L'administrateur recharge son compte (scénario A4).
5. Elle se reconnecte : **tout est intact** (produits, commandes, banques, design). La carte affiche la nouvelle date d'expiration.

#### Scénario B8 — Paramètres et déconnexion
1. Paramètres → elle change de design en choisissant dans la même galerie qu'à l'inscription. [`PATCH /shop/me/design/`]
2. Elle change son mot de passe (ses autres sessions sont fermées), puis son e-mail (code envoyé à la nouvelle adresse). [`POST /account/change-password/`, `POST /account/change-email/request/`, `POST /account/change-email/confirm/`]
3. Mot de passe oublié : code par e-mail, puis nouveau mot de passe. [`POST /auth/password/forgot/`, `.../verify-code/`, `.../reset/`]
4. Elle clique sur « Déconnexion », confirme dans la fenêtre « Voulez-vous vraiment vous déconnecter ? ». [`POST /auth/logout/`]

### 10.3 Dashboard admin

#### Scénario A1 — Connexion et vue d'ensemble
1. L'administrateur ouvre **son lien de connexion dédié** (non affiché sur le site public) et se connecte. [`POST /auth/admin/login/`]
2. Le tableau de bord affiche : 3 boutiques en attente, 52 actives, 7 expirées, 1 bloquée, et la liste des boutiques qui expirent dans les 7 jours (avec un bouton WhatsApp pour les relancer). [`GET /admin/dashboard/`]

#### Scénario A2 — Valider ou refuser une boutique
1. Notification « Nouvelle demande : Aïcha Mode ». Menu Boutiques, filtre « En attente ». [`GET /admin/shops/?state=PENDING`]
2. Il ouvre la fiche : informations complètes, design choisi, **carte d'identité** recto et verso agrandissable. [`GET /admin/shops/3/`, `GET /admin/shops/3/id-card/front/`]
3. Le nom sur la carte correspond : il clique sur « Valider ». La boutique est active avec **un mois gratuit** (expiration le 20/12/2026) et Aïcha est notifiée. [`POST /admin/shops/3/approve/`]
4. Pour une autre boutique dont la carte est floue : « Refuser » avec le motif « Votre carte d'identité n'est pas lisible ». [`POST /admin/shops/8/reject/`]
5. Quand cette boutique renvoie sa demande, elle réapparaît dans le filtre « En attente » avec une notification.

#### Scénario A3 — Rechercher et filtrer
1. Il tape « aicha » dans la barre de recherche : il trouve la boutique par son nom, son e-mail, son téléphone ou le nom de sa propriétaire. [`GET /admin/shops/?search=aicha`]
2. Il bascule entre « En attente » et « Validées » (actives et expirées). [`GET /admin/shops/?state=ACTIVE,EXPIRED`]

#### Scénario A4 — Charger le compte d'une boutique
1. Aïcha lui écrit sur WhatsApp et paie un an hors du site.
2. Il ouvre la fiche d'Aïcha Mode, clique sur « Charger le compte » et choisit **1 an**. Avant de confirmer, il voit : « Nouvelle date d'expiration : 20/12/2027 ». [`GET /admin/shops/3/recharge-preview/?duration_months=12`]
3. Il saisit le montant reçu et confirme. Aïcha est notifiée, et la recharge apparaît dans l'historique. [`POST /admin/shops/3/recharge/`]

| Situation | Calcul |
|---|---|
| Boutique encore active, expire le 20/12/2026, recharge d'un an | 20/12/2027 (jours restants conservés) |
| Boutique expirée depuis le 01/10/2026, rechargée le 20/11/2026 pour un an | 20/11/2027 (à partir d'aujourd'hui) |
| Recharge de 5 ans d'une boutique qui expire le 20/11/2026 | 20/11/2031 |
| Date précise choisie | La date choisie (postérieure à l'expiration actuelle) |

#### Scénario A5 — Bloquer, débloquer, modérer
1. Des clients se plaignent de la boutique X. L'administrateur clique sur « Bloquer » avec un motif et confirme. La boutique disparaît du site et ne peut plus se connecter. [`POST /admin/shops/15/block/`]
2. Après explications, il clique sur « Débloquer » : la boutique retrouve son état et sa date d'expiration. [`POST /admin/shops/15/unblock/`]
3. Il retire un produit contrefait d'une boutique, avec un motif ; la boutique est notifiée. [`POST /admin/shops/15/products/310/remove/`]

#### Scénario A6 — Paramètres, audit et déconnexion
1. Paramètres de la plateforme : il change le numéro WhatsApp affiché dans tous les liens « Contactez l'administrateur », la durée de l'essai gratuit et le pourcentage d'acompte. [`PATCH /admin/settings/`]
2. Il change son e-mail et son mot de passe. [`/account/...`]
3. Journal d'audit : il retrouve qui a validé, bloqué ou rechargé chaque boutique, et quand. [`GET /admin/audit-logs/?target_type=shop&target_id=3`]
4. Il se déconnecte après confirmation. [`POST /auth/logout/`]
