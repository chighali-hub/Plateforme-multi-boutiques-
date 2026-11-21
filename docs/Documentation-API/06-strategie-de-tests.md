# 06 — Stratégie de tests

> Objectif : chaque règle métier (RG-xx) et chaque endpoint sont couverts par des tests automatiques qui tournent dans Docker. **Couverture minimale : 80 %** (configurée dans `backend/pyproject.toml`).

---

## 1. Outils

| Outil | Rôle |
|---|---|
| `pytest` + `pytest-django` | Exécution des tests, base de test PostgreSQL |
| `factory-boy` | Création de données de test lisibles |
| `pytest-cov` | Mesure de la couverture |
| `rest_framework.test.APIClient` | Appels HTTP sur l'API |
| `django_assert_max_num_queries` | Vérifie le nombre de requêtes SQL |
| `django.core.mail.outbox` | E-mails envoyés pendant le test (backend `locmem`) |

Paramètres de test (`config/settings/test.py`, déjà en place) : hachage de mot de passe rapide, cache mémoire, e-mails en mémoire, **Celery exécuté immédiatement** (`CELERY_TASK_ALWAYS_EAGER`), limitations de débit désactivées, dossiers de fichiers séparés (`test_media/`, `test_private_media/`).

Les tests utilisent **PostgreSQL** (comme la production), jamais SQLite : la recherche (`pg_trgm`, `unaccent`, `fuzzystrmatch`) et les contraintes en dépendent.

---

## 2. Lancer les tests

```bash
# Tous les tests
docker compose exec backend pytest

# Une application, un fichier, un test
docker compose exec backend pytest apps/shops
docker compose exec backend pytest apps/shops/tests/test_api_banks.py
docker compose exec backend pytest -k "test_rejected_shop_can_resubmit"

# Avec la couverture
docker compose exec backend pytest --cov --cov-report=term-missing

# Recréer la base de test (après un changement de migration)
docker compose exec backend pytest --create-db
```

---

## 3. Organisation

```
backend/
├── conftest.py                 fixtures communes (clients, utilisateurs, boutiques par état)
└── apps/<app>/tests/
    ├── factories.py            fabriques factory-boy de l'app
    ├── test_models.py          contraintes, propriétés, managers
    ├── test_services.py        règles métier (sans HTTP)
    ├── test_api_<groupe>.py    endpoints (HTTP)
    └── test_tasks.py           tâches Celery
```

### 3.1 Fixtures communes (phase 1, `backend/conftest.py`)

| Fixture | Fournit |
|---|---|
| `api_client` | `APIClient` non authentifié (déjà présente) |
| `admin_user` / `admin_client` | Un administrateur et un client authentifié en tant que lui |
| `make_shop(state="ACTIVE", **kwargs)` | Une boutique complète dans l'état voulu : `ONBOARDING`, `PENDING`, `REJECTED`, `ACTIVE`, `EXPIRED`, `BLOCKED` |
| `shop_client` | Un `APIClient` authentifié en tant que propriétaire d'une boutique **active** (avec une banque) ; la boutique est accessible par `shop_client.shop` |
| `make_shop_client(state)` | Fabrique : renvoie un `APIClient` authentifié pour une nouvelle boutique dans l'état demandé |
| `other_shop_client` | Une **seconde** boutique active : sert aux tests d'isolation |
| `image_file(fmt="JPEG", size=(800, 600))` | Une vraie image générée en mémoire (`SimpleUploadedFile`) |
| `fake_image_file` | Un fichier texte renommé `.jpg` (doit être refusé) |
| `freeze_now` | Fixe l'heure (avec `unittest.mock.patch` de `django.utils.timezone.now`) pour les tests d'expiration et de revenus |

### 3.2 Nommage
`test_<sujet>_<condition>_<résultat attendu>` :

```python
def test_recharge_of_expired_shop_starts_from_today(...)
def test_shop_cannot_read_other_shop_order_returns_404(...)
```

### 3.3 Structure d'un test (Préparer · Agir · Vérifier)

```python
@pytest.mark.django_db
def test_reject_order_requires_reason(shop_client, make_order):
    order = make_order(shop=shop_client.shop, status="SUBMITTED")

    response = shop_client.post(f"/api/v1/shop/orders/{order.id}/reject/", {"reason": ""}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "reason" in response.json()["error"]["details"]
    order.refresh_from_db()
    assert order.status == "SUBMITTED"
```

Toujours vérifier : **le code HTTP**, **le `code` d'erreur** (pas le message, qui est traduit) et **l'état en base** après l'appel.

---

## 4. Ce qu'il faut tester pour chaque endpoint

### 4.1 Liste de contrôle

