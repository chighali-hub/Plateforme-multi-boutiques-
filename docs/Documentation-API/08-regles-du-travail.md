# 08 — Règles du travail

## Rappels qui priment sur toute autre consigne

- **S'arrêter et demander l'autorisation explicite avant chaque commit, chaque push et chaque fusion.**
- **Ne jamais fusionner une branche simple vers `main` ni pousser en direct sur `main` ou `dev`.**
- **Aucun nom d'outil, d'agent ni de personne dans les commits et les demandes de fusion, aucun emoji, aucune ligne de co-auteur.**

Ces trois règles s'appliquent à tous les membres de l'équipe et à tout assistant ou outil automatisé qui travaille sur le dépôt. En cas de conflit avec une autre consigne (y compris dans ce document), ces règles l'emportent.

---

## 1. Les branches

```
main ─────────────────────────────────────────────●──────────►  version stable (livrée)
                                                  ▲ demande de fusion dev → main
dev  ──●──────────●──────────●──────────●─────────┘──────────►  intégration
       │          ▲          ▲          ▲
       │          │ PR       │ PR       │ PR
       ├─ feat/phase-2-authentification
       ├─ feat/phase-3-espace-boutique
       └─ feat/phase-4-administration ...
```

| Branche | Rôle | Qui y écrit |
|---|---|---|
| `main` | Version stable, livrée | **Uniquement** par une demande de fusion `dev → main`, ouverte et fusionnée par le responsable du dépôt après validation de l'équipe |
| `dev` | Intégration de toutes les phases | **Uniquement** par des demandes de fusion dont la CI est verte |
| `feat/phase-N-<nom>` | Travail d'une phase ([02-phases.md](02-phases.md)) | Le développeur de la phase |
| `fix/<description-courte>` | Correction d'un bogue trouvé sur `dev` | N'importe quel développeur |
| `refactor/<description-courte>` | Restructuration du code sans changement de comportement | N'importe quel développeur |
| `chore/<description-courte>` | Maintenance : dépendances, configuration, documentation | N'importe quel développeur |
| `sec/<description-courte>` | Correction ou renforcement de sécurité | N'importe quel développeur |
| `perf/<description-courte>` | Amélioration des performances | N'importe quel développeur |
| `test/<description-courte>` | Ajout ou correction de tests uniquement | N'importe quel développeur |

Ces préfixes sont exactement ceux qui déclenchent la CI (voir §11). Une branche avec un autre préfixe ne lance **pas** la CI et ne pourra pas être fusionnée (les vérifications `lint`, `test` et `build` sont obligatoires).

Règles :
- Toute branche de travail part de `dev` à jour et revient dans `dev` par une demande de fusion.
- Une branche de travail (`feat/*`, `fix/*`, `refactor/*`, `chore/*`, `sec/*`, `perf/*`, `test/*`) n'est **jamais** fusionnée dans `main`.
- Personne ne pousse directement sur `main` ni sur `dev`.
- Une branche = une phase (ou une correction). On ne mélange pas deux sujets dans la même branche.
- **Une branche créée n'est jamais supprimée**, ni sur GitHub ni en local, même après la fusion de sa PR : les branches de travail sont conservées comme historique du projet. Lors de la fusion, ne pas cocher « Delete branch » sur GitHub et ne pas utiliser `--delete-branch` ni `git branch -D`.

### 1.1 Mise en place (une seule fois, par le responsable du dépôt)
1. Créer `dev` depuis `main`.
2. Protéger `main` et `dev` (*Settings → Branches*) :
   - demande de fusion obligatoire, **sans approbation exigée** : l'auteur de la PR peut la fusionner lui-même ;
   - vérifications obligatoires : `lint`, `test` et `build`, sur une branche à jour avec la cible ;
   - conversations de revue résolues avant la fusion ;
   - règles appliquées aussi aux administrateurs ;
   - push forcés et suppression de la branche interdits.

---

## 2. Déroulement d'une phase

