# 03 — Référence de l'API

> Base : `http://localhost:8000/api/v1` en développement.
> Documentation interactive générée par le code : `http://localhost:8000/api/docs/` (Swagger) et `http://localhost:8000/api/schema/` (OpenAPI 3).
> **Ce document est la référence contractuelle.** Si le code et ce document divergent, on corrige l'un ou l'autre dans la même branche, jamais l'un sans l'autre.

---

## Sommaire

0. [Conventions communes](#0-conventions-communes)
1. [Index de tous les endpoints](#1-index-de-tous-les-endpoints)
2. [Système](#2-système)
3. [Authentification](#3-authentification)
4. [Compte (boutique et admin)](#4-compte-boutique-et-admin)
5. [Espace boutique : onboarding, profil, banques, recharge](#5-espace-boutique--onboarding-profil-banques-recharge)
6. [Espace boutique : catégories et produits](#6-espace-boutique--catégories-et-produits)
7. [Espace boutique : import Excel + ZIP](#7-espace-boutique--import-excel--zip)
8. [Espace boutique : commandes et tableau de bord](#8-espace-boutique--commandes-et-tableau-de-bord)
9. [Notifications](#9-notifications)
10. [Site public](#10-site-public)
11. [Administration](#11-administration)

---

## 0. Conventions communes

### 0.1 En-têtes

| En-tête | Valeur | Quand |
|---|---|---|
| `Authorization` | `Bearer <access_token>` | Tous les endpoints marqués 🔒 |
| `Accept-Language` | `fr` ou `ar` (défaut `fr`) | Toujours : langue des messages d'erreur, des notifications et des champs traduits du site public |
| `Content-Type` | `application/json` | Corps JSON |
| `Content-Type` | `multipart/form-data` | Endpoints marqués 📎 (envoi de fichiers) |

### 0.2 Niveaux d'accès

| Symbole | Signification |
|---|---|
| 🌐 | Public, sans authentification |
| 🔒 SHOP | Utilisateur `role = SHOP` ; les **états autorisés** de la boutique sont précisés pour chaque endpoint |
| 🔒 ADMIN | Utilisateur `role = ADMIN` |
| 🔒 TOUS | Tout utilisateur authentifié (boutique ou admin) |

Pour tout endpoint 🔒 SHOP, l'API vérifie l'état de la boutique **à chaque requête**, dans cet ordre :

1. boutique bloquée → `403 SHOP_BLOCKED` ;
2. boutique expirée → `403 SHOP_EXPIRED` ;
3. état non autorisé pour cet endpoint → `403 SHOP_STATE_FORBIDDEN`.

### 0.3 Matrice des états de la boutique

| Groupe d'endpoints | ONBOARDING | PENDING | REJECTED | ACTIVE |
|---|:-:|:-:|:-:|:-:|
| `GET /auth/me/`, `/account/*`, `/notifications/*` | ✅ | ✅ | ✅ | ✅ |
| `GET /shop/me/` | ✅ | ✅ | ✅ | ✅ |
| `POST /shop/onboarding/*` | ✅ (selon l'étape) | ❌ | ❌ | ❌ |
| `GET /shop/banks/` | ❌ | ✅ | ✅ | ✅ |
| `PATCH /shop/me/`, `PATCH /shop/me/design/`, écriture `/shop/banks/*` | ❌ | ❌ | ✅ | ✅ |
| `PUT /shop/me/id-card/`, `POST /shop/me/resubmit/` | ❌ | ❌ | ✅ | ❌ |
| `GET /shop/me/id-card/{side}/` | ❌ | ✅ | ✅ | ✅ |
| `/shop/dashboard/`, `/shop/recharge-info/`, `/shop/recharges/` | ❌ | ❌ | ❌ | ✅ |
| `/shop/categories/*`, `/shop/products/*`, `/shop/orders/*` | ❌ | ❌ | ❌ | ✅ |

Les états `EXPIRED` et `BLOCKED` n'apparaissent pas : ils sont refusés partout (étapes 1 et 2 ci-dessus).

### 0.4 Format des erreurs

Toutes les erreurs ont la même forme :

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Les données envoyées sont invalides.",
    "details": {
      "phone": ["Saisissez un numéro mauritanien de 8 chiffres commençant par 2, 3 ou 4."],
      "items": {"0": {"quantity": ["Assurez-vous que cette valeur est inférieure ou égale à 99."]}}
    }
  }
}
```

- `code` : identifiant stable, **en anglais**, que le front utilise pour décider quoi afficher.
- `message` : texte lisible, traduit selon `Accept-Language`.
- `details` : objet facultatif. Pour `VALIDATION_ERROR`, il contient les erreurs **par champ** (format DRF). Pour les autres codes, il contient des données utiles (voir chaque code).

### 0.5 Codes d'erreur

| HTTP | `code` | Signification | `details` |
|---|---|---|---|
| 400 | `VALIDATION_ERROR` | Données invalides | Erreurs par champ |
| 400 | `OTP_INVALID` | Code OTP incorrect | `{"attempts_left": 3}` |
| 400 | `OTP_EXPIRED` | Code expiré ou déjà utilisé, ou aucun code en cours | — |
| 400 | `OTP_TOO_MANY_ATTEMPTS` | 5 essais incorrects : il faut demander un nouveau code | — |
| 400 | `RESET_TOKEN_INVALID` | Jeton de réinitialisation invalide, expiré ou déjà utilisé | — |
| 401 | `AUTHENTICATION_REQUIRED` | Jeton absent | — |
| 401 | `TOKEN_INVALID` | Jeton invalide ou expiré : le front tente un rafraîchissement | — |
| 401 | `INVALID_CREDENTIALS` | E-mail ou mot de passe incorrect | — |
| 403 | `PERMISSION_DENIED` | Rôle non autorisé (ex. boutique sur un endpoint admin) | — |
| 403 | `EMAIL_NOT_VERIFIED` | E-mail non vérifié | `{"email": "..."}` |
| 403 | `SHOP_BLOCKED` | Boutique bloquée | `{"admin_whatsapp": "22334455", "whatsapp_url": "https://wa.me/22222334455"}` |
| 403 | `SHOP_EXPIRED` | Boutique expirée | `{"expired_at": "...", "admin_whatsapp": "...", "whatsapp_url": "..."}` |
| 403 | `SHOP_STATE_FORBIDDEN` | Action interdite dans l'état actuel | `{"state": "PENDING"}` |
| 404 | `NOT_FOUND` | Ressource inexistante **ou appartenant à une autre boutique** | — |
| 405 | `METHOD_NOT_ALLOWED` | Méthode HTTP non prise en charge | — |
| 409 | `EMAIL_ALREADY_USED` | E-mail déjà utilisé | `{"is_verified": false}` |
| 409 | `ALREADY_VERIFIED` | E-mail déjà vérifié | — |
| 409 | `INVALID_STATE_TRANSITION` | Transition de statut impossible | `{"current_status": "DELIVERED"}` ou `{"current_state": "ACTIVE"}` |
| 409 | `ONBOARDING_STEP_MISMATCH` | Étape d'onboarding incorrecte | `{"onboarding_step": "CHOOSE_DESIGN"}` |
| 409 | `LIMIT_REACHED` | Limite atteinte (produits, catégories, banques) | `{"limit": 10}` |
| 409 | `IMPORT_ALREADY_RUNNING` | Un import est déjà en cours | `{"job_id": 12}` |
| 409 | `CART_CHANGED` | Produits devenus indisponibles depuis l'ajout au panier | `{"unavailable_product_ids": [5], "current_total": 4500}` |
| 413 | `FILE_TOO_LARGE` | Fichier trop volumineux | `{"field": "zip_file", "max_bytes": 209715200}` |
| 429 | `THROTTLED` | Trop de requêtes | `{"retry_after": 42}` (secondes) |
| 429 | `OTP_RESEND_TOO_SOON` | Nouveau code demandé trop tôt | `{"retry_after": 37}` |
| 500 | `SERVER_ERROR` | Erreur inattendue (journalisée) | — |

### 0.6 Pagination

Endpoints marqués *paginé* : paramètres `page` (défaut 1) et `page_size` (défaut 20, maximum 100).

```json
{
  "count": 137,
  "next": "http://localhost:8000/api/v1/shop/products/?page=3",
  "previous": "http://localhost:8000/api/v1/shop/products/?page=1",
  "results": [ ... ]
}
```

Une page hors limites renvoie `404 NOT_FOUND`.

### 0.7 Types de données

| Type | Format | Exemple |
|---|---|---|
| Date-heure | ISO 8601 avec fuseau | `"2026-12-20T14:30:00+00:00"` |
| Date | `AAAA-MM-JJ` | `"2026-12-20"` |
| Montant | Entier, MRU | `2500` |
| Téléphone | 8 chiffres, commence par 2, 3 ou 4 | `"36123456"` |
| Couleur | `#RRGGBB`, renvoyée en majuscules | `"#064E3B"` |
| URL de fichier public | URL absolue | `"http://localhost:8000/media/products/2026/11/abc.webp"` |
| URL de fichier privé | URL absolue d'un endpoint authentifié | `"http://localhost:8000/api/v1/shop/orders/42/payment-proof/"` |
| Lien WhatsApp | `https://wa.me/222` + numéro (+ `?text=` encodé) | `"https://wa.me/22236123456"` |

### 0.8 Fichiers envoyés

| Champ | Formats | Taille max |
|---|---|---|
| Logo, images produits, carte d'identité, capture de paiement | JPEG, PNG, WebP (contenu vérifié, pas seulement l'extension) | 5 Mo |
| Excel d'import | `.xlsx` | 5 Mo |
| ZIP d'import | `.zip` | 200 Mo (500 Mo une fois décompressé) |

---

## 1. Index de tous les endpoints

| Méthode | Chemin | Accès | Phase |
|---|---|---|---|
| GET | `/health/` | 🌐 | socle |
| POST | `/auth/shop/register/` 📎 | 🌐 | 2 |
| POST | `/auth/shop/verify-email/` | 🌐 | 2 |
| POST | `/auth/otp/resend/` | 🌐 | 2 |
| POST | `/auth/shop/login/` | 🌐 | 2 |
| POST | `/auth/admin/login/` | 🌐 | 2 |
| POST | `/auth/token/refresh/` | 🌐 | 2 |
| POST | `/auth/logout/` | 🔒 TOUS | 2 |
| POST | `/auth/password/forgot/` | 🌐 | 2 |
| POST | `/auth/password/verify-code/` | 🌐 | 2 |
| POST | `/auth/password/reset/` | 🌐 | 2 |
| GET | `/auth/me/` | 🔒 TOUS | 2 |
| POST | `/account/change-password/` | 🔒 TOUS | 2 |
| POST | `/account/change-email/request/` | 🔒 TOUS | 2 |
| POST | `/account/change-email/confirm/` | 🔒 TOUS | 2 |
| GET | `/public/themes/` | 🌐 | 3 |
| POST | `/shop/onboarding/design/` | 🔒 SHOP | 3 |
| POST | `/shop/onboarding/accept-terms/` | 🔒 SHOP | 3 |
| GET | `/shop/me/` | 🔒 SHOP | 3 |
| PATCH | `/shop/me/` 📎 | 🔒 SHOP | 3 |
| PATCH | `/shop/me/design/` | 🔒 SHOP | 3 |
| PUT | `/shop/me/id-card/` 📎 | 🔒 SHOP | 3 |
| GET | `/shop/me/id-card/{side}/` | 🔒 SHOP | 3 |
| POST | `/shop/me/resubmit/` | 🔒 SHOP | 3 |
| GET, POST | `/shop/banks/` | 🔒 SHOP | 3 |
| PATCH, DELETE | `/shop/banks/{id}/` | 🔒 SHOP | 3 |
| GET | `/shop/recharge-info/` | 🔒 SHOP | 3 |
| GET | `/shop/recharges/` | 🔒 SHOP | 3 |
| GET | `/notifications/` | 🔒 TOUS | 3 |
| GET | `/notifications/unread-count/` | 🔒 TOUS | 3 |
| POST | `/notifications/{id}/read/` | 🔒 TOUS | 3 |
| POST | `/notifications/read-all/` | 🔒 TOUS | 3 |
| GET | `/admin/dashboard/` | 🔒 ADMIN | 4 |
| GET | `/admin/shops/` | 🔒 ADMIN | 4 |
| GET | `/admin/shops/{id}/` | 🔒 ADMIN | 4 |
| GET | `/admin/shops/{id}/id-card/{side}/` | 🔒 ADMIN | 4 |
| POST | `/admin/shops/{id}/approve/` | 🔒 ADMIN | 4 |
| POST | `/admin/shops/{id}/reject/` | 🔒 ADMIN | 4 |
| POST | `/admin/shops/{id}/block/` | 🔒 ADMIN | 4 |
| POST | `/admin/shops/{id}/unblock/` | 🔒 ADMIN | 4 |
| GET | `/admin/shops/{id}/recharge-preview/` | 🔒 ADMIN | 4 |
| POST | `/admin/shops/{id}/recharge/` | 🔒 ADMIN | 4 |
| GET | `/admin/shops/{id}/recharges/` | 🔒 ADMIN | 4 |
| GET | `/admin/shops/{id}/products/` | 🔒 ADMIN | 4 |
| POST | `/admin/shops/{id}/products/{product_id}/remove/` | 🔒 ADMIN | 4 |
| GET | `/admin/recharges/` | 🔒 ADMIN | 4 |
| GET, PATCH | `/admin/settings/` | 🔒 ADMIN | 4 |
| GET | `/admin/audit-logs/` | 🔒 ADMIN | 4 |
| GET | `/public/platform-info/` | 🌐 | 4 |
| GET, POST | `/shop/categories/` | 🔒 SHOP | 5 |
| PATCH, DELETE | `/shop/categories/{id}/` | 🔒 SHOP | 5 |
| GET, POST 📎 | `/shop/products/` | 🔒 SHOP | 5 |
| GET, PATCH 📎, DELETE | `/shop/products/{id}/` | 🔒 SHOP | 5 |
| POST | `/shop/products/bulk-publish/` | 🔒 SHOP | 5 |
| POST | `/shop/products/bulk-update/` | 🔒 SHOP | 5 |
| POST | `/shop/products/bulk-delete/` | 🔒 SHOP | 5 |
| GET | `/shop/products/import/template/` | 🔒 SHOP | 6 |
| POST | `/shop/products/import/` 📎 | 🔒 SHOP | 6 |
| GET | `/shop/products/import/jobs/` | 🔒 SHOP | 6 |
| GET | `/shop/products/import/jobs/{id}/` | 🔒 SHOP | 6 |
| GET | `/shop/products/import/errors/` | 🔒 SHOP | 6 |
| GET, PATCH 📎, DELETE | `/shop/products/import/errors/{id}/` | 🔒 SHOP | 6 |
| POST | `/shop/products/import/errors/publish/` | 🔒 SHOP | 6 |
| GET | `/public/shops/` | 🌐 | 7 |
| GET | `/public/shops/suggest/` | 🌐 | 7 |
| GET | `/public/shops/{slug}/` | 🌐 | 7 |
| GET | `/public/shops/{slug}/products/` | 🌐 | 7 |
| GET | `/public/shops/{slug}/products/{id}/` | 🌐 | 7 |
| POST | `/public/shops/{slug}/cart/quote/` | 🌐 | 7 |
| POST | `/public/shops/{slug}/orders/` 📎 | 🌐 | 8 |
| POST | `/public/orders/track/` | 🌐 | 8 |
| GET | `/shop/orders/` | 🔒 SHOP | 8 |
| GET | `/shop/orders/{id}/` | 🔒 SHOP | 8 |
| GET | `/shop/orders/{id}/payment-proof/` | 🔒 SHOP | 8 |
| POST | `/shop/orders/{id}/confirm/` | 🔒 SHOP | 8 |
| POST | `/shop/orders/{id}/deliver/` | 🔒 SHOP | 8 |
| POST | `/shop/orders/{id}/reject/` | 🔒 SHOP | 8 |
| GET | `/shop/dashboard/` | 🔒 SHOP | 8 |

> **Ordre des routes :** les routes littérales (`/shop/products/import/...`, `/shop/products/bulk-publish/`…) doivent être déclarées **avant** `/shop/products/{id}/`. Les identifiants numériques utilisent le convertisseur `<int:id>`.

---

## 2. Système

### `GET /health/` 🌐
Vérifie que l'API et la base de données répondent. **Déjà implémenté.**

**200**
```json
{"status": "ok"}
```

---

## 3. Authentification

### Objet `User` (renvoyé par plusieurs endpoints)

```json
{
  "id": 7,
  "email": "aicha@example.com",
  "role": "SHOP",
  "is_email_verified": true,
  "shop": {
    "id": 3,
    "name": "Aïcha Mode",
    "slug": "aicha-mode",
    "logo_url": "http://localhost:8000/media/shops/logos/2026/11/a1b2.webp",
    "state": "PENDING",
    "onboarding_step": "COMPLETED",
    "expires_at": null
  }
}
```

Pour un admin, `role = "ADMIN"` et `shop = null`.

### Objet `Tokens`

```json
{
  "access": "eyJhbGciOiJIUzI1NiIs...",
  "refresh": "eyJhbGciOiJIUzI1NiIs...",
  "user": { "...objet User..." }
}
```

Durées de vie : `access` 15 minutes, `refresh` 7 jours. Chaque rafraîchissement renvoie un **nouveau** `refresh` et invalide l'ancien (rotation).

---

### `POST /auth/shop/register/` 🌐 📎
Inscription d'une boutique (RG-01, RG-02). Crée le compte (e-mail non vérifié) et la boutique (`onboarding_step = VERIFY_EMAIL`, `status = PENDING`), puis envoie un OTP par e-mail.

Limite : 10 requêtes/minute par IP.

| Champ | Type | Obligatoire | Règles |
|---|---|---|---|
| `shop_name` | texte | oui | 2 à 80 caractères |
| `logo` | image | oui | JPEG/PNG/WebP, 5 Mo max |
| `description_fr` | texte | oui | 10 à 500 caractères |
| `description_ar` | texte | oui | 10 à 500 caractères |
| `address` | texte | oui | 5 à 255 caractères |
| `phone` | texte | oui | Téléphone mauritanien |
| `whatsapp` | texte | oui | Téléphone mauritanien |
| `email` | e-mail | oui | Unique, converti en minuscules |
| `password` | texte | oui | RG-06 |
| `password_confirm` | texte | oui | Identique à `password` |
| `owner_full_name` | texte | oui | 3 à 120 caractères |
| `id_card_front` | image | oui | JPEG/PNG/WebP, 5 Mo max |
| `id_card_back` | image | oui | JPEG/PNG/WebP, 5 Mo max |

**201**
```json
{
  "email": "aicha@example.com",
  "otp_expires_in": 600,
  "resend_available_in": 60
}
```

**Erreurs** : `400 VALIDATION_ERROR`, `409 EMAIL_ALREADY_USED` (`details.is_verified` indique si le compte existant est vérifié ; s'il ne l'est pas, le front propose « Renvoyer le code »), `413 FILE_TOO_LARGE`, `429 THROTTLED`.

---

### `POST /auth/shop/verify-email/` 🌐
Valide l'OTP d'inscription (RG-03). En cas de succès : `is_email_verified = true`, `onboarding_step = CHOOSE_DESIGN`, et la boutique est **connectée** directement.

Limite : 5 requêtes/minute par IP.

```json
{"email": "aicha@example.com", "code": "482913"}
```

**200** : objet `Tokens`.

**Erreurs** : `400 VALIDATION_ERROR` (code non composé de 6 chiffres), `400 OTP_INVALID`, `400 OTP_EXPIRED`, `400 OTP_TOO_MANY_ATTEMPTS`, `409 ALREADY_VERIFIED`, `429 THROTTLED`. Un e-mail inconnu renvoie `400 OTP_EXPIRED` (aucune divulgation).

---

### `POST /auth/otp/resend/` 🌐
Renvoie un code. Invalide les codes précédents du même type.

```json
{"email": "aicha@example.com", "purpose": "REGISTRATION"}
```

| `purpose` | Comportement |
|---|---|
| `REGISTRATION` | Uniquement si l'e-mail existe et n'est pas vérifié |
| `PASSWORD_RESET` | Uniquement si l'e-mail existe |

**200** (toujours la même réponse, que l'e-mail existe ou non)
```json
{"resend_available_in": 60}
```

**Erreurs** : `400 VALIDATION_ERROR`, `429 OTP_RESEND_TOO_SOON` (uniquement pour `REGISTRATION` ; pour `PASSWORD_RESET` la réponse reste `200` et aucun e-mail n'est envoyé pendant le délai).

---

### `POST /auth/shop/login/` 🌐
Connexion d'une boutique. Limite : 10 requêtes/minute par IP.

```json
{"email": "aicha@example.com", "password": "MotDePasse!2026"}
```

Contrôles, dans l'ordre :

| Contrôle | Résultat si échec |
|---|---|
| E-mail et mot de passe corrects, `role = SHOP` | `401 INVALID_CREDENTIALS` |
| E-mail vérifié | `403 EMAIL_NOT_VERIFIED` |
| Boutique non bloquée | `403 SHOP_BLOCKED` |
| Boutique non expirée | `403 SHOP_EXPIRED` |

**200** : objet `Tokens`. Les états `ONBOARDING`, `PENDING`, `REJECTED` et `ACTIVE` obtiennent des jetons ; le front utilise `user.shop.state` et `user.shop.onboarding_step` pour choisir l'écran.

Exemple `403 SHOP_EXPIRED` (le front affiche la page blanche avec le lien WhatsApp) :
```json
{
  "error": {
    "code": "SHOP_EXPIRED",
    "message": "Ce compte a expiré. Pour le recharger, contactez l'administrateur.",
    "details": {
      "expired_at": "2026-12-20T10:00:00+00:00",
      "admin_whatsapp": "22334455",
      "whatsapp_url": "https://wa.me/22222334455?text=Bonjour%2C%20je%20souhaite%20recharger%20le%20compte%20de%20la%20boutique%20A%C3%AFcha%20Mode"
    }
  }
}
```

---

### `POST /auth/admin/login/` 🌐
Connexion de l'administrateur (page dédiée). Limite : 5 requêtes/minute par IP.

```json
{"email": "admin@plateforme.mr", "password": "..."}
```

**200** : objet `Tokens` (`user.role = "ADMIN"`, `user.shop = null`). Chaque connexion réussie crée une entrée d'audit `ADMIN_LOGIN`.

**Erreurs** : `401 INVALID_CREDENTIALS` (y compris si le compte existe mais est une boutique), `429 THROTTLED`.

---

### `POST /auth/token/refresh/` 🌐

```json
{"refresh": "eyJ..."}
```

**200**
```json
{"access": "eyJ...", "refresh": "eyJ..."}
```

**Erreurs** : `400 VALIDATION_ERROR` (champ absent ou vide), `401 TOKEN_INVALID` (jeton invalide, expiré, déjà utilisé ou révoqué ; compte désactivé). Pour une boutique bloquée ou expirée, le rafraîchissement renvoie `403 SHOP_BLOCKED` / `403 SHOP_EXPIRED` et le jeton n'est **pas** consommé : il redevient utilisable après déblocage ou recharge.

---

### `POST /auth/logout/` 🔒 TOUS
Invalide le `refresh` (liste noire).

```json
{"refresh": "eyJ..."}
```

**204** sans corps. **Erreurs** : `401 AUTHENTICATION_REQUIRED` (pas de jeton `access`), `401 TOKEN_INVALID` (jeton `refresh` invalide ou appartenant à un autre utilisateur).

---

### `POST /auth/password/forgot/` 🌐
Étape 1 du mot de passe oublié (RG-07). Fonctionne pour les boutiques et l'admin. Limite : 5 requêtes/minute par IP.

```json
{"email": "aicha@example.com"}
```

**200** (identique que l'e-mail existe ou non)
```json
{"otp_expires_in": 600, "resend_available_in": 60}
```

### `POST /auth/password/verify-code/` 🌐
Étape 2 : vérifie l'OTP et renvoie un jeton de réinitialisation valable **15 minutes**, utilisable **une seule fois**.

```json
{"email": "aicha@example.com", "code": "120734"}
```

**200**
```json
{"reset_token": "Nw:1t9Xyz:abc...", "expires_in": 900}
```

**Erreurs** : `400 OTP_INVALID`, `400 OTP_EXPIRED`, `400 OTP_TOO_MANY_ATTEMPTS`.

### `POST /auth/password/reset/` 🌐
Étape 3 : nouveau mot de passe. Toutes les sessions (jetons `refresh`) de l'utilisateur sont invalidées. Audit `PASSWORD_RESET`.

```json
{"reset_token": "Nw:1t9Xyz:abc...", "new_password": "Nouveau!2026", "new_password_confirm": "Nouveau!2026"}
```

**204**. **Erreurs** : `400 RESET_TOKEN_INVALID`, `400 VALIDATION_ERROR`.

---

### `GET /auth/me/` 🔒 TOUS
**200** : objet `User`.

---

## 4. Compte (boutique et admin)

Ces endpoints sont dans l'onglet **Paramètres** des deux dashboards.

### `POST /account/change-password/` 🔒 TOUS

```json
{"current_password": "Ancien!2026", "new_password": "Nouveau!2026", "new_password_confirm": "Nouveau!2026"}
```

**200** : nouvel objet `Tokens`. Les autres sessions sont fermées ; la session courante reçoit de nouveaux jetons.

**Erreurs** : `400 VALIDATION_ERROR` (`current_password` incorrect, mots de passe différents, RG-06).

### `POST /account/change-email/request/` 🔒 TOUS
Envoie un OTP à la **nouvelle** adresse (RG-08). Limite : 5 requêtes/minute.

```json
{"new_email": "contact@aichamode.mr", "current_password": "MotDePasse!2026"}
```

**200**
```json
{"sent_to": "contact@aichamode.mr", "otp_expires_in": 600, "resend_available_in": 60}
```

**Erreurs** : `400 VALIDATION_ERROR` (mot de passe incorrect, nouvelle adresse identique à l'actuelle), `409 EMAIL_ALREADY_USED`, `429 OTP_RESEND_TOO_SOON`.

### `POST /account/change-email/confirm/` 🔒 TOUS

```json
{"code": "553201"}
```

**200** : objet `User` avec le nouvel e-mail. Audit `EMAIL_CHANGED`. Un e-mail d'information est envoyé à l'**ancienne** adresse.

**Erreurs** : `400 OTP_INVALID`, `400 OTP_EXPIRED`, `400 OTP_TOO_MANY_ATTEMPTS`, `409 EMAIL_ALREADY_USED` (adresse prise entre-temps).

---

## 5. Espace boutique : onboarding, profil, banques, recharge

### Objet `Theme`

```json
{
  "id": 2,
  "code": "elegant",
  "name": "Élégant",
  "name_fr": "Élégant",
  "name_ar": "أنيق",
  "layout": "MAGAZINE",
  "preview_image_url": "http://localhost:8000/media/themes/elegant.webp",
  "default_primary_color": "#7C2D5B",
  "default_accent_color": "#D4A52A"
}
```

`name` est la traduction dans la langue de la requête.

### `GET /public/themes/` 🌐
Galerie des designs (page « Bienvenue » et onglet Paramètres). Seuls les modèles actifs, triés par `sort_order`. Non paginé.

**200** : `[Theme, ...]`

---

### `POST /shop/onboarding/design/` 🔒 SHOP — état `ONBOARDING`, étape `CHOOSE_DESIGN` ou `ACCEPT_TERMS`
Enregistre le design choisi. Passe l'étape à `ACCEPT_TERMS`. Peut être rappelé depuis `ACCEPT_TERMS` (retour en arrière).

```json
{"theme_id": 2, "primary_color": "#7C2D5B", "accent_color": "#D4A52A"}
```

`primary_color` et `accent_color` sont facultatifs : par défaut, les couleurs du modèle.

**200** : objet `ShopProfile` (ci-dessous).
**Erreurs** : `400 VALIDATION_ERROR` (modèle inexistant ou inactif, couleur invalide), `409 ONBOARDING_STEP_MISMATCH`.

### `POST /shop/onboarding/accept-terms/` 🔒 SHOP — état `ONBOARDING`, étape `ACCEPT_TERMS`
La boutique clique sur « J'accepte » (RG-05). Effets : `terms_accepted_at` et `submitted_at` = maintenant, `onboarding_step = COMPLETED` (l'état devient `PENDING`), notification `SHOP_SUBMITTED` à tous les admins, audit `SHOP_SUBMITTED`.

```json
{"accept_terms": true}
```

**200** : objet `ShopProfile`.
**Erreurs** : `400 VALIDATION_ERROR` (`accept_terms` différent de `true`), `409 ONBOARDING_STEP_MISMATCH`.

---

### Objet `ShopProfile`

```json
{
  "id": 3,
  "name": "Aïcha Mode",
  "slug": "aicha-mode",
  "email": "aicha@example.com",
  "logo_url": "http://localhost:8000/media/shops/logos/2026/11/a1b2.webp",
  "description_fr": "Melhfas, voiles et parfums de qualité.",
  "description_ar": "ملاحف و خمارات و عطور عالية الجودة.",
  "address": "Tevragh Zeina, Nouakchott",
  "phone": "36123456",
  "whatsapp": "36123456",
  "owner_full_name": "Aïcha Mint Ahmed",
  "theme": { "...objet Theme..." },
  "primary_color": "#7C2D5B",
  "accent_color": "#D4A52A",
  "onboarding_step": "COMPLETED",
  "status": "APPROVED",
  "state": "ACTIVE",
  "rejection_reason": "",
  "submitted_at": "2026-11-20T09:12:00+00:00",
  "approved_at": "2026-11-20T15:40:00+00:00",
  "expires_at": "2026-12-20T15:40:00+00:00",
  "days_left": 29,
  "id_card_front_url": "http://localhost:8000/api/v1/shop/me/id-card/front/",
  "id_card_back_url": "http://localhost:8000/api/v1/shop/me/id-card/back/",
  "banks_count": 2,
  "is_publicly_visible": true,
  "public_url": "http://localhost:5173/boutiques/aicha-mode",
  "permissions": {
    "can_edit_profile": true,
    "can_edit_id_card": false,
    "can_resubmit": false,
    "can_manage_catalog": true,
    "can_manage_orders": true
  },
  "created_at": "2026-11-20T09:00:00+00:00"
}
```

- `days_left` : nombre de jours entiers restants (arrondi supérieur), `0` si expirée, `null` si `expires_at` est `null`.
- `permissions` : calculé depuis la matrice §0.3. Le front s'en sert pour activer ou griser les menus.

### `GET /shop/me/` 🔒 SHOP — tous les états
**200** : objet `ShopProfile`.

### `PATCH /shop/me/` 🔒 SHOP 📎 — états `REJECTED`, `ACTIVE`
Modifie le profil. Tous les champs sont facultatifs.

| Champ | Règles |
|---|---|
| `name` | 2 à 80 caractères (le `slug` ne change pas) |
| `logo` | Image, 5 Mo max ; l'ancien fichier est supprimé |
| `description_fr`, `description_ar` | 10 à 500 caractères |
| `address` | 5 à 255 caractères |
| `phone`, `whatsapp` | Téléphone mauritanien |
| `owner_full_name` | 3 à 120 caractères |

**200** : objet `ShopProfile`. **Erreurs** : `400 VALIDATION_ERROR`, `403 SHOP_STATE_FORBIDDEN`, `413 FILE_TOO_LARGE`.

### `PATCH /shop/me/design/` 🔒 SHOP — états `REJECTED`, `ACTIVE`
Change le design depuis l'onglet Paramètres (même galerie que l'onboarding).

```json
{"theme_id": 4, "primary_color": "#064E3B", "accent_color": "#D4A52A"}
```

Mêmes champs et mêmes règles que `POST /shop/onboarding/design/` : `theme_id` obligatoire (modèle actif), couleurs facultatives (par défaut, celles du modèle). L'étape d'onboarding ne change pas.

**200** : objet `ShopProfile`. **Erreurs** : `400 VALIDATION_ERROR`, `403 SHOP_STATE_FORBIDDEN`.

### `PUT /shop/me/id-card/` 🔒 SHOP 📎 — état `REJECTED`
Remplace la carte d'identité (ex. motif « carte illisible »). Au moins un des deux champs `id_card_front`, `id_card_back`. Les images sont nettoyées (métadonnées supprimées, qualité conservée) et stockées dans l'espace **privé** ; les anciens fichiers remplacés sont supprimés.

**200** : objet `ShopProfile`. **Erreurs** : `400 VALIDATION_ERROR` (aucune face envoyée : `details.non_field_errors` ; image invalide), `403 SHOP_STATE_FORBIDDEN`, `413 FILE_TOO_LARGE`.

### `GET /shop/me/id-card/{side}/` 🔒 SHOP — états `PENDING`, `REJECTED`, `ACTIVE`
`side` = `front` ou `back`. Renvoie le **fichier image** (`Content-Type: image/...`, `Cache-Control: private, no-store`). Une autre valeur de `side`, ou un fichier absent du stockage, renvoie `404 NOT_FOUND`. Une boutique ne lit que **sa** carte (le chemin ne contient aucun identifiant de boutique).

### `POST /shop/me/resubmit/` 🔒 SHOP — état `REJECTED`
« Renvoyer la demande de validation » (RG-13). Effets : `status = PENDING`, `submitted_at` = maintenant, notification `SHOP_RESUBMITTED` aux admins, audit `SHOP_RESUBMITTED` (le motif du refus précédent est recopié dans `metadata.previous_rejection_reason`). Le `rejection_reason` est conservé jusqu'à la prochaine décision.

Corps vide. **200** : objet `ShopProfile` (`state = "PENDING"`). **Erreurs** : `403 SHOP_STATE_FORBIDDEN` (demande déjà renvoyée), `409 INVALID_STATE_TRANSITION` (l'état a changé pendant la requête, ex. deux renvois simultanés).

---

### Banques

Objet `BankAccount` :
```json
{"id": 5, "bank_name": "Bankily", "payment_code": "22334455", "created_at": "...", "updated_at": "..."}
```

| Méthode | Chemin | États | Corps | Réponse |
|---|---|---|---|---|
| GET | `/shop/banks/` | `PENDING`, `REJECTED`, `ACTIVE` | — | **200** `[BankAccount]` (non paginé) |
| POST | `/shop/banks/` | `REJECTED`, `ACTIVE` | `{"bank_name": "Sedad", "payment_code": "44556677"}` | **201** `BankAccount` |
| PATCH | `/shop/banks/{id}/` | `REJECTED`, `ACTIVE` | champs à modifier | **200** `BankAccount` |
| DELETE | `/shop/banks/{id}/` | `REJECTED`, `ACTIVE` | — | **204** |

Règles : `bank_name` 2 à 60 caractères, `payment_code` 2 à 40 caractères (espaces de début et de fin retirés), couple unique par boutique, 10 banques maximum (`409 LIMIT_REACHED`). Un doublon (même banque, sans tenir compte de la casse, et même code dans la boutique) est refusé par `400 VALIDATION_ERROR` avec `details.non_field_errors`. Une banque d'une autre boutique renvoie `404 NOT_FOUND`. Supprimer la dernière banque rend la boutique invisible sur le site public (RG-40) ; `ShopProfile.is_publicly_visible` passe alors à `false`.

---

### `GET /shop/recharge-info/` 🔒 SHOP — état `ACTIVE`
Onglet « Charger mon compte ».

**200**
```json
{
  "expires_at": "2026-12-20T15:40:00+00:00",
  "days_left": 29,
  "admin_whatsapp": "22334455",
  "whatsapp_url": "https://wa.me/22222334455?text=Bonjour%2C%20je%20souhaite%20recharger%20le%20compte%20de%20la%20boutique%20A%C3%AFcha%20Mode%20(aicha%40example.com)",
  "admin_contact_email": "contact@plateforme.mr"
}
```

Le message pré-rempli est traduit selon `Accept-Language`. Tant que l'administrateur n'a pas renseigné son numéro (ou son e-mail) dans les paramètres, `admin_whatsapp` et `whatsapp_url` (ou `admin_contact_email`) valent `""`.

### `GET /shop/recharges/` 🔒 SHOP — état `ACTIVE` — *paginé*
Historique des recharges de la boutique, du plus récent au plus ancien.

```json
{
  "count": 1, "next": null, "previous": null,
  "results": [
    {
      "id": 9,
      "duration_months": 12,
      "previous_expires_at": "2026-12-20T15:40:00+00:00",
      "new_expires_at": "2027-12-20T15:40:00+00:00",
      "created_at": "2026-12-18T11:00:00+00:00"
    }
  ]
}
```

Le montant reçu et la note sont réservés à l'admin et ne figurent pas dans cette réponse.

---

## 6. Espace boutique : catégories et produits

Tous ces endpoints exigent l'état `ACTIVE`.

### Catégories

Objet `Category` :
```json
{"id": 4, "name_fr": "Melhfas", "name_ar": "ملاحف", "sort_order": 0, "products_count": 250, "created_at": "..."}
```

| Méthode | Chemin | Corps | Réponse |
|---|---|---|---|
| GET | `/shop/categories/` | — | **200** `[Category]` triées par `sort_order` puis `name_fr` (non paginé) |
| POST | `/shop/categories/` | `{"name_fr": "Voiles", "name_ar": "خمارات", "sort_order": 1}` | **201** `Category` |
| PATCH | `/shop/categories/{id}/` | champs à modifier | **200** `Category` |
| DELETE | `/shop/categories/{id}/` | — | **204** (les produits deviennent sans catégorie, RG-32) |

Règles : au moins un nom parmi `name_fr`/`name_ar`, 60 caractères max, unicité insensible à la casse dans la boutique, 100 catégories maximum.

---

### Objet `Product` (espace boutique)

```json
{
  "id": 120,
  "name_fr": "Melhfa bleue royale",
  "name_ar": "ملحفة زرقاء",
  "description_fr": "Voile léger 100 % coton.",
  "description_ar": "",
  "price": 2500,
  "category": {"id": 4, "name_fr": "Melhfas", "name_ar": "ملاحف"},
  "image_url": "http://localhost:8000/media/products/2026/11/9f3c.webp",
  "thumbnail_url": "http://localhost:8000/media/products/2026/11/9f3c_thumb.webp",
  "status": "PUBLISHED",
  "is_available": true,
  "source": "MANUAL",
  "import_job_id": null,
  "published_at": "2026-11-21T08:00:00+00:00",
  "created_at": "2026-11-21T08:00:00+00:00",
  "updated_at": "2026-11-21T08:00:00+00:00"
}
```

### `GET /shop/products/` 🔒 SHOP — *paginé*

| Paramètre | Type | Description |
|---|---|---|
| `search` | texte | Recherche dans les noms et descriptions (FR et AR), insensible à la casse et aux accents |
| `category` | entier | Identifiant de catégorie |
| `uncategorized` | `true` | Produits sans catégorie |
| `status` | `DRAFT` / `PUBLISHED` | |
| `is_available` | `true` / `false` | |
| `source` | `MANUAL` / `IMPORT` | |
| `import_job` | entier | Produits issus d'un import (liste 1 : `?status=DRAFT&import_job=12`) |
| `min_price`, `max_price` | entier ≥ 0 | Bornes incluses ; `min_price > max_price` → `400` |
| `ordering` | `created_at`, `-created_at` (défaut), `price`, `-price`, `name_fr`, `-name_fr` | |

**200** : page de `Product`.

### `POST /shop/products/` 🔒 SHOP 📎

| Champ | Obligatoire | Règles |
|---|---|---|
| `name_fr` / `name_ar` | au moins un | 150 caractères max |
| `description_fr`, `description_ar` | non | 2 000 caractères max |
| `price` | oui | Entier de 1 à 100 000 000 |
| `category_id` | non | Catégorie **de la boutique** |
| `image` | oui | JPEG/PNG/WebP, 5 Mo max |
| `status` | non | `PUBLISHED` (défaut) ou `DRAFT` |
| `is_available` | non | Défaut `true` |

**201** : `Product`. **Erreurs** : `400 VALIDATION_ERROR`, `409 LIMIT_REACHED` (5 000 produits), `413 FILE_TOO_LARGE`.

### `GET /shop/products/{id}/` · `PATCH /shop/products/{id}/` 📎 · `DELETE /shop/products/{id}/`
- `PATCH` : mêmes champs que `POST`, tous facultatifs. Passer `status` de `DRAFT` à `PUBLISHED` remplit `published_at`. JSON accepté si aucune image n'est envoyée.
- `DELETE` : **204**. Le produit disparaît du panier des clients lors du prochain devis (`cart/quote`).
- Un produit d'une autre boutique renvoie `404 NOT_FOUND`.

### `POST /shop/products/bulk-publish/` 🔒 SHOP
« Publier la sélection » (liste 1, RG-35).

```json
{"ids": [120, 121, 122]}
```

`ids` : 1 à 1 000 identifiants.

**200**
```json
{
  "published_ids": [120, 121],
  "skipped": [{"id": 122, "reason": "ALREADY_PUBLISHED"}]
}
```

Raisons possibles : `NOT_FOUND` (inexistant ou d'une autre boutique), `ALREADY_PUBLISHED`.

### `POST /shop/products/bulk-update/` 🔒 SHOP
Actions groupées. Au moins un champ parmi `category_id` (entier ou `null` pour « sans catégorie ») et `is_available`.

```json
{"ids": [120, 121], "category_id": 4, "is_available": true}
```

**200** `{"updated_count": 2}`

### `POST /shop/products/bulk-delete/` 🔒 SHOP

```json
{"ids": [120, 121]}
```

**200** `{"deleted_count": 2}`

---

## 7. Espace boutique : import Excel + ZIP

Tous ces endpoints exigent l'état `ACTIVE`.

### Déroulement

```
1. GET  /shop/products/import/template/   → la boutique télécharge le modèle Excel
2. La boutique remplit l'Excel et met ses photos dans un ZIP
3. POST /shop/products/import/            → contrôle immédiat de la structure, puis 202 + job
4. GET  /shop/products/import/jobs/{id}/  → le front interroge toutes les 3 s jusqu'à COMPLETED ou FAILED
   (une notification IMPORT_COMPLETED / IMPORT_FAILED est aussi créée)
5. Liste 1 (réussis, brouillons) : GET /shop/products/?status=DRAFT&import_job={id}
   → POST /shop/products/bulk-publish/     « Publier la sélection »
6. Liste 2 (erreurs) : GET /shop/products/import/errors/?job={id}
   → PATCH /shop/products/import/errors/{id}/   corriger une ligne
   → POST  /shop/products/import/errors/publish/ « Publier cette collection »
```

### `GET /shop/products/import/template/` 🔒 SHOP
Renvoie le fichier `modele-import-produits.xlsx` (`Content-Disposition: attachment`).

Feuille **`Produits`** (ligne 1 = en-têtes, données à partir de la ligne 2) :

| Colonne | En-tête | Obligatoire | Contenu |
|---|---|---|---|
| A | `nom_fr` | au moins un des deux | Nom en français (150 car. max) |
| B | `nom_ar` | au moins un des deux | Nom en arabe (150 car. max) |
| C | `description_fr` | non | 2 000 car. max |
| D | `description_ar` | non | 2 000 car. max |
| E | `prix` | **oui** | Entier en MRU (ex. `2500`) |
| F | `categorie` | non | Nom de la catégorie (créée si elle n'existe pas, RG-36) |
| G | `image` | **oui** | Nom exact du fichier dans le ZIP, ex. `melhfa1.jpg` |

Feuille **`Instructions`** : explications en français et en arabe, avec un exemple.

### `POST /shop/products/import/` 🔒 SHOP 📎

| Champ | Règles |
|---|---|
| `excel_file` | `.xlsx`, 5 Mo max |
| `zip_file` | `.zip`, 200 Mo max, 500 Mo max décompressé, 2 000 fichiers max |

**Contrôles immédiats** (réponse `400 VALIDATION_ERROR` avec `details` par champ si l'un échoue) : fichiers lisibles, feuille `Produits` présente, en-têtes `nom_fr`…`image` présents, entre 1 et 1 000 lignes de données, ZIP valide et non dangereux (voir [07-securite.md](07-securite.md)).

Le traitement des lignes (lecture, recherche de chaque photo dans le ZIP, conversion des images, création des brouillons) se fait ensuite **en arrière-plan** (Celery).

**202**
```json
{
  "id": 12,
  "status": "PENDING",
  "total_rows": 0,
  "success_count": 0,
  "error_count": 0,
  "failure_reason": "",
  "created_at": "2026-11-21T10:00:00+00:00",
  "started_at": null,
  "finished_at": null
}
```

**Erreurs** : `400 VALIDATION_ERROR`, `409 IMPORT_ALREADY_RUNNING`, `409 LIMIT_REACHED` (le nombre de lignes dépasse le quota restant de produits), `413 FILE_TOO_LARGE`.

### Règles de traitement d'une ligne

- Les cellules vides en fin de fichier sont ignorées ; une ligne entièrement vide est ignorée.
- Le prix accepte `2500`, `2 500`, `2500.0` ; il refuse `2500.5`, `abc`, `0` et les valeurs négatives.
- La recherche de la photo dans le ZIP ignore la casse et les dossiers (`Photos/MELHFA1.JPG` correspond à `melhfa1.jpg`). Si deux fichiers du ZIP portent le même nom, la ligne est en erreur `IMAGE_AMBIGUOUS`.
- Une ligne valide → produit `DRAFT`, `source = IMPORT`, `import_job_id` renseigné.
- Une ligne invalide → `catalog_import_error_row` avec **toutes** ses erreurs (pas seulement la première). Si la photo a été trouvée et est valide, elle est conservée dans la ligne d'erreur pour éviter de la renvoyer.

Codes d'erreur de ligne :

| `code` | `field` | Signification |
|---|---|---|
| `NAME_REQUIRED` | `name` | `nom_fr` et `nom_ar` vides |
| `NAME_TOO_LONG` | `name_fr` / `name_ar` | Plus de 150 caractères |
| `DESCRIPTION_TOO_LONG` | `description_fr` / `description_ar` | Plus de 2 000 caractères |
| `PRICE_REQUIRED` | `price` | Prix vide |
| `INVALID_PRICE` | `price` | Prix non entier ou non numérique |
| `PRICE_OUT_OF_RANGE` | `price` | Hors de 1 à 100 000 000 |
| `CATEGORY_TOO_LONG` | `category` | Plus de 60 caractères |
| `IMAGE_REQUIRED` | `image` | Colonne `image` vide et aucune image envoyée |
| `IMAGE_NOT_FOUND_IN_ZIP` | `image` | Fichier absent du ZIP |
| `IMAGE_AMBIGUOUS` | `image` | Plusieurs fichiers du ZIP portent ce nom |
| `IMAGE_INVALID` | `image` | Fichier illisible ou format non pris en charge |
| `IMAGE_TOO_LARGE` | `image` | Plus de 5 Mo |
| `PRODUCT_LIMIT_REACHED` | `product` | Limite de 5 000 produits atteinte |

### Objet `ImportJob`
Voir la réponse `202` ci-dessus. `status` : `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`.

### `GET /shop/products/import/jobs/` 🔒 SHOP — *paginé*
Imports de la boutique, du plus récent au plus ancien. **200** : page de `ImportJob`.

### `GET /shop/products/import/jobs/{id}/` 🔒 SHOP
**200** : `ImportJob`.

### Objet `ImportErrorRow`

```json
{
  "id": 301,
  "job_id": 12,
  "row_number": 42,
  "name_fr": "Voile noir",
  "name_ar": "",
  "description_fr": "",
  "description_ar": "",
  "price_raw": "huit cents",
  "category_raw": "Voiles",
  "image_filename": "voile9.jpg",
  "image_url": null,
  "thumbnail_url": null,
  "errors": [
    {"field": "price", "code": "INVALID_PRICE", "message": "Le prix doit être un nombre entier."},
    {"field": "image", "code": "IMAGE_NOT_FOUND_IN_ZIP", "message": "Le fichier « voile9.jpg » est absent du ZIP."}
  ],
  "created_at": "2026-11-21T10:01:00+00:00",
  "updated_at": "2026-11-21T10:01:00+00:00"
}
```

Les `message` sont traduits selon `Accept-Language` au moment de la lecture.

### `GET /shop/products/import/errors/` 🔒 SHOP — *paginé*
Liste 2. Paramètre facultatif `job` (identifiant d'import). Tri par `job_id` puis `row_number`.

### `PATCH /shop/products/import/errors/{id}/` 🔒 SHOP 📎
Corrige une ligne. Champs facultatifs : `name_fr`, `name_ar`, `description_fr`, `description_ar`, `price_raw`, `category_raw`, `image` (fichier). Après la modification, la ligne est **revalidée** et `errors` est recalculé (vide si la ligne est désormais valide).

**200** : `ImportErrorRow`.

### `DELETE /shop/products/import/errors/{id}/` 🔒 SHOP
Abandonne la ligne. **204**.

### `POST /shop/products/import/errors/publish/` 🔒 SHOP
« Publier cette collection » (RG-35). Revalide les lignes, crée un produit **publié** pour chaque ligne valide et supprime ces lignes de la liste 2.

```json
{"ids": [301, 302, 303]}
```

`ids` est facultatif : s'il est absent, **toutes** les lignes de la liste 2 de la boutique sont traitées (dans la limite de 1 000 par appel).

**200**
```json
{
  "published_count": 2,
  "product_ids": [540, 541],
  "remaining": [
    {"id": 303, "errors": [{"field": "image", "code": "IMAGE_REQUIRED", "message": "Une image est obligatoire."}]}
  ]
}
```

---

## 8. Espace boutique : commandes et tableau de bord

Tous ces endpoints exigent l'état `ACTIVE`.

### Objet `OrderSummary`

```json
{
  "id": 42,
  "reference": "CMD-2026-000042",
  "customer_name": "Mohamed Salem",
  "customer_phone": "36998877",
  "total_amount": 6000,
  "deposit_required": 1800,
  "amount_paid": 1800,
  "remaining_amount": 4200,
  "status": "SUBMITTED",
  "items_count": 2,
  "created_at": "2026-11-21T12:00:00+00:00"
}
```

### Objet `OrderDetail` (= `OrderSummary` +)

```json
{
  "delivery_address": "Ksar, près de la mosquée",
  "bank_name": "Bankily",
  "deposit_percent": 30,
  "payment_proof_url": "http://localhost:8000/api/v1/shop/orders/42/payment-proof/",
  "customer_whatsapp_url": "https://wa.me/22236998877?text=Bonjour%20Mohamed%20Salem%2C%20concernant%20votre%20commande%20CMD-2026-000042",
  "rejection_reason": "",
  "confirmed_at": null,
  "delivered_at": null,
  "rejected_at": null,
  "updated_at": "2026-11-21T12:00:00+00:00",
  "items": [
    {
      "product_id": 120,
      "product_name_fr": "Melhfa bleue royale",
      "product_name_ar": "ملحفة زرقاء",
      "product_thumbnail_url": "http://localhost:8000/media/products/2026/11/9f3c_thumb.webp",
      "unit_price": 2500,
      "quantity": 2,
      "line_total": 5000
    }
  ]
}
```

### `GET /shop/orders/` 🔒 SHOP — *paginé*

| Paramètre | Description |
|---|---|
| `status` | Un ou plusieurs statuts séparés par des virgules, ex. `SUBMITTED,CONFIRMED` |
| `search` | Référence, nom ou téléphone du client |
| `created_from`, `created_to` | Dates `AAAA-MM-JJ` (bornes incluses) |
| `ordering` | `-created_at` (défaut), `created_at`, `total_amount`, `-total_amount` |

**200** : page de `OrderSummary`.

### `GET /shop/orders/{id}/` 🔒 SHOP
**200** : `OrderDetail`.

### `GET /shop/orders/{id}/payment-proof/` 🔒 SHOP
Renvoie l'image de la capture (`Cache-Control: private, no-store`).

### Changements de statut (RG-47)

| Endpoint | Corps | Transition autorisée | Effet |
|---|---|---|---|
| `POST /shop/orders/{id}/confirm/` | — | `SUBMITTED → CONFIRMED` | `confirmed_at` |
| `POST /shop/orders/{id}/deliver/` | — | `CONFIRMED → DELIVERED` | `delivered_at` ; la commande entre dans le revenu du mois (RG-50) |
| `POST /shop/orders/{id}/reject/` | `{"reason": "Capture invalide : aucun virement reçu."}` (5 à 500 caractères) | `SUBMITTED → REJECTED`, `CONFIRMED → REJECTED` | `rejected_at`, `rejection_reason` ; visible par le client dans le suivi (RG-49) |

**200** : `OrderDetail`. **Erreurs** : `409 INVALID_STATE_TRANSITION` (`details.current_status`), `400 VALIDATION_ERROR`.

---

### `GET /shop/dashboard/` 🔒 SHOP
Onglet « Tableau de bord ».

| Paramètre | Description |
|---|---|
| `month` | Facultatif, `AAAA-MM` ; défaut : mois en cours (fuseau `Africa/Nouakchott`) |

**200**
```json
{
  "revenue": {
    "month": "2026-11",
    "amount": 125000,
    "delivered_orders": 14,
    "previous_month_amount": 98000,
    "daily": [
      {"date": "2026-11-01", "amount": 0},
      {"date": "2026-11-02", "amount": 6000}
    ]
  },
  "subscription": {
    "expires_at": "2026-12-20T15:40:00+00:00",
    "days_left": 29,
    "level": "OK",
    "whatsapp_url": "https://wa.me/22222334455?text=..."
  },
  "orders": {"submitted": 3, "confirmed": 2},
  "products": {"published": 280, "draft": 40, "import_errors": 5}
}
```

- `revenue.amount` : somme des `total_amount` des commandes `DELIVERED` dont `delivered_at` est dans le mois (RG-50).
- `revenue.daily` : un élément par jour du mois (jusqu'à aujourd'hui pour le mois en cours).
- `subscription.level` : `OK` (plus de 7 jours), `WARNING` (4 à 7 jours), `DANGER` (3 jours ou moins). Le front affiche le bandeau d'alerte si `level ≠ OK`.

---

## 9. Notifications

### Objet `Notification`

```json
{
  "id": 88,
  "type": "SHOP_REJECTED",
  "title": "Demande refusée",
  "message": "Votre demande a été refusée : votre carte d'identité n'est pas lisible.",
  "data": {"reason": "votre carte d'identité n'est pas lisible."},
  "is_read": false,
  "read_at": null,
  "created_at": "2026-11-20T16:00:00+00:00"
}
```

`title` et `message` sont produits dans la langue de la requête à partir de `type` et `data` (types : voir [04-schema-base-de-donnees.md §7](04-schema-base-de-donnees.md)).

| Méthode | Chemin | Description | Réponse |
|---|---|---|---|
| GET | `/notifications/` | *Paginé*, du plus récent au plus ancien. Filtre `is_read=true/false` | Page de `Notification` |
| GET | `/notifications/unread-count/` | Pour le badge de la cloche (le front interroge toutes les 30 s) | `{"count": 3}` |
| POST | `/notifications/{id}/read/` | Marque comme lue | **200** `Notification` |
| POST | `/notifications/read-all/` | Marque tout comme lu | **200** `{"updated_count": 3}` |

Un utilisateur ne voit que **ses** notifications (`404 NOT_FOUND` sinon). Une valeur de `is_read` autre que `true` ou `false` renvoie `400 VALIDATION_ERROR`. Marquer comme lue une notification déjà lue conserve son `read_at` d'origine ; `read-all` ne compte que les notifications qui étaient non lues.

---

## 10. Site public

Tous les endpoints de cette section sont 🌐. Le paramètre `lang` (`fr` ou `ar`) choisit la langue des champs traduits et de la recherche ; s'il est absent, la langue de `Accept-Language` est utilisée.

**Visibilité (RG-40, RG-41)** : une boutique non visible renvoie `404 NOT_FOUND` sur toutes ses routes ; un produit brouillon ou indisponible renvoie `404 NOT_FOUND`.

**Champs traduits** : `description` vaut `description_fr` ou `description_ar` selon la langue. Pour les produits, `name` et `description` utilisent la langue demandée et, si le champ est vide, **l'autre langue** (repli).

### `GET /public/platform-info/`
Utilisé par la page « compte expiré » et l'en-tête du site.

**200**
```json
{
  "admin_whatsapp": "22334455",
  "admin_whatsapp_url": "https://wa.me/22222334455",
  "admin_contact_email": "contact@plateforme.mr",
  "deposit_percent": 30
}
```

Tant que l'administrateur n'a pas renseigné son numéro (ou son e-mail), `admin_whatsapp` et `admin_whatsapp_url` (ou `admin_contact_email`) valent `""`.

### `GET /public/shops/` — *paginé*
Page d'accueil : cartes des boutiques.

| Paramètre | Description |
|---|---|
| `search` | Texte recherché (RG-42), 100 caractères max ; ignoré s'il fait moins de 2 caractères après normalisation |
| `lang` | `fr` / `ar` |
| `page`, `page_size` | Défaut `page_size = 24` |

Tri : par **pertinence** si `search` est fourni, sinon par date de validation (plus récentes d'abord).

**200** (élément de `results`)
```json
{
  "id": 3,
  "name": "Aïcha Mode",
  "slug": "aicha-mode",
  "description": "Melhfas, voiles et parfums de qualité.",
  "logo_url": "http://localhost:8000/media/shops/logos/2026/11/a1b2.webp",
  "primary_color": "#7C2D5B",
  "accent_color": "#D4A52A",
  "products_count": 280
}
```

Fonctionnement de la recherche : voir [05-aspects-transversaux.md §9](05-aspects-transversaux.md).

### `GET /public/shops/suggest/`
Autocomplétion pendant la frappe. Paramètres `q` (2 à 100 caractères) et `lang`. Maximum 8 résultats, triés par pertinence.

**200**
```json
[{"name": "Aïcha Mode", "slug": "aicha-mode", "logo_url": "..."}]
```

### `GET /public/shops/{slug}/`

**200**
```json
{
  "id": 3,
  "name": "Aïcha Mode",
  "slug": "aicha-mode",
  "description": "Melhfas, voiles et parfums de qualité.",
  "logo_url": "...",
  "address": "Tevragh Zeina, Nouakchott",
  "phone": "36123456",
  "whatsapp": "36123456",
  "whatsapp_url": "https://wa.me/22236123456",
  "theme": {"code": "elegant", "layout": "MAGAZINE"},
  "primary_color": "#7C2D5B",
  "accent_color": "#D4A52A",
  "categories": [
    {"id": 4, "name": "Melhfas", "products_count": 250},
    {"id": 5, "name": "Voiles", "products_count": 30}
  ],
  "has_multiple_categories": true,
  "has_uncategorized_products": false,
  "price_range": {"min": 500, "max": 45000},
  "products_count": 280
}
```

- `categories` : uniquement les catégories qui contiennent au moins un produit visible.
- `has_multiple_categories` : `true` si au moins deux catégories visibles. Sinon, le front n'affiche **pas** de filtre de catégories (une seule liste de produits).
- `price_range` : bornes réelles des produits visibles (pré-remplissage du filtre de prix) ; `null` si aucun produit.

### `GET /public/shops/{slug}/products/` — *paginé*

| Paramètre | Description |
|---|---|
| `category` | Identifiant de catégorie (de cette boutique) |
| `min_price`, `max_price` | Entiers ≥ 0, bornes **incluses** ; `min_price > max_price` → `400 VALIDATION_ERROR` |
| `search` | Recherche dans le nom et la description, dans la langue `lang` |
| `lang` | `fr` / `ar` |
| `ordering` | `-published_at` (défaut), `price`, `-price` ; avec `search`, défaut = pertinence |
| `page`, `page_size` | Défaut `page_size = 24` |

Les filtres se **combinent** (ET logique). Un paramètre invalide (ex. `min_price=abc`, catégorie inexistante) renvoie `400 VALIDATION_ERROR`.

**200** (élément de `results`)
```json
{
  "id": 120,
  "name": "Melhfa bleue royale",
  "price": 2500,
  "image_url": "...",
  "thumbnail_url": "...",
  "category": {"id": 4, "name": "Melhfas"}
}
```

### `GET /public/shops/{slug}/products/{id}/`
**200** : comme ci-dessus, plus `description`.

### `POST /public/shops/{slug}/cart/quote/`
Le front appelle cet endpoint à l'ouverture du panier et avant le paiement. Le serveur recalcule tout (RG-43, RG-44).

```json
{"items": [{"product_id": 120, "quantity": 2}, {"product_id": 133, "quantity": 1}]}
```

Règles : 1 à 50 lignes, `quantity` de 1 à 99, un même `product_id` ne peut apparaître qu'une fois.

**200**
```json
{
  "items": [
    {"product_id": 120, "name": "Melhfa bleue royale", "thumbnail_url": "...", "unit_price": 2500, "quantity": 2, "line_total": 5000},
    {"product_id": 133, "name": "Voile noir", "thumbnail_url": "...", "unit_price": 1000, "quantity": 1, "line_total": 1000}
  ],
  "unavailable_product_ids": [],
  "total_amount": 6000,
  "deposit_percent": 30,
  "deposit_amount": 1800,
  "banks": [
    {"id": 5, "bank_name": "Bankily", "payment_code": "22334455"},
    {"id": 6, "bank_name": "Sedad", "payment_code": "44556677"}
  ],
  "shop": {"name": "Aïcha Mode", "phone": "36123456", "whatsapp": "36123456"}
}
```

- `unavailable_product_ids` : produits du panier supprimés, dépubliés, indisponibles ou d'une autre boutique. Ils sont exclus du total ; le front les retire du panier et prévient le client.
- `deposit_amount = ceil(total_amount × deposit_percent / 100)`. Le front affiche directement ce montant (le client n'a rien à calculer).

**Erreurs** : `400 VALIDATION_ERROR`, `404 NOT_FOUND` (boutique non visible).

### `POST /public/shops/{slug}/orders/` 📎
Soumission du paiement (RG-45). Limites : 5 requêtes/heure par IP et 10 commandes/jour par numéro de téléphone.

| Champ | Obligatoire | Règles |
|---|---|---|
| `items` | oui | Chaîne JSON, même format que `cart/quote` |
| `customer_name` | oui | 2 à 100 caractères |
| `customer_phone` | oui | Téléphone mauritanien |
| `amount_paid` | oui | Entier de 1 à `total_amount` |
| `payment_proof` | oui | Image JPEG/PNG/WebP, 5 Mo max |
| `bank_account_id` | non | Banque **de cette boutique** |
| `delivery_address` | non | 255 caractères max |

Traitement, dans une transaction : recalcul des prix, vérification de la disponibilité de chaque produit, création de la commande et de ses lignes (copies nom/prix/miniature), génération de la référence, notification `ORDER_NEW` à la boutique, e-mail à la boutique.

**201**
```json
{
  "reference": "CMD-2026-000042",
  "status": "SUBMITTED",
  "total_amount": 6000,
  "deposit_required": 1800,
  "amount_paid": 1800,
  "remaining_amount": 4200,
  "created_at": "2026-11-21T12:00:00+00:00",
  "shop": {
    "name": "Aïcha Mode",
    "phone": "36123456",
    "whatsapp": "36123456",
    "whatsapp_url": "https://wa.me/22236123456?text=Bonjour%2C%20j%27ai%20pass%C3%A9%20la%20commande%20CMD-2026-000042"
  }
}
```

Le front affiche : « Votre paiement a été envoyé avec succès. La boutique va le vérifier et vous contacter », la référence, le contact de la boutique, puis **vide le panier de cette boutique** et ajoute la référence à la liste des commandes suivies.

**Erreurs** : `400 VALIDATION_ERROR`, `404 NOT_FOUND`, `409 CART_CHANGED` (le front rappelle `cart/quote` et affiche le nouveau total), `413 FILE_TOO_LARGE`, `429 THROTTLED`.

### `POST /public/orders/track/`
Suivi des commandes par le client sans compte (RG-49). Le front l'appelle à l'ouverture du site puis toutes les 60 s, avec les références gardées dans le navigateur. Si un statut a changé (ex. `REJECTED`), il affiche une notification au client.

```json
{"customer_phone": "36998877", "references": ["CMD-2026-000042", "CMD-2026-000051"]}
```

Règles : 1 à 20 références. Limite : 30 requêtes/minute par IP.

**200**
```json
{
  "results": [
    {
      "reference": "CMD-2026-000042",
      "status": "REJECTED",
      "rejection_reason": "Capture invalide : aucun virement reçu.",
      "total_amount": 6000,
      "amount_paid": 1800,
      "created_at": "2026-11-21T12:00:00+00:00",
      "updated_at": "2026-11-21T13:10:00+00:00",
      "shop": {"name": "Aïcha Mode", "slug": "aicha-mode", "phone": "36123456", "whatsapp_url": "https://wa.me/22236123456"}
    }
  ]
}
```

Une référence inconnue ou dont le téléphone ne correspond pas est simplement **absente** des résultats (aucune information divulguée).

---

## 11. Administration

Tous les endpoints de cette section sont 🔒 ADMIN. Toute action qui modifie une boutique crée une entrée d'audit.

### `GET /admin/dashboard/`

**200**
```json
{
  "shops": {"onboarding": 4, "pending": 3, "active": 52, "rejected": 2, "expired": 7, "blocked": 1, "total": 69},
  "expiring_soon": [
    {"id": 3, "name": "Aïcha Mode", "logo_url": "...", "phone": "36123456", "whatsapp_url": "https://wa.me/22236123456", "expires_at": "2026-11-25T15:40:00+00:00", "days_left": 4}
  ],
  "recharges": {"month": "2026-11", "count": 12, "amount_received": 84000},
  "latest_submissions": [
    {"id": 70, "name": "TechShop", "logo_url": "...", "submitted_at": "2026-11-21T09:00:00+00:00"}
  ]
}
```

- `shops` : nombre de boutiques par état calculé (`state`), plus le total.
- `expiring_soon` : boutiques `ACTIVE` qui expirent dans les 7 jours, de la plus urgente à la moins urgente (20 maximum). `whatsapp_url` pointe vers le numéro WhatsApp de la boutique.
- `recharges` : recharges du mois en cours (fuseau `Africa/Nouakchott`) ; `amount_received` additionne les montants renseignés (`0` si aucun).
- `latest_submissions` : 5 dernières boutiques `PENDING`, de la plus récente à la plus ancienne.

### Objet `AdminShopSummary`

```json
{
  "id": 3,
  "name": "Aïcha Mode",
  "slug": "aicha-mode",
  "logo_url": "...",
  "owner_full_name": "Aïcha Mint Ahmed",
  "email": "aicha@example.com",
  "phone": "36123456",
  "state": "ACTIVE",
  "is_blocked": false,
  "submitted_at": "...",
  "approved_at": "...",
  "expires_at": "...",
  "days_left": 29,
  "created_at": "..."
}
```

### `GET /admin/shops/` — *paginé*

| Paramètre | Description |
|---|---|
| `state` | Un ou plusieurs états séparés par des virgules : `ONBOARDING`, `PENDING`, `ACTIVE`, `REJECTED`, `EXPIRED`, `BLOCKED`. Ex. « En attente » = `PENDING`, « Validées » = `ACTIVE,EXPIRED` |
| `search` | Nom de la boutique, e-mail, téléphone, nom du propriétaire (insensible à la casse et aux accents) |
| `ordering` | `-submitted_at` (défaut), `submitted_at`, `expires_at`, `-expires_at`, `name`, `-created_at` |

**200** : page de `AdminShopSummary`. Les boutiques sans date de soumission ou d'expiration sont toujours placées en fin de liste. **Erreurs** : `400 VALIDATION_ERROR` (état inconnu dans `state`, valeur de `ordering` hors liste).

`days_left` : comme dans `ShopProfile` (arrondi supérieur, `0` si expirée, `null` sans date d'expiration).

### `GET /admin/shops/{id}/`

**200** : `AdminShopSummary` +
```json
{
  "description_fr": "...",
  "description_ar": "...",
  "address": "...",
  "whatsapp": "36123456",
  "whatsapp_url": "https://wa.me/22236123456",
  "theme": { "...objet Theme..." },
  "primary_color": "#7C2D5B",
  "accent_color": "#D4A52A",
  "onboarding_step": "COMPLETED",
  "status": "APPROVED",
  "rejection_reason": "",
  "rejected_at": null,
  "block_reason": "",
  "blocked_at": null,
  "approved_by": {"id": 1, "email": "admin@plateforme.mr"},
  "id_card_front_url": "http://localhost:8000/api/v1/admin/shops/3/id-card/front/",
  "id_card_back_url": "http://localhost:8000/api/v1/admin/shops/3/id-card/back/",
  "banks": [{"id": 5, "bank_name": "Bankily", "payment_code": "22334455"}],
  "stats": {"products_published": 280, "products_draft": 40, "orders_total": 61, "orders_delivered": 48, "revenue_delivered_total": 410000},
  "recent_audit": [
    {"action": "SHOP_APPROVED", "actor_email": "admin@plateforme.mr", "metadata": {}, "created_at": "..."}
  ]
}
```

`recent_audit` : les 20 dernières entrées d'audit qui concernent cette boutique (y compris les retraits de ses produits, `PRODUCT_REMOVED_BY_ADMIN`), de la plus récente à la plus ancienne. `stats.revenue_delivered_total` additionne le `total_amount` des commandes `DELIVERED`. Une boutique inexistante renvoie `404 NOT_FOUND`.

### `GET /admin/shops/{id}/id-card/{side}/`
`side` = `front` ou `back`. Renvoie l'image (`Cache-Control: private, no-store`). Une autre valeur de `side`, une boutique inexistante ou un fichier absent du stockage renvoient `404 NOT_FOUND`.

### Actions sur une boutique

| Endpoint | Corps | Condition | Effets | Erreur si condition fausse |
|---|---|---|---|---|
| `POST /admin/shops/{id}/approve/` | — | `state = PENDING` | `status = APPROVED`, `approved_at`, `approved_by`, `expires_at = maintenant + trial_months`, `rejection_reason = ''` ; notification `SHOP_APPROVED` + e-mail ; audit (RG-10, RG-11) | `409 INVALID_STATE_TRANSITION` |
| `POST /admin/shops/{id}/reject/` | `{"reason": "..."}` (10 à 500 car.) | `state = PENDING` | `status = REJECTED`, `rejected_at`, `rejection_reason` ; notification `SHOP_REJECTED` + e-mail ; audit (RG-12) | `409 INVALID_STATE_TRANSITION` |
| `POST /admin/shops/{id}/block/` | `{"reason": "..."}` (5 à 500 car.) | `is_blocked = false` | `is_blocked = true`, `blocked_at`, `block_reason` ; sessions de la boutique invalidées ; e-mail ; audit (RG-14) | `409 INVALID_STATE_TRANSITION` |
| `POST /admin/shops/{id}/unblock/` | — | `is_blocked = true` | `is_blocked = false`, `block_reason = ''`, `blocked_at = null` ; notification `SHOP_UNBLOCKED` + e-mail ; audit (`metadata.previous_block_reason`) | `409 INVALID_STATE_TRANSITION` |

**200** : objet détaillé de la boutique (comme `GET /admin/shops/{id}/`).

- `409 INVALID_STATE_TRANSITION` : `details = {"current_state": "ACTIVE"}` (état calculé au moment de la demande). Rien n'est modifié.
- `400 VALIDATION_ERROR` : `reason` absent ou de longueur invalide (`details.reason`).
- Le blocage est possible depuis tout état (`ONBOARDING` compris). Le déblocage ne modifie ni le statut ni `expires_at` : l'état est recalculé (une boutique dont la date est dépassée pendant le blocage redevient `EXPIRED`). Les jetons révoqués au blocage restent invalides : la boutique se reconnecte.
- Les e-mails envoyés à la boutique après une action de l'admin sont rédigés en français puis en arabe (même message).

### `GET /admin/shops/{id}/recharge-preview/`
Calcule la nouvelle date **sans rien enregistrer** (affichage avant confirmation). Un seul des deux paramètres :

| Paramètre | Description |
|---|---|
| `duration_months` | Entier de 1 à 120 |
| `target_date` | Date `AAAA-MM-JJ` ; la nouvelle expiration est fixée à 23:59:59 (heure de Nouakchott) ce jour-là |

**200**
```json
{
  "current_expires_at": "2026-12-20T15:40:00+00:00",
  "base_date": "2026-12-20T15:40:00+00:00",
  "new_expires_at": "2027-12-20T15:40:00+00:00",
  "is_currently_expired": false
}
```

`base_date = max(current_expires_at, maintenant)` (RG-22). Ajout de mois calendaire : le 31 janvier + 1 mois = le 28 (ou 29) février. `target_date` doit être un jour **strictement postérieur** au jour de `base_date` (heure de Nouakchott).

**Erreurs** : `400 VALIDATION_ERROR` (aucun ou deux paramètres : `details.non_field_errors` ; `duration_months` hors de 1 à 120 ; date mal formée ; `target_date` non postérieure à `base_date` : `details.target_date`), `404 NOT_FOUND`, `409 INVALID_STATE_TRANSITION` (statut différent de `APPROVED`, `details = {"current_state": "PENDING"}`).

### `POST /admin/shops/{id}/recharge/`
« Charger le compte » (RG-20 à RG-24).

```json
{"duration_months": 12, "amount_received": 12000, "note": "Paiement Bankily du 18/12"}
```
ou
```json
{"target_date": "2031-11-20", "amount_received": 50000}
```

Exactement un parmi `duration_months` et `target_date`, avec les mêmes règles et les mêmes erreurs que l'aperçu. `amount_received` (entier ≥ 0, ou `null`) et `note` (255 car.) sont facultatifs. Une boutique bloquée au statut `APPROVED` peut être rechargée : elle reste bloquée.

Effets (transaction, verrou `SELECT … FOR UPDATE` sur la boutique) : `expires_at` mis à jour, `last_expiry_reminder_days = NULL` (les rappels reprennent), ligne `administration_recharge`, notification `SHOP_RECHARGED` + e-mail, audit `SHOP_RECHARGED` (`metadata` : `recharge_id`, anciennes et nouvelles dates, `duration_months`, `target_date`, `amount_received`).

**201**
```json
{
  "recharge": {
    "id": 9,
    "duration_months": 12,
    "previous_expires_at": "2026-12-20T15:40:00+00:00",
    "new_expires_at": "2027-12-20T15:40:00+00:00",
    "amount_received": 12000,
    "note": "Paiement Bankily du 18/12",
    "performed_by": {"id": 1, "email": "admin@plateforme.mr"},
    "created_at": "2026-12-18T11:00:00+00:00"
  },
  "shop": { "...AdminShopSummary..." }
}
```

### `GET /admin/shops/{id}/recharges/` — *paginé*
Historique des recharges de la boutique (objet `recharge` ci-dessus), du plus récent au plus ancien.

### `GET /admin/recharges/` — *paginé*
Toutes les recharges, de la plus récente à la plus ancienne. Filtres : `shop` (id), `date_from`, `date_to` (`AAAA-MM-JJ`, bornes incluses, jours de Nouakchott). Chaque élément contient aussi `shop: {id, name}`. Valeur invalide ou `date_from > date_to` → `400 VALIDATION_ERROR`.

### `GET /admin/shops/{id}/products/` — *paginé*
Produits d'une boutique pour la modération (brouillons compris). Mêmes filtres que `GET /shop/products/`, validés de la même façon (`400 VALIDATION_ERROR`). Éléments au format `Product`.

### `POST /admin/shops/{id}/products/{product_id}/remove/`
Supprime un produit interdit.

```json
{"reason": "Produit contrefait."}
```

`reason` : 5 à 500 caractères. Effets : suppression du produit (les commandes gardent leurs copies, RG-46) et de ses fichiers image, notification `PRODUCT_REMOVED` à la boutique, audit `PRODUCT_REMOVED_BY_ADMIN` (avec `shop_id`, le nom, le prix et le motif dans `metadata`). **204**. Un produit d'une autre boutique renvoie `404 NOT_FOUND`.

### `GET /admin/settings/` · `PATCH /admin/settings/`

```json
{
  "admin_whatsapp": "22334455",
  "admin_contact_email": "contact@plateforme.mr",
  "trial_months": 1,
  "deposit_percent": 30,
  "updated_at": "2026-11-20T08:00:00+00:00",
  "updated_by": {"id": 1, "email": "admin@plateforme.mr"}
}
```

`PATCH` : `admin_whatsapp` (téléphone mauritanien), `admin_contact_email` (enregistré en minuscules), `trial_months` (0 à 12), `deposit_percent` (1 à 100). Tous les champs sont facultatifs. Audit `SETTINGS_UPDATED` avec les anciennes et nouvelles valeurs des seuls champs modifiés (`metadata.changes`) ; une requête qui ne change rien n'écrit rien. Les changements s'appliquent aux **prochaines** validations et commandes uniquement. **Erreurs** : `400 VALIDATION_ERROR`.

### `GET /admin/audit-logs/` — *paginé*

| Paramètre | Description |
|---|---|
| `action` | Une action (liste dans [04-schema-base-de-donnees.md §3.2](04-schema-base-de-donnees.md)) |
| `actor` | Identifiant de l'utilisateur |
| `target_type`, `target_id` | Cible |
| `date_from`, `date_to` | `AAAA-MM-JJ`, bornes incluses (jours de Nouakchott) |

Du plus récent au plus ancien. Valeur invalide (action inconnue, identifiant non numérique, date mal formée, `date_from > date_to`) → `400 VALIDATION_ERROR`.

**200** (élément)
```json
{
  "id": 501,
  "action": "SHOP_RECHARGED",
  "actor": {"id": 1, "email": "admin@plateforme.mr"},
  "target_type": "shop",
  "target_id": 3,
  "metadata": {"previous_expires_at": "...", "new_expires_at": "...", "duration_months": 12},
  "ip_address": "41.188.10.20",
  "created_at": "2026-12-18T11:00:00+00:00"
}
```

---

## Annexe — Création du premier administrateur

Il n'existe pas d'endpoint pour créer un admin. On utilise la commande (phase 2) :

```bash
docker compose exec backend python manage.py create_admin --email admin@plateforme.mr
```

La commande demande le mot de passe deux fois (saisie masquée) et crée un utilisateur `role = ADMIN`, `is_email_verified = true`. Le mot de passe suit la politique RG-06 ; après trois saisies refusées, la commande s'arrête sans rien créer. Une adresse déjà utilisée est refusée.
