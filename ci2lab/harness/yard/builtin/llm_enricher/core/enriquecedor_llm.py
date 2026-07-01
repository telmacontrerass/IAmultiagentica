import json
import logging
import os
import re
import unicodedata


_MODELO_DEFAULT = "gpt-4.1"
_TIMEOUT_SEGUNDOS = 30

RUTA_INSTRUCCIONES = "instrucciones-especificas.txt"
RUTA_INSTRUCCIONES_FILTRO = "instrucciones_filtro_inteligente.txt"

# Caché privada indexada por nombre normalizado (sin acentos, casefold).
# Persiste entre llamadas dentro del mismo proceso para evitar repetir
# clasificaciones idénticas.
_CACHE = {}

# Caché separada para el clasificador "¿es óptica?". Mantenida aparte para
# evitar colisiones de claves con el cache de promociones de tier.
_CACHE_OPTICAS = {}

_TIERS_VALIDOS = {1, 2, 3}

_logger = logging.getLogger(__name__)


# ── JSON Schema estricto para la salida del LLM ───────────────────────
# ... [omitido: JSON Schema con campos de dominio del proyecto origen] ...


_SYSTEM_PROMPT = (
    # ... [omitido: prompt de negocio del proyecto origen] ...
)


def limpiar_cache():
    """Vacía las cachés internas. Útil para tests que no quieran reuso entre
    casos."""
    _CACHE.clear()
    _CACHE_OPTICAS.clear()


def _normalizar(texto):
    """Devuelve `texto` en minúsculas y sin acentos para comparar nombres."""
    if not texto:
        return ""
    descompuesto = unicodedata.normalize("NFD", texto)
    sin_acentos = "".join(c for c in descompuesto
                           if unicodedata.category(c) != "Mn")
    return sin_acentos.casefold().strip()


def _parsear_output(texto):
    """Extrae el JSON del output del LLM (puede venir envuelto en ```json...```).

    Devuelve dict o lanza ValueError si el JSON no es parseable.
    """
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip(),
                    flags=re.MULTILINE)
    return json.loads(limpio)


def _cargar_instrucciones_especificas(base_dir, nombre_fichero):
    """Lee el fichero de instrucciones del analista y devuelve su texto útil.

    Descarta líneas vacías y comentarios (que empiezan por `#`) para no
    contaminar el prompt del LLM. Devuelve cadena vacía si no hay base_dir,
    el fichero no existe o no contiene ninguna línea útil.

    Args:
        base_dir: directorio base de la app. Si es None, devuelve "".
        nombre_fichero: nombre del fichero a leer dentro de `base_dir`
            (p. ej. RUTA_INSTRUCCIONES o RUTA_INSTRUCCIONES_FILTRO).

    Returns:
        str con las líneas útiles unidas por "\\n", o "" si no hay
        contenido útil.
    """
    if base_dir is None:
        return ""
    ruta = os.path.join(base_dir, nombre_fichero)
    if not os.path.exists(ruta):
        return ""
    with open(ruta, "r", encoding="utf-8") as f:
        lineas_utiles = []
        for linea in f:
            stripped = linea.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lineas_utiles.append(stripped)
    return "\n".join(lineas_utiles)


def _componer_prompt(base_prompt, base_dir, nombre_fichero):
    """Devuelve `base_prompt` opcionalmente ampliado con las instrucciones
    específicas del analista si existen y no están vacías tras limpiar
    comentarios.

    Args:
        base_prompt: system prompt base sobre el que se ancla la ampliación.
        base_dir: directorio base de la app, usado para localizar el fichero
            de instrucciones específicas. Si es None, se devuelve
            `base_prompt` sin cambios.
        nombre_fichero: nombre del fichero de instrucciones (p. ej.
            RUTA_INSTRUCCIONES para promoción de tier o
            RUTA_INSTRUCCIONES_FILTRO para filtro inteligente).

    Returns:
        str: `base_prompt` o `base_prompt` + bloque de instrucciones.
    """
    extra = _cargar_instrucciones_especificas(base_dir, nombre_fichero)
    if not extra:
        return base_prompt
    return (
        f"{base_prompt}\n\n"
        # ... [omitido: texto de negocio que enmarca las instrucciones del analista] ...
        f"{extra}"
    )


