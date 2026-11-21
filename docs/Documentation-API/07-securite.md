# 07 — Sécurité

> Ce document décrit comment protéger l'application et ses données. Chaque mesure indique **où** elle est implémentée. Une mesure marquée « obligatoire » bloque la fusion si elle manque.
> Référence : OWASP Top 10 (2021) et OWASP API Security Top 10 (2023).

---

## 1. Données sensibles du projet

| Donnée | Sensibilité | Protection |
|---|---|---|
| Mots de passe | Critique | Hachage Argon2id, jamais journalisés ni renvoyés |
| Cartes d'identité des propriétaires | Critique (données personnelles) | Stockage privé, accès par l'admin et la boutique concernée uniquement |
| Captures de paiement des clients | Élevée | Stockage privé, accès par la boutique concernée (et l'admin) uniquement |
| Nom et téléphone des clients | Élevée | Visibles uniquement par la boutique de la commande |
| Codes OTP, jetons JWT, jetons de réinitialisation | Critique | Hachés (OTP), durée courte, jamais journalisés |
| Codes de paiement des boutiques (banques) | Publique par nature (affichés aux clients) | Modifiables uniquement par la boutique |

---

## 2. Authentification

| Mesure | Détail | Où |
|---|---|---|
| Hachage des mots de passe | **Argon2id** (`Argon2PasswordHasher` en premier dans `PASSWORD_HASHERS`) | `config/settings/base.py` ✅ |
| Politique de mot de passe | 8 caractères minimum, pas entièrement numérique, pas courant, différent de l'e-mail (validateurs Django) | `base.py` ✅ |
| Jetons JWT | `access` 15 min, `refresh` 7 jours, rotation, liste noire après rotation | `base.py` ✅ |
| Révocation | Liste noire de tous les `refresh` lors de : réinitialisation du mot de passe, changement de mot de passe, blocage, déconnexion | Phase 2 / 4 |
| État vérifié à chaque requête | Une boutique bloquée ou expirée perd l'accès immédiatement, même avec un `access` encore valide | `IsShopOwner`, phase 1 |
| Connexions séparées | `/auth/shop/login/` refuse les admins, `/auth/admin/login/` refuse les boutiques, avec la **même** erreur `INVALID_CREDENTIALS` | Phase 2 |
| Messages non révélateurs | « E-mail ou mot de passe incorrect » sans préciser lequel ; « mot de passe oublié » et « renvoyer le code » répondent pareil que l'e-mail existe ou non | Phase 2 |
| Temps de réponse constant | Si l'e-mail n'existe pas, on hache quand même un mot de passe factice (évite de deviner les comptes au chronomètre) | Phase 2 |

### 2.1 Codes OTP (obligatoire)
- Génération avec `secrets.randbelow(10**6)` (jamais `random`), sur 6 chiffres avec les zéros de tête.
- Stockage **haché** (`make_password`) ; comparaison par `check_password`.
- Validité 10 minutes ; 5 essais au maximum, puis le code est invalidé ; un nouveau code invalide les précédents ; renvoi possible après 60 secondes.
- Limitation de débit supplémentaire par IP (`otp` : 5/min).

### 2.2 Jeton de réinitialisation du mot de passe
- Créé avec `django.core.signing.TimestampSigner(salt="password-reset")`, contient l'identifiant de l'utilisateur et celui du code OTP utilisé.
- Valable 15 minutes (`max_age=900`), à usage unique (le code OTP associé est marqué consommé).

---

## 3. Autorisation et isolation des boutiques

C'est le risque n°1 des API (OWASP API1 : *Broken Object Level Authorization*).

| Mesure | Détail |
|---|---|
| **Obligatoire** : filtrage par boutique | Tout accès aux données de l'espace boutique part de `request.shop` (voir [05 §4.3](05-aspects-transversaux.md)) |
| **Obligatoire** : clés étrangères vérifiées | `category_id`, `bank_account_id`, `ids` des actions groupées : vérifiés dans la boutique |
| `404` plutôt que `403` | On ne confirme pas l'existence d'une ressource d'une autre boutique |
| Rôles | `IsPlatformAdmin` sur **toutes** les vues `/admin/` ; `IsShopOwner` sur **toutes** les vues `/shop/` |
| Permissions par défaut | `IsAuthenticated` est la permission par défaut de DRF (déjà configurée) : un oubli ferme l'accès au lieu de l'ouvrir. Les vues publiques déclarent explicitement `AllowAny` |
| Attribution en masse (OWASP API3) | Les serializers listent explicitement leurs champs (`fields = [...]`, jamais `"__all__"`). Les champs `status`, `state`, `expires_at`, `is_blocked`, `shop`, `owner`, `role`, `total_amount` ne sont **jamais** modifiables par une boutique ou un client |
| Prix calculés par le serveur | Le total, l'acompte et les prix unitaires d'une commande viennent de la base, jamais du client |
| Tests | Chaque endpoint a un test d'isolation et un test de rôle ([06 §4](06-strategie-de-tests.md)) |

---

## 4. Fichiers envoyés (obligatoire)

| Risque | Mesure |
|---|---|
| Faux fichier image (script renommé `.jpg`) | Ouverture et `verify()` avec Pillow ; seuls JPEG, PNG et WebP sont acceptés |
| Bombe de décompression d'image | `Image.MAX_IMAGE_PIXELS = 64_000_000`, dimensions ≤ 8 000 px |
| Fichier trop gros | 5 Mo par image, 5 Mo pour l'Excel, 200 Mo pour le ZIP ; limites aussi configurées sur le serveur web en production |
| Nom de fichier malveillant (`../../`) | Le nom fourni n'est jamais utilisé : nom aléatoire `uuid4` |
| Métadonnées (GPS dans une photo) | Suppression de toutes les métadonnées EXIF |
| Exécution de fichier | Les dossiers de fichiers ne sont jamais exécutables ; en production, les fichiers publics sont servis avec `X-Content-Type-Options: nosniff` |
| Accès direct aux fichiers privés | Stockage privé **hors** de `MEDIA_ROOT`, sans URL ; accès uniquement par une vue authentifiée avec `Cache-Control: private, no-store` |

### 4.1 ZIP d'import (obligatoire, phase 6)
Contrôles **avant** toute extraction, avec `zipfile.ZipFile` :
- le fichier est un ZIP valide (`zipfile.is_zipfile`) ;
- nombre d'entrées ≤ 2 000 ;
- somme des tailles décompressées (`ZipInfo.file_size`) ≤ 500 Mo (protection contre les « bombes ZIP ») ;
- aucune entrée avec un chemin absolu, `..`, ou un lien symbolique ;
- seules les entrées `.jpg`, `.jpeg`, `.png`, `.webp` sont lues ; les autres sont ignorées.

Les images ne sont **jamais extraites sur le disque** sous leur nom d'origine : chaque image est lue en mémoire (`zip.open(info)`, 5 Mo maximum par entrée), validée, traitée et enregistrée sous un nom aléatoire.

### 4.2 Excel d'import
- Ouverture avec `openpyxl.load_workbook(read_only=True, data_only=True)` : les formules ne sont pas évaluées et les macros ne sont pas chargées.
- Les valeurs lues sont traitées comme du texte brut et validées comme n'importe quelle entrée utilisateur.
- **Injection de formules dans le modèle exporté** : toute valeur écrite dans un fichier Excel généré par la plateforme qui commence par `=`, `+`, `-`, `@` est préfixée par une apostrophe.

---

## 5. Validation des entrées et injections

| Risque | Mesure |
|---|---|
| Injection SQL | ORM Django uniquement. L'expression SQL de recherche (`FuzzyWordMatch`) passe **toujours** les valeurs en paramètres (`%s`), jamais par concaténation. `raw()` et `extra()` sont interdits |
| XSS | L'API renvoie du JSON ; les textes ne sont jamais interprétés comme du HTML côté serveur. Le front React échappe par défaut ; `dangerouslySetInnerHTML` est interdit pour les contenus des boutiques |
| Validation | Chaque champ a un type, une longueur et un format (serializers) ; les téléphones, couleurs et e-mails ont des validateurs dédiés |
| Paramètres de requête | Les filtres invalides renvoient `400`, jamais une erreur 500 |
| SSRF | Le serveur ne télécharge **aucune** URL fournie par un utilisateur (pas d'image par lien) |
| Données excessives (OWASP API3) | Les serializers publics n'exposent que les champs listés dans la référence ; jamais l'e-mail du propriétaire, sa carte d'identité ni les dates internes |

---

## 6. Protection contre les abus

| Endpoint | Limite | Raison |
|---|---|---|
| Connexion boutique, inscription | 10/min par IP | Force brute, création de comptes en masse |
| Connexion admin | 5/min par IP | Force brute sur le compte le plus sensible |
| OTP (vérification, renvoi, mot de passe oublié, changement d'e-mail) | 5/min par IP + règles du §2.1 | Deviner un code |
| Soumission de commande | 5/heure par IP **et** 10/jour par téléphone | Fausses commandes, remplissage du disque avec des captures |
| Suivi de commande | 30/min par IP | Énumération des références |
| Public anonyme (par défaut) | 120/min par IP | Aspiration du site |
| Authentifié (par défaut) | 300/min par utilisateur | Scripts abusifs |

- En production, l'IP réelle vient de l'en-tête `X-Forwarded-For` posé par le proxy de confiance (`NUM_PROXIES = 1` dans `REST_FRAMEWORK`), sinon toutes les requêtes auraient l'IP du proxy.
- Les compteurs utilisent le cache Redis (partagé par tous les processus).

---

## 7. Configuration et secrets

| Mesure | Détail |
|---|---|
| Secrets hors du code | Tout est lu depuis les variables d'environnement (`.env`, jamais commité, déjà dans `.gitignore`) ; `.env.example` contient uniquement des valeurs factices |
| `SECRET_KEY` de production | Générée aléatoirement (50 caractères minimum), différente par environnement |
| `DEBUG` | `False` en production (`config/settings/prod.py`) |
| `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` | Listes explicites ; jamais `*` |
| HTTPS | Obligatoire en production : `SECURE_SSL_REDIRECT`, HSTS 1 an, cookies `Secure` (déjà dans `prod.py`) ; TLS 1.2 minimum, TLS 1.3 de préférence, sur le proxy |
| En-têtes | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin` |
| Admin Django | Déplacé sur `/django-admin/` ; réservé à `is_staff` ; en production, accessible uniquement depuis le réseau d'administration |
| Swagger | `/api/docs/` désactivé en production ou protégé par authentification admin |
| Vérification | `python manage.py check --deploy --settings=config.settings.prod` ne doit signaler aucun avertissement en production |

---

## 8. Journalisation, audit et surveillance

- **Journal d'audit** (`core_audit_log`) : toutes les actions de l'admin, les connexions admin, les réinitialisations de mot de passe et les changements d'e-mail, avec l'auteur, l'IP et le détail. Il n'est jamais modifié ni supprimé par l'application.
- **Journaux techniques** : erreurs 500 avec la pile d'appels ; avertissements pour les échecs répétés de connexion et d'OTP.
- **Ne jamais journaliser** : mots de passe, OTP, jetons, contenus de fichiers, corps des requêtes d'authentification.
- Les erreurs 500 renvoient un message générique (`SERVER_ERROR`), jamais la pile d'appels.

---

## 9. Données personnelles

Principes (RGPD et loi mauritanienne n° 2017-020 sur la protection des données à caractère personnel) :

| Principe | Application |
|---|---|
| Minimisation | Le client ne fournit que son nom, son téléphone et une capture ; l'adresse est facultative |
| Finalité | Les données du client servent uniquement à la boutique pour livrer la commande |
| Accès restreint | Une boutique ne voit que les clients de **ses** commandes ; les cartes d'identité ne sont visibles que par l'admin et leur propriétaire |
| Conservation | Fichiers d'import supprimés 7 jours après la fin de l'import ; règles de conservation des captures et cartes d'identité à valider avec le responsable du projet avant la mise en production |
| Information | Les conditions d'utilisation acceptées à l'inscription (`terms_accepted_at`) décrivent l'usage des données |

---

## 10. Dépendances et infrastructure

- Versions **figées** dans `requirements.txt` (déjà le cas) ; mise à jour mensuelle et contrôle des vulnérabilités connues avec `pip-audit` (`docker compose exec backend pip install pip-audit && pip-audit`).
- L'image Docker tourne avec un utilisateur **non root** (`app`, déjà configuré dans `backend/Dockerfile`).
- PostgreSQL et Redis ne sont pas exposés sur Internet en production (réseau privé uniquement).
- Sauvegardes quotidiennes de la base et des dossiers `media/` et `private_media/`, conservées 30 jours et chiffrées ; restauration testée.

---

## 11. Liste de contrôle de sécurité pour la revue de code

À vérifier sur chaque demande de fusion :

- [ ] Toutes les nouvelles vues ont des `permission_classes` explicites.
- [ ] Les querysets de l'espace boutique partent de `request.shop`.
- [ ] Les clés étrangères reçues sont vérifiées dans la boutique.
- [ ] Les serializers listent leurs champs ; aucun champ sensible n'est modifiable.
- [ ] Les fichiers reçus passent par les validateurs communs.
- [ ] Aucun secret, mot de passe ou jeton dans le code, les tests ou les journaux.
- [ ] Aucune requête SQL construite par concaténation.
- [ ] Les nouveaux endpoints sensibles ont une limitation de débit.
- [ ] Les tests d'isolation et de rôle existent et passent.
