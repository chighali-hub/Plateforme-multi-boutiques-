# 02 — Phases de réalisation du backend

> Le backend est réalisé en **8 phases**. Chaque phase est développée dans **sa propre branche**, créée depuis `dev`, et fusionnée dans `dev` par une demande de fusion (pull request) dont la CI est verte. Les règles Git sont dans [08-regles-du-travail.md](08-regles-du-travail.md).
>
> L'équipe compte **4 développeurs** : chacun prend **2 phases**.

---

## 0. Ce qui est déjà fait (socle livré avec la documentation)

| Élément | Emplacement |
|---|---|
| Docker Compose : `backend`, `worker`, `beat`, `db` (PostgreSQL 16), `redis`, `mailpit` | `docker-compose.yml`, `backend/Dockerfile`, `backend/entrypoint.sh` |
| Projet Django, paramètres `base` / `dev` / `test` / `prod` | `backend/config/` |
| DRF, JWT, drf-spectacular (Swagger `/api/docs/`), CORS, Celery, Redis, e-mail | `backend/config/settings/base.py` |
| 7 applications vides et enregistrées | `backend/apps/{core,accounts,shops,catalog,orders,notifications,administration}` |
| Modèle `User` personnalisé + migration initiale | `backend/apps/accounts/models.py` |
| Extensions PostgreSQL `pg_trgm` et `unaccent` | `backend/apps/core/migrations/0001_postgres_extensions.py` |
| Endpoint `GET /api/v1/health/` + tests | `backend/apps/core/` |
| pytest, ruff, couverture | `backend/pytest.ini`, `backend/pyproject.toml` |

---

## 1. Vue d'ensemble

| # | Phase | Branche | Dépend de | Vague |
|---|---|---|---|---|
| 1 | Socle commun et modèles de données | `feat/phase-1-socle-et-modeles` | — | 1 |
| 2 | Authentification et comptes | `feat/phase-2-authentification` | 1 | 2 |
| 3 | Espace boutique : onboarding, profil, banques, notifications | `feat/phase-3-espace-boutique` | 1 | 2 |
| 4 | Administration des boutiques | `feat/phase-4-administration` | 1 | 2 |
| 5 | Catalogue : catégories et produits | `feat/phase-5-catalogue` | 1 | 2 |
| 6 | Import en masse Excel + ZIP | `feat/phase-6-import-produits` | 5 | 3 |
| 7 | Site public et recherche | `feat/phase-7-site-public` | 5 | 3 |
| 8 | Commandes, paiement et tableau de bord boutique | `feat/phase-8-commandes` | 5 | 3 |

### Pourquoi la phase 1 crée **tous** les modèles

Si chaque phase créait ses propres tables, quatre branches modifieraient les migrations en parallèle et les conflits seraient permanents. La phase 1 crée donc **toutes les tables et toutes les migrations** du [schéma](04-schema-base-de-donnees.md). Ensuite, les phases 2 à 8 n'ajoutent que de la **logique** (services, serializers, vues, tâches, tests) et peuvent avancer en parallèle sans conflit de migration.

### Les vagues

```
Vague 1 :  [P1 socle + modèles]
                 │ fusion dans dev
Vague 2 :  [P2 auth] [P3 espace boutique] [P4 administration] [P5 catalogue]   (en parallèle)
                                                                 │ fusion dans dev
Vague 3 :                         [P6 import] [P7 site public] [P8 commandes]   (en parallèle)
```

- Pendant la vague 1, les trois autres développeurs lisent la documentation, préparent leurs tests (fixtures, cas à couvrir) et relisent la branche de la phase 1.
- En vague 2, les phases 3, 4 et 5 n'attendent **pas** la phase 2 : leurs tests utilisent les fixtures `shop_client` / `admin_client`, qui authentifient l'utilisateur avec `force_authenticate` ([06-strategie-de-tests.md](06-strategie-de-tests.md)).

### Répartition proposée

