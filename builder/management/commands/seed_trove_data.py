from django.core.management.base import BaseCommand
from django.utils.text import slugify
from builder.models import GameClass, Gem, EquipmentSlot, Subclass, Dragon, RingHiddenEffect


# Las 18 clases jugables de Trove (nombre, arma principal, rol sugerido, tipo de daño, descripcion corta)
# Fuente: trovesaurus.com/classes
# Tipo de daño (Physical/Magic) confirmado por trove.fandom.com/wiki/Class y guias de
# la comunidad: Melee/Bow/Spear/Fist = Physical; Pistol/Staff = Magic.
CLASSES = [
    ("Bard", "Fist", "support", "physical",
     "Embellece con su música, asistiendo a sus aliados y debilitando enemigos."),
    ("Boomeranger", "Bow/Melee", "dps", "physical",
     "Hábil con arco y espada; usa bumeranes explosivos y aturdidores."),
    ("Candy Barbarian", "Melee", "dps", "physical",
     "Guerrero cuerpo a cuerpo que invoca thundercones desde su deidad de dulces."),
    ("Chloromancer", "Staff", "healer", "magic",
     "Lanzador cuyo ataque básico cura aliados y daña enemigos mientras hace crecer plantas."),
    ("Dino Tamer", "Pistol", "dps", "magic",
     "Ataca a distancia con redes, dardos tranquilizantes y aliados dinosaurios."),
    ("Dracolyte", "Staff", "dps", "magic",
     "Mago de fuego que invoca dragones; su definitiva lo transforma en dragón."),
    ("Fae Trickster", "Staff", "dps", "magic",
     "Especialista en evadir daño mientras inflige mucho, usando ilusiones (blink)."),
    ("Gunslinger", "Pistol", "dps", "magic",
     "Luchador a distancia con doble pistola; definitiva dispara ráfagas de energía."),
    ("Ice Sage", "Staff", "dps", "magic",
     "Hechicero de hielo que congela enemigos e invoca icebergs mortales."),
    ("Knight", "Melee", "tank", "physical",
     "Luchador acorazado y resistente; su definitiva restaura vida y reduce daño recibido."),
    ("Lunar Lancer", "Spear", "dps", "physical",
     "Acumula poder lunar en combate hasta entrar en 'Modo Lunático'."),
    ("Neon Ninja", "Melee", "dps", "physical",
     "Ágil y letal, ataca desde el sigilo con shurikens y técnica final."),
    ("Pirate Captain", "Pistol", "dps", "magic",
     "Usa explosivos y doblones para potenciar el cañón de su primer oficial."),
    ("Revenant", "Spear", "tank", "physical",
     "Espíritu protector con un Spirit Wraith que lo salva de la muerte."),
    ("Shadow Hunter", "Bow", "dps", "physical",
     "Destructor del mal a distancia; usa flechas cargadas y trampas solares."),
    ("Solarion", "Bow", "dps", "physical",
     "Sirviente de la Diosa Sol con un Fénix; se especializa en daño en el tiempo (DoT)."),
    ("Tomb Raiser", "Staff", "support", "magic",
     "Invoca y cura minions no-muertos mientras daña con un rayo perforante."),
    ("Vanguardian", "Fist", "tank", "physical",
     "Empodera aliados y aniquila enemigos cerca o lejos, con opciones híbridas tanque/daño."),
]

# Gemas reales del sistema de Trove.
# Lesser gems: Water / Air / Fire (3 de cada elemento, stats genéricos que se pueden rolear).
# Empowered gems: una por elemento + Cosmic, con efectos únicos (solo 1 equipable a la vez).
# Fuente: trovesaurus.com/gems, trove.fandom.com/wiki/Gem, "Gems! How do they work?!"
# IMPORTANTE (confirmado en trove.fandom.com/wiki/Gem): las gemas MENORES de rareza
# Shadow/Radiant/Stellar se dividen en Fierce (solo Physical Damage, nunca Magic) y
# Arcane (solo Magic Damage, nunca Physical). No existe una gema menor "universal"
# a esas rarezas. Las Empowered y Class Gems si son universales (cualquier clase/daño).
LESSER_GEM_STATS_UNIVERSAL = [
    "Critical Hit", "Critical Damage", "Max Health", "Max Health %",
    "Health Regen", "Attack Speed", "Movement Speed", "Energy Regen", "Light",
]
ELEMENTS = ["Water", "Air", "Fire", "Cosmic"]

GEMS = [
    # (name, gem_type, element, damage_variant, description, max_rank, stat_scaling_override)
]

# Gemas menores: 4 elementos x 2 variantes de daño (Fierce/Arcane) = 8 gemas.
for _el in ELEMENTS:
    GEMS.append((
        f"{_el} Gem (Fierce)", "utility", _el.lower(), "fierce",
        f"Gema menor de elemento {_el}, variante Fierce: solo puede rolear Physical "
        f"Damage (nunca Magic Damage), además de hasta 2 stats más entre "
        f"{', '.join(LESSER_GEM_STATS_UNIVERSAL[:4])}, etc. Sirve para clases Physical.",
        30, None,
    ))
    GEMS.append((
        f"{_el} Gem (Arcane)", "utility", _el.lower(), "arcane",
        f"Gema menor de elemento {_el}, variante Arcane: solo puede rolear Magic "
        f"Damage (nunca Physical Damage), además de hasta 2 stats más entre "
        f"{', '.join(LESSER_GEM_STATS_UNIVERSAL[:4])}, etc. Sirve para clases Magic.",
        30, None,
    ))

# Empowered gems: universales (cualquier clase), pero SOLO se puede tener una
# equipada por slot elemental a la vez. Las 8 abilities "generales" pueden salir
# como gema Water, Air O Fire (al azar, nunca Cosmic) -- confirmado en
# trove.fandom.com/wiki/Empowered_Gem: "The first 8 abilities can appear in
# Water, Air and Fire elemental gems. The last 4 abilities can only appear in
# Cosmic gems." Por eso se generan 3 versiones (una por elemento) de cada una.
# Fuente de las estadisticas: PDFs "Empowered Gem Abilities" y "Cosmic Empowered
# Gems" (compilados por ZIPPYZENPIN), verificadas por el usuario.
GENERAL_EMPOWERED_ABILITIES = [
    ("Explosive Epilogue", "offense",
     "Al matar a un enemigo, este explota y causa daño en área a los enemigos "
     "cercanos, usando el tipo de daño de la clase (Physical o Magic Damage).",
     30,
     {"activation": "Al matar a un enemigo", "cooldown": "15s",
      "damage_formula": "50 + (4.5 × Physical/Magic Damage)",
      "effect": "Daño en área alrededor del enemigo derrotado"}),
    ("Cubic Curtain", "defense",
     "Tras 5 segundos sin recibir daño, genera un escudo que absorbe por completo "
     "el siguiente ataque y aturde al atacante que lo destruye.",
     30,
     {"activation": "5s sin recibir daño", "absorbs": "1 ataque completo",
      "stun_duration": "1s", "cooldown": "se regenera tras 5s sin recibir daño de nuevo"}),
    ("Mired Mojo", "utility",
     "Al recibir daño, probabilidad de generar 5 proyectiles alrededor del jugador "
     "que dañan y ralentizan temporalmente a los enemigos que alcanzan.",
     30,
     {"activation_chance": "33% al recibir daño", "projectiles": 5,
      "slow_duration": "2s", "damage_formula": "10 + (1.5 × Physical/Magic Damage)",
      "hits_per_projectile": 2, "cooldown": "5s"}),
    ("Pyrodisc", "offense",
     "Al matar a un enemigo, probabilidad de generar un disco de fuego centrado en "
     "el jugador que daña repetidamente a los enemigos cercanos y aumenta su "
     "Movement Speed mientras está activo.",
     30,
     {"activation_chance": "20% tras matar", "duration": "10s", "cooldown": "25s",
      "damage_formula": "550 + (2.75 × Physical/Magic Damage)",
      "hit_frequency": "1.5 impactos/s", "movement_speed_bonus": "+30"}),
    ("Spirit Surge", "offense",
     "Al recibir daño, probabilidad de generar 5 proyectiles que causan daño "
     "directo y aplican un Damage over Time acumulable basado en Maximum Health.",
     30,
     {"activation_chance": "20% al recibir daño", "projectiles": 5,
      "direct_damage_formula": "10 + (1.5 × Physical/Magic Damage)",
      "hits_per_projectile": 2, "dot_per_tick": "2.5% de Maximum Health",
      "dot_duration": "5s", "dot_frequency": "2 ticks/s",
      "dot_stacks": True, "dot_can_crit": False, "cooldown": "4s"}),
    ("Stinging Curse", "offense",
     "Los ataques normales tienen probabilidad de aplicar un Damage over Time "
     "acumulable (varias veces sobre el mismo objetivo) basado en el daño de la "
     "clase.",
     30,
     {"activation_chance": "20% en ataques normales",
      "dot_per_tick": "5% de Physical/Magic Damage", "dot_duration": "4s",
      "dot_frequency": "2 ticks/s", "dot_stacks": True,
      "max_stacks": "no determinado", "dot_can_crit": False}),
    ("Stunburst", "utility",
     "Al recibir daño, probabilidad de generar 5 proyectiles que dañan y aturden "
     "brevemente a los enemigos alcanzados.",
     30,
     {"activation_chance": "20% al recibir daño", "projectiles": 5,
      "stun_duration": "1s", "damage_formula": "10 + (1.5 × Physical/Magic Damage)",
      "hits_per_projectile": 2, "cooldown": "8s"}),
    ("Volatile Velocity", "utility",
     "Aumenta la velocidad de los proyectiles del personaje (no el Attack Speed), "
     "lo que en la mayoría de los casos también aumenta su alcance efectivo.",
     30,
     {"projectile_speed": "+50%", "affects_attack_speed": False,
      "note": "El Boomerang del Boomeranger recibe el aumento de velocidad pero "
              "no de distancia recorrida"}),
]