| # | Cas | Exemple |
|---|---|---|
| 1 | Cas nominal | Création → 201, corps conforme à la référence |
| 2 | Non authentifié | → `401 AUTHENTICATION_REQUIRED` |
| 3 | Mauvais rôle | Boutique sur `/admin/...` → `403 PERMISSION_DENIED` ; admin sur `/shop/...` → `403 PERMISSION_DENIED` |
| 4 | **Chaque état de boutique** de la matrice [03 §0.3](03-reference-api.md) | `PENDING` sur `PATCH /shop/me/` → `403 SHOP_STATE_FORBIDDEN` ; `EXPIRED` → `403 SHOP_EXPIRED` ; `BLOCKED` → `403 SHOP_BLOCKED` |
| 5 | **Isolation** | La boutique B lit, modifie ou supprime une ressource de A → `404 NOT_FOUND`, et la ressource de A est inchangée |
| 6 | Validation | Chaque champ obligatoire manquant, chaque limite (longueur, valeur, taille de fichier) |
| 7 | Règles métier | Chaque RG concernée |
| 8 | Effets de bord | Notification créée, e-mail dans `mail.outbox`, entrée d'audit, fichier supprimé |
| 9 | Requêtes SQL | Listes : `django_assert_max_num_queries(N)` avec 1 et 30 éléments → même nombre |

### 4.2 Test paramétré de la matrice des états
Un seul test couvre tous les états pour un endpoint :

```python
@pytest.mark.django_db
@pytest.mark.parametrize(
    "state, expected_status, expected_code",
    [
        ("ONBOARDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("PENDING", 403, "SHOP_STATE_FORBIDDEN"),
        ("REJECTED", 200, None),
        ("ACTIVE", 200, None),
        ("EXPIRED", 403, "SHOP_EXPIRED"),
        ("BLOCKED", 403, "SHOP_BLOCKED"),
    ],
)
def test_patch_profile_by_state(make_shop_client, state, expected_status, expected_code):
    client = make_shop_client(state=state)
    response = client.patch("/api/v1/shop/me/", {"address": "Ksar, Nouakchott"}, format="json")
    assert response.status_code == expected_status
    if expected_code:
        assert response.json()["error"]["code"] == expected_code
```

### 4.3 Test d'isolation type

```python
@pytest.mark.django_db
def test_shop_cannot_delete_other_shop_product(shop_client, other_shop_client, make_product):
    product = make_product(shop=other_shop_client.shop)

    response = shop_client.delete(f"/api/v1/shop/products/{product.id}/")

    assert response.status_code == 404
    assert Product.objects.filter(id=product.id).exists()
```

---

## 5. Tests obligatoires par phase

