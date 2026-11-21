# 01 — Vue d'ensemble du backend

> Ce document est le point d'entrée de la documentation technique. Il décrit **ce que fait la plateforme**, **les règles métier** que le backend doit faire respecter et **l'architecture** retenue. Les autres fichiers détaillent chaque aspect :
>
> | Fichier | Contenu |
> |---|---|
> | [02-phases.md](02-phases.md) | Découpage du travail en 8 phases (une branche par phase) |
> | [03-reference-api.md](03-reference-api.md) | Liste complète des endpoints, requêtes, réponses, erreurs |
> | [04-schema-base-de-donnees.md](04-schema-base-de-donnees.md) | Tables, colonnes, contraintes, index, relations |
> | [05-aspects-transversaux.md](05-aspects-transversaux.md) | Conventions de code et parties techniques communes |
> | [06-strategie-de-tests.md](06-strategie-de-tests.md) | Ce qu'il faut tester et comment |
> | [07-securite.md](07-securite.md) | Protection de l'application et des données |
> | [08-regles-du-travail.md](08-regles-du-travail.md) | Règles Git, revues, organisation de l'équipe |

---

## 1. Le projet en quelques lignes

La plateforme est une **marketplace web** (aucune application mobile) qui permet :

- à un **commerçant** de créer sa **boutique en ligne** personnalisée (logo, description, design, couleurs), d'y publier ses produits et de recevoir des commandes ;
- à un **client**, **sans créer de compte**, de parcourir les boutiques, de remplir le panier d'une boutique, de payer **hors du site** (Bankily, Sedad, Click…) puis d'envoyer la **capture** de son paiement ;
- à l'**administrateur** de valider les boutiques, de les bloquer et de **recharger** leur durée d'utilisation après un paiement reçu hors site (via WhatsApp).

Modèle économique : chaque boutique validée reçoit **1 mois gratuit**. Ensuite, elle paie l'administrateur hors du site et l'administrateur prolonge sa date d'expiration.

---

## 2. Acteurs

| Acteur | Compte | Accès |
|---|---|---|
| **Client** (visiteur) | Aucun | Site public : endpoints `/api/v1/public/...` sans authentification |
| **Boutique** | Oui (`role = SHOP`), connexion par e-mail et mot de passe | Dashboard boutique : endpoints `/api/v1/shop/...` |
| **Administrateur** | Oui (`role = ADMIN`), connexion par e-mail et mot de passe sur une **page de connexion dédiée** | Dashboard admin : endpoints `/api/v1/admin/...` |

Il y a **deux formulaires de connexion distincts** côté front, et **deux endpoints distincts** côté API :

- `POST /api/v1/auth/shop/login/` : connexion des boutiques (lien « Se connecter » du site public) ;
- `POST /api/v1/auth/admin/login/` : connexion de l'administrateur (lien privé, non affiché sur le site public).

Un compte boutique ne peut pas se connecter par l'endpoint admin, et inversement.

---

## 3. Les trois interfaces web (servies par le futur front React)

| Interface | Utilisateur | Fonctions principales |
|---|---|---|
| **Site public** | Client | Liste des boutiques (cartes), recherche, page boutique, filtres produits, panier par boutique, paiement par capture, suivi des commandes, boutons « Créer votre boutique » et « Se connecter » |
| **Dashboard boutique** | Boutique | Tableau de bord, commandes, produits (CRUD + import Excel/ZIP), recharger mon compte, profil (logo, banques…), paramètres (design, mot de passe, e-mail), notifications |
| **Dashboard admin** | Administrateur | Tableau de bord, boutiques (valider, refuser, bloquer, débloquer, recharger), historique des recharges, paramètres de la plateforme, journal d'audit, notifications |

Les trois interfaces proposent le **mode sombre** et deux langues : **français** et **arabe** (affichage de droite à gauche). Le mode sombre est géré uniquement par le front. La langue est transmise à l'API par l'en-tête `Accept-Language: fr` ou `Accept-Language: ar`.

---

## 4. Cycle de vie d'une boutique

### 4.1 Les champs qui portent l'état

