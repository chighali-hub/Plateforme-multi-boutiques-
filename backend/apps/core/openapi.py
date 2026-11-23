"""Aides a la documentation Swagger. Voir 05-aspects-transversaux.md section 14."""

from drf_spectacular.utils import OpenApiResponse


def error_responses(*codes: str) -> dict[int, OpenApiResponse]:
    """Reponses d'erreur documentees : error_responses("403 SHOP_BLOCKED", ...).

    Les codes d'un meme statut HTTP sont regroupes dans une seule description.
    """
    by_status: dict[int, list[str]] = {}
    for item in codes:
        http_status, code = item.split(" ", 1)
        by_status.setdefault(int(http_status), []).append(code)
    return {
        http_status: OpenApiResponse(description=", ".join(names))
        for http_status, names in by_status.items()
    }
