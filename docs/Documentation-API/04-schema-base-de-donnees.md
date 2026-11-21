# 04 — Schéma de la base de données

> SGBD : **PostgreSQL 16**. Accès exclusivement par l'**ORM Django**.
> Extensions activées par la migration `core/0001_postgres_extensions` : `pg_trgm` (trigrammes), `unaccent` (accents), `fuzzystrmatch` (distance de Levenshtein).
> Toutes les tables ont une clé primaire `id` de type `BIGINT` auto-incrémentée (`BigAutoField`).
> Tous les horodatages sont de type `TIMESTAMP WITH TIME ZONE` et stockés en UTC.
> Tous les montants sont des **entiers en MRU**.

**Toutes les tables et migrations sont créées pendant la phase 1** (voir [02-phases.md](02-phases.md)). Les phases suivantes n'ajoutent pas de tables : elles ajoutent la logique. Une modification de schéma après la phase 1 suit la procédure décrite au §9.

---

## 1. Diagramme des relations

```
accounts_user (role ADMIN | SHOP)
   │ 1
   │ 1 (OneToOne, owner)
   ▼
shops_shop ───────────── N:1 ──► shops_theme_template
   │ 1
   ├──< shops_bank_account          (N)
   ├──< catalog_category            (N)
   ├──< catalog_product             (N) ──► catalog_category (N:1, facultatif)
   │                                     └► catalog_import_job (N:1, facultatif)
   ├──< catalog_import_job          (N)
   │        └──< catalog_import_error_row (N)
   ├──< orders_order                (N)
   │        └──< orders_order_item  (N) ──► catalog_product (N:1, SET NULL)
   │        └──► shops_bank_account (N:1, SET NULL)
   └──< administration_recharge     (N) ──► accounts_user (performed_by)

accounts_user ──< accounts_otp_code
accounts_user ──< notifications_notification (recipient)
accounts_user ──< core_audit_log (actor)
core_platform_settings (une seule ligne, id = 1)
```

Légende : `──<` relation 1 vers N, `──►` clé étrangère.

---

## 2. Application `accounts`

### 2.1 `accounts_user` — utilisateurs (admins et boutiques)

> Déjà créée dans le socle (`apps/accounts/migrations/0001_initial.py`).

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `email` | varchar(254) | **UNIQUE**, NOT NULL | Identifiant de connexion, toujours en minuscules |
| `password` | varchar(128) | NOT NULL | Hachage Argon2id |
| `role` | varchar(10) | NOT NULL, défaut `SHOP` | `ADMIN` ou `SHOP` |
| `is_email_verified` | boolean | défaut `false` | Passe à `true` après l'OTP d'inscription |
| `is_active` | boolean | défaut `true` | `false` = compte désactivé techniquement (non utilisé pour le blocage métier, voir `shops_shop.is_blocked`) |
| `is_staff` | boolean | défaut `false` | Accès à `/django-admin/` (admins techniques) |
| `is_superuser` | boolean | défaut `false` | |
| `last_login` | timestamptz | NULL | Mis à jour à chaque connexion |
| `date_joined` | timestamptz | NOT NULL | |
| `updated_at` | timestamptz | NOT NULL | Mis à jour automatiquement |

Les tables de liaison `accounts_user_groups` et `accounts_user_user_permissions` (Django) existent mais ne sont pas utilisées par la logique métier.

### 2.2 `accounts_otp_code` — codes à usage unique

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `user_id` | bigint | FK → `accounts_user.id`, ON DELETE CASCADE, NOT NULL | Propriétaire du code |
| `purpose` | varchar(20) | NOT NULL | `REGISTRATION`, `PASSWORD_RESET`, `EMAIL_CHANGE` |
| `sent_to` | varchar(254) | NOT NULL | Adresse qui a reçu le code (nouvelle adresse pour `EMAIL_CHANGE`) |
| `code_hash` | varchar(128) | NOT NULL | Hachage du code (jamais le code en clair) |
| `attempts` | smallint | NOT NULL, défaut 0 | Essais incorrects |
| `expires_at` | timestamptz | NOT NULL | `created_at + 10 minutes` |
| `consumed_at` | timestamptz | NULL | Rempli quand le code est utilisé ou invalidé |
| `created_at` | timestamptz | NOT NULL | |

