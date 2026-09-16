from django import template

register = template.Library()


@register.filter
def irrelevant_stat_for(slot, game_class):
    """Uso en template: {{ equipment_slot|irrelevant_stat_for:some_game_class }}"""
    if slot is None or game_class is None:
        return None
    return slot.irrelevant_stat_for(game_class)


@register.filter
def equip_damage_mismatch(build_equipment, game_class):
    """
    Revisa los stats que el usuario REALMENTE eligio para esta pieza de
    equipo (build_equipment.chosen_stats) y devuelve 'Physical Damage' o
    'Magic Damage' si eligio el que no combina con la clase. A diferencia
    de irrelevant_stat_for (que solo mira si el slot PODRIA rolear ese stat
    en teoria), esto solo avisa si de verdad se eligio.
    Uso: {{ build_equipment|equip_damage_mismatch:build.primary_class }}
    """
    if not build_equipment or game_class is None:
        return None
    chosen = build_equipment.chosen_stats or []
    wrong = "Magic Damage" if game_class.damage_type == "physical" else "Physical Damage"
    return wrong if wrong in chosen else None


@register.filter
def dict_get(d, key):
    """Busca `key` en un diccionario dentro del template. Uso: {{ mydict|dict_get:key }}"""
    if not d:
        return None
    return d.get(str(key))


@register.filter
def humanize_key(key):
    """'damage_formula' -> 'Damage formula'. Uso: {{ key|humanize_key }}"""
    if not key:
        return key
    text = key.replace("_", " ").replace("-", " ")
    return text[:1].upper() + text[1:]


@register.filter
def damage_stat_for(gem):
    """
    Devuelve 'Physical Damage' o 'Magic Damage' si la gema es Fierce/Arcane
    (ese stat viene garantizado en una gema menor de ese tipo), o None si no aplica.
    Uso: {{ gem|damage_stat_for }}
    """
    variant = getattr(gem, "damage_variant", None)
    if variant == "fierce":
        return "Physical Damage"
    if variant == "arcane":
        return "Magic Damage"
    return None


@register.filter
def gem_damage_mismatch(gem, game_class):
    """
    Si la gema es Fierce/Arcane y su tipo de daño NO combina con el
    damage_type de la clase, devuelve el nombre del stat desperdiciado
    (ej. 'Magic Damage'). Devuelve None si combina o si la gema es
    Empowered/Class (universal, sin variante de daño).
    Uso: {{ gem|gem_damage_mismatch:build.primary_class }}
    """
    if not gem or game_class is None:
        return None
    guaranteed = damage_stat_for(gem)
    if not guaranteed:
        return None
    expected = "Physical Damage" if game_class.damage_type == "physical" else "Magic Damage"
    return guaranteed if guaranteed != expected else None


@register.filter
def gem_tooltip_stats(gem):
    """
    Resumen corto de que stats puede tener esta gema, para el tooltip.
    Gemas menores: lista de rollable_stats. Gemas empoderadas/class: las
    primeras claves de su stat_scaling (formula de dano, cooldown, etc).
    Uso: {{ gem|gem_tooltip_stats }}
    """
    if gem is None or not gem.stat_scaling:
        return ""
    if "rollable_stats" in gem.stat_scaling:
        return ", ".join(gem.stat_scaling["rollable_stats"])
    parts = []
    for key, value in list(gem.stat_scaling.items())[:3]:
        parts.append(f"{humanize_key(key)}: {value}")
    return " · ".join(parts)


@register.filter
def subclass_bonus_damage_type(subclass):
    """
    'physical' o 'magic' si el BONO de la subclase (bonus_stat) es
    literalmente Physical Damage o Magic Damage; cadena vacia si el bono es
    otra cosa (Critical Damage, Jump, Stability, etc. -- esos sirven para
    cualquier clase sin importar su damage_type).
    IMPORTANTE: esto no es lo mismo que el damage_type de la clase DUEÑA de
    la subclase -- por ejemplo la subclase de Shadow Hunter (clase Physical)
    da un bono de Magic Damage, asi que hay que revisar el bono en si, no la
    clase de origen.
    Uso: {{ subclass|subclass_bonus_damage_type }}
    """
    stat = getattr(subclass, "bonus_stat", "")
    if stat == "Physical Damage":
        return "physical"
    if stat == "Magic Damage":
        return "magic"
    return ""


# Elementos que tienen icono real (imagen generada) disponible en
# builder/static/builder/img/gems/. Si el elemento de la gema no esta en
# esta lista, el template usa el rombo de CSS como respaldo.
GEM_ICON_ELEMENTS = {"water", "air", "fire", "cosmic"}

# Class Gems con icono individual propio (imagen generada) en
# builder/static/builder/img/class-gems/<slug>.png
CLASS_GEM_ICON_SLUGS = {
    "shadow-blitz-gem", "bawk-bomb", "aegis-assault", "scoop-n-gloop",
    "heuristic-hackstar", "faerocious-facsimile", "overcharged", "spirit-squire",
    "dragonling-ember", "leafy-lasher-overgrowth", "blizzard-barrage",
    "twin-cannon-command", "banshees-communion", "lunar-echo",
}


@register.filter
def gem_icon_path(gem, size):
    """
    Ruta estatica al icono real de la gema: primero revisa si es una Class
    Gem con icono individual propio (siempre el mismo icono, sin importar
    'size', porque las Class Gems solo van en slots grandes); si no, usa el
    icono generico por elemento (Water/Air/Fire/Cosmic) segun tamano ('big'
    o 'small'). Devuelve None si no hay icono (usa el rombo de CSS de
    respaldo). Uso: {{ gem|gem_icon_path:"big" }}
    """
    slug = getattr(gem, "slug", None)
    if slug in CLASS_GEM_ICON_SLUGS:
        return f"builder/img/class-gems/{slug}.png"

    element = getattr(gem, "element", None)
    if not element or element not in GEM_ICON_ELEMENTS:
        return None
    return f"builder/img/gems/gem-{element}-{size}.png"


# Tipos de equipo con icono real disponible en builder/static/builder/img/equipment/.
EQUIPMENT_ICON_TYPES = {"weapon", "hat", "face", "ring"}


@register.filter
def equipment_icon_path(equipment_slot):
    """
    Ruta estatica al icono real de la pieza de equipo segun su slot_type,
    o None si todavia no hay icono para ese tipo. Uso:
    {{ build_equipment.slot|equipment_icon_path }}
    """
    slot_type = getattr(equipment_slot, "slot_type", None)
    if not slot_type or slot_type not in EQUIPMENT_ICON_TYPES:
        return None
    return f"builder/img/equipment/equip-{slot_type}.png"
