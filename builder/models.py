from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse
import uuid


class GameClass(models.Model):
    """Una clase jugable de Trove (Knight, Pirate Captain, Dracolyte, etc.)"""
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    description = models.TextField(blank=True)
    icon_url = models.URLField(blank=True)
    ROLE_CHOICES = [
        ("tank", "Tank"),
        ("dps", "DPS"),
        ("healer", "Healer"),
        ("support", "Support"),
    ]
    primary_role = models.CharField(max_length=20, choices=ROLE_CHOICES, blank=True)
    DAMAGE_TYPE_CHOICES = [
        ("physical", "Physical Damage"),
        ("magic", "Magic Damage"),
    ]
    damage_type = models.CharField(
        max_length=10, choices=DAMAGE_TYPE_CHOICES, blank=True,
        help_text="Determina si esta clase escala con Physical Damage o Magic Damage. "
                   "No restringe qué gemas se pueden equipar, solo cuáles stats sirven."
    )

    class Meta:
        verbose_name_plural = "Game classes"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Subclass(models.Model):
    """
    La habilidad pasiva de subclase de cada clase (sistema desde el parche Eclipse).
    Cada clase tiene exactamente una: la propia (game_class) es la fuente, pero
    CUALQUIER OTRA clase puede equiparla como su subclase (nunca la propia).
    Fuente: PDF "Trove - Subclassing" (tabla completa por Tier de Power Rank y
    nivel de subclase), cruzado con trovesaurus.com/subclasses.
    """
    game_class = models.OneToOneField(
        GameClass, on_delete=models.CASCADE, related_name="subclass"
    )
    name = models.CharField(max_length=80)
    passive_description = models.TextField(
        help_text="Descripción corta de la pasiva (efecto del Tier I, como referencia rápida)."
    )
    bonus_stat = models.CharField(
        max_length=60,
        help_text="Stat que otorga como bono fijo al equipar esta subclase, ej: "
                   "'Critical Damage', 'Jump', 'Magic Find'."
    )
    bonus_range = models.CharField(
        max_length=40, blank=True,
        help_text="Rango del bono segun el nivel de subclase (1 a 30), ej: '+1% a +20%'."
    )
    # Progresion completa de la pasiva segun el Power Rank del personaje.
    # Lista de {"tier": "I", "power_rank": "1 - 4,999", "effect": "..."}
    tier_progression = models.JSONField(default=list, blank=True)
    # Progresion completa del bono de stat segun el nivel de subclase (1 a 30).
    # Lista de {"level": 1, "bonus": "+1% Critical Damage"}
    level_bonus_progression = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["game_class__name"]

    def __str__(self):
        return f"{self.name} ({self.game_class.name})"


