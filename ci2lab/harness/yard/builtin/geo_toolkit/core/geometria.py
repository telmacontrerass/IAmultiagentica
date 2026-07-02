import math

try:  # lazy/optional: pure entrypoints run without it; network ones are gated
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore


def calcular_distancia_haversine(lat1, lon1, lat2, lon2):
    """Distancia en metros entre dos puntos lat/lon usando la fórmula de Haversine."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def calcular_distancia_andando(origen, destino, api_key):
    """Distancia andando (en metros) entre dos puntos vía Google Distance Matrix.

    Args:
        origen: cadena "lat,lon".
        destino: cadena "lat,lon".
        api_key: clave de Google Maps.

    Returns:
        Distancia en metros, o None si la API falla o no encuentra ruta.
    """
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origen,
        "destinations": destino,
        "mode": "walking",
        "language": "es",
        "key": api_key
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if data["status"] == "OK":
            elemento = data["rows"][0]["elements"][0]
            if elemento["status"] == "OK":
                return elemento["distance"]["value"]
    except Exception as e:
        print(f"Error en Distance Matrix: {e}")
    return None


def calcular_distancias_andando_batch(origen, destinos, api_key):
    """Calcula distancias andando desde un origen a múltiples destinos en una sola petición.

    Args:
        origen: str con "lat,lon" del origen.
        destinos: str con destinos separados por '|' ("lat1,lon1|lat2,lon2|...").
        api_key: clave de Google Maps.

    Returns:
        Lista de distancias en metros (None para elementos fallidos), o None si falla la petición.
    """
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origen,
        "destinations": destinos,
        "mode": "walking",
        "language": "es",
        "key": api_key
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if data["status"] == "OK":
            return [
                elem["distance"]["value"] if elem["status"] == "OK" else None
                for elem in data["rows"][0]["elements"]
            ]
    except Exception as e:
        print(f"Error en Distance Matrix (batch): {e}")
    return None


def calcular_rectangulos_perimetrales(lat_min, lon_min, lat_max, lon_max, margen_metros=700):
    """Calcula los 4 rectángulos perimetrales que rodean el rectángulo de búsqueda
    del usuario, con un margen dado en metros.

    Layout (sin solape entre bandas):
        - Extra 1 (arriba): banda horizontal sobre el rectángulo, ocupa todo el
          ancho incluyendo las esquinas superiores.
        - Extra 3 (abajo): banda horizontal bajo el rectángulo, ocupa todo el
          ancho incluyendo las esquinas inferiores.
        - Extra 2 (derecha): banda vertical a la derecha, sin esquinas.
        - Extra 4 (izquierda): banda vertical a la izquierda, sin esquinas.

    Returns:
        Lista de 4 dicts con claves lat_min, lon_min, lat_max, lon_max, nombre.
    """
    # Conversión metros → grados
    delta_lat = margen_metros / 111000.0
    lat_centro = (lat_min + lat_max) / 2
    delta_lon = margen_metros / (111000.0 * math.cos(math.radians(lat_centro)))

    return [
        {
            "nombre": "Extra 1 (arriba)",
            "lat_min": lat_max,
            "lon_min": lon_min - delta_lon,
            "lat_max": lat_max + delta_lat,
            "lon_max": lon_max + delta_lon,
        },
        {
            "nombre": "Extra 3 (abajo)",
            "lat_min": lat_min - delta_lat,
            "lon_min": lon_min - delta_lon,
            "lat_max": lat_min,
            "lon_max": lon_max + delta_lon,
        },
        {
            "nombre": "Extra 2 (derecha)",
            "lat_min": lat_min,
            "lon_min": lon_max,
            "lat_max": lat_max,
            "lon_max": lon_max + delta_lon,
        },
        {
            "nombre": "Extra 4 (izquierda)",
            "lat_min": lat_min,
            "lon_min": lon_min - delta_lon,
            "lat_max": lat_max,
            "lon_max": lon_min,
        },
    ]


def calcular_celdas_grid(lat_min, lon_min, lat_max, lon_max, lado_metros=1000):
    """Divide el rectángulo de búsqueda en una rejilla de celdas cuadradas
    de lado `lado_metros`. Las "puntas" sobrantes en los bordes derecho y
    superior se integran en la última columna/fila respectivamente, generando
    rectángulos de hasta 2*lado-eps.

    Returns:
        Lista de dicts con claves lat_min, lon_min, lat_max, lon_max.
    """
    # Conversión metros → grados (latitud media para corregir longitud)
    lat_centro = (lat_min + lat_max) / 2
    delta_lat = lado_metros / 111000.0
    delta_lon = lado_metros / (111000.0 * math.cos(math.radians(lat_centro)))

    # Número de celdas "completas" en cada dimensión
    n_lat = max(1, int((lat_max - lat_min) / delta_lat))
    n_lon = max(1, int((lon_max - lon_min) / delta_lon))

    celdas = []
    for i in range(n_lat):
        # Bordes verticales de la fila i
        lat_low = lat_min + i * delta_lat
        # Última fila absorbe el sobrante hasta lat_max
        lat_high = lat_max if i == n_lat - 1 else lat_low + delta_lat

        for j in range(n_lon):
            lon_low = lon_min + j * delta_lon
            # Última columna absorbe el sobrante hasta lon_max
            lon_high = lon_max if j == n_lon - 1 else lon_low + delta_lon

            celdas.append({
                "lat_min": lat_low,
                "lon_min": lon_low,
                "lat_max": lat_high,
                "lon_max": lon_high,
            })
    return celdas
