from django.db import models, transaction
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import uuid


class GameVersion(models.Model):
    """
    Una version (parche) del juego, ej: "Rematch". Cada build queda atada a la
    version en la que se creo o se confirmo por ultima vez, para saber si
    sigue al dia cuando sale un parche nuevo (pilar "builds vivos" del plan).
    Solo UNA version puede ser la actual (is_current) a la vez.
    """
    name = models.CharField(max_length=80, unique=True)
    released_on = models.DateField()
    patch_notes_url = models.URLField(blank=True)
    is_current = models.BooleanField(default=False)
    affected_classes = models.ManyToManyField(
        "GameClass", blank=True, related_name="affected_by_versions",
        help_text="Clases que este parche cambio. Sus builds se marcaran para revisar."
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-released_on"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_current:
                GameVersion.objects.exclude(pk=self.pk).filter(is_current=True).update(is_current=False)
            super().save(*args, **kwargs)

    @classmethod
    def current(cls):
        return cls.objects.filter(is_current=True).first()

    def publish(self):
        """
        Convierte esta version en la actual y pone al dia las builds:
        - Builds cuya clase principal esta en `affected_classes` -> "Revisar",
          y su autor recibe una notificacion.
        - El resto de builds al dia -> pasan a esta version sin tocar nada,
          porque el parche no las afecta.
        Devuelve cuantas builds quedaron para revisar.
        """
        with transaction.atomic():
            self.is_current = True
            self.save()
            affected_ids = list(self.affected_classes.values_list("id", flat=True))
            older = Build.objects.exclude(game_version=self)
            to_review = older.filter(primary_class_id__in=affected_ids, status="current")
            flagged = list(to_review.values_list("id", "owner_id"))
            to_review.update(status="review")
            older.exclude(primary_class_id__in=affected_ids).filter(
                status="current"
            ).update(game_version=self)
            Notification.objects.bulk_create([
                Notification(recipient_id=owner_id, verb="review", build_id=build_id)
                for build_id, owner_id in flagged
            ])
        return len(flagged)


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
        ("offense", _("Ofensiva")),
        ("defense", _("Defensiva")),
        ("utility", _("Utilidad")),
        ("class", _("Gema de Clase")),
    ]
    ELEMENT_CHOICES = [
        ("water", "Water"),
        ("air", "Air"),
        ("fire", "Fire"),
        ("cosmic", "Cosmic"),
    ]
    DAMAGE_VARIANT_CHOICES = [
        ("fierce", _("Fierce (solo Physical Damage)")),
        ("arcane", _("Arcane (solo Magic Damage)")),
        ("universal", _("Universal (Empowered/Class, cualquier tipo de daño)")),
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
        ("non_crystal", _("No-Crystal (Shadow/Radiant/Stellar)")),
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
        ("signatory_or_mystic", _("Signatory o Mystic Ring")),
        ("mystic_only", _("Solo en Mystic Ring")),
        ("shared_dodge", _("Efecto compartido de esquive (Mystic Ring)")),
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
        ("normal", _("Dragón normal")),
        ("primordial", _("Dragón Primordial (de gemas)")),
    ]
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    dragon_type = models.CharField(max_length=15, choices=DRAGON_TYPE_CHOICES)
    description = models.TextField(blank=True)
    power_rank_bonus = models.CharField(
        max_length=300,
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
        ("beginner", _("Beginner Friendly")),
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
    ally = models.ForeignKey(
        "EquipmentItem", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="builds_as_ally", limit_choices_to={"kind": "ally"},
    )
    emblem = models.ForeignKey(
        "EquipmentItem", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="builds_as_emblem", limit_choices_to={"kind": "emblem"},
    )
    flask = models.ForeignKey(
        "EquipmentItem", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="builds_as_flask", limit_choices_to={"kind": "flask"},
    )
    banner = models.ForeignKey(
        "EquipmentItem", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="builds_as_banner", limit_choices_to={"kind": "banner"},
        help_text="Algunos banners dan Physical Damage o Magic Damage: conviene "
                   "elegir el que combine con el damage_type de la clase.",
    )
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)  # lista de strings de TAG_CHOICES
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    share_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # --- Builds vivos (Fase 0 del plan) ---
    STATUS_CHOICES = [
        ("current", _("Al día")),
        ("review", _("Revisar")),
        ("stale", _("Obsoleto")),
    ]
    LANGUAGE_CHOICES = [
        ("es", "Español"),
        ("en", "English"),
    ]
    game_version = models.ForeignKey(
        GameVersion, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="builds",
        help_text="Version del juego en la que se creo o confirmo por ultima vez."
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="current")
    verified_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Ultima vez que el autor guardo o confirmo que la build sigue al dia."
    )
    remixed_from = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="remixes",
        help_text="Build original de la que se hizo este remix (se conserva el credito)."
    )
    language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, default="es")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.owner.username})"

    def get_absolute_url(self):
        return reverse("builder:build_detail", kwargs={"slug": self.slug})

    def snapshot(self):
        """
        Foto completa del estado actual de la build, en JSON. Usa slugs y
        nombres en vez de ids para que siga siendo legible aunque se
        re-siembren los datos del juego.
        """
        return {
            "name": self.name,
            "primary_class": self.primary_class.slug if self.primary_class_id else None,
            "secondary_class": self.secondary_class.slug if self.secondary_class_id else None,
            "subclass": self.subclass.name if self.subclass_id else None,
            "description": self.description,
            "tags": list(self.tags or []),
            "language": self.language,
            "gems": [
                {"slot": bg.slot_number, "gem": bg.gem.slug, "rank": bg.rank,
                 "stats": list(bg.chosen_stats or [])}
                for bg in self.gem_slots.select_related("gem").order_by("slot_number")
            ],
            "equipment": [
                {"slot_type": eq.slot.slot_type, "tier": eq.slot.tier,
                 "stats": list(eq.chosen_stats or [])}
                for eq in self.equipment.select_related("slot").order_by("slot__slot_type")
            ],
            "items": {
                kind: (getattr(self, kind).source_path if getattr(self, f"{kind}_id") else None)
                for kind in ("ally", "emblem", "flask", "banner")
            },
        }

    def latest_revision(self):
        return self.revisions.order_by("-number").first()

    def record_revision(self, author=None):
        """
        Guarda una revision nueva SOLO si la build cambio desde la ultima.
        Tambien deja la build atada a la version actual del juego y al dia.
        Devuelve la revision creada, o None si no hubo cambios.
        """
        data = self.snapshot()
        version = GameVersion.current()
        last = self.latest_revision()
        now = timezone.now()

        Build.objects.filter(pk=self.pk).update(
            game_version=version, status="current", verified_at=now,
        )
        self.game_version, self.status, self.verified_at = version, "current", now

        if last is not None and last.data == data:
            return None
        return BuildRevision.objects.create(
            build=self,
            number=(last.number + 1) if last else 1,
            game_version=version,
            author=author,
            data=data,
        )

    def confirm_up_to_date(self):
        """El autor confirma (sin editar) que la build sigue funcionando en la
        version actual del juego. No crea revision nueva: la build no cambio."""
        now = timezone.now()
        version = GameVersion.current()
        Build.objects.filter(pk=self.pk).update(
            game_version=version, status="current", verified_at=now,
        )
        self.game_version, self.status, self.verified_at = version, "current", now

    @property
    def needs_review(self):
        return self.status != "current" or self.is_outdated_version

    @property
    def is_outdated_version(self):
        """True si la build se confirmo en una version anterior a la actual."""
        current = GameVersion.current()
        return bool(current and self.game_version_id and self.game_version_id != current.id)

    @property
    def score(self):
        agg = self.votes.aggregate(total=models.Sum("value"))
        return agg["total"] or 0

    @property
    def equipment_items_list(self):
        """Ally/Emblem/Flask/Banner elegidos, solo los que estan seteados."""
        return [i for i in (self.ally, self.emblem, self.flask, self.banner) if i]


