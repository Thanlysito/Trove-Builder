"""
Busca en las plantillas textos en español que NO estan marcados para
traducir con {% translate %} / {% blocktranslate %}.

Lo usa el test LanguageTests.test_all_template_text_is_translatable: si
escribes <h2>Nueva sección</h2> sin {% translate %}, el test falla y te
dice el archivo, la linea y el texto.
"""
import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Plantillas que no se revisan: how_it_works.html es la version en español de
# una pagina que tiene su propia version en ingles (how_it_works_en.html), y
# sitemap.xml no tiene texto para personas.
SKIP = {"builder/how_it_works.html", "builder/sitemap.xml"}

# Textos que se muestran igual en los dos idiomas.
ALLOWED = {"Español", "ES", "EN"}

SPANISH = re.compile(
    r"[áéíóúñ¿¡]|\b(de|del|la|las|el|los|para|con|por|una|uno|tu|tus|sin|que|"
    r"es|son|mi|mis|al|más|ya|aquí|esta|este|todavía|ninguna|ninguno|guardar|"
    r"crear|editar|eliminar|volver|buscar|nueva|nuevo)\b",
    re.IGNORECASE,
)
ATTRS = re.compile(r'\b(title|placeholder|alt|aria-label)="([^"]*)"')


def _blank(match):
    """Reemplaza el bloque por espacios, conservando los saltos de linea."""
    return re.sub(r"[^\n]", " ", match.group(0))


def untranslated_texts():
    """Lista de (plantilla, linea, texto) con español sin marcar."""
    problems = []
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        name = path.relative_to(TEMPLATES_DIR).as_posix()
        if name in SKIP:
            continue
        src = path.read_text(encoding="utf-8")
        for pattern in (
            r"\{#.*?#\}",
            r"\{% comment %\}.*?\{% endcomment %\}",
            r"<script\b.*?</script>",
            r"<style\b.*?</style>",
            r"\{% blocktranslate.*?\{% endblocktranslate %\}",
            r"\{% translate .*?%\}",
            r"\{%.*?%\}",
            r"\{\{.*?\}\}",
        ):
            src = re.sub(pattern, _blank, src, flags=re.S)

        for lineno, line in enumerate(src.split("\n"), start=1):
            candidates = [m.group(2) for m in ATTRS.finditer(line)]
            candidates += re.sub(r"<[^>]*>", "\n", line).split("\n")
            for text in candidates:
                text = text.strip()
                if text and text not in ALLOWED and SPANISH.search(text):
                    problems.append((name, lineno, text))
    return problems