for _ability_name, _gem_type, _desc, _max_rank, _stats in GENERAL_EMPOWERED_ABILITIES:
    for _el in ("water", "air", "fire"):
        GEMS.append((
            f"{_ability_name} ({_el.capitalize()})", _gem_type, _el, "universal",
            _desc, _max_rank, _stats,
        ))

GEMS += [
    # Cosmic Empowered Gems (confirmadas como Cosmic en la fuente)
    ("Berserk Battler", "offense", "cosmic", "universal",
     "Dañar enemigos activa Frenzy (aumenta Attack Speed y Light temporalmente); "
     "seguir atacando durante Frenzy puede escalar a Berserk, con un bono aún mayor.",
     30,
     {"frenzy_duration": "3s", "frenzy_attack_speed": "+15%", "frenzy_light": "+250",
      "hits_to_berserk": 10, "berserk_duration": "2s",
      "berserk_attack_speed_bonus": "+25% (total +40%)",
      "berserk_light_bonus": "+500 (total +750)", "cooldown": "1s"}),
    ("Vampirian Vanquisher", "offense", "cosmic", "universal",
     "Los golpes críticos tienen probabilidad de aumentar temporalmente Movement "
     "Speed; mientras dura, los críticos también pueden activar robo de vida.",
     30,
     {"activation_chance": "65% en critical hit", "movement_speed_bonus": "+20",
      "movement_speed_duration": "5.5s",
      "lifesteal_chance_during_effect": "65%", "lifesteal": "5% del daño causado",
      "cooldown": "0.1s"}),
    ("Empyrean Barrier", "defense", "cosmic", "universal",
     "Genera periódicamente un escudo que reduce el daño recibido; al absorber "
     "suficiente daño, el escudo se rompe y explota dañando enemigos cercanos.",
     30,
     {"shield_cycle": "cada 15s (no es cooldown tradicional)",
      "damage_reduction": "10%", "shield_breaks_at": "25% de Maximum Health absorbido",
      "explosion_damage_formula": "50 + (25% de Maximum Health)",
      "shields_stack": False}),
    ("Flower Power", "offense", "cosmic", "universal",
     "Al recibir daño, probabilidad de generar una Blast Flower: un objeto "
     "independiente que drena vida a enemigos cercanos y explota al quedarse sin "
     "vida, dañando enemigos y bloques.",
     30,
     {"activation_chance": "20% al recibir daño",
      "flower_max_health": 10000, "flower_stability": 9999,
      "enemy_drain": "20% cada 0.5s a enemigos cercanos",
      "explosion_damage_formula": "550 + (2.75 × Physical/Magic Damage)",
      "explosion_hits_blocks": True, "cooldown": "12s"}),
]

# Class Gems: gemas empoderadas exclusivas de una clase, obtenidas en Shores of the
# Everdark con una Class Gem Key. Modifican una habilidad especifica de esa clase.
# name, clase (debe coincidir con un nombre en CLASSES), descripcion del efecto.
# Fuente: trovesaurus.com/page=1336 (Class Gem Abilities) y trove.fandom.com/wiki/Class_Gem
# Reglas reales de stats por slot de equipo (Weapon, Hat, Face, Ring).
# No son items especificos (hay miles de skins cosmeticas), son las plantillas
# de que stats puede rolear cada slot en cada posicion.
# Fuente: trovesaurus.com/rolls (Equipment Stat Rolls, actualizado 14/06/2024)
EQUIPMENT_SLOTS = [
    # (slot_type, tier, fixed_stats, rollable_stats_by_position, notes)
    ("weapon", "non_crystal",
     ["Physical Damage o Magic Damage (segun damage_type de la clase)"],
     {
         "2_4": ["Attack Speed", "Movement Speed", "Energy Regen", "Max Health", "Critical Damage"],
         "3": ["Critical Hit", "Stability", "Health Regen", "Jump"],
     },
     "El stat 1 depende del damage_type de la clase que use el arma. Las "
     "posiciones 2 y 4 comparten el mismo pool (no se repiten)."),
    ("weapon", "crystal",
     ["Physical Damage o Magic Damage (segun damage_type de la clase)", "Light"],
     {
         "3_5": ["Attack Speed", "Critical Damage", "Energy Regen", "Movement Speed", "Max Health"],
         "4": ["Critical Hit", "Magic Find", "Jump", "Stability", "Health Regen"],
     },
     "Crystal agrega Light fijo en la posicion 2. Las posiciones 3 y 5 "
     "comparten pool."),
    ("hat", "non_crystal",
     ["Max Health"],
     {
         "2_4": ["Attack Speed", "Health Regen", "Movement Speed", "Critical Damage"],
         "3": ["Lasermancy", "Jump", "Max Health %", "Stability"],
     },
     "El stat 1 siempre es Max Health en Hats y Faces. Magic Find NO puede "
     "salir en equipo No-Crystal (exclusivo de Crystal)."),
    ("hat", "crystal",
     ["Max Health", "Light"],
     {
         "3_5": ["Attack Speed", "Critical Damage", "Health Regen", "Movement Speed"],
         "4": ["Jump", "Lasermancy", "Magic Find", "Max Health %", "Stability"],
     },
     "Crystal agrega Light fijo en la posicion 2."),
    ("face", "non_crystal",
     ["Max Health"],
     {
         "2_4": ["Attack Speed", "Health Regen", "Movement Speed", "Critical Damage"],
         "3": ["Magic Damage", "Stability", "Jump", "Max Health %", "Physical Damage"],
     },
     "El stat 1 siempre es Max Health. A diferencia del Hat, la posicion 3 "
     "puede dar Magic Damage o Physical Damage adicional."),
    ("face", "crystal",
     ["Max Health", "Light"],
     {
         "3_5": ["Attack Speed", "Critical Damage", "Health Regen", "Movement Speed"],
         "4": ["Jump", "Magic Damage", "Magic Find", "Max Health %", "Physical Damage", "Stability"],
     },
     "Crystal agrega Light fijo en la posicion 2."),

    # Los 5 tipos reales de Ring Box. Un Ring NO se puede forjar/mejorar como
    # el resto del equipo — solo se consigue craftear mas Ring Boxes hasta
    # que te toque el stat secundario que quieres. Solo el Signatory (el de
    # tu propia clase) da Light y desbloquea los Hidden Effects; los otros 4
    # son genericos (cualquier clase los puede usar) y no dan Light.
    ("ring", "wisdom",
     ["Magic Damage"],
     {"2": ["Health Regen", "Energy Regen", "Stability", "Critical Hit", "Jump", "Magic Find"]},
     "Ring Box genérico. No da Light ni Hidden Effects — para eso hace "
     "falta el Ring Box Signatory de tu propia clase."),
    ("ring", "power",
     ["Physical Damage"],
     {"2": ["Health Regen", "Energy Regen", "Stability", "Critical Hit", "Jump", "Magic Find"]},
     "Ring Box genérico. No da Light ni Hidden Effects."),
    ("ring", "vitality",
     ["Max Health"],
     {"2": ["Health Regen", "Energy Regen", "Stability", "Critical Hit", "Jump", "Magic Find"]},
     "Ring Box genérico. No da Light ni Hidden Effects."),
    ("ring", "delving",
     ["Lasermancy"],
     {"2": ["Health Regen", "Energy Regen", "Stability", "Critical Hit", "Jump", "Magic Find"]},
     "Ring Box genérico. No da Light ni Hidden Effects."),
    ("ring", "signatory",
     ["Physical Damage o Magic Damage (según damage_type de la clase)", "Light"],
     {"3": ["Critical Hit", "Jump", "Magic Find", "Energy Regen"]},
     "El único que da Light y desbloquea los Hidden Effects de tu clase "
     "(colocándolo en un Ring Polisher). Stability y Health Regen NUNCA "
     "pueden salir en un Signatory/Mystic Ring — sí en los 4 genéricos de "
     "arriba. Energy Regen no aplica a clases sin barra de Energía."),
]