Index : `(user_id, purpose, created_at DESC)`.
Règle : un code est **valide** si `consumed_at IS NULL`, `expires_at > maintenant` et `attempts < 5`. L'émission d'un nouveau code remplit `consumed_at` de tous les codes encore valides du même `user_id` et `purpose`.

---

## 3. Application `core`

### 3.1 `core_platform_settings` — paramètres de la plateforme (une seule ligne)

| Colonne | Type | Contraintes | Défaut | Description |
|---|---|---|---|---|
| `id` | bigint | PK, toujours `1` | 1 | Singleton |
| `admin_whatsapp` | varchar(8) | NOT NULL | `''` | Numéro WhatsApp de l'admin, utilisé dans tous les liens « contactez l'administrateur » |
| `admin_contact_email` | varchar(254) | NOT NULL | `''` | E-mail de contact affiché aux boutiques |
| `trial_months` | smallint | NOT NULL, CHECK 0 ≤ valeur ≤ 12 | 1 | Durée de l'essai gratuit offert à la validation |
| `deposit_percent` | smallint | NOT NULL, CHECK 1 ≤ valeur ≤ 100 | 30 | Acompte minimum (%) affiché au client |
| `updated_by_id` | bigint | FK → `accounts_user.id`, ON DELETE SET NULL, NULL | | Dernier admin ayant modifié |
| `updated_at` | timestamptz | NOT NULL | | |

La ligne est créée par une migration de données. Elle est lue via `PlatformSettings.load()` (mise en cache, invalidée à chaque modification).

### 3.2 `core_audit_log` — journal d'audit des actions sensibles

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `actor_id` | bigint | FK → `accounts_user.id`, ON DELETE SET NULL, NULL | Auteur de l'action |
| `action` | varchar(50) | NOT NULL | Voir la liste ci-dessous |
| `target_type` | varchar(50) | NOT NULL | Ex. `shop`, `product`, `platform_settings` |
| `target_id` | bigint | NULL | Identifiant de la cible |
| `metadata` | jsonb | NOT NULL, défaut `{}` | Détails (motif, ancienne/nouvelle date…) |
| `ip_address` | inet | NULL | IP de l'auteur |
| `created_at` | timestamptz | NOT NULL | |

Index : `(target_type, target_id)`, `(action)`, `(created_at DESC)`.

Actions enregistrées : `SHOP_SUBMITTED`, `SHOP_RESUBMITTED`, `SHOP_APPROVED`, `SHOP_REJECTED`, `SHOP_BLOCKED`, `SHOP_UNBLOCKED`, `SHOP_RECHARGED`, `PRODUCT_REMOVED_BY_ADMIN`, `SETTINGS_UPDATED`, `ADMIN_LOGIN`, `PASSWORD_RESET`, `EMAIL_CHANGED`.

---

## 4. Application `shops`

### 4.1 `shops_theme_template` — modèles de design proposés

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `code` | varchar(40) | **UNIQUE**, NOT NULL | Identifiant stable, ex. `elegant` |
| `name_fr` | varchar(60) | NOT NULL | Nom affiché en français |
| `name_ar` | varchar(60) | NOT NULL | Nom affiché en arabe |
| `layout` | varchar(20) | NOT NULL | `GRID`, `LIST`, `MAGAZINE`, `MINIMAL` : mise en page que le front applique |
| `preview_image` | varchar(255) | NOT NULL | Chemin de l'image d'aperçu (fichier public) |
| `default_primary_color` | char(7) | NOT NULL | Couleur hexadécimale, ex. `#064E3B` |
| `default_accent_color` | char(7) | NOT NULL | Ex. `#D4A52A` |
| `is_active` | boolean | défaut `true` | Les modèles inactifs ne sont plus proposés |
| `sort_order` | smallint | défaut 0 | Ordre d'affichage |

