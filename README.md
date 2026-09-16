# Trove Builder

Web app para armar, guardar y compartir builds de personaje para el juego Trove
(clase principal/secundaria + gemas + stats), inspirado en el character builder
de questlog.gg pero para Trove.

## Cómo correrlo

```bash
python -m venv venv
source venv/bin/activate  # en Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_trove_data     # carga las 18 clases y las gemas reales de Trove
python manage.py createsuperuser   # crea tu usuario admin
python manage.py runserver
```

Luego abre http://127.0.0.1:8000/ para la app y
http://127.0.0.1:8000/admin/ para cargar datos (clases y gemas) desde el panel de administración.

## Estructura

- `builder/models.py` — GameClass, Gem, Build, BuildGem, BuildVote
- `builder/views.py` — listar/filtrar builds, ver detalle, crear build
- `builder/templates/builder/` — plantillas HTML básicas (sin diseño aún)
- `builder/admin.py` — panel para cargar clases y gemas manualmente

## Datos incluidos

`builder/management/commands/seed_trove_data.py` carga automáticamente:
- Las 18 clases reales de Trove (Bard, Boomeranger, Candy Barbarian, Chloromancer,
  Dino Tamer, Dracolyte, Fae Trickster, Gunslinger, Ice Sage, Knight, Lunar Lancer,
  Neon Ninja, Pirate Captain, Revenant, Shadow Hunter, Solarion, Tomb Raiser, Vanguardian)
- 20 gemas genéricas:
  - 8 gemas menores (Lesser): los 4 elementos (Water/Air/Fire/Cosmic) x 2 variantes
    de daño reales — **Fierce** (solo Physical Damage) y **Arcane** (solo Magic
    Damage). A partir de rareza Shadow, el juego nunca mezcla ambos tipos en una
    gema menor (confirmado en trove.fandom.com/wiki/Gem).
  - 12 gemas empoderadas con nombre, efecto y **estadísticas mecánicas exactas**
    (probabilidad de activación, cooldown, fórmula de daño, duración, etc.) en
    `Gem.stat_scaling`: 8 generales (Explosive Epilogue, Cubic Curtain, Mired
    Mojo, Pyrodisc, Spirit Surge, Stinging Curse, Stunburst, Volatile Velocity) y
    4 Cosmic confirmadas (Berserk Battler, Vampirian Vanquisher, Empyrean
    Barrier, Flower Power). El elemento exacto (Water/Air/Fire) de las 8
    generales no está confirmado en la fuente, así que se deja en blanco en vez
    de inventarlo.
- 14 Class Gems reales (gemas exclusivas de una clase, obtenidas en Shores of the
  Everdark), cada una vinculada a su clase mediante `Gem.restricted_to_class`.
  Ej: Spirit Squire (Knight), Bawk-Bomb (Boomeranger), Overcharged (Gunslinger).
  Bard, Dino Tamer, Solarion y Vanguardian no tienen una Class Gem documentada
  todavía en las fuentes consultadas.

Puedes correr `python manage.py seed_trove_data` las veces que quieras; no duplica datos
(usa `get_or_create`).

## Equipo (Weapon / Hat / Face / Ring)

Además de gemas, ahora el sistema modela el equipo real de Trove:

- `EquipmentSlot`: catálogo de referencia (no items específicos, sino las reglas de
  stats) para Weapon, Hat, Face y Ring, separado por tier (Crystal vs No-Crystal).
  Incluye qué stat es fijo en cada posición y cuáles son roleables — datos reales de
  trovesaurus.com/rolls. Ej: Hat y Face siempre tienen Max Health fijo en la
  posición 1; el Weapon tiene Physical o Magic Damage fijo según el `damage_type`
  de la clase que lo usa.
- `BuildEquipment`: lo que el usuario elige para su build — a qué `EquipmentSlot`
  corresponde y qué stats prioriza en las posiciones variables (ej. Critical Hit +
  Critical Damage en el Weapon).

Igual que con las gemas: el equipo en sí no está restringido a una clase por el
juego, pero solo tiene sentido si sus stats calzan con el `damage_type` de la
clase (por eso Face puede rolear Magic Damage O Physical Damage en su tercera
posición — sirve para ambos tipos de clase, pero solo uno de los dos te sirve
según cuál juegues).

## Subclases

Sistema real desde el parche Eclipse: cada clase tiene una habilidad pasiva de
"firma" (su Subclass) que **cualquier otra clase puede equipar** como bono
adicional — pero nunca la propia. Ej: un Knight puede usar la subclase de
Lunar Lancer ("Sorta Crazy"), pero no la suya propia ("Mounted Cavalry").