# Dragones: fuente adicional de Power Rank, aplicada a nivel de cuenta (no por
# build/clase). Solo se catalogan aca los 2 ejemplos confirmados por captura de
# pantalla real; el juego tiene decenas mas que no se documentan por no tener
# datos verificados. Fuente: PDF "Guía de Power Rank" (Mystic Cave / zexy1).
# Hidden Effects de Mystic Rings: una habilidad especial exclusiva por clase,
# que se activa colocando el anillo en un Ring Polisher. Introducidos en el
# parche "Ring it On!" (29 abril 2026).
# Fuente: trovegame.com/patch-notes/patch-notes-ring-it-on
# Hidden Effects de anillos: cada clase tiene varios (3 "Signatory or Mystic"
# + 1 "Mystic only"), mas un efecto de esquive compartido por casi todas las
# clases ("Rushed Escape"; Shadow Hunter tiene su propia variante, "Casual
# Escape"). Un anillo dado expone un PAR de estos; el Ring Polisher activa
# uno del par.
# Fuente: trovesaurus.com/class-ring-hidden-effects (extraido del cliente
# del juego) + trovegame.com/patch-notes/patch-notes-ring-it-on
# COBERTURA: los 18 "Mystic only" estan confirmados para todas las clases.
# Los 3 "Signatory or Mystic" solo se documentaron para Bard y Vanguardian
# (verificados); al resto de clases les falta esa parte del catalogo.
RING_HIDDEN_EFFECTS = [
    # (name, class_name_or_None, description, availability)
    ("Primitive Toxin", "Dino Tamer",
     "Los ataques básicos aplican un poderoso veneno primitivo, causando daño "
     "en el tiempo al objetivo.", "mystic_only"),
    ("Fowlmancy", "Boomeranger",
     "Las muertes de enemigos cercanos a veces crean gallinas que pelean "
     "para ti.", "mystic_only"),
    ("Dread Arrow", "Shadow Hunter",
     "La habilidad de Shadow Seekers se reemplaza por Dread Arrow, aplicando "
     "Shadow Mark, Snare y daño en el tiempo al objetivo. En vez de "
     "acumularse, cada Shadow Seeker acumulado dispara automáticamente "
     "flechas veloces.", "mystic_only"),
    ("Conduit", "Neon Ninja",
     "Tú y tus aliados cercanos reciben ráfagas de Energía durante la "
     "duración de Final Technique.", "mystic_only"),
    ("Para-Soul", "Tomb Raiser",
     "El ataque básico hace daño extra, y ahora golpea enemigos y cura a los "
     "Skellittles en un círculo alrededor tuyo.", "mystic_only"),
    ("Explosive Defense", "Revenant",
     "Bulwark Bash explota al usarse. Una vez cada 3 segundos, las muertes "
     "de enemigos cercanos pueden reiniciar el cooldown de Bulwark Bash.", "mystic_only"),
    ("Gravity Well", "Lunar Lancer",
     "Usar Lunar Leap o Lunar Slam atrae a los enemigos cercanos. Este "
     "efecto solo puede ocurrir una vez cada 30 segundos.", "mystic_only"),
    ("Mine Time", "Gunslinger",
     "Reemplaza Blast Jump por una habilidad de Mina de Proximidad. Las "
     "minas se arman al aterrizar y explotan tras 3 segundos o cuando un "
     "enemigo se acerca. Máximo 5 minas en stock, que se reponen cada 4s.", "mystic_only"),
    ("Divine Touch", "Solarion",
     "Las muertes de enemigos cercanos otorgan Divine Radiance.", "mystic_only"),
    ("Momentum Shift", "Knight",
     "Reemplaza Iron Will por Momentum Shift. Al activarse, aumenta Daño, "
     "Stability, Attack Speed y Energy Regen del Knight. Mientras está "
     "inactivo, aumenta Health Regen y Movement Speed.", "mystic_only"),
    ("Frozen Tempest", "Ice Sage",
     "Ice Crash se reemplaza por Frozen Tempest, aumentando el Movement "
     "Speed del Ice Sage y dañando/ralentizando a los enemigos cercanos "
     "mientras está activo.", "mystic_only"),
    ("Split-Fire", "Dracolyte",
     "Al activar Spitfire, también se envían proyectiles ígneos en todas "
     "direcciones. Sin embargo, el Familiar carga más lento.", "mystic_only"),
    ("Cherry Bomber", "Candy Barbarian",
     "Usar Vanilla Swirlwind poco después de Sugar Crash hace caer racimos "
     "de Cherry Bomb sobre hasta 5 enemigos en el área.", "mystic_only"),
    ("Passion Play", "Bard",
     "Mientras Bardsong está activo, usar Dodge puede sumar +1 Melody "
     "adicional una vez cada 5 segundos, sin importar si Dodge es lo que "
     "Bardsong estaba pidiendo.", "mystic_only"),
    ("Bliiiiink", "Fae Trickster",
     "Blink ahora teletransporta más lejos, pero ya no crea un señuelo.", "mystic_only"),
    ("Uncanny Balance", "Vanguardian",
     "Otorga un buff de Stability y Health Regen de 5 segundos al usar "
     "Fired Up o Force Flash.", "mystic_only"),
    ("Dummy Defused", "Pirate Captain",
     "Reemplaza la habilidad 'Pirate Decoy' por 'Defused Dummy'. Defused "
     "Dummy ya no explota, pero solo requiere 45 de Energía para lanzarse.", "mystic_only"),
    ("Wild Pulse", "Chloromancer",
     "Reemplaza la habilidad 'Green Gatling' por 'Wild Pulse'. Mientras "
     "está activa, hace daño periódico a enemigos cercanos; los enemigos "
     "'Snared' golpeados quedan aturdidos brevemente.", "mystic_only"),

    # Efecto compartido de esquive: todas las clases lo pueden tener en su
    # Mystic Ring, EXCEPTO Shadow Hunter que tiene su propia variante.
    (None, None, None, None),  # marcador, se reemplaza abajo por logica especial
]

# "Rushed Escape": efecto de esquive compartido (todas las clases menos
# Shadow Hunter). Se maneja aparte porque game_class es None (aplica a todas).
RUSHED_ESCAPE = (
    "Rushed Escape", None,
    "Otorga un aumento breve de Movement Speed (+40%, 8 segundos) tras esquivar (Dodge).",
    "shared_dodge",
)
# Shadow Hunter tiene su propia variante de ese mismo efecto compartido.
CASUAL_ESCAPE = (
    "Casual Escape", "Shadow Hunter",
    "Variante de Shadow Hunter del efecto de esquive compartido: duplica la "
    "duración de tu buff de Movement Speed post-Dodge.",
    "shared_dodge",
)