Données initiales (migration de données, phase 1) : 6 modèles `classique`, `elegant`, `moderne`, `minimal`, `magazine`, `tradition`.

### 4.2 `shops_shop` — boutiques

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `owner_id` | bigint | FK → `accounts_user.id`, **UNIQUE** (OneToOne), ON DELETE CASCADE | Compte propriétaire |
| `name` | varchar(80) | NOT NULL | Nom de la boutique (une seule valeur, en lettres latines ou arabes) |
| `slug` | varchar(100) | **UNIQUE**, NOT NULL | Utilisé dans l'URL publique, généré depuis le nom (§8) |
| `logo` | varchar(255) | NOT NULL | Fichier **public** (`media/shops/logos/…`) |
| `description_fr` | varchar(500) | NOT NULL | Ce que vend la boutique, en français |
| `description_ar` | varchar(500) | NOT NULL | Ce que vend la boutique, en arabe |
| `address` | varchar(255) | NOT NULL | |
| `phone` | varchar(8) | NOT NULL | Téléphone affiché aux clients |
| `whatsapp` | varchar(8) | NOT NULL | Numéro WhatsApp affiché aux clients |
| `owner_full_name` | varchar(120) | NOT NULL | Nom du propriétaire (comparé à la carte d'identité) |
| `id_card_front` | varchar(255) | NOT NULL | Fichier **privé** (`private_media/id_cards/…`) |
| `id_card_back` | varchar(255) | NOT NULL | Fichier **privé** |
| `theme_id` | bigint | FK → `shops_theme_template.id`, ON DELETE PROTECT, NULL | NULL tant que le design n'est pas choisi |
| `primary_color` | char(7) | NOT NULL, défaut `''` | Couleur principale choisie |
| `accent_color` | char(7) | NOT NULL, défaut `''` | Couleur d'accent choisie |
| `onboarding_step` | varchar(20) | NOT NULL, défaut `VERIFY_EMAIL` | `VERIFY_EMAIL`, `CHOOSE_DESIGN`, `ACCEPT_TERMS`, `COMPLETED` |
| `status` | varchar(10) | NOT NULL, défaut `PENDING` | `PENDING`, `APPROVED`, `REJECTED` |
| `rejection_reason` | text | NOT NULL, défaut `''` | Dernier motif de refus |
| `terms_accepted_at` | timestamptz | NULL | |
| `submitted_at` | timestamptz | NULL | Date de la dernière (re)soumission à l'admin |
| `approved_at` | timestamptz | NULL | |
| `approved_by_id` | bigint | FK → `accounts_user.id`, ON DELETE SET NULL, NULL | |
| `rejected_at` | timestamptz | NULL | |
| `expires_at` | timestamptz | NULL | Fin de validité ; NULL tant que non validée |
| `is_blocked` | boolean | NOT NULL, défaut `false` | |
| `block_reason` | text | NOT NULL, défaut `''` | |
| `blocked_at` | timestamptz | NULL | |
| `last_expiry_reminder_days` | smallint | NULL | Dernier rappel envoyé (7, 3 ou 1) ; remis à NULL à chaque recharge |
| `search_name` | text | NOT NULL, défaut `''` | `normaliser(name)` — sert à donner plus de poids au nom dans le classement |
| `search_text_fr` | text | NOT NULL, défaut `''` | `normaliser(name + " " + description_fr)` — maintenu automatiquement (§9.3) |
| `search_text_ar` | text | NOT NULL, défaut `''` | `normaliser(name + " " + description_ar)` |
| `created_at` | timestamptz | NOT NULL | |
| `updated_at` | timestamptz | NOT NULL | |

Contraintes :
- `CHECK (status IN ('PENDING','APPROVED','REJECTED'))`
- `CHECK (status <> 'APPROVED' OR expires_at IS NOT NULL)`

Index :
- `(status, is_blocked, expires_at)` — filtrage des boutiques visibles et du tableau de bord admin ;
- `(submitted_at)` ;
- **GIN** `search_text_fr gin_trgm_ops` et **GIN** `search_text_ar gin_trgm_ops` — recherche.

Champ calculé (non stocké) `state` : voir [01-vue-d-ensemble.md §4.2](01-vue-d-ensemble.md). Il est implémenté **à la fois** comme propriété Python `Shop.state` et comme annotation de queryset `Shop.objects.with_state()` (expression `Case/When`) pour pouvoir filtrer et compter en base.

### 4.3 `shops_bank_account` — moyens de paiement de la boutique

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `shop_id` | bigint | FK → `shops_shop.id`, ON DELETE CASCADE, NOT NULL | |
| `bank_name` | varchar(60) | NOT NULL | Ex. `Bankily`, `Sedad`, `Click` |
| `payment_code` | varchar(40) | NOT NULL | Code ou numéro que le client utilise pour payer |
| `created_at` | timestamptz | NOT NULL | |
| `updated_at` | timestamptz | NOT NULL | |

Contrainte : `UNIQUE (shop_id, bank_name, payment_code)`. Maximum **10** banques par boutique (vérifié dans le service).

---

## 5. Application `catalog`

### 5.1 `catalog_category` — catégories d'une boutique

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `shop_id` | bigint | FK → `shops_shop.id`, ON DELETE CASCADE, NOT NULL | |
| `name_fr` | varchar(60) | NOT NULL, défaut `''` | |
| `name_ar` | varchar(60) | NOT NULL, défaut `''` | |
| `sort_order` | smallint | NOT NULL, défaut 0 | |
| `created_at` | timestamptz | NOT NULL | |

Contraintes :
- `CHECK (name_fr <> '' OR name_ar <> '')`
- `UNIQUE (shop_id, lower(name_fr)) WHERE name_fr <> ''` (unicité insensible à la casse)
- `UNIQUE (shop_id, lower(name_ar)) WHERE name_ar <> ''`

Maximum **100** catégories par boutique.

### 5.2 `catalog_product` — produits

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `shop_id` | bigint | FK → `shops_shop.id`, ON DELETE CASCADE, NOT NULL | |
| `category_id` | bigint | FK → `catalog_category.id`, ON DELETE SET NULL, NULL | Facultative |
| `name_fr` | varchar(150) | NOT NULL, défaut `''` | |
| `name_ar` | varchar(150) | NOT NULL, défaut `''` | |
| `description_fr` | text | NOT NULL, défaut `''` | Max 2 000 caractères (validé par le serializer) |
| `description_ar` | text | NOT NULL, défaut `''` | Max 2 000 caractères |
| `price` | integer | NOT NULL, CHECK `price >= 1 AND price <= 100000000` | Prix en MRU |
| `image` | varchar(255) | NOT NULL | Image principale traitée (WebP, 1 600 px max) — fichier **public** |
| `thumbnail` | varchar(255) | NOT NULL | Miniature (WebP, 400 px) — fichier **public** |
| `status` | varchar(10) | NOT NULL, défaut `PUBLISHED` | `DRAFT` ou `PUBLISHED` |
| `is_available` | boolean | NOT NULL, défaut `true` | |
| `source` | varchar(10) | NOT NULL, défaut `MANUAL` | `MANUAL` ou `IMPORT` |
| `import_job_id` | bigint | FK → `catalog_import_job.id`, ON DELETE SET NULL, NULL | Import d'origine |
| `search_text_fr` | text | NOT NULL, défaut `''` | `normaliser(name_fr ou name_ar + description_fr)` |
| `search_text_ar` | text | NOT NULL, défaut `''` | `normaliser(name_ar ou name_fr + description_ar)` |
| `published_at` | timestamptz | NULL | Rempli au passage en `PUBLISHED` |
| `created_at` | timestamptz | NOT NULL | |
| `updated_at` | timestamptz | NOT NULL | |

Contraintes :
- `CHECK (name_fr <> '' OR name_ar <> '')`
- `CHECK (status IN ('DRAFT','PUBLISHED'))`

Index :
- `(shop_id, status, is_available, price)` — filtres du site public ;
- `(shop_id, category_id)` ;
- `(shop_id, created_at DESC)` ;
- **GIN** `search_text_fr gin_trgm_ops`, **GIN** `search_text_ar gin_trgm_ops`.

Limite : **5 000** produits par boutique (brouillons compris).

### 5.3 `catalog_import_job` — imports Excel + ZIP

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `shop_id` | bigint | FK → `shops_shop.id`, ON DELETE CASCADE, NOT NULL | |
| `excel_file` | varchar(255) | NOT NULL | Fichier **privé**, supprimé 7 jours après la fin |
| `zip_file` | varchar(255) | NOT NULL | Fichier **privé**, supprimé 7 jours après la fin |
| `status` | varchar(12) | NOT NULL, défaut `PENDING` | `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED` |
| `total_rows` | integer | NOT NULL, défaut 0 | Lignes de données lues |
| `success_count` | integer | NOT NULL, défaut 0 | Brouillons créés |
| `error_count` | integer | NOT NULL, défaut 0 | Lignes en erreur |
| `failure_reason` | text | NOT NULL, défaut `''` | Rempli si `FAILED` (fichier illisible, colonnes manquantes…) |
| `created_at` | timestamptz | NOT NULL | |
| `started_at` | timestamptz | NULL | |
| `finished_at` | timestamptz | NULL | |

Index : `(shop_id, created_at DESC)`.
Règle : une boutique ne peut avoir qu'**un seul** import `PENDING` ou `PROCESSING` à la fois.

### 5.4 `catalog_import_error_row` — lignes d'import en erreur (liste 2)

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `job_id` | bigint | FK → `catalog_import_job.id`, ON DELETE CASCADE, NOT NULL | |
| `shop_id` | bigint | FK → `shops_shop.id`, ON DELETE CASCADE, NOT NULL | Dénormalisé pour filtrer vite et isoler les boutiques |
| `row_number` | integer | NOT NULL | Numéro de ligne dans l'Excel (la ligne d'en-tête est la ligne 1) |
| `name_fr` | varchar(150) | NOT NULL, défaut `''` | Valeur lue (tronquée à 150) |
| `name_ar` | varchar(150) | NOT NULL, défaut `''` | |
| `description_fr` | text | NOT NULL, défaut `''` | |
| `description_ar` | text | NOT NULL, défaut `''` | |
| `price_raw` | varchar(50) | NOT NULL, défaut `''` | Valeur brute (peut être invalide, ex. `"deux mille"`) |
| `category_raw` | varchar(60) | NOT NULL, défaut `''` | |
| `image_filename` | varchar(255) | NOT NULL, défaut `''` | Nom de fichier indiqué dans l'Excel |
| `image` | varchar(255) | NOT NULL, défaut `''` | Image traitée si elle a été trouvée dans le ZIP ou envoyée lors de la correction (fichier public) |
| `thumbnail` | varchar(255) | NOT NULL, défaut `''` | |
| `errors` | jsonb | NOT NULL, défaut `[]` | Liste `[{"field": "price", "code": "INVALID_PRICE", "message": "..."}]` |
| `created_at` | timestamptz | NOT NULL | |
| `updated_at` | timestamptz | NOT NULL | |