- `Subclass`: catálogo con las 18 subclases reales (una por clase), con su **tabla
  completa de progresión**: 9 tiers según el Power Rank del personaje
  (`tier_progression`, ej. "IX: 40,000-44,999 PR → Jubilant 20%...") y 6 niveles de
  bono de stat (`level_bonus_progression`, ej. "Nivel 30 → +20% Critical Damage").
  Fuente: PDF "Trove - Subclassing" (datos exactos por tier), cruzado con
  trovesaurus.com/subclasses. El detalle de cada build muestra esta tabla completa
  en un desplegable.
  ⚠ Nota: el dato de Chloromancer ("5000% reflect") viene textual de la fuente tal
  cual — se conserva sin corregir porque no se pudo confirmar si es un error de la
  fuente original o el valor real.
- `Build.subclass`: la subclase elegida para la build. La vista `build_create`
  valida en el servidor que no sea la subclase de la propia `primary_class`;
  si lo es, se descarta con un mensaje de advertencia (probado con el test
  client de Django).

## Cómo funcionan las restricciones de gemas (importante)

- **Gemas genéricas** (Water/Air/Fire y las empoderadas tipo Berserk Battler, Shield of
  Reprisal, etc.): el juego permite equiparlas en **cualquier clase**. Lo que las hace
  útiles o no es si sus stats coinciden con el `damage_type` de la clase (Physical vs
  Magic Damage) — por eso `GameClass.damage_type` existe: no para restringir, sino para
  poder mostrar/sugerir qué stats tienen sentido en cada clase (10 clases Physical,
  8 Magic).
- **Class Gems** (Spirit Squire, Bawk-Bomb, Overcharged, etc.): estas sí están
  restringidas de verdad por el juego a una sola clase (`Gem.restricted_to_class`).
  La vista `build_create` valida esto en el servidor: si intentas meter una Class Gem
  que no corresponde a la clase principal de la build, se descarta y se muestra un
  mensaje de advertencia en vez de guardarse silenciosamente mal.

## Dragones y otras fuentes de Power Rank

Además de gemas y equipo, el Power Rank de un personaje también sube por:

- `Dragon`: dragones desbloqueados permanentemente, que dan un bono de PR **a
  nivel de cuenta** (no por build/clase). Hay dos tipos: **normales** (~+30 PR
  fijo cada uno) y **Primordiales** (dan +10% de bono sobre el PR de un tipo de
  gema específico, ej. Taeryn Veernok da +10% sobre gemas Cósmicas). Solo se
  cargaron 2 dragones de ejemplo con datos confirmados por captura de pantalla
  real (Drak-o-Lantern y Taeryn Veernok); el juego tiene decenas más no
  catalogados por falta de datos verificados.
- **Mastery y Geode Mastery**: suben el PR de toda la cuenta al completar la
  colección de objetos/gemas del juego. No se modelan como tabla propia porque
  son progreso de cuenta, no una elección de build — se documentan aquí como
  contexto: los primeros 500 niveles de Mastery dan +4 PR cada uno (luego +1 PR
  +1 Magic Find); los primeros 100 niveles de Geode Mastery dan +5 PR y +10
  Light cada uno.
- **Rareza de gemas y equipo**: la escala real es Common → Uncommon → Rare →
  Epic → Legendary → Relic → Resplendent → Shadow → Radiant → Stellar →
  Crystal (C1 a C5). `Gem.max_rank` se corrigió a **30** (antes decía 15 por
  error): una gema Stellar tiene tope de nivel 25, una Crystal tiene tope 30 —
  confirmado con capturas de pantalla reales del juego. El nivel máximo
  realista de equipo antes de 30k PR es Crystal nivel 4 (C4); C5 casi no es
  alcanzable en ese rango.

Fuente de esta sección: PDF "Guía de Power Rank" (Mystic Cave, por zexy1).

## Siguientes pasos sugeridos

1. Agregar Class Gems para Bard, Dino Tamer, Solarion y Vanguardian cuando se
   documenten (o revisando directamente el juego/wiki).
2. Mejorar el diseño (CSS / frontend con React si se quiere más interactividad).
3. Agregar sistema de votos/rating desde la vista (ya existe el modelo BuildVote).
4. Agregar API REST (djangorestframework ya está instalado) para consumir builds
   desde un frontend separado si se desea.
5. Despliegue (Render, Railway, PythonAnywhere, etc.) con PostgreSQL en producción.