# Los 3 efectos "Signatory or Mystic" de cada clase, ahora completos para
# las 18 clases (confirmados via trovesaurus.com/polished-paragon/hidden-effects,
# pagina mantenida y corregida por la comunidad — incluye Solarion, que salio
# despues del parche original de 2021).
EXTRA_RING_EFFECTS_BY_CLASS = [
    ("Peaceful Moment", "Bard",
     "El buff de la canción Peaceful reduce el daño hecho a aliados cercanos "
     "(25% de reducción, 30s por aplicación).", "signatory_or_mystic"),
    ("Musical Master", "Bard",
     "El Bard gana un buff de +35% Critical Damage (30s) cuando los 3 buffs "
     "de Bardsong están activos a la vez.", "signatory_or_mystic"),
    ("Melody Overload", "Bard",
     "Al llegar a Melody máxima, ganas un pequeño aumento de Magic Damage "
     "(+20%).", "signatory_or_mystic"),
    ("Combo", "Vanguardian",
     "Plasma Blast ahora aplica el mismo aumento de daño recibido que "
     "aplica Eyebeam (+5% daño recibido, 10s).", "signatory_or_mystic"),
    ("Hero's Stand", "Vanguardian",
     "Laser Leap y Hero's Charge otorgan un buff que cura mientras haces "
     "daño (6.5% de Maximum Health por golpe básico elegible, 15s).", "signatory_or_mystic"),
    ("Champions! Congregate!", "Vanguardian",
     "Fired Up y Force Flash ahora también aplican a hasta 2 aliados "
     "cercanos al usarse.", "signatory_or_mystic"),

    ("Blast Bow", "Boomeranger",
     "Cada ataque con arco genera una explosión al impactar.", "signatory_or_mystic"),
    ("Cyclone", "Boomeranger",
     "El 3er ataque cuerpo a cuerpo ahora atrae a los enemigos hacia ti.", "signatory_or_mystic"),
    ("Overstuffed Urn", "Boomeranger",
     "Urn (la habilidad de urna) activa un efecto adicional al usarse.", "signatory_or_mystic"),

    ("Emergency Snack", "Candy Barbarian",
     "Al bajar de 50% de vida, genera un Cupcake que rellena tu energía y "
     "reinicia el cooldown de tus habilidades.", "signatory_or_mystic"),
    ("So Sweet", "Candy Barbarian",
     "Swirlwind ahora también genera un Gumdrop al golpear a un enemigo "
     "(dura 5s).", "signatory_or_mystic"),
    ("Spin To Win", "Candy Barbarian",
     "Reduce el costo de energía de Swirlwind y quita su reducción de "
     "Movement Speed.", "signatory_or_mystic"),

    ("Phytobarrier", "Chloromancer",
     "Genera un escudo que reduce el daño recibido cuando tu vida está baja.", "signatory_or_mystic"),
    ("Weird Growth", "Chloromancer",
     "Al hacer daño, ganas un buff que hace crecer plantas al azar cerca "
     "tuyo por un tiempo corto.", "signatory_or_mystic"),
    ("Gatling Gatling Gatling", "Chloromancer",
     "Los ataques básicos tienen probabilidad de generar un Mini Green "
     "Gatling, que a su vez puede generar Mini Mini Green Gatlings.", "signatory_or_mystic"),

    ("Oh my Dinos!", "Dino Tamer",
     "Dino Buddy ahora genera dos minions en vez de uno.", "signatory_or_mystic"),
    ("MR. CHOMP CHOMP!", "Dino Tamer",
     "Dino Mount ahora genera un minion T-rex adicional.", "signatory_or_mystic"),
    ("Deep Wounds", "Dino Tamer",
     "Aplica un debuff de daño incrementado a los enemigos golpeados por "
     "el Dino Tamer y sus dinosaurios.", "signatory_or_mystic"),

    ("Dragon Force", "Dracolyte",
     "Invoca dos aliados Dracolyte adicionales al usar la Ultimate.", "signatory_or_mystic"),
    ("Firestorm", "Dracolyte",
     "Spitfire tiene probabilidad de dar un buff que permite usarla "
     "libremente por un tiempo corto.", "signatory_or_mystic"),
    ("Dragonborn", "Dracolyte",
     "Al esquivar (Dodge), el Dracolyte deja un Burnt Offering.", "signatory_or_mystic"),

    ("Dance Partner", "Fae Trickster",
     "Faerie Dance invoca un Fae Juggernaut que atrae (taunt) a los "
     "enemigos.", "signatory_or_mystic"),
    ("Mobilize", "Fae Trickster",
     "Faerie Dance invoca un báculo encantado grande que te sigue.", "signatory_or_mystic"),
    ("Trick Trick Boom", "Fae Trickster",
     "Al recibir daño, probabilidad de generar un Glitterbomb en tu "
     "posición, con más alcance y aturdimiento.", "signatory_or_mystic"),

    ("Berserk Slinger", "Gunslinger",
     "Al usar Run and Gun, entras en modo berserk: más daño y velocidad de "
     "ataque, pero mucho menos Movement Speed.", "signatory_or_mystic"),
    ("Lock n Load", "Gunslinger",
     "Esquivar (Dodge) otorga un disparo cargado instantáneo, con un "
     "cooldown corto.", "signatory_or_mystic"),
    ("Stunning Ammo", "Gunslinger",
     "Los disparos cargados (Charged Shot) tienen probabilidad de aturdir.", "signatory_or_mystic"),

    ("Nice Ice Baby", "Ice Sage",
     "The Big Chill genera un Ice Crash sobre ti que convierte el suelo en "
     "hielo.", "signatory_or_mystic"),
    ("As Cold as Ice", "Ice Sage",
     "Mientras estás sobre hielo, ganas Critical Hit y Critical Damage "
     "adicionales.", "signatory_or_mystic"),
    ("Chill Out", "Ice Sage",
     "Frozen Ward se activa automáticamente cuando tu vida está baja.", "signatory_or_mystic"),

    ("Iron-er Will", "Knight",
     "Aumenta la redirección de daño de Iron Will y le da más reducción de "
     "daño al Knight.", "signatory_or_mystic"),
    ("Over Charge", "Knight",
     "Usar Charge otorga un aumento temporal de Movement Speed.", "signatory_or_mystic"),
    ("Smashing", "Knight",
     "El daño hecho con Smash! reduce el cooldown de Iron Will en 1 "
     "segundo.", "signatory_or_mystic"),

    ("From the Moon", "Lunar Lancer",
     "En Lunarform, los ataques básicos tienen probabilidad de invocar "
     "meteoros desde el cielo.", "signatory_or_mystic"),
    ("Cliffhanger", "Lunar Lancer",
     "Esquivar reduce el cooldown de Grapple y Empowered Grapple (esta "
     "habilidad tiene un cooldown corto).", "signatory_or_mystic"),
    ("Need For Speed", "Lunar Lancer",
     "Tras usar el grapple potenciado, ganas un buff de velocidad en vez "
     "de daño.", "signatory_or_mystic"),

    ("Clone Jutsu", "Neon Ninja",
     "El clon creado por Shadow Flip explota al terminar su duración.", "signatory_or_mystic"),
    ("Float Like A Butterfly", "Neon Ninja",
     "Ganas Slowfall durante toda la duración de Final Technique.", "signatory_or_mystic"),
    ("Recharge", "Neon Ninja",
     "Ganas energía al esquivar (Dodge).", "signatory_or_mystic"),

    ("All Hands On Deck", "Pirate Captain",
     "Usar Man O' War también invoca un Pirrot Cannoneer.", "signatory_or_mystic"),
    ("AVAST YE!!!", "Pirate Captain",
     "Los ataques básicos hacen que tus minions ataquen a tu objetivo, "
     "aplicando además un debuff de daño incrementado.", "signatory_or_mystic"),
    ("Raiders", "Pirate Captain",
     "First Mate tiene probabilidad de soltar doblones al golpear "
     "enemigos.", "signatory_or_mystic"),

    ("Speed Spears", "Revenant",
     "Spirit Spears ya no ralentiza al Revenant.", "signatory_or_mystic"),
    ("Spirit Squad", "Revenant",
     "Spirit Storm invoca un grupo de pequeños Spirit Wraiths.", "signatory_or_mystic"),
    ("Vengeful Storm", "Revenant",
     "Con poca vida, Spirit Storm se activa automáticamente (cooldown "
     "largo).", "signatory_or_mystic"),

    ("Sneaky Traps", "Shadow Hunter",
     "Al esquivar, el Shadow Hunter deja caer una Sun Snare.", "signatory_or_mystic"),
    ("Tactical Seekers", "Shadow Hunter",
     "Cuando los enemigos reciben daño de Sacred Arrow, un Shadow Seeker "
     "sale disparado hacia el objetivo más cercano. (Reemplazó a 'Tactical "
     "Shot').", "signatory_or_mystic"),
    ("Unholy Heal", "Shadow Hunter",
     "Al derrotar enemigos marcados con Shadowmark, el Shadow Hunter se "
     "cura un poco.", "signatory_or_mystic"),

    ("Guiding Flight", "Solarion",
     "Prismatic Blast y Guiding Light también aplican el efecto Slowfall "
     "de Solar Wings.", "signatory_or_mystic"),
    ("Solar Stance", "Solarion",
     "Quita el efecto Solar Wings, aplicando en su lugar un buff de "
     "reducción de daño por un tiempo corto.", "signatory_or_mystic"),
    ("Prismatic Chain", "Solarion",
     "Los enemigos dañados por Prismatic Blast disparan a su vez otro "
     "Prismatic Blast, dañando a enemigos cercanos.", "signatory_or_mystic"),

    ("Banshee Blast", "Tomb Raiser",
     "Los ataques básicos tienen probabilidad de invocar Baby Banshees.", "signatory_or_mystic"),
    ("Ghost More", "Tomb Raiser",
     "Reduce el consumo de energía de Ghostform.", "signatory_or_mystic"),
    ("Skellbiggle Split", "Tomb Raiser",
     "Bonetourage tiene probabilidad de invocar un skellittle grande, que "
     "al morir genera más skellittles.", "signatory_or_mystic"),
]

# Remover el marcador placeholder y unir todo
RING_HIDDEN_EFFECTS = [t for t in RING_HIDDEN_EFFECTS if t[0] is not None]
RING_HIDDEN_EFFECTS += [RUSHED_ESCAPE, CASUAL_ESCAPE] + EXTRA_RING_EFFECTS_BY_CLASS


DRAGONS = [
    ("Drak-o-Lantern", "normal",
     "Dragón/montura estacional con forma dracónica. Los dragones normales "
     "otorgan en general +30 Power Rank fijo cada uno una vez desbloqueados "
     "permanentemente.",
     "+30 PR (aprox., como la mayoría de dragones normales); además otorga "
     "+0.6% Critical Hit, +1000 Max Health, +250 Damage, +1 Jump, +50 Magic Find"),
    ("Taeryn Veernok, Progenitor of the Cosmos", "primordial",
     "Dragón Primordial (de gemas): la fuente de todo el espacio y el tiempo. "
     "Al desbloquearlo permanentemente, incrementa el Jump y aplica un bono "
     "porcentual sobre el Power Rank que dan las Gemas Cósmicas.",
     "+10% de Power Rank proveniente de Gemas Cósmicas (no de todas las gemas, "
     "solo las Cosmic)"),
]