class BuildRevision(models.Model):
    """
    Revision inmutable de una build: una foto en JSON de como estaba al
    guardarse, atada a la version del juego de ese momento. Las tablas
    BuildGem/BuildEquipment siguen siendo el estado "vivo" que usa el editor;
    las revisiones son el historial.
    """
    build = models.ForeignKey(Build, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    game_version = models.ForeignKey(
        GameVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name="revisions"
    )
    author = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["build", "number"], name="unique_revision_number_per_build")
        ]

    def __str__(self):
        return f"{self.build.name} · rev {self.number}"


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


class Notification(models.Model):
    """
    Aviso simple para el dueño de una build cuando alguien mas comenta o
    vota en ella. No se genera cuando el dueño interactua con su propia
    build.
    """
    VERB_CHOICES = [
        ("comment", _("comentó en tu build")),
        ("vote", _("votó tu build")),
        ("review", _("El nuevo parche puede afectar tu build")),
    ]
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+", null=True, blank=True)
    verb = models.CharField(max_length=10, choices=VERB_CHOICES)
    build = models.ForeignKey(Build, on_delete=models.CASCADE, related_name="notifications")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        actor_name = self.actor.username if self.actor else "Alguien"
        return f"{actor_name} {self.get_verb_display()} '{self.build.name}' (para {self.recipient.username})"


