# ... [omitido: docstring de modulo con terminos de dominio del proyecto origen] ...
import base64
import json
import os
import re

try:  # lazy/optional: pure entrypoints run without it; network ones are gated
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore
# ... [omitido: CATEGORIAS_VALIDAS, constante de categorias de dominio del proyecto origen] ...
def descargar_imagen_streetview(direccion, ruta_destino, api_key, fov=80):
    """Descarga la imagen de Street View para una dirección.

    Returns:
        True si hay panorama disponible y se descargó, False en caso contrario.
    """
    meta = requests.get(
        "https://maps.googleapis.com/maps/api/streetview/metadata",
        params={"location": direccion, "key": api_key},
        timeout=10,
    ).json()
    if meta.get("status") != "OK":
        return False

    response = requests.get(
        "https://maps.googleapis.com/maps/api/streetview",
        params={
            "size": "640x640",
            "location": direccion,
            "fov": fov,
            "source": "outdoor",
            "key": api_key,
        },
        timeout=15,
    )
    if not response.ok:
        return False
    with open(ruta_destino, "wb") as f:
        f.write(response.content)
    return True


def _encode_image(ruta):
    with open(ruta, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _parsear_respuesta_llm(texto):
    """Extrae el JSON del output del LLM (puede venir envuelto en ```json...```)."""
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip(),
                    flags=re.MULTILINE)
    return json.loads(limpio)


def estimar_anchura_con_llm(ruta_imagen, nombre_optica, openai_api_key,
                             modelo="gpt-4.1"):
    """Pide al modelo multimodal una clasificación de la anchura de fachada.

    Returns:
        dict con keys "anchura" (una de las 5 categorías) y "motivo" (texto
        breve, máx. ~20 palabras).

    Raises:
        Cualquier excepción del SDK/HTTP se propaga; el orquestador la captura
        para no romper el pipeline.
    """
    from openai import OpenAI  # import lazy: evita coste de import si no se usa

    base64_image = _encode_image(ruta_imagen)
    solicitud = (
        # ... [omitido: prompt de negocio del proyecto origen] ...
    )

    client = OpenAI(api_key=openai_api_key)
    response = client.responses.create(
        model=modelo,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": solicitud},
                {"type": "input_image",
                 "image_url": f"data:image/jpeg;base64,{base64_image}"},
            ],
        }],
    )

    parsed = _parsear_respuesta_llm(response.output_text)
    return {
        # ... [omitido: mapeo de keys de dominio del proyecto origen] ...
    }


def estimar_fachada(candidata, dir_imagenes, places_api_key, openai_api_key):
    """Descarga la imagen de Street View y estima la anchura de fachada.

    Returns:
        dict con keys "anchura", "motivo", "ruta_imagen". `ruta_imagen` puede
        ser None si Street View no tenía panorama disponible.
    """
    nombre_archivo = f"O_{candidata['id']}.jpg"
    ruta_imagen = os.path.join(dir_imagenes, nombre_archivo)

    descargada = descargar_imagen_streetview(
        candidata["direccion"], ruta_imagen, places_api_key
    )
    if not descargada:
        return {
            # ... [omitido: payload de resultado especifico del dominio origen] ...
        }

    try:
        resultado = estimar_anchura_con_llm(
            ruta_imagen, candidata["nombre"], openai_api_key
        )
    except Exception as e:
        return {
            # ... [omitido: payload de error especifico del dominio origen] ...
        }

    return {**resultado, "ruta_imagen": ruta_imagen}