class Gem(models.Model):
    """Una gema equipable, con stats que escalan por rango."""
    TYPE_CHOICES = [
        ("offense", "Ofensiva"),
        ("defense", "Defensiva"),
        ("utility", "Utilidad"),
        ("class", "Gema de Clase"),
    ]
    ELEMENT_CHOICES = [
        ("water", "Water"),
        ("air", "Air"),
        ("fire", "Fire"),
        ("cosmic", "Cosmic"),
    ]
    DAMAGE_VARIANT_CHOICES = [
        ("fierce", "Fierce (solo Physical Damage)"),
        ("arcane", "Arcane (solo Magic Damage)"),
        ("universal", "Universal (Empowered/Class, cualquier tipo de daño)"),
    ]
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    gem_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    element = models.CharField(max_length=10, choices=ELEMENT_CHOICES, blank=True)
    damage_variant = models.CharField(
        max_length=10, choices=DAMAGE_VARIANT_CHOICES, blank=True,
        help_text="Solo aplica a gemas menores (Shadow/Radiant/Stellar): son Fierce "
                   "(Physical) o Arcane (Magic), nunca ambas. Empowered/Class gems son universales."
    )
    max_rank = models.PositiveSmallIntegerField(
        default=30,
        help_text="Nivel máximo de la gema. Depende de su rareza real al dropear "
                   "(Common...Shadow...Radiant...Stellar...Crystal), no del tipo de "
                   "gema en sí: Stellar tope 25, Crystal tope 30 (confirmado por "
                   "capturas de pantalla del juego). 30 aquí representa el techo "
                   "teórico en la mejor rareza posible."
    )
    restricted_to_class = models.ForeignKey(
        "GameClass", on_delete=models.CASCADE, null=True, blank=True,
        related_name="class_gems",
        help_text="Si se define, esta gema solo puede usarse con esta clase (Class Gem)."
    )
    description = models.TextField(blank=True)
    icon_url = models.URLField(blank=True)
    # stats base y por rango en JSON,
    # ej: {"crit_damage": {"base": 5, "per_rank": 1.5}}
    stat_scaling = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class EquipmentSlot(models.Model):
    """
    Catalogo de referencia: que stats puede tener cada tipo de equipo (Weapon,
    Hat, Face, Ring) en cada posicion, segun las reglas reales del juego.
    No representa un item especifico (Trove tiene miles de skins cosmeticas),
    sino la plantilla de stats que cualquier item de ese slot puede rolear.
    Fuente: trovesaurus.com/rolls (Equipment Stat Rolls)
    """
    SLOT_CHOICES = [
        ("weapon", "Weapon"),
        ("hat", "Hat"),
        ("face", "Face"),
        ("ring", "Ring"),
    ]
    TIER_CHOICES = [
        ("non_crystal", "No-Crystal (Shadow/Radiant/Stellar)"),
        ("crystal", "Crystal"),
        ("signatory", "Signatory"),
        ("wisdom", "Wisdom"),
        ("power", "Power"),
        ("vitality", "Vitality"),
        ("delving", "Delving"),
    ]
    slot_type = models.CharField(max_length=10, choices=SLOT_CHOICES)
    tier = models.CharField(max_length=15, choices=TIER_CHOICES, blank=True)
    # Stat(s) fijos que siempre aparecen en la posicion 1 (y 2 en Crystal Weapon).
    # Para "weapon" esto depende del damage_type de la clase (Physical/Magic Damage),
    # no es literalmente fijo, se resuelve en tiempo de build.
    fixed_stats = models.JSONField(default=list, blank=True)
    # Stats que se pueden rolear en las posiciones variables, en JSON:
    # {"2": ["Attack Speed", "Movement Speed", ...], "3": [...], "4": [...]}
    rollable_stats_by_position = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["slot_type", "tier"]
        constraints = [
            models.UniqueConstraint(fields=["slot_type", "tier"], name="unique_slot_tier")
        ]

    def __str__(self):
        tier_label = dict(self.TIER_CHOICES).get(self.tier, "")
        return f"{self.get_slot_type_display()} ({tier_label})" if tier_label \
            else self.get_slot_type_display()

    def irrelevant_stat_for(self, game_class):
        """
        Devuelve el nombre del stat de daño (Physical o Magic Damage) que NO le
        sirve a la clase dada, si este slot puede rolear ambos. Util para que la
        UI marque ese roll como desperdiciado. Devuelve None si no aplica.
        """
        if not game_class.damage_type:
            return None
        wrong = "Magic Damage" if game_class.damage_type == "physical" else "Physical Damage"
        all_rollable = [s for stats in self.rollable_stats_by_position.values() for s in stats]
        return wrong if wrong in all_rollable else None


class RingHiddenEffect(models.Model):
    """
    Efecto Oculto (Hidden Effect) de anillo: una habilidad especial que
    modifica una habilidad de clase, activable colocando el anillo en un
    Ring Polisher. CORREGIDO: cada clase en realidad tiene VARIOS Hidden
    Effects (no solo uno) — 3 "Signatory or Mystic" + 1 "Mystic only" — mas
    un efecto compartido de esquive ("Rushed Escape") que aplica a todas las
    clases excepto Shadow Hunter (que tiene su propia variante, "Casual
    Escape"). Un anillo dado solo expone UN PAR de esos efectos a la vez;
    Ring Polishing activa uno del par.
    Fuente: trovesaurus.com/polished-paragon/hidden-effects (los 3 "Signatory
    or Mystic" de cada clase, pagina mantenida por la comunidad) +
    trovegame.com/patch-notes/patch-notes-ring-it-on (el 4to "Mystic only").
    COBERTURA: las 18 clases tienen sus 4 efectos propios completos, mas el
    efecto de esquive compartido ("Rushed Escape"/"Casual Escape").
    """
    AVAILABILITY_CHOICES = [
        ("signatory_or_mystic", "Signatory o Mystic Ring"),
        ("mystic_only", "Solo en Mystic Ring"),
        ("shared_dodge", "Efecto compartido de esquive (Mystic Ring)"),
    ]
    game_class = models.ForeignKey(
        GameClass, on_delete=models.CASCADE, related_name="ring_hidden_effects",
        null=True, blank=True,
        help_text="En blanco solo para el 'Rushed Escape' generico, compartido "
                   "por todas las clases excepto Shadow Hunter."
    )
    name = models.CharField(max_length=80)
    description = models.TextField()
    availability = models.CharField(max_length=20, choices=AVAILABILITY_CHOICES)

    class Meta:
        ordering = ["game_class__name", "availability"]

    def __str__(self):
        class_label = self.game_class.name if self.game_class else "cualquier clase"
        return f"{self.name} ({class_label})"