class Suggestion(models.Model):
    """Sugerencia o reporte de bug que un usuario manda sobre el sitio."""
    CATEGORY_CHOICES = [
        ("bug", _("Reportar un problema")),
        ("idea", _("Sugerir una idea")),
        ("other", _("Otro")),
    ]
    STATUS_CHOICES = [
        ("new", _("Nueva")),
        ("reviewed", _("Revisada")),
        ("done", _("Hecha")),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="suggestions")
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default="idea")
    title = models.CharField(max_length=120)
    description = models.TextField(max_length=2000)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="new")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_category_display()}] {self.title} ({self.user.username})"


class EquipmentItem(models.Model):
    """
    Ally, Emblem o Flask real del juego (no una regla generica como
    EquipmentSlot, sino un item concreto con nombre y stats propios).
    Se puebla automaticamente desde la Kiwi API de Better Trove Tools
    (api.aallyn.net/v1/codexes/...), que expone estos datos ya parseados
    del cliente del juego. Ver: builder/management/commands/sync_trove_codex.py
    """
    KIND_CHOICES = [
        ("ally", "Ally"),
        ("emblem", "Emblem"),
        ("flask", "Flask"),
        ("banner", "Banner"),
    ]
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170)
    # "path" del codex (ej: "item/emblem/masterchick"), es el id estable que
    # usamos para actualizar en vez de duplicar cuando se vuelve a sincronizar.
    source_path = models.CharField(max_length=255)
    category = models.CharField(
        max_length=100, blank=True,
        help_text="Subcategoria tal como la reporta el codex (ej: 'minion', 'buff')."
    )
    description = models.TextField(blank=True)
    icon_url = models.URLField(blank=True)
    tradable = models.BooleanField(default=False)
    mastery = models.PositiveIntegerField(null=True, blank=True)
    power_rank = models.PositiveIntegerField(null=True, blank=True)
    # Bonos numericos tal como los reporta el codex:
    # [{"stat_name": "Physical Damage", "amount": 10, "is_percent": True, ...}, ...]
    stats = models.JSONField(default=list, blank=True)
    # Habilidades/efectos (ej: lo que dispara un Emblem al usar el Flask):
    # [{"name": "...", "description": "..."}, ...]
    abilities = models.JSONField(default=list, blank=True)
    # Blob completo de "data" del codex, por si se necesita algo no modelado arriba.
    raw_data = models.JSONField(default=dict, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "source_path"], name="unique_equipmentitem_kind_source_path"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.get_kind_display()})"

    def damage_type_hint(self):
        """
        Revisa los stats reales (traidos de la Kiwi API) y devuelve 'physical'
        si el item da Physical Damage, 'magic' si da Magic Damage, o '' si no
        da ninguno de los dos (neutral, sirve para cualquier clase). Se usa
        para marcar en el formulario de build si un Banner/Ally/etc. combina
        con el damage_type de la clase elegida.
        """
        names = " ".join(
            str(s.get("stat_name") or s.get("label") or "") for s in (self.stats or [])
        ).lower()
        has_physical = "physical damage" in names
        has_magic = "magic damage" in names
        if has_physical and not has_magic:
            return "physical"
        if has_magic and not has_physical:
            return "magic"
        return ""