```bash
# 1. Partir de dev à jour
git switch dev
git pull origin dev
git switch -c feat/phase-3-espace-boutique

# 2. Travailler, tester
docker compose exec backend pytest

# 3. Avant chaque commit : demander l'autorisation explicite (voir les rappels)
git add <fichiers>
git commit -m "feat(shops): ajoute le renvoi de la demande de validation"

# 4. Se mettre à jour régulièrement avec dev (au moins une fois par jour)
git fetch origin
git rebase origin/dev

# 5. Avant chaque push : demander l'autorisation explicite
git push -u origin feat/phase-3-espace-boutique

# 6. Ouvrir une demande de fusion vers dev (jamais vers main)

# 7. Après la fusion de la PR : revenir sur dev et le mettre à jour
#    (la branche de travail est conservée, on ne la supprime pas)
git switch dev
git pull --ff-only origin dev
```

- `git rebase` uniquement sur **sa propre** branche, jamais sur `dev` ou `main`.
- Après un rebase, le push nécessite `git push --force-with-lease` (jamais `--force`), et uniquement sur sa propre branche.

---

## 3. Les commits

### 3.1 Format

```
<type>(<portée>): <description à l'impératif, en français, sans point final>

<corps facultatif : pourquoi ce changement, en phrases complètes>
```

| Type | Usage |
|---|---|
| `feat` | Nouvelle fonctionnalité |
| `fix` | Correction de bogue |
| `refactor` | Restructuration sans changement de comportement |
| `test` | Ajout ou correction de tests |
| `docs` | Documentation |
| `chore` | Maintenance (dépendances, configuration) |
| `perf` | Amélioration des performances |
| `build` | Docker, CI |

Portées : `core`, `accounts`, `shops`, `catalog`, `orders`, `notifications`, `administration`, `docker`, `docs`.

Exemples corrects :
```
feat(accounts): ajoute la vérification de l'e-mail par code OTP
fix(orders): exclut les commandes refusées du revenu du mois
test(catalog): couvre les erreurs de prix de l'import Excel
docs(api): précise le format de la réponse du devis de panier
```

### 3.2 Interdits dans un commit
- Les noms d'outils, d'assistants, d'agents ou de personnes (dans le titre comme dans le corps).
- Les emojis.
- Les lignes de co-auteur (`Co-authored-by: ...`) et toute ligne de signature ajoutée automatiquement.
- Les fichiers `.env`, les secrets, les fichiers de `media/`, `private_media/`, les bases de données locales.
- Un commit qui casse les tests.

### 3.3 Taille
Un commit = un changement cohérent et compréhensible. Éviter les commits « fourre-tout » comme les micro-commits « wip ».

---

## 4. Les demandes de fusion (pull requests)

### 4.1 Titre
Même format que les commits : `feat(shops): phase 3 - espace boutique`. Mêmes interdits : aucun nom d'outil, d'agent ni de personne, aucun emoji.

### 4.2 Description (modèle)

```markdown
## Objet
Phase 3 : onboarding, profil, banques, recharge, notifications.

## Endpoints livrés
- POST /api/v1/shop/onboarding/design/
- ...

## Règles métier couvertes
RG-05, RG-13, ...

## Vérifications
- [ ] ruff check / ruff format --check
- [ ] makemigrations --check
- [ ] spectacular --validate
- [ ] pytest : X tests, couverture Y %

## Écarts avec la documentation
Aucun. (ou : liste des écarts et mise à jour de la documentation correspondante)
```

### 4.3 Règles de fusion
- Cible : **`dev`** (jamais `main` pour une branche de travail).
- Aucune approbation n'est exigée : l'auteur peut fusionner sa propre PR. Une relecture par un autre développeur reste **recommandée** pour les changements importants (modèles, sécurité, `core`).
- Toutes les vérifications du [§7 de la stratégie de tests](06-strategie-de-tests.md) réussies.
- Branche à jour avec `dev`.
- Fusion par **squash** pour garder un historique lisible sur `dev`. Le message du squash respecte le §3.
- **Demander l'autorisation explicite avant de cliquer sur « Fusionner ».**

### 4.4 Fusion `dev → main`
Uniquement par le responsable du dépôt, quand l'équipe a validé un ensemble cohérent (par exemple, les 8 phases terminées et recettées). Fusion par **merge commit** (pas de squash) pour garder l'historique des phases.