| Champ (`shops_shop`) | Valeurs | Rôle |
|---|---|---|
| `onboarding_step` | `VERIFY_EMAIL`, `CHOOSE_DESIGN`, `ACCEPT_TERMS`, `COMPLETED` | Avancement de l'inscription |
| `status` | `PENDING`, `APPROVED`, `REJECTED` | Décision de l'administrateur |
| `is_blocked` | `true` / `false` | Blocage décidé par l'administrateur, indépendant du statut |
| `expires_at` | date-heure ou `null` | Fin de la période payée (ou du mois gratuit) |

### 4.2 L'état effectif (calculé, jamais stocké)

L'API expose un champ calculé `state`, évalué **dans cet ordre** (la première règle vraie l'emporte) :

| Ordre | Condition | `state` |
|---|---|---|
| 1 | `is_blocked = true` | `BLOCKED` |
| 2 | `onboarding_step ≠ COMPLETED` | `ONBOARDING` |
| 3 | `status = PENDING` | `PENDING` |
| 4 | `status = REJECTED` | `REJECTED` |
| 5 | `status = APPROVED` et `expires_at ≤ maintenant` | `EXPIRED` |
| 6 | `status = APPROVED` et `expires_at > maintenant` | `ACTIVE` |

Comme l'état `EXPIRED` est **calculé**, aucune tâche planifiée n'est nécessaire pour faire expirer une boutique : elle expire automatiquement à la seconde près.

### 4.3 Diagramme

```
 Inscription (formulaire + carte d'identité)
        │  e-mail OTP envoyé
        ▼
 ONBOARDING ──(OTP validé)──► choix du design ──► « J'accepte »
                                                     │ submitted_at = maintenant
                                                     ▼
                                                  PENDING  ◄─────────────┐
                                        admin valide │   │ admin refuse  │ « Renvoyer la demande »
                                                     ▼   ▼ (motif)       │
          approved_at = maintenant              ACTIVE   REJECTED ───────┘
          expires_at = maintenant + 1 mois         │
                                                   │ expires_at dépassée
                                                   ▼
                                                EXPIRED ──(admin recharge)──► ACTIVE

 À tout moment : admin bloque ──► BLOCKED ──(admin débloque)──► état calculé à nouveau
```

### 4.4 Ce que chaque état autorise