# Progresion completa de cada subclase: 9 tiers segun el Power Rank del personaje
# (I a IX) y 6 niveles de bono de stat (1 a 30). Datos exactos del PDF de usuario
# "Trove - Subclassing".
# NOTA: el dato de Chloromancer ("5000% reflect") viene textual del PDF fuente;
# se conserva tal cual aunque el numero parezca alto para el resto de la tabla,
# en vez de corregirlo sin confirmar.
SUBCLASS_TIERS = {
    "Bard": [
        ("I", "1 - 4,999", "Jubilant 2%, Peaceful 1%, Battle 2%"),
        ("II", "5,000 - 9,999", "Jubilant 4%, Peaceful 1%, Battle 4%"),
        ("III", "10,000 - 14,999", "Jubilant 6%, Peaceful 2%, Battle 6%"),
        ("IV", "15,000 - 19,999", "Jubilant 8%, Peaceful 2%, Battle 8%"),
        ("V", "20,000 - 24,999", "Jubilant 10%, Peaceful 3%, Battle 10%"),
        ("VI", "25,000 - 29,999", "Jubilant 12%, Peaceful 4%, Battle 12%"),
        ("VII", "30,000 - 34,999", "Jubilant 15%, Peaceful 5%, Battle 15%"),
        ("VIII", "35,000 - 39,999", "Jubilant 17.5%, Peaceful 6.5%, Battle 17.5%"),
        ("IX", "40,000 - 44,999", "Jubilant 20%, Peaceful 7.5%, Battle 20%"),
    ],
    "Boomeranger": [
        ("I", "1 - 4,999", "30% Heal at low health; 30s cooldown"),
        ("II", "5,000 - 9,999", "32% Heal at low health; 30s cooldown"),
        ("III", "10,000 - 14,999", "34% Heal at low health; 30s cooldown"),
        ("IV", "15,000 - 19,999", "36% Heal at low health; 30s cooldown"),
        ("V", "20,000 - 24,999", "38% Heal at low health; 30s cooldown"),
        ("VI", "25,000 - 29,999", "40% Heal at low health; 30s cooldown"),
        ("VII", "30,000 - 34,999", "42% Heal at low health; 30s cooldown"),
        ("VIII", "35,000 - 39,999", "45% Heal at low health; 30s cooldown"),
        ("IX", "40,000 - 44,999", "50% Heal at low health; 30s cooldown"),
    ],
    "Candy Barbarian": [
        ("I", "1 - 4,999", "22.5% chance on damage dealt"),
        ("II", "5,000 - 9,999", "25% chance on damage dealt"),
        ("III", "10,000 - 14,999", "27.5% chance on damage dealt"),
        ("IV", "15,000 - 19,999", "30% chance on damage dealt"),
        ("V", "20,000 - 24,999", "32.5% chance on damage dealt"),
        ("VI", "25,000 - 29,999", "35% chance on damage dealt"),
        ("VII", "30,000 - 34,999", "37.5% chance on damage dealt"),
        ("VIII", "35,000 - 39,999", "40% chance on damage dealt"),
        ("IX", "40,000 - 44,999", "50% chance on damage dealt"),
    ],
    "Chloromancer": [
        ("I", "1 - 4,999", "20% chance on NPC damage received; 3s duration; 5000% reflect; 30s cooldown"),
        ("II", "5,000 - 9,999", "20% chance; 4s duration; 5000% reflect; 30s cooldown"),
        ("III", "10,000 - 14,999", "20% chance; 5s duration; 5000% reflect; 30s cooldown"),
        ("IV", "15,000 - 19,999", "20% chance; 6s duration; 5000% reflect; 30s cooldown"),
        ("V", "20,000 - 24,999", "20% chance; 7s duration; 5000% reflect; 30s cooldown"),
        ("VI", "25,000 - 29,999", "20% chance; 8s duration; 5000% reflect; 30s cooldown"),
        ("VII", "30,000 - 34,999", "20% chance; 9s duration; 5000% reflect; 30s cooldown"),
        ("VIII", "35,000 - 39,999", "65% chance; 10s duration; 5000% reflect; 30s cooldown"),
        ("IX", "40,000 - 44,999", "75% chance; 12s duration; 5000% reflect; 30s cooldown"),
    ],
    "Dino Tamer": [
        ("I", "1 - 4,999", "20% chance on Critical Hit; 2s root; 8s cooldown"),
        ("II", "5,000 - 9,999", "22% chance on Critical Hit; 2s root; 8s cooldown"),
        ("III", "10,000 - 14,999", "24% chance on Critical Hit; 2s root; 8s cooldown"),
        ("IV", "15,000 - 19,999", "26% chance on Critical Hit; 2s root; 8s cooldown"),
        ("V", "20,000 - 24,999", "28% chance on Critical Hit; 2s root; 8s cooldown"),
        ("VI", "25,000 - 29,999", "30% chance on Critical Hit; 2s root; 8s cooldown"),
        ("VII", "30,000 - 34,999", "32% chance on Critical Hit; 2s root; 8s cooldown"),
        ("VIII", "35,000 - 39,999", "40% chance on Critical Hit; 3s root; 8s cooldown"),
        ("IX", "40,000 - 44,999", "45% chance on Critical Hit; 4s root; 8s cooldown"),
    ],
    "Dracolyte": [
        ("I", "1 - 4,999", "15% chance on Physical Damage; fire DoT: 5% Magic Damage"),
        ("II", "5,000 - 9,999", "16% chance; fire DoT: 8% Magic Damage"),
        ("III", "10,000 - 14,999", "17% chance; fire DoT: 12% Magic Damage"),
        ("IV", "15,000 - 19,999", "18% chance; fire DoT: 16% Magic Damage"),
        ("V", "20,000 - 24,999", "19% chance; fire DoT: 20% Magic Damage"),
        ("VI", "25,000 - 29,999", "20% chance; fire DoT: 25% Magic Damage"),
        ("VII", "30,000 - 34,999", "21% chance; fire DoT: 28% Magic Damage"),
        ("VIII", "35,000 - 39,999", "25% chance; fire DoT: 30% Magic Damage"),
        ("IX", "40,000 - 44,999", "30% chance; fire DoT: 40% Magic Damage"),
    ],
    "Fae Trickster": [
        ("I", "1 - 4,999", "20% chance on Critical Hit; 150% Magic Damage; 1.5s stun"),
        ("II", "5,000 - 9,999", "21% chance; 175% Magic Damage; 1.5s stun"),
        ("III", "10,000 - 14,999", "22% chance; 200% Magic Damage; 1.5s stun"),
        ("IV", "15,000 - 19,999", "23% chance; 250% Magic Damage; 1.5s stun"),
        ("V", "20,000 - 24,999", "24% chance; 275% Magic Damage; 1.5s stun"),
        ("VI", "25,000 - 29,999", "25% chance; 300% Magic Damage; 1.5s stun"),
        ("VII", "30,000 - 34,999", "26% chance; 350% Magic Damage; 1.5s stun"),
        ("VIII", "35,000 - 39,999", "30% chance; 400% Magic Damage; 1.5s stun"),
        ("IX", "40,000 - 44,999", "40% chance; 450% Magic Damage; 1.5s stun"),
    ],
    "Gunslinger": [
        ("I", "1 - 4,999", "+2.5% outgoing damage while airborne"),
        ("II", "5,000 - 9,999", "+3% outgoing damage while airborne"),
        ("III", "10,000 - 14,999", "+3.5% outgoing damage while airborne"),
        ("IV", "15,000 - 19,999", "+4% outgoing damage while airborne"),
        ("V", "20,000 - 24,999", "+4.5% outgoing damage while airborne"),
        ("VI", "25,000 - 29,999", "+5% outgoing damage while airborne"),
        ("VII", "30,000 - 34,999", "+5.5% outgoing damage while airborne"),
        ("VIII", "35,000 - 39,999", "+7.5% outgoing damage while airborne"),
        ("IX", "40,000 - 44,999", "+10% outgoing damage while airborne"),
    ],
    "Ice Sage": [
        ("I", "1 - 4,999", "20% chance on damage taken; shield; stats +5%; 30s cooldown"),
        ("II", "5,000 - 9,999", "21% chance; stats +8%; 30s cooldown"),
        ("III", "10,000 - 14,999", "22% chance; stats +11%; 30s cooldown"),
        ("IV", "15,000 - 19,999", "23% chance; stats +14%; 30s cooldown"),
        ("V", "20,000 - 24,999", "24% chance; stats +17%; 30s cooldown"),
        ("VI", "25,000 - 29,999", "25% chance; stats +20%; 30s cooldown"),
        ("VII", "30,000 - 34,999", "26% chance; stats +23%; 30s cooldown"),
        ("VIII", "35,000 - 39,999", "30% chance; stats +25%; 30s cooldown"),
        ("IX", "40,000 - 44,999", "35% chance; stats +35%; 30s cooldown"),
    ],
    "Knight": [
        ("I", "1 - 4,999", "95 Ground Mount Speed; 25% Damage Reduction shield"),
        ("II", "5,000 - 9,999", "97 Ground Mount Speed; 30% Damage Reduction shield"),
        ("III", "10,000 - 14,999", "100 Ground Mount Speed; 35% Damage Reduction shield"),
        ("IV", "15,000 - 19,999", "105 Ground Mount Speed; 45% Damage Reduction shield"),
        ("V", "20,000 - 24,999", "110 Ground Mount Speed; 55% Damage Reduction shield"),
        ("VI", "25,000 - 29,999", "120 Ground Mount Speed; 65% Damage Reduction shield"),
        ("VII", "30,000 - 34,999", "125 Ground Mount Speed; 65% Damage Reduction shield"),
        ("VIII", "35,000 - 39,999", "125 Ground Mount Speed; 75% Damage Reduction shield"),
        ("IX", "40,000 - 44,999", "125 Ground Mount Speed; 85% Damage Reduction shield"),
    ],
    "Lunar Lancer": [
        ("I", "1 - 4,999", "20% chance on damage dealt; +5% damage done; 6s duration"),
        ("II", "5,000 - 9,999", "21% chance; +6% damage done"),
        ("III", "10,000 - 14,999", "22% chance; +7% damage done"),
        ("IV", "15,000 - 19,999", "23% chance; +8% damage done"),
        ("V", "20,000 - 24,999", "24% chance; +9% damage done"),
        ("VI", "25,000 - 29,999", "25% chance; +10% damage done"),
        ("VII", "30,000 - 34,999", "26% chance; +11% damage done"),
        ("VIII", "35,000 - 39,999", "30% chance; +15% damage done"),
        ("IX", "40,000 - 44,999", "35% chance; +20% damage done"),
    ],
    "Neon Ninja": [
        ("I", "1 - 4,999", "20% chance when target is below 20% health; 50% Physical Damage"),
        ("II", "5,000 - 9,999", "22% chance; 100% Physical Damage"),
        ("III", "10,000 - 14,999", "24% chance; 150% Physical Damage"),
        ("IV", "15,000 - 19,999", "26% chance; 200% Physical Damage"),
        ("V", "20,000 - 24,999", "28% chance; 250% Physical Damage"),
        ("VI", "25,000 - 29,999", "30% chance; 300% Physical Damage"),
        ("VII", "30,000 - 34,999", "32% chance; 350% Physical Damage"),
        ("VIII", "35,000 - 39,999", "34% chance; 400% Physical Damage"),
        ("IX", "40,000 - 44,999", "36% chance; 550% Physical Damage"),
    ],
    "Pirate Captain": [
        ("I", "1 - 4,999", "20% chance on damage dealt; cannonball; 30s cooldown"),
        ("II", "5,000 - 9,999", "21% chance on damage dealt; 30s cooldown"),
        ("III", "10,000 - 14,999", "22% chance on damage dealt; 30s cooldown"),
        ("IV", "15,000 - 19,999", "23% chance on damage dealt; 30s cooldown"),
        ("V", "20,000 - 24,999", "24% chance on damage dealt; 30s cooldown"),
        ("VI", "25,000 - 29,999", "25% chance on damage dealt; 30s cooldown"),
        ("VII", "30,000 - 34,999", "26% chance on damage dealt; 30s cooldown"),
        ("VIII", "35,000 - 39,999", "30% chance on damage dealt; increased AoE; 30s cooldown"),
        ("IX", "40,000 - 44,999", "35% chance on damage dealt; increased AoE; 30s cooldown"),
    ],
    "Revenant": [
        ("I", "1 - 4,999", "Successful attacks return 1% health"),
        ("II", "5,000 - 9,999", "Successful attacks return 1.5% health"),
        ("III", "10,000 - 14,999", "Successful attacks return 2% health"),
        ("IV", "15,000 - 19,999", "Successful attacks return 2.5% health"),
        ("V", "20,000 - 24,999", "Successful attacks return 3% health"),
        ("VI", "25,000 - 29,999", "Successful attacks return 3.5% health"),
        ("VII", "30,000 - 34,999", "Successful attacks return 4% health"),
        ("VIII", "35,000 - 39,999", "Successful attacks return 6% health"),
        ("IX", "40,000 - 44,999", "Successful attacks return 8% health"),
    ],
    "Shadow Hunter": [
        ("I", "1 - 4,999", "15% chance on Magic Damage dealt; DoT: 5% Physical Damage"),
        ("II", "5,000 - 9,999", "16% chance; DoT: 8% Physical Damage"),
        ("III", "10,000 - 14,999", "17% chance; DoT: 11% Physical Damage"),
        ("IV", "15,000 - 19,999", "18% chance; DoT: 14% Physical Damage"),
        ("V", "20,000 - 24,999", "19% chance; DoT: 17% Physical Damage"),
        ("VI", "25,000 - 29,999", "20% chance; DoT: 20% Physical Damage"),
        ("VII", "30,000 - 34,999", "21% chance; DoT: 25% Physical Damage"),
        ("VIII", "35,000 - 39,999", "25% chance; DoT: 30% Physical Damage"),
        ("IX", "40,000 - 44,999", "30% chance; DoT: 40% Physical Damage"),
    ],
    "Solarion": [
        ("I", "1 - 4,999", "25% chance; 100% Physical Damage; 50% DoT"),
        ("II", "5,000 - 9,999", "25% chance; 125% Physical Damage; 50% DoT"),
        ("III", "10,000 - 14,999", "25% chance; 150% Physical Damage; 50% DoT"),
        ("IV", "15,000 - 19,999", "25% chance; 200% Physical Damage; 50% DoT"),
        ("V", "20,000 - 24,999", "25% chance; 225% Physical Damage; 75% DoT"),
        ("VI", "25,000 - 29,999", "33% chance; 250% Physical Damage; 75% DoT"),
        ("VII", "30,000 - 34,999", "33% chance; 275% Physical Damage; 75% DoT"),
        ("VIII", "35,000 - 39,999", "33% chance; 300% Physical Damage; 85% DoT"),
        ("IX", "40,000 - 44,999", "40% chance; 350% Physical Damage; 100% DoT"),
    ],
    "Tomb Raiser": [
        ("I", "1 - 4,999", "Minion 52%, Ranged/Tank/DPS 14%, Epic 5%"),
        ("II", "5,000 - 9,999", "Minion 42%, Ranged/Tank/DPS 14%, Epic 14%"),
        ("III", "10,000 - 14,999", "Minion 33%, Ranged/Tank/DPS 14%, Epic 24%"),
        ("IV", "15,000 - 19,999", "Minion 24%, Ranged/Tank/DPS 14%, Epic 33%"),
        ("V", "20,000 - 24,999", "Minion 15%, Ranged/Tank/DPS 14%, Epic 42%"),
        ("VI", "25,000 - 29,999", "Minion 5%, Ranged/Tank/DPS 14%, Epic 52%"),
        ("VII", "30,000 - 34,999", "Minion 5%, Ranged/Tank/DPS 14%, Epic 52%"),
        ("VIII", "35,000 - 39,999", "Minion 5%, Ranged/Tank/DPS 14%, Epic 52%"),
        ("IX", "40,000 - 44,999", "Minion 5%, Ranged/Tank/DPS 14%, Epic 52%"),
    ],
    "Vanguardian": [
        ("I", "1 - 4,999", "Shockwave deals 100% Physical/Magic Damage"),
        ("II", "5,000 - 9,999", "Shockwave deals 150% Physical/Magic Damage"),
        ("III", "10,000 - 14,999", "Shockwave deals 200% Physical/Magic Damage"),
        ("IV", "15,000 - 19,999", "Shockwave deals 250% Physical/Magic Damage"),
        ("V", "20,000 - 24,999", "Shockwave deals 300% Physical/Magic Damage"),
        ("VI", "25,000 - 29,999", "Shockwave deals 350% Physical/Magic Damage"),
        ("VII", "30,000 - 34,999", "Shockwave deals 400% Physical/Magic Damage"),
        ("VIII", "35,000 - 39,999", "Shockwave deals 600% Physical/Magic Damage"),
        ("IX", "40,000 - 44,999", "Shockwave deals 800% Physical/Magic Damage"),
    ],
}

