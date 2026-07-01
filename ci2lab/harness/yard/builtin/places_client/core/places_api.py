import json
import re
import unicodedata

try:  # lazy/optional: pure entrypoints run without it; network ones are gated
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

import geometria


# Alias en forma de tokens para detectar centros comerciales en una dirección.
# Tras normalizar, "C.C." y "C. C." quedan como dos tokens "c" "c" (los puntos
# desaparecen al tokenizar con \w+), mientras que "cc"/"ccial" son un único
# token. "centro" suelto NO se incluye porque "Centro" es además el nombre del
# distrito céntrico de Madrid y daría falsos positivos.
_ALIAS_CC_TOKENS = [
    ["centro", "comercial"],
    ["c", "c"],
    ["cc"],
    ["ccial"],
    ["shopping"],
    ["mall"],
]


def _tokens_direccion(direccion):
    """Normaliza (NFKD + casefold + ñ→n) y tokeniza por \\w+."""
    if not direccion:
        return []
    t = unicodedata.normalize("NFKD", direccion)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.casefold().replace("ñ", "n")
    return re.findall(r"\w+", t)


def es_centro_comercial(direccion):
    """Detecta si una dirección postal indica un centro comercial.

    Aliases reconocidos (tras normalizar mayúsculas/acentos/ñ y descartar
    puntuación al tokenizar): "centro comercial", "c c" — que cubre también
    "C.C." y "C. C." —, "cc", "ccial", "shopping", "mall".

    El matching se hace por subsecuencia contigua de tokens, no por substring,
    para evitar falsos positivos como el distrito "Centro" de Madrid o un
    "cc" embebido en otra palabra.
    """
    tokens = _tokens_direccion(direccion)
    if not tokens:
        return False
    for alias in _ALIAS_CC_TOKENS:
        n = len(alias)
        for i in range(len(tokens) - n + 1):
            if tokens[i:i + n] == alias:
                return True
    return False


def buscar_opticas_places_api(lat_min=None, lon_min=None, lat_max=None, lon_max=None,
                              api_key=None, text_query="óptica"):
    """Una sola llamada a Places API (searchText) restringida a un rectángulo."""
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.location,places.websiteUri"
    }

    payload = {
        "textQuery": text_query,
        "languageCode": "es",
        "locationRestriction": {
            "rectangle": {
                "low": {"latitude": lat_min, "longitude": lon_min},
                "high": {"latitude": lat_max, "longitude": lon_max},
            }
        }
    }

    response = requests.post(url, headers=headers, json=payload)
    if not response.ok:
        raise RuntimeError(f"Places API ({response.status_code}): {response.text}")
    return response.json().get("places", [])


# ... [omitido: comentario con dominio del proyecto origen] ...
LIMITE_PLACES_API_TEXTSEARCH = 20


def _buscar_celda_con_split(lat_min, lon_min, lat_max, lon_max, api_key,
                            etiqueta, progreso, permitir_split=True):
    """Consulta Places API en una celda; si satura el límite y `permitir_split`,
    subdivide la celda por la mitad en latitud y consulta las dos mitades.

    Args:
        etiqueta: identificador descriptivo de la celda para el log
            (ej. "celda 1/4" o "celda 1/4 [N]").

    Returns:
        Lista de places (puede contener duplicados entre niveles; el caller
        deduplica por id).
    """
    resultados = buscar_opticas_places_api(
        lat_min=lat_min, lon_min=lon_min, lat_max=lat_max, lon_max=lon_max,
        api_key=api_key,
    )
    n = len(resultados)
    progreso(10, f"  {etiqueta}: {n} resultado(s).")

    if n < LIMITE_PLACES_API_TEXTSEARCH:
        return resultados

    if not permitir_split:
        # ... [omitido: log con dominio del proyecto origen] ...
        return resultados

    progreso(10,
        f"  {etiqueta}: límite alcanzado ({n}); subdividiendo en N/S y "
        "reconsultando.")
    lat_mid = (lat_min + lat_max) / 2
    sur = _buscar_celda_con_split(
        lat_min, lon_min, lat_mid, lon_max, api_key,
        f"{etiqueta} [S]", progreso, permitir_split=False,
    )
    norte = _buscar_celda_con_split(
        lat_mid, lon_min, lat_max, lon_max, api_key,
        f"{etiqueta} [N]", progreso, permitir_split=False,
    )
    return resultados + sur + norte