| `state` | Connexion | Dashboard boutique | Visible sur le site public |
|---|---|---|---|
| `ONBOARDING` | Oui (après vérification de l'e-mail) | Uniquement les étapes d'inscription restantes | Non |
| `PENDING` | Oui | **Lecture seule** : design choisi + message « en attente de validation » | Non |
| `REJECTED` | Oui | **Écriture limitée au profil** (infos, logo, carte d'identité, design, banques) + bouton « Renvoyer la demande » | Non |
| `ACTIVE` | Oui | Complet | Oui, si au moins une banque est enregistrée |
| `EXPIRED` | **Non** : réponse `403 SHOP_EXPIRED` avec le lien WhatsApp de l'admin | — | Non |
| `BLOCKED` | **Non** : réponse `403 SHOP_BLOCKED` | — | Non |

L'état est vérifié **à chaque requête** (pas seulement à la connexion). Une boutique qui expire pendant qu'elle est connectée reçoit `403 SHOP_EXPIRED` à sa requête suivante, et le front la redirige vers la page de connexion.

---

## 5. Règles métier (RG)

Chaque règle est référencée dans le code, les tests et les revues par son identifiant.

### Inscription et compte

| Id | Règle |
|---|---|
| RG-01 | L'inscription d'une boutique exige : nom de la boutique, logo, description en français **et** en arabe, adresse, téléphone, WhatsApp, e-mail, mot de passe, nom complet du propriétaire, carte d'identité (recto et verso). |
| RG-02 | L'e-mail est unique sur toute la plateforme (comparaison insensible à la casse, stocké en minuscules). |
| RG-03 | Un code OTP à 6 chiffres est envoyé par e-mail. Il est valable **10 minutes**, accepte **5 essais** au maximum, et un nouveau code ne peut être demandé qu'après **60 secondes**. Un nouveau code invalide les précédents. |
| RG-04 | Tant que l'e-mail n'est pas vérifié, la connexion renvoie `403 EMAIL_NOT_VERIFIED`. |
| RG-05 | Après vérification de l'e-mail, la boutique choisit un design (modèle + couleur principale + couleur d'accent), puis accepte les conditions. La demande est alors **soumise** à l'administrateur (`submitted_at`). |
| RG-06 | Le mot de passe compte au moins 8 caractères, n'est pas entièrement numérique, n'est pas un mot de passe courant et ne ressemble pas à l'e-mail. |
| RG-07 | « Mot de passe oublié » : un OTP est envoyé par e-mail. La réponse est identique, que l'e-mail existe ou non. Après réinitialisation, toutes les sessions ouvertes sont fermées. |
| RG-08 | Le changement d'e-mail exige le mot de passe actuel et un OTP envoyé à la **nouvelle** adresse. |

### Validation, refus, blocage, expiration

| Id | Règle |
|---|---|
| RG-10 | Seule une boutique à l'état `PENDING` peut être validée ou refusée. |
| RG-11 | La validation fixe `approved_at = maintenant` et `expires_at = maintenant + durée d'essai` (paramètre `trial_months`, par défaut **1 mois**). Le mois gratuit commence donc à la validation, pas à l'inscription. |
| RG-12 | Un refus exige un **motif** (10 à 500 caractères). La boutique reçoit une notification contenant ce motif. |
| RG-13 | Une boutique refusée peut modifier son profil, sa carte d'identité, son design et ses banques, puis **renvoyer sa demande** : elle repasse à `PENDING`, le motif de refus précédent est conservé dans l'historique de l'audit et l'administrateur est notifié. |
| RG-14 | Le blocage exige un motif. Il rend la boutique invisible et empêche sa connexion. Le déblocage ne modifie ni le statut ni la date d'expiration. |
| RG-15 | Une boutique expirée ou bloquée **conserve toutes ses données** (produits, commandes, banques, design). |

### Recharge

| Id | Règle |
|---|---|
| RG-20 | Seule une boutique au statut `APPROVED` peut être rechargée (active, expirée ou bloquée). |
| RG-21 | La recharge s'exprime soit en **nombre de mois** (1 à 120), soit par une **date cible**. |
| RG-22 | En mois : `nouvelle date = max(expires_at, maintenant) + N mois`. Une boutique encore active ne perd pas ses jours restants ; une boutique expirée repart d'aujourd'hui. |
| RG-23 | En date cible : la date doit être postérieure à `max(expires_at, maintenant)`. |
| RG-24 | Chaque recharge est enregistrée (`administration_recharge`) avec l'ancienne date, la nouvelle date, l'auteur et, optionnellement, le montant reçu. La boutique reçoit une notification. |
| RG-25 | Des rappels sont envoyés à la boutique (notification + e-mail) **7, 3 et 1 jour(s)** avant l'expiration. |

### Catalogue

| Id | Règle |
|---|---|
| RG-30 | Un produit possède : un nom (au moins un parmi `name_fr` et `name_ar`), une description facultative en français et/ou en arabe, un **prix en MRU** (entier, au moins 1), **une image**, une catégorie **facultative**. Pas de vidéo. |
| RG-31 | Un produit est soit **brouillon** (`DRAFT`, invisible pour les clients), soit **publié** (`PUBLISHED`). Un produit publié peut être marqué indisponible (`is_available = false`) pour être masqué temporairement. |
| RG-32 | Les catégories appartiennent à une boutique. La suppression d'une catégorie ne supprime pas ses produits : ils deviennent « sans catégorie ». |
| RG-33 | Import en masse : la boutique télécharge le **modèle Excel** depuis le site, le remplit (une ligne par produit, la colonne `image` contient le **nom du fichier** de la photo), puis envoie l'Excel **et** un **ZIP** contenant les photos. Maximum **1 000 lignes** par import. |
| RG-34 | Chaque ligne valide devient un produit **brouillon** (liste 1). Chaque ligne invalide est enregistrée dans la **liste des erreurs** (liste 2) avec le détail des erreurs, pour être corrigée plus tard. |
| RG-35 | Liste 1 : « Publier la sélection » publie les brouillons choisis. Liste 2 : après correction, « Publier cette collection » publie les lignes devenues valides ; celles encore invalides restent dans la liste avec leurs erreurs. |
| RG-36 | Une catégorie inconnue dans l'Excel est **créée automatiquement** pour la boutique. Une cellule catégorie vide donne un produit sans catégorie. |

### Site public, panier et commandes

| Id | Règle |
|---|---|
| RG-40 | Une boutique est visible sur le site public si et seulement si `state = ACTIVE` **et** elle possède au moins une banque. Sinon, toutes ses routes publiques répondent `404`. |
| RG-41 | Seuls les produits `PUBLISHED` et `is_available = true` sont visibles sur le site public. |
| RG-42 | La recherche de boutiques porte sur le nom et la description **dans la langue active** (`lang=fr` : nom + `description_fr` ; `lang=ar` : nom + `description_ar`). Elle ignore la casse et les accents, tolère les fautes de frappe et classe les résultats par pertinence (le nom compte plus que la description). |
| RG-43 | Le panier est **propre à chaque boutique** et stocké dans le navigateur du client. Le serveur ne stocke pas de panier : il **recalcule** systématiquement les prix et le total. |
| RG-44 | L'acompte minimum affiché = `arrondi supérieur(total × deposit_percent / 100)`, avec `deposit_percent = 30` par défaut (paramétrable par l'admin). Le serveur **n'empêche pas** un montant payé inférieur : la boutique contacte alors le client. |
| RG-45 | La soumission d'une commande exige : au moins un produit, la capture du paiement (image), le nom et le téléphone du client, le montant payé. La banque utilisée et l'adresse de livraison sont facultatives. |
| RG-46 | Une commande conserve une copie du nom et du prix de chaque produit au moment de l'achat. Modifier ou supprimer un produit ensuite ne change pas les commandes existantes. |
| RG-47 | Statuts d'une commande : `SUBMITTED` (nouvelle) → `CONFIRMED` (capture vérifiée) → `DELIVERED` (livrée, solde payé en main propre). Depuis `SUBMITTED` ou `CONFIRMED`, la boutique peut **refuser** (`REJECTED`) avec un motif obligatoire. `DELIVERED` et `REJECTED` sont définitifs. |
| RG-48 | Chaque nouvelle commande crée une notification pour la boutique. |
| RG-49 | Le client (sans compte) suit ses commandes avec leur **référence** et son **numéro de téléphone**. Le front garde les références dans le navigateur et interroge l'API pour afficher les changements de statut, notamment un **refus avec son motif**. |

