"""
Traduccion de los DATOS DEL JUEGO guardados en la base (descripciones de
clases, gemas, subclases, Efectos Ocultos, bonos, etc.).

Esos textos se escriben en español en seed_trove_data. Su traduccion al
ingles vive en locale/en/game_data.json ({"texto en español": "English"}),
que genera automaticamente tools/auto_traducir.py en GitHub Actions.

En las plantillas se usa el filtro {{ texto|tr_data }}: devuelve la version
en ingles cuando la pagina esta en ingles y existe traduccion; si no, el
texto original.
"""
import json
from pathlib import Path

from django.conf import settings
from django.utils.translation import get_language

GAME_DATA_PATH = Path(settings.BASE_DIR) / "locale" / "en" / "game_data.json"

_cache = {"mtime": None, "data": {}}


def _mapping():
    try:
        mtime = GAME_DATA_PATH.stat().st_mtime
    except FileNotFoundError:
        return {}
    if _cache["mtime"] != mtime:
        with open(GAME_DATA_PATH, encoding="utf-8") as fh:
            _cache["data"] = json.load(fh)
        _cache["mtime"] = mtime
    return _cache["data"]


def tr(value):
    """Traduce un texto (o cada texto de una lista) si la pagina esta en ingles."""
    if (get_language() or "es")[:2] != "en":
        return value
    if isinstance(value, str):
        return _mapping().get(value, value)
    if isinstance(value, (list, tuple)):
        return [tr(v) for v in value]
    return value


def collect_texts():
    """Todos los textos de datos del juego que se muestran en el sitio."""
    from .models import Dragon, EquipmentSlot, GameClass, Gem, RingHiddenEffect, Subclass

    texts = set()

    def add(value):
        if isinstance(value, str) and value.strip() and any(c.isalpha() for c in value):
            texts.add(value)
        elif isinstance(value, (list, tuple)):
            for v in value:
                add(v)

    for c in GameClass.objects.all():
        add(c.description)
    for s in Subclass.objects.all():
        add(s.passive_description)
        add(s.bonus_range)
        for row in s.tier_progression or []:
            add(row.get("effect"))
        for row in s.level_bonus_progression or []:
            add(row.get("bonus"))
    for g in Gem.objects.all():
        add(g.description)
        for key, value in (g.stat_scaling or {}).items():
            if key != "rollable_stats":
                add(value)
    for e in EquipmentSlot.objects.all():
        add(e.fixed_stats)
        add(e.notes)
    for d in Dragon.objects.all():
        add(d.description)
        add(d.power_rank_bonus)
    for r in RingHiddenEffect.objects.all():
        add(r.description)
    return texts