class BuildEquipment(models.Model):
    """
    Lo que el usuario elige para una pieza de equipo dentro de su build: no es
    un item especifico (hay miles de skins), sino que stats prioriza en cada
    posicion variable, segun las reglas de EquipmentSlot.
    """
    build = models.ForeignKey("Build", on_delete=models.CASCADE, related_name="equipment")
    slot = models.ForeignKey(EquipmentSlot, on_delete=models.PROTECT)
    # lista de stats elegidos para las posiciones variables, ej: ["Critical Hit", "Critical Damage"]
    chosen_stats = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["slot__slot_type"]

    def __str__(self):
        return f"{self.slot} en {self.build.name}"


class Dragon(models.Model):
    """
    Los dragones son monturas/mascotas que, una vez desbloqueados
    permanentemente, otorgan un bono fijo de Power Rank (y a veces otras
    stats) a TODOS los personajes de la cuenta, sin ocupar un slot de build.
    No son parte del loadout de una clase especifica, pero se documentan aca
    porque son una fuente real de Power Rank que conviene tener en cuenta.
    Fuente: PDF "Guía de Power Rank" (Mystic Cave / zexy1).
    """
    DRAGON_TYPE_CHOICES = [
        ("normal", "Dragón normal"),
        ("primordial", "Dragón Primordial (de gemas)"),
    ]
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    dragon_type = models.CharField(max_length=15, choices=DRAGON_TYPE_CHOICES)
    description = models.TextField(blank=True)
    power_rank_bonus = models.CharField(
        max_length=120,
        help_text="Bono de Power Rank que otorga una vez desbloqueado, ej: "
                   "'+30 PR fijo' o '+10% del PR total de gemas'."
    )

    class Meta:
        ordering = ["dragon_type", "name"]

    def __str__(self):
        return self.name


class Build(models.Model):
    """Una build creada por un usuario: clase(s) + gemas + descripcion."""
    TAG_CHOICES = [
        ("pve", "PvE"),
        ("pvp", "PvP"),
        ("dungeon", "Dungeon"),
        ("farming", "Farming"),
        ("beginner", "Beginner Friendly"),
        ("endgame", "Endgame"),
        ("tank", "Tank"),
        ("dps", "DPS"),
        ("healer", "Healer"),
        ("support", "Support"),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="builds")
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    primary_class = models.ForeignKey(
        GameClass, on_delete=models.PROTECT, related_name="builds_as_primary"
    )
    secondary_class = models.ForeignKey(
        GameClass, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="builds_as_secondary"
    )
    subclass = models.ForeignKey(
        Subclass, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="used_in_builds",
        help_text="Subclase equipada (la habilidad pasiva de OTRA clase). Nunca "
                   "puede ser la subclase de la propia primary_class."
    )
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)  # lista de strings de TAG_CHOICES
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    share_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.owner.username})"

    def get_absolute_url(self):
        return reverse("builder:build_detail", kwargs={"slug": self.slug})

    @property
    def score(self):
        agg = self.votes.aggregate(total=models.Sum("value"))
        return agg["total"] or 0


class BuildGem(models.Model):
    """Gema equipada en una build, en un slot y rango especifico."""
    build = models.ForeignKey(Build, on_delete=models.CASCADE, related_name="gem_slots")
    gem = models.ForeignKey(Gem, on_delete=models.PROTECT, related_name="used_in_builds")
    slot_number = models.PositiveSmallIntegerField()
    rank = models.PositiveSmallIntegerField(default=1)
    # Solo aplica a gemas menores (Fierce/Arcane): las 2 stats elegidas dentro
    # del pool roleable de la gema (el 3er stat, el de daño, ya viene
    # garantizado por ser Fierce/Arcane y no se elige aqui).
    chosen_stats = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["slot_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["build", "slot_number"], name="unique_slot_per_build"
            )
        ]

    def __str__(self):
        return f"{self.gem.name} (rango {self.rank}) en slot {self.slot_number}"


class BuildVote(models.Model):
    """Voto/rating de un usuario sobre una build publica."""
    build = models.ForeignKey(Build, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="build_votes")
    value = models.SmallIntegerField(choices=[(1, "Up"), (-1, "Down")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["build", "user"], name="one_vote_per_user_per_build")
        ]


class BuildComment(models.Model):
    """Comentario de un usuario en una build. Cualquier usuario logueado puede
    comentar en cualquier build publica (o la propia, aunque sea privada)."""
    build = models.ForeignKey(Build, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="build_comments")
    text = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user.username} en {self.build.name}"


class BuildFavorite(models.Model):
    """
    Marca de "favorita" de un usuario sobre una build (propia o ajena),
    privada (solo la ve el usuario que la marco). Distinto del voto, que
    es publico y afecta el Power Rank score de la build.
    """
    build = models.ForeignKey(Build, on_delete=models.CASCADE, related_name="favorited_by")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="favorite_builds")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["build", "user"], name="one_favorite_per_user_per_build")
        ]

    def __str__(self):
        return f"{self.user.username} ♥ {self.build.name}"