Index : `(shop_id, job_id)`.
Quand une ligne est publiée avec succès, elle est **supprimée** de cette table (le produit créé la remplace).

---

## 6. Application `orders`

### 6.1 `orders_order` — commandes

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `reference` | varchar(20) | **UNIQUE**, NOT NULL | `CMD-AAAA-NNNNNN` (§8) |
| `shop_id` | bigint | FK → `shops_shop.id`, ON DELETE **PROTECT**, NOT NULL | |
| `customer_name` | varchar(100) | NOT NULL | |
| `customer_phone` | varchar(8) | NOT NULL | |
| `delivery_address` | varchar(255) | NOT NULL, défaut `''` | Facultatif |
| `bank_account_id` | bigint | FK → `shops_bank_account.id`, ON DELETE SET NULL, NULL | Banque choisie par le client |
| `bank_name_snapshot` | varchar(60) | NOT NULL, défaut `''` | Copie du nom de la banque |
| `total_amount` | integer | NOT NULL, CHECK `> 0` | Total recalculé par le serveur |
| `deposit_percent` | smallint | NOT NULL | Copie de `deposit_percent` au moment de la commande |
| `deposit_required` | integer | NOT NULL | `ceil(total_amount × deposit_percent / 100)` |
| `amount_paid` | integer | NOT NULL, CHECK `>= 0` | Montant déclaré payé par le client |
| `payment_proof` | varchar(255) | NOT NULL | Capture — fichier **privé** |
| `status` | varchar(10) | NOT NULL, défaut `SUBMITTED` | `SUBMITTED`, `CONFIRMED`, `DELIVERED`, `REJECTED` |
| `rejection_reason` | text | NOT NULL, défaut `''` | Obligatoire si `REJECTED` |
| `confirmed_at` | timestamptz | NULL | |
| `delivered_at` | timestamptz | NULL | Sert au calcul du revenu du mois |
| `rejected_at` | timestamptz | NULL | |
| `created_at` | timestamptz | NOT NULL | |
| `updated_at` | timestamptz | NOT NULL | |