| Développeur | Phases | Logique de la répartition |
|---|---|---|
| Dev A | **1** puis **5** | Connaît les modèles, enchaîne sur le catalogue |
| Dev B | **2** puis **6** | Auth puis import (traitement de fichiers) |
| Dev C | **3** puis **7** | Espace boutique puis vitrine publique (mêmes objets `Shop`) |
| Dev D | **4** puis **8** | Administration puis commandes (transitions d'état, statistiques) |

Chaque vague 3 n'a besoin que de la phase 5. Dev B, C et D peuvent commencer la vague 3 dès que la phase 5 est fusionnée, même si leur phase de vague 2 est encore en revue.

---

## 2. Définition de « terminé » (commune à toutes les phases)

Une phase n'est fusionnée que si **toutes** ces conditions sont remplies :

- [ ] Tous les endpoints de la phase sont conformes à [03-reference-api.md](03-reference-api.md) (chemins, codes HTTP, corps, codes d'erreur).
- [ ] Chaque endpoint est documenté dans Swagger (`@extend_schema` : résumé, tag, corps, réponses).
- [ ] Les règles métier (RG-xx) de la phase sont implémentées et **chacune a au moins un test**.
- [ ] Les tests de permissions et d'isolation entre boutiques passent ([06-strategie-de-tests.md](06-strategie-de-tests.md) §4).
- [ ] Couverture ≥ 80 % sur les fichiers modifiés.
- [ ] `ruff check .` et `ruff format --check .` ne signalent rien.
- [ ] `python manage.py makemigrations --check --dry-run` ne détecte aucune migration manquante.
- [ ] Les messages visibles par l'utilisateur sont traduisibles (`gettext`) et traduits en arabe dans `locale/ar`.
- [ ] La documentation est mise à jour si quelque chose a changé.
- [ ] Les jobs CI `lint`, `test` et `build` du dernier push de la branche sont verts.

---

## 3. Détail des phases

### Phase 1 — Socle commun et modèles de données
**Branche :** `feat/phase-1-socle-et-modeles` · **Développeur :** Dev A · **Vague :** 1

**Objectif :** donner à toute l'équipe les modèles, les migrations et les outils communs sur lesquels les autres phases s'appuient.

**Tâches**
1. **Modèles et migrations** de toutes les tables de [04-schema-base-de-donnees.md](04-schema-base-de-donnees.md) : `accounts_otp_code`, `core_platform_settings`, `core_audit_log`, `shops_theme_template`, `shops_shop`, `shops_bank_account`, `catalog_category`, `catalog_product`, `catalog_import_job`, `catalog_import_error_row`, `orders_order`, `orders_order_item`, `notifications_notification`, `administration_recharge`. Avec toutes les contraintes `CHECK`, `UNIQUE` et les index (dont les index GIN trigrammes).
2. **Migrations de données** : la ligne unique de `core_platform_settings` ; les 6 modèles de design (`shops_theme_template`) avec leurs images d'aperçu.
3. **`Shop.state`** : propriété Python et annotation `Shop.objects.with_state()` ([01-vue-d-ensemble.md §4.2](01-vue-d-ensemble.md)), plus les méthodes `is_publicly_visible()` et `Shop.objects.publicly_visible()`.
4. **Module `apps/core`** ([05-aspects-transversaux.md](05-aspects-transversaux.md)) :
   - `exceptions.py` : gestionnaire d'exceptions DRF au format `{"error": {...}}` + classes d'exceptions métier (`BusinessError` et ses sous-classes avec `code` et `status_code`) ;
   - `pagination.py` : `StandardPagination` (page_size 20, max 100) et `PublicPagination` (24) ;
   - `permissions.py` : `IsPlatformAdmin`, `IsShopOwner`, `ShopStateAllowed` (paramétrée par la liste des états autorisés) ;
   - `text.py` : `normalize_search_text()` ;
   - `validators.py` : téléphone mauritanien, couleur hexadécimale, images (type réel, taille) ;
   - `whatsapp.py` : `build_whatsapp_url(phone, text=None)` ;
   - `images.py` : `process_image()` (redimensionnement, WebP, miniature, suppression des métadonnées EXIF) ;
   - `storage.py` : stockage des fichiers privés et `private_file_response()` ;
   - `audit.py` : `log_action(actor, action, target, metadata, request)` ;
   - `models.py` : `TimeStampedModel`, `PlatformSettings.load()` avec cache.
5. **Service de notifications** (`apps/notifications/services.py`) : `notify(user, type, data)`, `notify_admins(type, data)`, et le rendu traduit `render(notification, language)`.
6. **Service d'e-mail** (`apps/core/emails.py`) : `send_templated_email(to, template, context, language)` en tâche Celery, gabarits texte FR/AR dans `templates/emails/`.
7. **Admin Django** : enregistrement de tous les modèles (lecture seule pour les champs sensibles).
8. **Calcul du panier** (`apps/orders/pricing.py`) : `compute_deposit(total, percent)` (arrondi supérieur en arithmétique entière) et `compute_cart(shop, items)` qui renvoie les lignes recalculées, les produits indisponibles et le total. Ces fonctions sont utilisées par le devis (phase 7) et par la soumission de commande (phase 8) : les placer dans la phase 1 évite que ces deux phases parallèles dépendent l'une de l'autre.
9. **Fabriques de test** (`factory-boy`) pour chaque modèle dans `apps/<app>/tests/factories.py`, et fixtures communes dans `backend/conftest.py` : `make_shop(state)`, `admin_user`, `admin_client`, `api_client`, `shop_client`, `make_shop_client(state)`, `other_shop_client`, `image_file` (liste complète : [06-strategie-de-tests.md §3.1](06-strategie-de-tests.md)).

**Livrables vérifiables**
- `docker compose exec backend python manage.py migrate` crée toutes les tables.
- `docker compose exec backend pytest` : tests des modèles (contraintes, `state` pour chacun des 6 états, `with_state()` cohérent avec `state`), du gestionnaire d'erreurs, des permissions, de `compute_cart` et `compute_deposit`, de `normalize_search_text`, de `process_image`, des validateurs.

---

### Phase 2 — Authentification et comptes
**Branche :** `feat/phase-2-authentification` · **Développeur :** Dev B · **Vague :** 2

**Objectif :** inscription des boutiques avec OTP, connexion boutique et admin, gestion des jetons, mot de passe oublié, paramètres du compte.

**Endpoints** ([03-reference-api.md §3 et §4](03-reference-api.md))
`POST /auth/shop/register/`, `POST /auth/shop/verify-email/`, `POST /auth/otp/resend/`, `POST /auth/shop/login/`, `POST /auth/admin/login/`, `POST /auth/token/refresh/`, `POST /auth/logout/`, `POST /auth/password/forgot/`, `POST /auth/password/verify-code/`, `POST /auth/password/reset/`, `GET /auth/me/`, `POST /account/change-password/`, `POST /account/change-email/request/`, `POST /account/change-email/confirm/`.

**Tâches**
1. Service OTP (`apps/accounts/otp.py`) : génération (`secrets`), hachage, expiration, essais, délai de renvoi, invalidation des anciens codes (RG-03).
2. Inscription : création atomique `User` + `Shop` + enregistrement des fichiers (logo traité en WebP, carte d'identité en stockage privé), envoi de l'OTP.
3. Connexion boutique avec la séquence de contrôles (identifiants → e-mail vérifié → bloquée → expirée).
4. Connexion admin séparée, audit `ADMIN_LOGIN`.
5. Rafraîchissement avec contrôle bloquée/expirée ; déconnexion par liste noire.
6. Mot de passe oublié en 3 étapes, avec jeton signé (`django.core.signing.TimestampSigner`) à usage unique.
7. Changement de mot de passe (nouveaux jetons, autres sessions invalidées) et d'e-mail (OTP à la nouvelle adresse).
8. Limitations de débit (`ScopedRateThrottle` : `auth`, `otp`).
9. Commande `python manage.py create_admin --email ...`.
10. Gabarits d'e-mail : OTP d'inscription, OTP de réinitialisation, OTP de changement d'e-mail, avis de changement d'e-mail.

**Tests clés** : RG-01 à RG-08 ; chaque code d'erreur de la section ; non-divulgation de l'existence d'un e-mail (forgot, resend) ; une boutique ne se connecte pas par l'endpoint admin et inversement ; jeton de réinitialisation réutilisé → refusé.

---

### Phase 3 — Espace boutique : onboarding, profil, banques, notifications
**Branche :** `feat/phase-3-espace-boutique` · **Développeur :** Dev C · **Vague :** 2

**Objectif :** tout ce que la boutique fait sur son propre compte, hors catalogue et commandes.

**Endpoints** ([03-reference-api.md §5 et §9](03-reference-api.md))
`GET /public/themes/`, `POST /shop/onboarding/design/`, `POST /shop/onboarding/accept-terms/`, `GET /shop/me/`, `PATCH /shop/me/`, `PATCH /shop/me/design/`, `PUT /shop/me/id-card/`, `GET /shop/me/id-card/{side}/`, `POST /shop/me/resubmit/`, `GET|POST /shop/banks/`, `PATCH|DELETE /shop/banks/{id}/`, `GET /shop/recharge-info/`, `GET /shop/recharges/`, `GET /notifications/`, `GET /notifications/unread-count/`, `POST /notifications/{id}/read/`, `POST /notifications/read-all/`.

**Tâches**
1. Serializer `ShopProfile` complet, y compris `days_left` et `permissions` (matrice [03 §0.3](03-reference-api.md)).
2. Onboarding : contrôle de l'étape, passage à `COMPLETED`, notification `SHOP_SUBMITTED` aux admins, audit.
3. Profil : modification avec remplacement et suppression de l'ancien logo ; mise à jour de `search_text_*`.
4. Carte d'identité (état `REJECTED`) et renvoi de la demande (RG-13).
5. Banques : CRUD, unicité, limite de 10.
6. Recharge : lien WhatsApp pré-rempli, historique.
7. Notifications : liste, compteur, lecture, rendu traduit.

**Tests clés** : matrice des états complète pour chaque endpoint ; RG-05, RG-13 ; une boutique ne peut ni lire ni modifier les banques d'une autre ; les fichiers de carte d'identité ne sont jamais accessibles par une URL `/media/`.

---

### Phase 4 — Administration des boutiques
**Branche :** `feat/phase-4-administration` · **Développeur :** Dev D · **Vague :** 2

**Objectif :** le dashboard admin complet et les rappels d'expiration.

**Endpoints** ([03-reference-api.md §11](03-reference-api.md), plus `GET /public/platform-info/` de la §10)
`GET /admin/dashboard/`, `GET /admin/shops/`, `GET /admin/shops/{id}/`, `GET /admin/shops/{id}/id-card/{side}/`, `POST /admin/shops/{id}/approve/`, `.../reject/`, `.../block/`, `.../unblock/`, `GET .../recharge-preview/`, `POST .../recharge/`, `GET .../recharges/`, `GET .../products/`, `POST .../products/{product_id}/remove/`, `GET /admin/recharges/`, `GET|PATCH /admin/settings/`, `GET /admin/audit-logs/`, `GET /public/platform-info/`.

**Tâches**
1. Liste des boutiques filtrable par `state` (annotation `with_state()`), recherche insensible aux accents.
2. Actions valider / refuser / bloquer / débloquer avec contrôles d'état, notifications, e-mails et audit (RG-10 à RG-14). Le blocage invalide les jetons `refresh` de la boutique.
3. Calcul de recharge (`apps/administration/services.py::compute_new_expiry`) partagé par l'aperçu et la recharge (RG-20 à RG-23) ; recharge transactionnelle avec verrou.
4. Paramètres de la plateforme (invalidation du cache), journal d'audit filtrable.
5. Modération des produits.
6. **Tâche Celery beat** `send_expiry_reminders` (tous les jours à 08:00, heure de Nouakchott) : rappels à 7, 3 et 1 jour(s), sans doublon grâce à `last_expiry_reminder_days` (RG-25).
7. Gabarits d'e-mail : boutique validée, refusée, bloquée, débloquée, rechargée, rappel d'expiration.

**Tests clés** : chaque transition autorisée et interdite ; calcul de recharge (boutique active, expirée, fin de mois, date cible invalide) ; rappels non envoyés deux fois ; un utilisateur `SHOP` reçoit `403 PERMISSION_DENIED` sur tous les endpoints `/admin/`.

---

### Phase 5 — Catalogue : catégories et produits
**Branche :** `feat/phase-5-catalogue` · **Développeur :** Dev A · **Vague :** 2

**Objectif :** la gestion manuelle du catalogue par la boutique.

**Endpoints** ([03-reference-api.md §6](03-reference-api.md))
`GET|POST /shop/categories/`, `PATCH|DELETE /shop/categories/{id}/`, `GET|POST /shop/products/`, `GET|PATCH|DELETE /shop/products/{id}/`, `POST /shop/products/bulk-publish/`, `POST /shop/products/bulk-update/`, `POST /shop/products/bulk-delete/`.

**Tâches**
1. CRUD des catégories avec unicité insensible à la casse et limite de 100.
2. CRUD des produits : traitement d'image (`process_image` → image + miniature), `search_text_*`, `published_at`, limite de 5 000.
3. Filtres (`django-filter`) : `search`, `category`, `uncategorized`, `status`, `is_available`, `source`, `import_job`, `min_price`, `max_price`, `ordering`.
4. Actions groupées (publication, mise à jour, suppression) limitées aux produits de la boutique.
5. Suppression des fichiers image après suppression d'un produit (`transaction.on_commit`).
6. Service réutilisable `create_product_from_data(shop, data, image_file)` : il sera appelé par l'import (phase 6).

**Tests clés** : RG-30 à RG-32 ; filtres combinés ; `min_price > max_price` ; isolation (une boutique ne peut pas utiliser la catégorie d'une autre ni modifier ses produits) ; actions groupées avec identifiants d'une autre boutique → `NOT_FOUND` dans `skipped` pour `bulk-publish`, ignorés et non comptés pour `bulk-update` et `bulk-delete`.

---

### Phase 6 — Import en masse Excel + ZIP
**Branche :** `feat/phase-6-import-produits` · **Développeur :** Dev B · **Vague :** 3

**Objectif :** permettre l'ajout de centaines de produits en une fois ([03-reference-api.md §7](03-reference-api.md)).

**Endpoints**
`GET /shop/products/import/template/`, `POST /shop/products/import/`, `GET /shop/products/import/jobs/`, `GET /shop/products/import/jobs/{id}/`, `GET /shop/products/import/errors/`, `GET|PATCH|DELETE /shop/products/import/errors/{id}/`, `POST /shop/products/import/errors/publish/`.

**Tâches**
1. Génération du modèle Excel (openpyxl) : feuille `Produits` avec en-têtes figés et largeur de colonnes, feuille `Instructions` FR/AR.
2. Contrôles synchrones : extensions, tailles, Excel lisible, en-têtes, nombre de lignes, ZIP sûr (taille décompressée, nombre de fichiers, chemins).
3. Tâche Celery `process_import_job(job_id)` : lecture ligne par ligne, recherche de la photo dans le ZIP (insensible à la casse, sans dossier), validation de **toutes** les erreurs de la ligne, création des brouillons par lots (`bulk_create` de 100), création des catégories manquantes, enregistrement des lignes en erreur, compteurs, notification `IMPORT_COMPLETED` ou `IMPORT_FAILED`.
4. Correction d'une ligne d'erreur avec revalidation ; publication de la collection (RG-35).
5. Un seul import actif par boutique ; nettoyage des fichiers d'import 7 jours après la fin (tâche beat quotidienne).

**Tests clés** : fichier modèle conforme ; Excel sans en-tête, avec 1 001 lignes, avec des cellules vides ; ZIP avec chemins `../`, ZIP trop gros une fois décompressé ; ligne avec plusieurs erreurs ; image en double dans le ZIP ; publication partielle ; isolation des lignes d'erreur entre boutiques.

---

### Phase 7 — Site public et recherche
**Branche :** `feat/phase-7-site-public` · **Développeur :** Dev C · **Vague :** 3

**Objectif :** tout ce que voit le client sans compte, sauf la soumission de commande.

**Endpoints** ([03-reference-api.md §10](03-reference-api.md))
`GET /public/shops/`, `GET /public/shops/suggest/`, `GET /public/shops/{slug}/`, `GET /public/shops/{slug}/products/`, `GET /public/shops/{slug}/products/{id}/`, `POST /public/shops/{slug}/cart/quote/`.

**Tâches**
1. Recherche de boutiques et de produits selon [05-aspects-transversaux.md §9](05-aspects-transversaux.md) (trigrammes + correspondance de sous-chaîne + score pondéré), dans la langue `lang`.
2. Champs traduits avec repli sur l'autre langue.
3. Page boutique : catégories visibles avec compteurs, `has_multiple_categories`, `price_range`.
4. Filtres produits combinés et validés.
5. Devis du panier : recalcul des prix, produits indisponibles, acompte (RG-43, RG-44) avec `compute_cart` de la phase 1, banques.
6. Mise en cache courte (60 s) de la liste des boutiques sans recherche.
7. Commandes `seed_demo` (données de démonstration pour le front et la recette) et `seed_load` (jeu de données de charge, local uniquement) décrites dans [06-strategie-de-tests.md §6](06-strategie-de-tests.md) ; mesure des temps de recherche.

**Tests clés** : RG-40 à RG-44 ; recherche « melehfa » trouve « Melhfa » ; « telephone » trouve « Téléphone » ; recherche arabe avec et sans diacritiques, `أ`/`ا`, `ة`/`ه` ; une boutique expirée, bloquée, en attente ou sans banque n'apparaît nulle part ; acompte arrondi au supérieur (ex. total 1 001 → 301).

---

### Phase 8 — Commandes, paiement et tableau de bord boutique
**Branche :** `feat/phase-8-commandes` · **Développeur :** Dev D · **Vague :** 3

**Objectif :** du paiement du client jusqu'au revenu affiché à la boutique.

**Endpoints** ([03-reference-api.md §8 et §10](03-reference-api.md))
`POST /public/shops/{slug}/orders/`, `POST /public/orders/track/`, `GET /shop/orders/`, `GET /shop/orders/{id}/`, `GET /shop/orders/{id}/payment-proof/`, `POST /shop/orders/{id}/confirm/`, `POST /shop/orders/{id}/deliver/`, `POST /shop/orders/{id}/reject/`, `GET /shop/dashboard/`.

**Tâches**
1. Soumission de commande transactionnelle : recalcul avec `compute_cart` de la phase 1, `409 CART_CHANGED`, copies des produits, référence, capture en stockage privé, notification `ORDER_NEW`, e-mail à la boutique, limites de débit (IP et téléphone).
2. Suivi public par téléphone + références sans divulgation.
3. Liste et détail des commandes de la boutique avec filtres ; lien WhatsApp vers le client.
4. Transitions de statut (RG-47) avec verrou de ligne.
5. Tableau de bord : revenu du mois (RG-50) par jour et mois précédent, carte d'expiration, compteurs.

**Tests clés** : RG-45 à RG-50 ; un prix modifié côté client est ignoré ; produit dépublié entre le devis et la commande → `409 CART_CHANGED` ; transitions interdites ; seules les commandes `DELIVERED` du mois comptent dans le revenu ; une commande livrée le dernier jour du mois à 23:30 (heure de Nouakchott) compte dans ce mois ; une boutique ne voit pas les commandes ni les captures d'une autre.

---

## 4. Après la phase 8

Quand les 8 phases sont fusionnées dans `dev` :

1. Recette complète des scénarios du [README](../../README.md) via Swagger ou une collection de requêtes.
2. Vérification de la couverture globale (≥ 80 %) et de la conformité de toute l'API avec [03-reference-api.md](03-reference-api.md).
3. Fusion de `dev` dans `main` par le responsable du dépôt (voir [08-regles-du-travail.md](08-regles-du-travail.md)), puis démarrage du front React.