SUBCLASS_LEVELS = {
    "Bard": [(1, "+1% Critical Damage"), (10, "+3% Critical Damage"), (15, "+6% Critical Damage"),
             (20, "+9% Critical Damage"), (25, "+12% Critical Damage"), (30, "+20% Critical Damage")],
    "Boomeranger": [(1, "+1% Critical Damage"), (10, "+2% Critical Damage"), (15, "+4% Critical Damage"),
                    (20, "+8% Critical Damage"), (25, "+12% Critical Damage"), (30, "+20% Critical Damage")],
    "Candy Barbarian": [(1, "+5 Stability"), (10, "+15 Stability"), (15, "+30 Stability"),
                         (20, "+50 Stability"), (25, "+75 Stability"), (30, "+105 Stability")],
    "Chloromancer": [(1, "+1% Maximum Health"), (10, "+2% Maximum Health"), (15, "+4% Maximum Health"),
                      (20, "+7% Maximum Health"), (25, "+10% Maximum Health"), (30, "+15% Maximum Health")],
    "Dino Tamer": [(1, "+0.5% Attack Speed"), (10, "+1% Attack Speed"), (15, "+2% Attack Speed"),
                   (20, "+3% Attack Speed"), (25, "+4% Attack Speed"), (30, "+5% Attack Speed")],
    "Dracolyte": [(1, "+1% Cooldown Time Reduction"), (10, "+2% Cooldown Time Reduction"),
                  (15, "+3% Cooldown Time Reduction"), (20, "+4% Cooldown Time Reduction"),
                  (25, "+5% Cooldown Time Reduction"), (30, "+7% Cooldown Time Reduction")],
    "Fae Trickster": [(1, "101 Movement Speed (Flying)"), (10, "102 Movement Speed (Flying)"),
                       (15, "103 Movement Speed (Flying)"), (20, "104 Movement Speed (Flying)"),
                       (25, "105 Movement Speed (Flying)"), (30, "110 Movement Speed (Flying)")],
    "Gunslinger": [(1, "+1 Jump"), (10, "+2 Jump"), (15, "+3 Jump"),
                   (20, "+4 Jump"), (25, "+6 Jump"), (30, "+10 Jump")],
    "Ice Sage": [(1, "+10 Magic Damage"), (10, "+60 Magic Damage"), (15, "+160 Magic Damage"),
                 (20, "+300 Magic Damage"), (25, "+500 Magic Damage"), (30, "+750 Magic Damage")],
    "Knight": [(1, "+1 Flask Capacity"), (10, "+2 Flask Capacity"), (15, "+3 Flask Capacity"),
               (20, "+4 Flask Capacity"), (25, "+5 Flask Capacity"), (30, "+6 Flask Capacity")],
    "Lunar Lancer": [(1, "+10 Physical Damage"), (10, "+60 Physical Damage"), (15, "+160 Physical Damage"),
                      (20, "+300 Physical Damage"), (25, "+500 Physical Damage"), (30, "+750 Physical Damage")],
    "Neon Ninja": [(1, "+1 Jump"), (10, "+2 Jump"), (15, "+3 Jump"),
                   (20, "+4 Jump"), (25, "+6 Jump"), (30, "+10 Jump")],
    "Pirate Captain": [(1, "+10 Magic Find"), (10, "+20 Magic Find"), (15, "+30 Magic Find"),
                        (20, "+40 Magic Find"), (25, "+50 Magic Find"), (30, "+70 Magic Find")],
    "Revenant": [(1, "-1% Incoming Damage"), (10, "-2% Incoming Damage"), (15, "-3% Incoming Damage"),
                 (20, "-4% Incoming Damage"), (25, "-5% Incoming Damage"), (30, "-6% Incoming Damage")],
    "Shadow Hunter": [(1, "+10 Magic Damage"), (10, "+60 Magic Damage"), (15, "+160 Magic Damage"),
                       (20, "+300 Magic Damage"), (25, "+500 Magic Damage"), (30, "+750 Magic Damage")],
    "Solarion": [(1, "+5 Light"), (10, "+15 Light"), (15, "+30 Light"),
                 (20, "+55 Light"), (25, "+90 Light"), (30, "+140 Light")],
    "Tomb Raiser": [(1, "+0.5% Critical Hit"), (10, "+1% Critical Hit"), (15, "+1.5% Critical Hit"),
                     (20, "+2.5% Critical Hit"), (25, "+3.5% Critical Hit"), (30, "+5.5% Critical Hit")],
    "Vanguardian": [(1, "+1 Jump"), (10, "+2 Jump"), (15, "+3 Jump"),
                     (20, "+4 Jump"), (25, "+6 Jump"), (30, "+10 Jump")],
}