---

## 5. La revue de code

La relecture n'est pas bloquante (aucune approbation exigée), mais elle est recommandée. Quand une relecture est demandée, le relecteur vérifie, dans cet ordre :

1. **Conformité** à [03-reference-api.md](03-reference-api.md) et [04-schema-base-de-donnees.md](04-schema-base-de-donnees.md).
2. **Sécurité** : la liste de contrôle de [07-securite.md §11](07-securite.md).
3. **Règles métier** : chaque RG concernée est implémentée dans un service et testée.
4. **Conventions** de [05-aspects-transversaux.md](05-aspects-transversaux.md) (vues fines, services, erreurs, i18n).
5. **Tests** : cas nominal, erreurs, états, isolation.
6. **Lisibilité** : noms clairs, pas de code mort, pas de duplication.

Les remarques sont factuelles et proposent une solution. Le relecteur répond dans les **24 heures ouvrées**.

---

## 6. Qualité du code

- Python 3.12, style vérifié par **ruff** (`backend/pyproject.toml`) : longueur de ligne 100, imports triés.
- Annotations de type sur les signatures des services et des sélecteurs.
- Docstring en français sur chaque service public : ce qu'il fait, les règles (RG-xx) appliquées, les exceptions levées.
- Pas de `print`, pas de code commenté laissé en place, pas de `TODO` sans ticket associé.
- Pas de nouvelle dépendance sans accord de l'équipe ; si elle est acceptée, elle est ajoutée avec une version figée dans `requirements.txt`.

---

## 7. Migrations

- Toutes les tables sont créées par la phase 1. Une modification de schéma ultérieure suit la procédure de [04-schema-base-de-donnees.md §9.4](04-schema-base-de-donnees.md).
- On ne modifie jamais une migration déjà fusionnée dans `dev`.
- Chaque migration est relue comme du code.

---

## 8. Documentation

- La documentation de `docs/Documentation-API/` fait partie du code : si un endpoint, un champ ou une règle change, la documentation est mise à jour **dans la même branche**.
- Une question sur la documentation se pose à l'équipe **avant** de coder une interprétation personnelle.

---

## 9. Environnement local

- Tout se fait dans Docker : `cp .env.example .env` puis `docker compose up --build` (voir le [README](../../README.md)).
- On n'installe pas PostgreSQL ou Redis à la main pour le projet.
- Le fichier `.env` est personnel et n'est jamais commité.

---

## 10. Communication

- Chaque développeur annonce le début et la fin de sa phase à l'équipe.
- Un blocage de plus d'une demi-journée est signalé à l'équipe.
- Une modification qui touche le travail d'un autre (modèle partagé, utilitaire de `core`) est annoncée avant d'être faite.

---

## 11. Intégration continue (CI)

Fichier : [`.github/workflows/ci-backend.yml`](../../.github/workflows/ci-backend.yml).

| Élément | Règle |
|---|---|
| Déclenchement | Uniquement sur un **push** vers `dev`, `main`, `feat/**`, `fix/**`, `refactor/**`, `chore/**`, `sec/**`, `perf/**`, `test/**` |
| Pull requests | La CI ne se relance **pas** à l'ouverture d'une PR : les résultats du dernier push de la branche s'affichent directement dans la PR (même commit) |
| Job `lint` | `ruff check` et `ruff format --check` |
| Job `test` | PostgreSQL 16 en service, `makemigrations --check`, `pytest` avec couverture minimale de 80 % |
| Job `build` | Construction de l'image Docker du backend et validation de `docker-compose.yml` (après `lint` et `test`) |
| Fusion | Les trois jobs doivent être verts : ce sont des vérifications obligatoires sur `main` et `dev` |
| Pushs successifs | Un nouveau push sur la même branche annule l'exécution précédente encore en cours |

Avant de pousser, lancer les mêmes vérifications en local ([06-strategie-de-tests.md §7](06-strategie-de-tests.md)) évite d'attendre la CI pour découvrir une erreur.