Contraintes :
- `CHECK (status IN ('SUBMITTED','CONFIRMED','DELIVERED','REJECTED'))`
- `CHECK (status <> 'DELIVERED' OR delivered_at IS NOT NULL)`
- `CHECK (status <> 'REJECTED' OR rejection_reason <> '')`

Index :
- `(shop_id, status, created_at DESC)` — liste des commandes du dashboard ;
- `(shop_id, delivered_at)` — revenu du mois ;
- `(customer_phone)` — suivi public.

Champ calculé `remaining_amount = max(total_amount − amount_paid, 0)`.

### 6.2 `orders_order_item` — lignes de commande

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `order_id` | bigint | FK → `orders_order.id`, ON DELETE CASCADE, NOT NULL | |
| `product_id` | bigint | FK → `catalog_product.id`, ON DELETE SET NULL, NULL | NULL si le produit a été supprimé depuis |
| `product_name_fr` | varchar(150) | NOT NULL, défaut `''` | Copie au moment de l'achat |
| `product_name_ar` | varchar(150) | NOT NULL, défaut `''` | Copie au moment de l'achat |
| `product_thumbnail` | varchar(255) | NOT NULL, défaut `''` | Copie du chemin de la miniature |
| `unit_price` | integer | NOT NULL, CHECK `> 0` | Prix unitaire au moment de l'achat |
| `quantity` | smallint | NOT NULL, CHECK `quantity BETWEEN 1 AND 99` | |
| `line_total` | integer | NOT NULL | `unit_price × quantity` |