# Subclases: la habilidad pasiva "de firma" de cada clase, que CUALQUIER OTRA clase
# puede equipar como su subclase (nunca la propia). Da la pasiva + un bono de stat
# fijo que escala con el nivel de subclase (1-30).
# name, clase de origen, descripcion de la pasiva, stat de bono, rango del bono.
# Fuente: trovesaurus.com/subclasses (info oficial de Trion Worlds)
SUBCLASSES = [
    ("Personal Song", "Bard",
     "Al atacar, gana en orden los buffs Jubilant (velocidad de movimiento y energía "
     "máxima), Peaceful (vida al hacer daño) y Battle (velocidad de ataque y daño "
     "crítico), cada uno 3s con 15s de cooldown.",
     "Critical Damage", "+1.0% a +20.0%"),
    ("Fae Companion", "Boomeranger",
     "Un compañero fae que cura automáticamente al llegar a 20% de vida (30s de "
     "cooldown).",
     "Critical Damage", "+1% a +20%"),
    ("Sugar Rush", "Candy Barbarian",
     "Dañar a un enemigo tiene probabilidad de soltar dulce: Rage Candy (+movimiento "
     "y +velocidad de ataque) o Heal Candy (cura), 15s de cooldown.",
     "Stability", "+5 a +105"),
    ("Prickly Persona", "Chloromancer",
     "Probabilidad al recibir daño de un NPC de reflejar 50% del daño al atacante "
     "(30s de cooldown, no afecta a Shadow Titans).",
     "Max Health", "+1% a +15%"),
    ("Research Net", "Dino Tamer",
     "Los golpes críticos tienen probabilidad de enraizar al objetivo brevemente "
     "(8s de cooldown).",
     "Attack Speed", "+0.5% a +5%"),
    ("Burning Zealot", "Dracolyte",
     "El daño físico tiene probabilidad de prender fuego al enemigo, causando daño "
     "en el tiempo (10s de cooldown).",
     "Cooldown Time Reduction", "1% a 7%"),
    ("Sparkle Grenade", "Fae Trickster",
     "Los golpes críticos pueden generar una granada brillante que daña y aturde "
     "enemigos (20s de cooldown).",
     "Movement Speed (Flying)", "101 a 110"),
    ("Rain Destruction", "Gunslinger",
     "El daño infligido mientras está en el aire se incrementa.",
     "Jump", "+1 a +10"),
    ("Glacial Ward", "Ice Sage",
     "Dañar enemigos tiene probabilidad de activar un escudo de absorción "
     "equivalente a 5% de la vida máxima (30s de cooldown).",
     "Magic Damage", "+10 a +750"),
    ("Mounted Cavalry", "Knight",
     "Incrementa la velocidad de movimiento mientras se monta en monturas "
     "terrestres.",
     "Flask Capacity", "+1 a +6"),
    ("Sorta Crazy", "Lunar Lancer",
     "Probabilidad en combate de transformarse temporalmente y recibir parte del "
     "poder del Lunar Lancer: +daño físico/mágico, +velocidad de movimiento y "
     "ataque, y reducción de daño recibido (30s de cooldown).",
     "Physical Damage", "+10 a +750"),
    ("Assassinate", "Neon Ninja",
     "Probabilidad de infligir daño extra a enemigos con menos de 20% de vida "
     "(30s de cooldown).",
     "Jump", "+1 a +10"),
    ("Naval Gunfire", "Pirate Captain",
     "Dañar a un enemigo tiene probabilidad de invocar una bala de cañón desde el "
     "cielo (30s de cooldown).",
     "Magic Find", "+10 a +70"),
    ("Hatred of the Oathbound", "Revenant",
     "Los ataques exitosos devuelven un porcentaje de la vida máxima del "
     "personaje.",
     "Incoming Damage", "-1% a -6%"),
    ("Searing Light", "Shadow Hunter",
     "El daño mágico tiene probabilidad de activar un efecto de daño en el tiempo "
     "sobre el enemigo (10s de cooldown).",
     "Magic Damage", "+10 a +750"),
    ("Phoenix Fire", "Solarion",
     "Los ataques básicos tienen probabilidad de explotar, dañando y aplicando un "
     "efecto de daño en el tiempo que restaura energía al usuario.",
     "Light", "5 a 140"),
    ("Corpse Run", "Tomb Raiser",
     "Los enemigos caídos tienen probabilidad de generar un minion aleatorio "
     "(solo uno activo a la vez, 30s de cooldown).",
     "Critical Hit", "+0.5% a +5.5%"),
    ("Up and Away", "Vanguardian",
     "Obtiene la pasiva Touchdown del Vanguardian: al planear se sobrecarga y crea "
     "una onda de choque al aterrizar (100% de daño físico/mágico).",
     "Jump", "+1 a +10"),
]


CLASS_GEMS = [
    ("Shadow Blitz Gem", "Shadow Hunter",
     "El ataque básico se vuelve una ráfaga rápida de flechas. Dañar a un enemigo "
     "marcado por las sombras consume la marca y provoca una explosión."),
    ("Bawk-Bomb", "Boomeranger",
     "Aumenta Big Bomb: al usarla aparecen varias gallinas que atacan a los enemigos "
     "durante un tiempo, además de la explosión normal."),
    ("Aegis Assault", "Revenant",
     "Bulwark Bash pierde su cooldown (se puede spamear) y aplica daño acumulativo, "
     "pero deja de provocar (taunt) a los enemigos."),
    ("Scoop n Gloop", "Candy Barbarian",
     "Aumenta Sugar Crush: arrastra a los enemigos hacia el jugador y los aplasta, "
     "de forma similar al Spirit Storm del Revenant."),
    ("Heuristic Hackstar", "Neon Ninja",
     "Reemplaza el shuriken normal por una sierra circular masiva que atraviesa "
     "enemigos, dañando a todos en su trayectoria y aplicando Stasis Blade."),
    ("Faerocious Facsimile", "Fae Trickster",
     "Los señuelos de Blink dejan de ser inmóviles: persiguen enemigos y explotan al "
     "contacto, dañando y aturdiendo."),
    ("Overcharged", "Gunslinger",
     "Run and Gun ya no aumenta la velocidad de ataque, pero todos los disparos "
     "salen como disparos cargados al máximo."),
    ("Spirit Squire", "Knight",
     "Charge ya no impulsa hacia adelante; en su lugar invoca un Spirit Squire que "
     "arremete contra varios enemigos, dañándolos y aturdiéndolos."),
    ("Dragonling Ember", "Dracolyte",
     "Al detonar un Burnt Offering, hay probabilidad de invocar un mini dragón que "
     "ataca a los enemigos brevemente."),
    ("Leafy Lasher Overgrowth", "Chloromancer",
     "El ataque M2 (Leafy Lasher) tiene probabilidad de generar una planta "
     "ametralladora que ataca por su cuenta."),
    ("Blizzard Barrage", "Ice Sage",
     "Ice Crash se convierte en una habilidad que dispara 3 proyectiles a la vez; "
     "impactar aplica un debuff con probabilidad de generar un anillo de proyectiles."),
    ("Twin Cannon Command", "Pirate Captain",
     "First Mate ahora puede invocar dos cañones en batalla en lugar de uno solo."),
    ("Banshee's Communion", "Tomb Raiser",
     "Banshee's Boon deja de solo reducir el daño recibido y en su lugar invoca una "
     "banshee real que cura a los minions y ataca enemigos."),
    ("Lunar Echo", "Lunar Lancer",
     "Aumenta la pasiva de lunancia: al activarse invoca un clon del Lunar Lancer que "
     "también inflige daño al enemigo."),
    ("Prismatic Link", "Solarion",
     "Class Gem Empoderada del Solarion. Prismatic Blast ahora también pulsa "
     "alrededor del Phoenix además del Solarion, permitiendo mantener distancia "
     "mientras se ataca y dañar en área alrededor del Phoenix. Solo se puede "
     "socketear una de estas gemas a la vez."),
]