### Phase 1 — Socle et modèles
- `Shop.state` pour les 6 états, y compris la priorité (`BLOCKED` l'emporte sur `EXPIRED`), et cohérence entre `Shop.state` et `Shop.objects.with_state()`.
- Une boutique expire à la seconde près (avant / après `expires_at`).
- Contraintes `CHECK` : prix ≤ 0 refusé, nom de produit vide dans les deux langues refusé, commande `REJECTED` sans motif refusée.
- `normalize_search_text` : chaque règle de [04 §9.3](04-schema-base-de-donnees.md) (accents, diacritiques arabes, `أ/ا`, `ة/ه`, `7 → h`, `ph → f`, lettres doublées, ponctuation).
- `compute_deposit` : 6 000 × 30 % = 1 800 ; 1 001 × 30 % = 301 ; 1 × 30 % = 1 ; 100 %.
- `compute_cart` : prix recalculés depuis la base, produits indisponibles exclus, produits d'une autre boutique exclus.
- Gestionnaire d'erreurs : chaque exception DRF donne le bon `code` ; une exception inattendue donne `500 SERVER_ERROR` sans fuite de détails.
- `process_image` : sortie WebP, dimensions maximales, métadonnées EXIF supprimées ; faux fichier image refusé.
- `build_whatsapp_url` : préfixe `222`, encodage du texte.

### Phase 2 — Authentification
- Inscription complète puis vérification de l'e-mail puis jetons.
- OTP : expiré après 10 min, 5 essais, nouveau code invalide l'ancien, renvoi avant 60 s → `429`.
- Connexion : les 4 contrôles dans l'ordre ; e-mail insensible à la casse.
- Une boutique ne se connecte pas par `/auth/admin/login/` et un admin pas par `/auth/shop/login/`.
- Mot de passe oublié : réponse identique pour un e-mail inconnu ; jeton de réinitialisation à usage unique et limité à 15 min ; anciennes sessions invalidées.
- Rafraîchissement refusé pour une boutique bloquée ou expirée ; jeton mis en liste noire après déconnexion.
- Les mots de passe sont stockés hachés (jamais en clair).

### Phase 3 — Espace boutique
- Matrice des états pour **chaque** endpoint de la phase.
- Onboarding : ordre des étapes, `409 ONBOARDING_STEP_MISMATCH`, notification `SHOP_SUBMITTED` aux admins.
- Boutique refusée : modifie son profil et sa carte d'identité, renvoie la demande → `PENDING` + notification admin.
- Banques : limite de 10, doublon refusé, isolation.
- `permissions` et `days_left` de `ShopProfile`.
- La carte d'identité n'est pas sous `/media/` et n'est lisible que par sa boutique et l'admin.
- Notifications : un utilisateur ne voit ni ne marque les notifications d'un autre ; textes rendus en `fr` et en `ar`.

### Phase 4 — Administration
- Valider / refuser / bloquer / débloquer : transitions autorisées et interdites, notifications, e-mails, audit.
- Recharge : boutique active (ajout à la date d'expiration), boutique expirée (ajout à aujourd'hui), 31 janvier + 1 mois, date cible antérieure refusée, deux paramètres refusés, boutique non `APPROVED` refusée.
- Le blocage ferme les sessions (le `refresh` de la boutique est refusé).
- Filtre `state` de la liste des boutiques pour chaque valeur et combinaison.
- Rappels d'expiration : envoyés à J-7, J-3, J-1, une seule fois chacun, à nouveau après une recharge.
- Tous les endpoints `/admin/` refusent un utilisateur `SHOP`.

### Phase 5 — Catalogue
- CRUD complet, images traitées, `published_at`.
- Filtres combinés (`category` + `min_price` + `max_price` + `search`), `min_price > max_price` → 400, `uncategorized`.
- Catégorie supprimée → produits sans catégorie.
- Actions groupées avec un mélange d'identifiants de la boutique et d'une autre boutique.
- Limites (5 000 produits, 100 catégories).

### Phase 6 — Import
- Modèle Excel : feuilles et en-têtes conformes.
- Contrôles synchrones : mauvais format, en-têtes manquants, 0 et 1 001 lignes, ZIP corrompu, ZIP avec `../`, ZIP qui dépasse 500 Mo une fois décompressé (fichier construit en test avec un contenu très compressible).
- Traitement : lignes valides → brouillons ; ligne avec plusieurs erreurs → toutes listées ; image trouvée malgré la casse et les dossiers ; image en double → `IMAGE_AMBIGUOUS` ; catégorie créée automatiquement.
- Correction d'une ligne puis « Publier cette collection » : publication partielle et `remaining`.
- Un seul import actif par boutique.
- Notification `IMPORT_COMPLETED` avec les bons compteurs.

### Phase 7 — Site public
- Visibilité : boutiques `ONBOARDING`, `PENDING`, `REJECTED`, `EXPIRED`, `BLOCKED` et `ACTIVE` sans banque → absentes de la liste et `404` sur leur page.
- Produits brouillons ou indisponibles → absents et `404`.
- Recherche : jeu de données fixe et résultats attendus pour `melehfa`, `MELHFA`, `mel7fa`, `telefone`, `acesoire`, `ملحفة`, `مَلْحَفَة`, `عطر`, et **absence** de résultat pour `voiture`. Classement : une boutique nommée « Melhfa Store » passe avant une boutique qui cite « melhfa » dans sa description.
- `lang=fr` cherche dans `description_fr` uniquement, `lang=ar` dans `description_ar` uniquement.
- Repli de langue des produits.
- `has_multiple_categories` vrai/faux ; `price_range`.
- Devis : prix envoyés par le client ignorés, produits indisponibles, acompte.

### Phase 8 — Commandes
- Soumission : commande + lignes + copies, référence au format `CMD-AAAA-NNNNNN`, capture en stockage privé, notification `ORDER_NEW`, e-mail à la boutique.
- `409 CART_CHANGED` si un produit est dépublié entre le devis et la commande.
- `amount_paid` inférieur à l'acompte accepté (RG-44) ; supérieur au total refusé.
- Suivi : bon téléphone → résultat ; mauvais téléphone → absent ; motif de refus visible.
- Transitions : toutes les combinaisons autorisées et interdites.
- Revenu du mois : seules les commandes `DELIVERED` comptent, sur `delivered_at` ; commande livrée le 30/11 à 23:30 → novembre ; commande livrée le 01/12 à 00:10 → décembre ; commandes refusées et confirmées exclues.
- Isolation des commandes et des captures.

---

## 6. Données de test pour la recherche et la charge (phase 7)

Commande `python manage.py seed_demo --shops 50 --products 30` : crée des boutiques actives réalistes (noms et descriptions FR/AR, catégories, produits avec images générées), un admin `admin@demo.local` et quelques commandes. Elle sert :
- au front pour développer avec des données ;
- à la recette manuelle via Swagger.

Commande `python manage.py seed_load --shops 10000 --products-per-shop 5000` (**uniquement en local**) : jeu de données de charge pour mesurer les temps de recherche (objectif : 95 % des requêtes < 300 ms).

---

## 7. Avant chaque demande de fusion

```bash
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .
docker compose exec backend python manage.py makemigrations --check --dry-run
docker compose exec backend python manage.py spectacular --validate --fail-on-warn --file /tmp/schema.yaml
docker compose exec backend pytest --cov --cov-report=term-missing
```

Les cinq commandes doivent réussir. Le résultat de la dernière (couverture) est copié dans la description de la demande de fusion.