### Revenus

| Id | Règle |
|---|---|
| RG-50 | Le **revenu du mois** d'une boutique = somme des `total_amount` de ses commandes `DELIVERED` dont `delivered_at` tombe dans le mois en cours (fuseau `Africa/Nouakchott`). Les commandes soumises, confirmées ou refusées ne comptent pas. Le montant compté est le **total** de la commande, pas l'acompte. |

---

## 6. Architecture technique

```
                ┌────────────────────────────────────────────┐
                │  Front React + Vite + Tailwind (plus tard)  │
                └───────────────────────┬────────────────────┘
                                        │ HTTPS · JSON · JWT (Bearer)
┌───────────────────────────────────────▼──────────────────────────────────────┐
│ Django 5.2 + Django REST Framework  (/api/v1/...)                            │
│  apps/core          utilitaires communs, paramètres plateforme, audit        │
│  apps/accounts      utilisateurs, OTP, authentification                      │
│  apps/shops         boutiques, designs, banques, onboarding, profil          │
│  apps/catalog       catégories, produits, import Excel + ZIP                 │
│  apps/orders        commandes, lignes de commande, suivi public              │
│  apps/notifications notifications in-app                                     │
│  apps/administration actions admin, recharges, tableau de bord admin       │
└───────┬──────────────────────┬───────────────────────┬───────────────────────┘
        │                      │                       │
  PostgreSQL 16          Redis 7                 Celery (worker + beat)
  (pg_trgm, unaccent)    (cache, broker)         import ZIP, e-mails, rappels
                                                       │
                                                 Mailpit (dev) / SMTP (prod)
```