class Command(BaseCommand):
    help = "Carga las clases y gemas reales de Trove en la base de datos."

    # Gemas de una version anterior de este seed que resultaron estar mal
    # nombradas o mal categorizadas, corregidas con datos mas precisos.
    STALE_GEM_SLUGS = [
        "shield-of-reprisal", "radiant-aegis", "frozen-fusillade",
        # Estas 8 se reemplazaron por 3 versiones cada una (Water/Air/Fire),
        # ya que una sola gema "generica" sin elemento no reflejaba que en
        # el juego real cada una puede salir de un elemento distinto.
        "explosive-epilogue", "cubic-curtain", "mired-mojo", "pyrodisc",
        "spirit-surge", "stinging-curse", "stunburst", "volatile-velocity",
    ]

    def handle(self, *args, **options):
        removed_stale = 0
        for stale_slug in self.STALE_GEM_SLUGS:
            try:
                gem = Gem.objects.get(slug=stale_slug)
            except Gem.DoesNotExist:
                continue
            try:
                gem.delete()
                removed_stale += 1
            except Exception:
                self.stdout.write(self.style.WARNING(
                    f"No se pudo eliminar la gema obsoleta '{stale_slug}' "
                    f"(probablemente esta en uso en alguna build)."
                ))

        # El Ring generico viejo (tier vacio, antes asumia siempre Signatory)
        # se reemplazo por los 5 tipos reales de Ring Box.
        try:
            old_ring = EquipmentSlot.objects.get(slot_type="ring", tier="")
        except EquipmentSlot.DoesNotExist:
            old_ring = None
        if old_ring:
            try:
                old_ring.delete()
            except Exception:
                self.stdout.write(self.style.WARNING(
                    "No se pudo eliminar el Ring obsoleto (tier vacío); "
                    "probablemente está en uso en alguna build. Esa build "
                    "seguirá funcionando, pero conviene editarla para elegir "
                    "uno de los 5 tipos de Ring Box nuevos."
                ))


        created_classes = 0
        for name, weapon, role, damage_type, description in CLASSES:
            obj, created = GameClass.objects.get_or_create(
                slug=slugify(name),
                defaults={
                    "name": name,
                    "primary_role": role,
                    "damage_type": damage_type,
                    "description": f"[{weapon}] {description}",
                },
            )
            created_classes += int(created)

        created_gems = 0
        for name, gem_type, element, damage_variant, description, max_rank, stat_scaling_override in GEMS:
            if stat_scaling_override is not None:
                stat_scaling = stat_scaling_override
            elif damage_variant in ("fierce", "arcane"):
                stat_scaling = {"rollable_stats": LESSER_GEM_STATS_UNIVERSAL}
            else:
                stat_scaling = {}
            obj, created = Gem.objects.get_or_create(
                slug=slugify(name),
                defaults={
                    "name": name,
                    "gem_type": gem_type,
                    "element": element,
                    "damage_variant": damage_variant,
                    "max_rank": max_rank,
                    "description": description,
                    "stat_scaling": stat_scaling,
                },
            )
            created_gems += int(created)

        created_subclasses = 0
        updated_subclasses = 0
        for name, class_name, passive_description, bonus_stat, bonus_range in SUBCLASSES:
            try:
                game_class = GameClass.objects.get(slug=slugify(class_name))
            except GameClass.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"Saltando subclase '{name}': no existe la clase '{class_name}'."
                ))
                continue

            tier_progression = [
                {"tier": tier, "power_rank": pr, "effect": effect}
                for tier, pr, effect in SUBCLASS_TIERS.get(class_name, [])
            ]
            level_bonus_progression = [
                {"level": level, "bonus": bonus}
                for level, bonus in SUBCLASS_LEVELS.get(class_name, [])
            ]

            obj, created = Subclass.objects.get_or_create(
                game_class=game_class,
                defaults={
                    "name": name,
                    "passive_description": passive_description,
                    "bonus_stat": bonus_stat,
                    "bonus_range": bonus_range,
                    "tier_progression": tier_progression,
                    "level_bonus_progression": level_bonus_progression,
                },
            )
            if created:
                created_subclasses += 1
            elif (obj.tier_progression != tier_progression
                    or obj.level_bonus_progression != level_bonus_progression):
                # Ya existia (de una version anterior del seed sin las tablas
                # completas): se completa con los datos nuevos sin duplicar.
                obj.tier_progression = tier_progression
                obj.level_bonus_progression = level_bonus_progression
                obj.save(update_fields=["tier_progression", "level_bonus_progression"])
                updated_subclasses += 1

        created_class_gems = 0
        for name, class_name, description in CLASS_GEMS:
            try:
                game_class = GameClass.objects.get(slug=slugify(class_name))
            except GameClass.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"Saltando '{name}': no existe la clase '{class_name}' "
                    f"(¿corriste el seed de clases primero?)."
                ))
                continue
            obj, created = Gem.objects.get_or_create(
                slug=slugify(name),
                defaults={
                    "name": name,
                    "gem_type": "class",
                    "damage_variant": "universal",
                    "max_rank": 30,
                    "description": description,
                    "restricted_to_class": game_class,
                },
            )
            created_class_gems += int(created)

        created_equipment_slots = 0
        updated_equipment_slots = 0
        for slot_type, tier, fixed_stats, rollable_by_position, notes in EQUIPMENT_SLOTS:
            obj, created = EquipmentSlot.objects.get_or_create(
                slot_type=slot_type,
                tier=tier,
                defaults={
                    "fixed_stats": fixed_stats,
                    "rollable_stats_by_position": rollable_by_position,
                    "notes": notes,
                },
            )
            if created:
                created_equipment_slots += 1
            elif (obj.fixed_stats != fixed_stats
                    or obj.rollable_stats_by_position != rollable_by_position
                    or obj.notes != notes):
                # Ya existia (de una version anterior del seed con datos
                # desactualizados): se corrige sin duplicar.
                obj.fixed_stats = fixed_stats
                obj.rollable_stats_by_position = rollable_by_position
                obj.notes = notes
                obj.save(update_fields=["fixed_stats", "rollable_stats_by_position", "notes"])
                updated_equipment_slots += 1

        created_dragons = 0
        for name, dragon_type, description, pr_bonus in DRAGONS:
            obj, created = Dragon.objects.get_or_create(
                slug=slugify(name),
                defaults={
                    "name": name,
                    "dragon_type": dragon_type,
                    "description": description,
                    "power_rank_bonus": pr_bonus,
                },
            )
            created_dragons += int(created)

        created_ring_effects = 0
        for name, class_name, description, availability in RING_HIDDEN_EFFECTS:
            game_class = None
            if class_name:
                try:
                    game_class = GameClass.objects.get(slug=slugify(class_name))
                except GameClass.DoesNotExist:
                    self.stdout.write(self.style.WARNING(
                        f"Saltando Ring Hidden Effect '{name}': no existe la clase "
                        f"'{class_name}'."
                    ))
                    continue
            obj, created = RingHiddenEffect.objects.get_or_create(
                name=name, game_class=game_class,
                defaults={"description": description, "availability": availability},
            )
            created_ring_effects += int(created)

        self.stdout.write(self.style.SUCCESS(
            f"Listo: {removed_stale} gemas obsoletas eliminadas, "
            f"{created_classes} clases nuevas, {created_gems} gemas nuevas, "
            f"{created_subclasses} subclases nuevas, {updated_subclasses} subclases "
            f"completadas con tablas de progresión, "
            f"{created_class_gems} class gems nuevas, "
            f"{created_equipment_slots} equipment slots nuevos, "
            f"{updated_equipment_slots} equipment slots corregidos, "
            f"{created_dragons} dragones nuevos, "
            f"{created_ring_effects} ring hidden effects nuevos "
            f"(total en BD: {GameClass.objects.count()} clases, {Gem.objects.count()} gemas, "
            f"{Subclass.objects.count()} subclases, "
            f"{EquipmentSlot.objects.count()} equipment slots, "
            f"{Dragon.objects.count()} dragones, "
            f"{RingHiddenEffect.objects.count()} ring hidden effects)."
        ))
