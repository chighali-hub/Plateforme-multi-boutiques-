# 05 — Aspects transversaux

> Ce document fixe **comment** coder les parties communes à toutes les phases. Tout le monde suit ces conventions ; une revue de code qui constate un écart demande une correction.
> Les outils décrits ici sont créés pendant la **phase 1** (sauf mention contraire), dans `backend/apps/core/`.

---

## 1. Organisation d'une application Django

Chaque application de `backend/apps/` suit la même structure :

| Fichier | Responsabilité | Ce qu'il ne doit **pas** contenir |
|---|---|---|
| `models.py` | Tables, contraintes, propriétés simples (`state`, `remaining_amount`) | Envoi d'e-mails, notifications, appels à d'autres apps |
| `selectors.py` | **Lectures** : fonctions qui renvoient des querysets filtrés (`get_visible_shops()`, `get_shop_orders(shop)`) | Écritures |
| `services.py` | **Écritures et logique métier** : transactions, transitions d'état, notifications, audit (`approve_shop()`, `submit_order()`) | Accès à `request`, sérialisation HTTP |
| `serializers.py` | Validation des entrées et format des sorties | Logique métier (appeler un service à la place) |
| `views.py` | Vues **fines** : permissions, appel du serializer, appel du service, réponse | Requêtes complexes, règles métier |
| `permissions.py` | Classes de permission propres à l'app | |
| `filters.py` | `FilterSet` de django-filter | |
| `tasks.py` | Tâches Celery (fines : elles appellent un service) | |
| `urls.py` | Routes de l'app (incluses sous `/api/v1/`) | |
| `admin.py` | Admin Django (outil technique, pas le dashboard admin) | |
| `tests/` | `factories.py`, `test_models.py`, `test_services.py`, `test_api_<groupe>.py` | |

Règle d'or : **une règle métier est écrite une seule fois, dans un service.** Les vues, les tâches Celery et les commandes appellent ce service.

Exemple de vue fine :

```python
class ApproveShopView(APIView):
    permission_classes = [IsPlatformAdmin]

    @extend_schema(tags=["Admin - Boutiques"], summary="Valider une boutique",
                   request=None, responses=AdminShopDetailSerializer)
    def post(self, request, pk: int):
        shop = get_object_or_404(Shop, pk=pk)
        shop = services.approve_shop(shop=shop, admin=request.user, request=request)
        return Response(AdminShopDetailSerializer(shop, context={"request": request}).data)
```

---

## 2. Conventions de nommage

| Élément | Convention | Exemple |
|---|---|---|
| Chemins d'URL | minuscules, mots séparés par `-`, barre finale | `/shop/products/bulk-publish/` |
| Noms de route Django | `<app>-<ressource>-<action>` | `shops-banks-list` |
| Champs JSON | `snake_case`, en anglais | `deposit_required` |
| Codes d'erreur, statuts, types | `UPPER_SNAKE_CASE`, en anglais | `SHOP_EXPIRED`, `DELIVERED` |
| Classes | `PascalCase` | `ShopProfileSerializer` |
| Fonctions de service | verbe à l'infinitif anglais | `approve_shop`, `recharge_shop` |
| Tags Swagger | `<Espace> - <Groupe>` | `Boutique - Produits`, `Public - Boutiques`, `Admin - Boutiques` |
| Docstrings et commentaires | en français | |

---

## 3. Erreurs

### 3.1 Format unique
Toutes les erreurs suivent le format décrit dans [03-reference-api.md §0.4](03-reference-api.md). Il est produit par **un seul** gestionnaire : `apps.core.exceptions.api_exception_handler`, déclaré dans `REST_FRAMEWORK["EXCEPTION_HANDLER"]`.

Correspondance entre les exceptions DRF et nos codes :

