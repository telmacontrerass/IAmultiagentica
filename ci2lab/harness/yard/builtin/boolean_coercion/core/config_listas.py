import unicodedata


def _normalizar(texto):
    """Quita diacríticos y pasa a minúsculas; para comparar 'sí'=='si' etc."""
    if texto is None:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.casefold().strip()


def _a_bool(valor):
    """Interpreta una celda como booleano (sí/no/True/False/1/0/vacío).

    Devuelve True/False para valores reconocidos; None si no es interpretable
    (el caller decide tratarlo como False y añadir warning).
    """
    if valor is None:
        return False
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        if valor == 0:
            return False
        if valor == 1:
            return True
        return None
    if isinstance(valor, str):
        norm = _normalizar(valor)
        if norm == "":
            return False
        if norm in ("si", "true"):
            return True
        if norm in ("no", "false"):
            return False
        return None
    return None