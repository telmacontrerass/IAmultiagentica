## Formato de herramientas (modo texto)

Para usar una herramienta, escribe un bloque de código con el nombre de la herramienta como etiqueta. El bloque se ejecutará automáticamente y verás el resultado.

Ejemplos:

```ls
.
```

```read_file
src/main.py
```

```bash
python -m pytest tests/ -q
```

```grep
{"pattern": "def main", "glob": "*.py"}
```

Herramientas disponibles: bash, read_file, ls, grep, glob, write_file, edit_file.

No uses ```python o ```sh para ejecutar acciones — solo las etiquetas de herramienta anteriores ejecutan código.