def buscar_opticas_en_grid(lat_min, lon_min, lat_max, lon_max, api_key,
                           lado_metros=1000, on_progress=None):
    # ... [omitido: docstring con dominio del proyecto origen] ...
    def progreso(pct, msg):
        print(msg)
        if on_progress:
            on_progress(pct, msg)

    celdas = geometria.calcular_celdas_grid(lat_min, lon_min, lat_max, lon_max, lado_metros)
    progreso(10, f"Rejilla de búsqueda: {len(celdas)} celdas (~{lado_metros} m de lado).")

    encontradas = {}  # dedup por id
    for idx, celda in enumerate(celdas, start=1):
        progreso(10, f"Consultando Places API en celda {idx}/{len(celdas)}...")
        resultados = _buscar_celda_con_split(
            celda["lat_min"], celda["lon_min"],
            celda["lat_max"], celda["lon_max"],
            api_key, f"celda {idx}/{len(celdas)}", progreso,
        )
        for place in resultados:
            place_id = place.get("id")
            if place_id and place_id not in encontradas:
                encontradas[place_id] = place

    return list(encontradas.values())


def buscar_negocios_entorno(lat_centro, lon_centro, api_key, radio_metros=500):
    # ... [omitido: docstring con dominio y referencia a un fichero de negocio del proyecto origen] ...
    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.formattedAddress"
    }

    payload = {
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat_centro, "longitude": lon_centro},
                "radius": radio_metros
            }
        },
        # En searchNearby es obligatorio incluir al menos un tipo.
        # ... [omitido: comentario que referencia un fichero de negocio del proyecto origen] ...
        "includedPrimaryTypes": [
            "clothing_store", "supermarket", "bank", "department_store", "shopping_mall"
        ],
        "languageCode": "es"
    }

    response = requests.post(url, headers=headers, json=payload)
    if not response.ok:
        raise RuntimeError(f"Places API Nearby ({response.status_code}): {response.text}")
    return response.json().get("places", [])


def buscar_lugares_text_circular(lat, lon, query, api_key,
                                 radio_metros=1500, top_k=2):
    """Busca lugares por texto con sesgo circular (sin restricción dura).

    Usa el endpoint Places API (New) `searchText` con `locationBias.circle`,
    que prioriza los resultados dentro del círculo pero NO los limita
    estrictamente. Pensado para encontrar anclajes del casco urbano (plaza,
    ayuntamiento, iglesia) alrededor de una candidata en modo "ciudad
    pequeña".

    Args:
        lat: latitud del centro del círculo.
        lon: longitud del centro del círculo.
        query: texto de búsqueda (p. ej. "plaza").
        api_key: clave de Google Places API.
        radio_metros: radio del círculo de sesgo. Default 1500.
        top_k: número máximo de resultados a devolver. Default 2.

    Returns:
        Lista (recortada a `top_k`) de dicts con claves `place_id`,
        `nombre`, `latitud`, `longitud`.

    Raises:
        RuntimeError: si la llamada a la Places API falla.
    """
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.location",
    }

    payload = {
        "textQuery": query,
        "languageCode": "es",
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": radio_metros,
            }
        },
        "maxResultCount": top_k,
    }

    response = requests.post(url, headers=headers, json=payload)
    if not response.ok:
        raise RuntimeError(
            f"Places API searchText circular ({response.status_code}): "
            f"{response.text[:200]}"
        )

    places = response.json().get("places", [])[:top_k]
    return [
        {
            "place_id": p.get("id"),
            "nombre": (p.get("displayName") or {}).get("text"),
            "latitud": (p.get("location") or {}).get("latitude"),
            "longitud": (p.get("location") or {}).get("longitude"),
        }
        for p in places
    ]