Une commande contient au maximum **50** lignes distinctes.

---

## 7. Application `notifications`

### 7.1 `notifications_notification`

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `recipient_id` | bigint | FK → `accounts_user.id`, ON DELETE CASCADE, NOT NULL | Boutique ou admin |
| `type` | varchar(40) | NOT NULL | Voir le tableau ci-dessous |
| `data` | jsonb | NOT NULL, défaut `{}` | Paramètres du message (référence, motif, date…) |
| `is_read` | boolean | NOT NULL, défaut `false` | |
| `read_at` | timestamptz | NULL | |
| `created_at` | timestamptz | NOT NULL | |

Index : `(recipient_id, is_read, created_at DESC)`.

Le **texte** de la notification n'est pas stocké : il est produit au moment de la lecture, dans la langue de la requête, à partir de `type` et `data`. Ainsi une notification s'affiche en arabe si l'interface est en arabe.

| `type` | Destinataire | `data` |
|---|---|---|
| `SHOP_SUBMITTED` | Tous les admins | `shop_id`, `shop_name` |
| `SHOP_RESUBMITTED` | Tous les admins | `shop_id`, `shop_name` |
| `SHOP_APPROVED` | Boutique | `expires_at` |
| `SHOP_REJECTED` | Boutique | `reason` |
| `SHOP_UNBLOCKED` | Boutique | — |
| `SHOP_RECHARGED` | Boutique | `previous_expires_at`, `new_expires_at` |
| `EXPIRY_REMINDER` | Boutique | `expires_at`, `days_left` |
| `ORDER_NEW` | Boutique | `order_id`, `reference`, `total_amount`, `customer_name` |
| `IMPORT_COMPLETED` | Boutique | `job_id`, `success_count`, `error_count` |
| `IMPORT_FAILED` | Boutique | `job_id`, `failure_reason` |
| `PRODUCT_REMOVED` | Boutique | `product_name`, `reason` |