def _llamar_llm(items_pendientes, openai_api_key, modelo, base_dir):
    """Llama a OpenAI Responses API con la lista de pendientes.

    Args:
        items_pendientes: lista de dicts {"nombre", "direccion"} a clasificar.
        openai_api_key: clave de OpenAI.
        modelo: identificador del modelo.
        base_dir: directorio base de la app, usado para localizar el fichero
            de instrucciones específicas del analista. Si es None, no se
            cargan instrucciones extra.

    Returns:
        dict deserializado con la clave `promociones`.

    Raises:
        Cualquier excepción del SDK/HTTP/JSON. El llamador la captura.
    """
    from openai import OpenAI  # import lazy: evita coste de import si no se usa

    lineas = [
        f"[{i}] {item['nombre']} | {item['direccion']}"
        for i, item in enumerate(items_pendientes)
    ]
    user_prompt = (
        # ... [omitido: user prompt de negocio del proyecto origen] ...
        + "\n".join(lineas)
    )

    system_prompt = _componer_prompt(_SYSTEM_PROMPT, base_dir, RUTA_INSTRUCCIONES)

    client = OpenAI(api_key=openai_api_key, timeout=_TIMEOUT_SEGUNDOS)
    response = client.responses.create(
        model=modelo,
        input=[
            {"role": "system",
             "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user",
             "content": [{"type": "input_text", "text": user_prompt}]},
        ],
        text={"format": _SCHEMA_PROMOCIONES},
    )

    return _parsear_output(response.output_text)


def promover_tier4(negocios_t4, openai_api_key, modelo=_MODELO_DEFAULT,
                   base_dir=None):
    # ... [omitido: docstring con detalle de dominio del proyecto origen] ...
    if not openai_api_key:
        _logger.info(
            "Sin OPENAI_API_KEY: se omite la promoción LLM de Tier 4."
        )
        return {}
    if not negocios_t4:
        return {}

    # Resolver con caché. Los items ya cacheados no se mandan al SDK.
    promociones = {}
    items_pendientes = []
    for item in negocios_t4:
        nombre = item.get("nombre") or ""
        direccion = item.get("direccion") or ""
        if not nombre:
            continue
        clave = _normalizar(nombre)
        if clave in _CACHE:
            cacheado = _CACHE[clave]
            if cacheado is not None:
                # Conservamos el nombre original tal y como lo envió el
                # llamador actual (puede diferir en mayúsculas/acentos).
                promociones[nombre] = cacheado
            continue
        items_pendientes.append({"nombre": nombre, "direccion": direccion})

    if not items_pendientes:
        return promociones

    # Set normalizado de nombres realmente enviados (anti-alucinación).
    nombres_enviados = {
        _normalizar(it["nombre"]): it["nombre"] for it in items_pendientes
    }

    try:
        respuesta = _llamar_llm(items_pendientes, openai_api_key, modelo,
                                base_dir)
    except Exception as e:
        _logger.info(
            "Llamada a OpenAI falló (%s); se omite la promoción LLM.",
            type(e).__name__,
        )
        return {}

    items = (respuesta or {}).get("promociones")
    if not isinstance(items, list):
        _logger.info("Respuesta LLM sin clave `promociones`; se omite.")
        return {}

    # Post-validación: descartamos alucinaciones, tiers fuera de rango y
    # consolidamos duplicados (gana el tier más alto = número menor).
    consolidado = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        nombre = item.get("nombre")
        tier_n = item.get("tier_propuesto")
        razon = item.get("razon", "")
        marca = item.get("marca_reconocida", "")

        if not nombre or not isinstance(tier_n, int) or isinstance(tier_n, bool):
            continue
        if tier_n not in _TIERS_VALIDOS:
            continue

        clave_norm = _normalizar(nombre)
        if clave_norm not in nombres_enviados:
            # Alucinación: el LLM devolvió un nombre que no estaba en la
            # lista de entrada.
            _logger.info(
                "Descartada promoción alucinada: %r no estaba en la lista.",
                nombre,
            )
            continue

        nombre_original = nombres_enviados[clave_norm]
        existente = consolidado.get(clave_norm)
        if existente is None or tier_n < existente["tier_n"]:
            consolidado[clave_norm] = {
                "nombre_original": nombre_original,
                "tier_n": tier_n,
                "razon": razon,
                "marca_reconocida": marca,
            }

    # Volcamos al diccionario de salida y a la caché.
    for clave_norm, datos in consolidado.items():
        entry = {
            "tier": f"Tier {datos['tier_n']}",
            "razon": datos["razon"],
            "marca_reconocida": datos["marca_reconocida"],
        }
        promociones[datos["nombre_original"]] = entry
        _CACHE[clave_norm] = entry

    # Items pendientes que NO fueron promovidos también se cachean (con
    # valor `None`) para no preguntarlos otra vez en la misma sesión.
    for clave_norm in nombres_enviados:
        if clave_norm not in consolidado and clave_norm not in _CACHE:
            _CACHE[clave_norm] = None

    return promociones