### Stack

| Couche | Technologie |
|---|---|
| Langage | Python 3.12 |
| Framework | Django 5.2 LTS, Django REST Framework 3.16 |
| Authentification | JWT (`djangorestframework-simplejwt`), hachage Argon2id |
| Base de données | PostgreSQL 16, ORM Django |
| Recherche | PostgreSQL `pg_trgm` + `unaccent` + normalisation arabe |
| Tâches asynchrones | Celery 5 + Redis 7 |
| Images | Pillow (redimensionnement, conversion WebP) |
| Excel | openpyxl |
| Documentation API | drf-spectacular (OpenAPI 3, Swagger sur `/api/docs/`) |
| Tests | pytest, pytest-django, factory-boy, pytest-cov |
| Qualité | ruff (lint + tri des imports) |
| Conteneurs | Docker, Docker Compose |

### Services Docker (développement)

| Service | Rôle | Port hôte |
|---|---|---|
| `backend` | API Django (`runserver`), applique les migrations au démarrage | 8000 |
| `worker` | Worker Celery | — |
| `beat` | Planificateur Celery (rappels d'expiration) | — |
| `db` | PostgreSQL 16 | 5433 (configurable via `POSTGRES_HOST_PORT`) |
| `redis` | Redis 7 | — |
| `mailpit` | Boîte e-mail de test (lire les OTP) | 8025 (interface), 1025 (SMTP) |

### Arborescence du backend

```
backend/
├── config/
│   ├── settings/  base.py · dev.py · test.py · prod.py
│   ├── urls.py    routes /api/v1/, /api/schema/, /api/docs/
│   ├── celery.py
│   ├── wsgi.py · asgi.py
├── apps/
│   ├── core/ accounts/ shops/ catalog/ orders/ notifications/ administration/
│   │   (chaque app : models.py, serializers.py, views.py, urls.py, services.py,
│   │    selectors.py, permissions.py, tasks.py, admin.py, migrations/, tests/)
├── locale/        traductions fr / ar
├── conftest.py    fixtures pytest communes
├── Dockerfile · entrypoint.sh · requirements.txt · requirements-dev.txt
└── pytest.ini · pyproject.toml
```

---

## 7. Conventions générales de l'API (résumé)

Le détail est dans [05-aspects-transversaux.md](05-aspects-transversaux.md).

| Sujet | Convention |
|---|---|
| Préfixe | `/api/v1/` |
| Format | JSON en UTF-8 ; `multipart/form-data` pour les envois de fichiers |
| Authentification | `Authorization: Bearer <access_token>` |
| Langue | En-tête `Accept-Language: fr` ou `ar` (par défaut `fr`) |
| Dates | ISO 8601 avec fuseau, ex. `2026-12-20T14:30:00+00:00` |
| Montants | Entiers en **MRU** (pas de décimales) |
| Téléphones | 8 chiffres mauritaniens commençant par 2, 3 ou 4, ex. `36123456` |
| Pagination | `?page=1&page_size=20` (max 100) → `{count, next, previous, results}` |
| Erreurs | `{"error": {"code": "...", "message": "...", "details": {...}}}` |

---

## 8. Glossaire

| Terme | Signification |
|---|---|
| **Boutique** | Compte commerçant (`role = SHOP`) et sa vitrine publique |
| **Onboarding** | Étapes après l'inscription : vérification de l'e-mail, choix du design, acceptation des conditions |
| **État (`state`)** | État effectif calculé d'une boutique (voir §4.2) |
| **Recharge** | Prolongation de la date d'expiration par l'administrateur après paiement hors site |
| **Acompte** | Part minimale (30 % par défaut) du total que le client paie avant la livraison |
| **Capture** | Image du reçu de paiement envoyée par le client |
| **Brouillon** | Produit non publié (`DRAFT`) |
| **Liste des erreurs d'import** | Lignes de l'Excel qui n'ont pas pu devenir des produits et qui attendent une correction |
| **MRU** | Ouguiya mauritanienne |
| **OTP** | Code à usage unique envoyé par e-mail |