| Exception | `code` |
|---|---|
| `ValidationError` | `VALIDATION_ERROR` (les erreurs par champ vont dans `details`) |
| `NotAuthenticated` | `AUTHENTICATION_REQUIRED` |
| `AuthenticationFailed`, `InvalidToken` (simplejwt) | `TOKEN_INVALID` |
| `PermissionDenied` | `PERMISSION_DENIED` |
| `NotFound`, `Http404` | `NOT_FOUND` |
| `MethodNotAllowed` | `METHOD_NOT_ALLOWED` |
| `Throttled` | `THROTTLED` (`details.retry_after`) |
| `RequestDataTooBig`, fichier trop gros | `FILE_TOO_LARGE` |
| Toute autre exception | `SERVER_ERROR` (journalisée avec la pile d'appels, message générique) |

### 3.2 Erreurs métier
Les services lèvent des exceptions métier, jamais des `Response` :

```python
# apps/core/exceptions.py
class BusinessError(APIException):
    status_code = 400
    code = "BUSINESS_ERROR"
    default_message = _("Opération impossible.")

    def __init__(self, message=None, details=None):
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class InvalidStateTransition(BusinessError):
    status_code = 409
    code = "INVALID_STATE_TRANSITION"
    default_message = _("Cette action n'est pas possible dans l'état actuel.")
```

Utilisation :

```python
if order.status != Order.Status.SUBMITTED:
    raise InvalidStateTransition(details={"current_status": order.status})
```

Chaque code de [03-reference-api.md §0.5](03-reference-api.md) a sa classe dans `apps/core/exceptions.py`. On n'invente pas de nouveau code sans mettre à jour la référence de l'API.

### 3.3 Messages
- Tout message destiné à l'utilisateur passe par `gettext_lazy` (`_()`), en français dans le code.
- Les traductions arabes sont dans `backend/locale/ar/LC_MESSAGES/django.po` (voir §7).

---

## 4. Authentification et permissions

### 4.1 JWT
- `djangorestframework-simplejwt` avec rotation et liste noire (`rest_framework_simplejwt.token_blacklist`, déjà installé).
- Le jeton `access` contient `user_id` et `role`. L'état de la boutique **n'est pas** dans le jeton : il est vérifié en base à chaque requête (il peut changer à tout moment).
- Invalider toutes les sessions d'un utilisateur (`apps.accounts.services.revoke_all_sessions(user)`) : mettre en liste noire tous ses `OutstandingToken` non expirés. Utilisé par : réinitialisation du mot de passe, changement de mot de passe, blocage.

### 4.2 Classes de permission (`apps/core/permissions.py`)

| Classe | Vérifie |
|---|---|
| `IsPlatformAdmin` | Authentifié et `role = ADMIN` ; sinon `403 PERMISSION_DENIED` |
| `IsShopOwner` | Authentifié, `role = SHOP` et possède une boutique ; puis bloquée → `SHOP_BLOCKED`, expirée → `SHOP_EXPIRED` |
| `ShopStateAllowed(*states)` | État de la boutique dans la liste ; sinon `403 SHOP_STATE_FORBIDDEN` |

Utilisation, en reprenant **exactement** la matrice de [03-reference-api.md §0.3](03-reference-api.md) :

```python
class BankListCreateView(generics.ListCreateAPIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsShopOwner(), ShopStateAllowed("PENDING", "REJECTED", "ACTIVE")]
        return [IsShopOwner(), ShopStateAllowed("REJECTED", "ACTIVE")]
```

`IsShopOwner` place la boutique dans `request.shop` (chargée une fois avec `select_related("theme")`). Les vues utilisent `request.shop`, jamais un identifiant de boutique venant de la requête.

### 4.3 Isolation entre boutiques (multi-tenant)
C'est la règle de sécurité la plus importante du projet.

- Tout queryset de l'espace boutique part de `request.shop` : `Product.objects.filter(shop=request.shop)`, jamais `Product.objects.all()`.
- Toute clé étrangère reçue dans le corps (ex. `category_id`, `bank_account_id`) est validée **dans la boutique** : `Category.objects.filter(shop=shop, pk=value)`.
- Une ressource d'une autre boutique renvoie `404 NOT_FOUND`, **jamais** `403` (on ne confirme pas son existence).
- Chaque endpoint de l'espace boutique a un test d'isolation (voir [06-strategie-de-tests.md](06-strategie-de-tests.md) §4).

### 4.4 Limitation de débit
Les limites sont déclarées dans `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` et appliquées avec `ScopedRateThrottle` (`throttle_scope = "auth"`, `"otp"`, `"order_submit"`…). Les valeurs sont celles de [03-reference-api.md](03-reference-api.md) ; les portées déjà déclarées dans `config/settings/base.py` sont `auth` (10/min), `admin_auth` (5/min), `otp` (5/min), `order_submit` (5/h) et `order_track` (30/min). La limite « 10 commandes/jour par téléphone » est une classe dédiée (`PhoneRateThrottle`) dont la clé est le numéro normalisé.

---

## 5. Pagination, filtres, tri

- `apps.core.pagination.StandardPagination` : `page_size = 20`, `page_size_query_param = "page_size"`, `max_page_size = 100`. Déclarée par défaut dans les paramètres.
- `apps.core.pagination.PublicPagination` : `page_size = 24`, pour les listes du site public.
- Filtres avec `django-filter` (`filters.py`). Les paramètres numériques sont validés : une valeur invalide renvoie `400 VALIDATION_ERROR`, jamais une erreur 500 ni un filtre silencieusement ignoré.
- Tri avec `OrderingFilter` et une liste blanche `ordering_fields` ; tri par défaut explicite (`ordering = ["-created_at"]`). Toujours ajouter `id` comme second critère pour un ordre stable entre les pages.
- Les listes « non paginées » de la référence (banques, catégories, thèmes) ont une limite naturelle (10, 100, quelques modèles).

---

## 6. Performance des requêtes

- Utiliser `select_related` pour les clés étrangères affichées et `prefetch_related` pour les listes imbriquées (`items` d'une commande).
- Les compteurs (`products_count`) se calculent par `annotate(Count(...))`, jamais dans une boucle.
- Objectif : **nombre de requêtes SQL constant** quelle que soit la taille de la page. Les tests le vérifient avec `django_assert_max_num_queries` sur les listes principales.
- Les créations en masse (import) utilisent `bulk_create` par lots de 100 ; `search_text_*` est alors calculé explicitement, car `save()` n'est pas appelé.
- Cible : 95 % des réponses en moins de 300 ms en local avec 10 000 boutiques et 5 000 produits par boutique (jeu de données de charge de la phase 7).

---

## 7. Internationalisation (français / arabe)

### 7.1 Langue de la requête
- `LocaleMiddleware` (déjà activé) lit `Accept-Language`. Langues : `fr` (défaut) et `ar`.
- Les endpoints publics acceptent aussi le paramètre `lang` ; il est prioritaire sur l'en-tête pour **les champs traduits et la recherche**.

### 7.2 Textes de l'interface
- Dans le code : `from django.utils.translation import gettext_lazy as _`, phrases en français.
- Générer et compiler les traductions :
  ```bash
  docker compose exec backend python manage.py makemessages -l ar
  # traduire backend/locale/ar/LC_MESSAGES/django.po
  docker compose exec backend python manage.py compilemessages
  ```
- Le fichier `.po` est versionné, le `.mo` aussi (pour que l'image Docker n'ait rien à compiler).

### 7.3 Contenus saisis par les boutiques
- Boutique : `description_fr` et `description_ar` (les deux obligatoires) ; `name` unique.
- Produit et catégorie : `name_fr`/`name_ar`, `description_fr`/`description_ar` ; au moins un nom.
- Sortie publique : un helper `apps.core.i18n.pick(obj, "name", lang)` renvoie le champ de la langue demandée, sinon celui de l'autre langue.
- L'espace boutique renvoie **les deux** champs (la boutique les modifie).

### 7.4 Notifications et e-mails
- Une notification stocke `type` + `data`. Le texte est produit à la lecture (`render(notification, language)`) avec `gettext` dans la langue de la requête.
- Un e-mail est envoyé dans la langue de la requête qui l'a déclenché si c'est l'utilisateur concerné ; sinon (ex. e-mail envoyé à une boutique suite à une action de l'admin) en **français et arabe** dans le même message.

---

## 8. Fichiers et images

### 8.1 Deux espaces de stockage

| Espace | Dossier | Servi par | Contenu |
|---|---|---|---|
| Public | `MEDIA_ROOT` (`backend/media/`), URL `/media/` | Serveur web (Django en dev, Nginx/CDN en prod) | Logos, images et miniatures des produits, aperçus des designs |
| Privé | `PRIVATE_MEDIA_ROOT` (`backend/private_media/`) | **Uniquement** des vues authentifiées | Cartes d'identité, captures de paiement, fichiers d'import |

- Le stockage privé est un `FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)` : il n'a **pas d'URL**.
- Les vues de fichiers privés utilisent `apps.core.storage.private_file_response(field_file)` : `FileResponse` avec le bon `Content-Type`, `Content-Disposition: inline`, `Cache-Control: private, no-store` et `X-Content-Type-Options: nosniff`.

### 8.2 Noms et chemins
- Le nom envoyé par l'utilisateur n'est **jamais** utilisé : chaque fichier est renommé `uuid4().hex` + extension.
- Chemins : `shops/logos/AAAA/MM/`, `products/AAAA/MM/`, `private: id_cards/AAAA/MM/`, `private: payment_proofs/AAAA/MM/`, `private: imports/AAAA/MM/`.

### 8.3 Validation des images (`apps/core/validators.py`)
1. Taille ≤ 5 Mo (sinon `FILE_TOO_LARGE`).
2. Ouverture avec Pillow + `verify()` : le contenu doit être un vrai JPEG, PNG ou WebP (l'extension seule ne suffit pas).
3. Dimensions ≤ 8 000 × 8 000 pixels (protection contre les « bombes de décompression » ; `Image.MAX_IMAGE_PIXELS` est fixé à 64 millions).

### 8.4 Traitement (`apps/core/images.py::process_image`)
- Correction de l'orientation (`ImageOps.exif_transpose`) puis **suppression de toutes les métadonnées** (EXIF, GPS).
- Conversion en RGB, enregistrement en **WebP** qualité 82.
- Logo : 512 × 512 max. Image produit : 1 600 px max sur le plus grand côté + miniature 400 px.
- Cartes d'identité et captures de paiement : **pas** de réduction de qualité (elles doivent rester lisibles) ; seule la suppression des métadonnées est appliquée, format d'origine conservé.

### 8.5 Suppression
Quand une image est remplacée ou que son objet est supprimé, l'ancien fichier est supprimé dans `transaction.on_commit(...)` (jamais avant la validation de la transaction).

---

## 9. Recherche (boutiques et produits)

### 9.1 Objectif
Le client tape un mot ; on doit trouver les boutiques dont le **nom** ou la **description dans la langue active** le contiennent, même avec des majuscules, des accents manquants, une faute de frappe ou un mot incomplet. Le résultat doit être rapide et bien classé.

### 9.2 Normalisation identique des deux côtés
Le texte stocké (`search_name`, `search_text_fr`, `search_text_ar`) et le texte tapé par le client passent par la **même** fonction `apps.core.text.normalize_search_text()` (étapes détaillées dans [04-schema-base-de-donnees.md §9.3](04-schema-base-de-donnees.md)). Exemples :

| Saisie | Forme normalisée |
|---|---|
| `Melhfa`, `MELHFA`, `mel7fa` | `melhfa` |
| `Téléphones` | `telefones` |
| `Accessoires` | `acesoires` |
| `مَلْحَفَة`, `ملحفة` | `ملحفه` |
| `أحذية` | `احذيه` |

### 9.3 Correspondance d'un mot
La requête normalisée est découpée en mots (5 au maximum ; les mots d'une seule lettre sont ignorés). Une ligne correspond si **chaque mot** de la requête correspond à au moins un mot de son texte. Un mot `q` de la requête correspond à un mot `w` du texte si :

1. **sous-chaîne** : `q` est contenu dans le texte (`search_text LIKE '%q%'`, accéléré par l'index GIN trigrammes) ; **ou**
2. **faute de frappe** : `levenshtein(q, w) ≤ k` ; **ou**
3. **mot incomplet avec faute** : `levenshtein(q, left(w, length(q))) ≤ k`.

Tolérance `k` selon la longueur de `q` :

| Longueur de `q` | Lettres latines | Lettres arabes |
|---|---|---|
| 2 | 0 | 0 |
| 3 | 0 | 1 (les mots arabes sont courts : `عطر` → `عطور`) |
| 4–5 | 1 | 1 |
| 6 et plus | 2 | 2 |

Les cas 2 et 3 sont implémentés par une expression SQL personnalisée `apps.core.search.FuzzyWordMatch(field, token, k)` :

```sql
EXISTS (
  SELECT 1 FROM unnest(string_to_array(<field>, ' ')) AS w
  WHERE levenshtein_less_equal(<token>, w, <k>) <= <k>
     OR levenshtein_less_equal(<token>, left(w, length(<token>)), <k>) <= <k>
)
```

Mesures réelles sur PostgreSQL 16 avec cette règle :

| Saisie | Texte de la boutique | Trouvé ? |
|---|---|---|
| `melehfa` | « Melhfas, voiles et parfums » | ✅ (distance 2) |
| `telefone` | « Téléphones et accessoires » | ✅ (distance 1 après pliage `ph → f`) |
| `acesoire` | « Téléphones et accessoires » | ✅ |
| `melf` (frappe en cours) | « Melfas… » | ✅ (préfixe) |
| `عطر` | « ملاحف و خمارات و عطور » | ✅ (distance 1) |
| `voiture` | « Melhfas, voiles et parfums » | ❌ (distance 4 : pas de faux positif) |

> Un simple seuil de similarité trigramme a été écarté : il donnait 0,40 à `melehfa` mais déjà 0,38 à `voiture` sur le même texte, donc trop de faux positifs.

### 9.4 Classement (pertinence)
Le score est calculé par une annotation, puis les résultats sont triés par score décroissant, puis par date de validation :

| Critère | Points |
|---|---|
| Le nom normalisé **est égal** à la requête | 100 |
| Le nom commence par la requête | 50 |
| Un mot de la requête est contenu dans le nom | 30 par mot |
| Un mot de la requête correspond au nom par tolérance (faute) | 15 par mot |
| Un mot de la requête est contenu dans la description | 10 par mot |
| Un mot de la requête correspond à la description par tolérance | 5 par mot |

Pour les produits, il n'y a pas de colonne de nom séparée : le classement s'applique à `search_text_*`, qui commence par le nom du produit (+50 si le texte commence par la requête, 30 par mot contenu, 15 par mot trouvé par tolérance).

### 9.5 Langue
- `lang=fr` : on cherche dans `search_name` et `search_text_fr`.
- `lang=ar` : on cherche dans `search_name` et `search_text_ar`.

Le nom de la boutique est commun aux deux langues, donc une boutique nommée « Aïcha Mode » est trouvée par « aicha » dans les deux langues.

### 9.6 Limites connues (à expliquer à l'équipe front)
- Un mot écrit en lettres latines ne trouve pas sa traduction en lettres arabes (`melhfa` ≠ `ملحفة`) : c'est pour cela que chaque boutique saisit sa description dans les deux langues.
- Les pluriels arabes irréguliers sont partiellement couverts par la tolérance (`ملحفه` → `ملاحف` : distance 2, trouvé).
- Si les mesures de charge de la phase 7 dépassent 300 ms, on ajoutera une table de vocabulaire (mots uniques indexés) ; l'API ne changera pas.

---

## 10. Dates, heures et montants

- `USE_TZ = True` ; tout est stocké en UTC. Le fuseau métier est `Africa/Nouakchott` (UTC+0, sans heure d'été), utilisé pour les « mois » du revenu et les rappels.
- Toujours utiliser `django.utils.timezone.now()`, jamais `datetime.now()`.
- Ajout de mois : `dateutil.relativedelta(months=n)` (fourni avec Celery). Le 31 janvier + 1 mois = fin février.
- `days_left = ceil((expires_at − maintenant) / 1 jour)`, minimum 0.
- Montants : entiers (`IntegerField` / `PositiveIntegerField`), jamais de `float`.
- Acompte : `apps.orders.pricing.compute_deposit(total, percent) = (total * percent + 99) // 100` (arrondi supérieur en arithmétique entière ; ex. 1 001 × 30 % → 301).

---

## 11. Téléphones et WhatsApp

- Format stocké : 8 chiffres (`^[234][0-9]{7}$`). Le validateur accepte en entrée des espaces, `+222` ou `00222` et les retire.
- `apps.core.whatsapp.build_whatsapp_url(phone, text=None)` → `https://wa.me/222<phone>` + `?text=<texte encodé en URL>`.
- Messages pré-remplis (traduits selon la langue) :

| Contexte | Texte |
|---|---|
| Boutique → admin (recharge, compte expiré) | « Bonjour, je souhaite recharger le compte de la boutique {nom} ({e-mail}). » |
| Boutique → client | « Bonjour {nom du client}, concernant votre commande {référence}. » |
| Client → boutique (après paiement) | « Bonjour, j'ai passé la commande {référence}. » |

---

## 12. Notifications, e-mails et audit

| Outil | Appel | Remarques |
|---|---|---|
| Notification | `notify(user, NotificationType.ORDER_NEW, data={...})` | Crée la ligne ; jamais d'envoi synchrone |
| Notification aux admins | `notify_admins(type, data)` | Une ligne par admin actif |
| E-mail | `send_templated_email.delay(to, "emails/order_new", context, language)` | Tâche Celery, 3 tentatives avec attente croissante |
| Audit | `log_action(actor, AuditAction.SHOP_APPROVED, target=shop, metadata={...}, request=request)` | Enregistre l'IP |

- Les notifications, e-mails et entrées d'audit déclenchés par un service sont émis dans `transaction.on_commit(...)` : rien n'est envoyé si la transaction échoue.
- Gabarits d'e-mail : `backend/templates/emails/<nom>.txt` (texte simple), sujet dans `<nom>_subject.txt`.
- En développement, tous les e-mails arrivent dans **Mailpit** : http://localhost:8025.

---

## 13. Tâches asynchrones (Celery)

| Tâche | Déclenchement | Phase |
|---|---|---|
| `core.send_templated_email` | À la demande | 1 |
| `catalog.process_import_job` | Après `POST /shop/products/import/` | 6 |
| `catalog.cleanup_import_files` | Tous les jours à 03:00 | 6 |
| `administration.send_expiry_reminders` | Tous les jours à 08:00 | 4 |

- Planification dans `CELERY_BEAT_SCHEDULE` (`config/settings/base.py`).
- Une tâche reçoit des **identifiants**, jamais des objets (`process_import_job.delay(job.id)`).
- Une tâche doit être **idempotente** : la relancer ne crée pas de doublon.
- En test, `CELERY_TASK_ALWAYS_EAGER = True` (déjà configuré) : les tâches s'exécutent immédiatement.

---

## 14. Documentation Swagger

- Chaque vue a un `@extend_schema(tags=[...], summary="...", request=..., responses={...})`.
- Les réponses d'erreur possibles sont déclarées (`OpenApiResponse(description="SHOP_EXPIRED")`).
- Les endpoints multipart déclarent `request={"multipart/form-data": Serializer}`.
- Vérifier avant chaque demande de fusion : `docker compose exec backend python manage.py spectacular --validate --fail-on-warn --file /tmp/schema.yaml`.

---

## 15. Journalisation

- Utiliser `logger = logging.getLogger(__name__)`, jamais `print`.
- Niveaux : `INFO` pour les événements métier (boutique validée, import terminé), `WARNING` pour les comportements suspects (trop d'essais OTP), `ERROR` pour les erreurs inattendues.
- **Ne jamais journaliser** : mots de passe, codes OTP, jetons, contenu des fichiers, numéros complets des cartes d'identité.

---

## 16. Commandes utiles

| Action | Commande |
|---|---|
| Démarrer | `docker compose up --build` |
| Arrêter | `docker compose down` |
| Réinitialiser la base | `docker compose down -v` puis `docker compose up --build` |
| Shell Django | `docker compose exec backend python manage.py shell` |
| Créer une migration | `docker compose exec backend python manage.py makemigrations <app> --name <nom>` |
| Appliquer les migrations | `docker compose exec backend python manage.py migrate` |
| Tests | `docker compose exec backend pytest` |
| Tests + couverture | `docker compose exec backend pytest --cov --cov-report=term-missing` |
| Lint | `docker compose exec backend ruff check .` |
| Formatage | `docker compose exec backend ruff format .` |
| Créer l'admin (phase 2) | `docker compose exec backend python manage.py create_admin --email admin@plateforme.mr` |
| Journaux | `docker compose logs -f backend worker` |