Les clients n'ont pas de compte : ils ne reçoivent pas de notification stockée. Ils suivent leurs commandes par l'endpoint public de suivi (RG-49).

---

## 8. Application `administration`

### 8.1 `administration_recharge` — historique des recharges

| Colonne | Type | Contraintes | Description |
|---|---|---|---|
| `id` | bigint | PK | |
| `shop_id` | bigint | FK → `shops_shop.id`, ON DELETE CASCADE, NOT NULL | |
| `performed_by_id` | bigint | FK → `accounts_user.id`, ON DELETE SET NULL, NULL | Admin auteur |
| `duration_months` | smallint | NULL | Rempli si la recharge est en mois |
| `previous_expires_at` | timestamptz | NOT NULL | |
| `new_expires_at` | timestamptz | NOT NULL, CHECK `new_expires_at > previous_expires_at` | |
| `amount_received` | integer | NULL, CHECK `>= 0` | Montant reçu hors site (facultatif) |
| `note` | varchar(255) | NOT NULL, défaut `''` | |
| `created_at` | timestamptz | NOT NULL | |

Index : `(shop_id, created_at DESC)`, `(created_at)`.

---

## 9. Règles de génération et de maintenance

### 9.1 Slug d'une boutique
`slug = slugify(name)` (translittération des caractères arabes impossible : si le résultat est vide, on utilise `boutique`). En cas de doublon, on ajoute `-2`, `-3`… Le slug **ne change pas** quand le nom est modifié (les liens partagés restent valides).

### 9.2 Référence de commande
Après l'insertion : `reference = "CMD-" + année(created_at) + "-" + id complété à 6 chiffres`, ex. `CMD-2026-000042`. L'insertion et la mise à jour se font dans la **même transaction**.

### 9.3 Colonnes `search_text_*`
Elles sont recalculées dans `save()` (et dans les services d'import en masse, qui utilisent `bulk_create`) avec la fonction `apps.core.text.normalize_search_text()` :
1. passage en minuscules ;
2. suppression des accents latins (`é → e`) ;
3. normalisation arabe : suppression des signes diacritiques (tashkeel) et du tatweel `ـ`, `أ إ آ → ا`, `ة → ه`, `ى → ي`, `ؤ → و`, `ئ → ي` ;
4. chiffres « arabizi » placés entre deux lettres : `7 → h`, `3 → a`, `9 → q`, `5 → kh`, `2 → a` (`mel7fa → melhfa`) ;
5. pliage phonétique latin : `ph → f` (`téléphone → telefone`) ;
6. réduction des lettres doublées (`accessoires → acesoires`) ;
7. remplacement de toute ponctuation par une espace et réduction des espaces multiples.

La même fonction est appliquée au **texte recherché** par le client, ce qui garantit que les deux côtés sont comparés sous la même forme.

### 9.4 Modifier le schéma après la phase 1
1. Prévenir l'équipe sur le canal du projet avant de commencer.
2. Une seule migration par application et par branche ; nom explicite (`--name ajout_champ_x`).
3. Avant la demande de fusion : se mettre à jour sur `dev`, supprimer sa migration, la **régénérer**, relancer les tests.
4. Ne jamais modifier une migration déjà fusionnée dans `dev`.
5. Mettre à jour ce document dans la même branche.

### 9.5 Suppressions
- Suppression d'une boutique : impossible tant qu'elle a des commandes (`PROTECT`). La plateforme ne supprime pas les boutiques : elle les bloque.
- Suppression d'un produit : physique (la ligne disparaît), les commandes gardent leurs copies (`product_id` passe à NULL). Les fichiers image sont supprimés par un signal `post_delete` après la validation de la transaction.
