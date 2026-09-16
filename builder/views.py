from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login as auth_login
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.core.cache import cache
from django.utils.text import slugify
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import HttpResponseForbidden
from django.core.paginator import Paginator
from .forms import SignupForm
from .models import (
    Build, GameClass, Gem, BuildGem, Subclass, EquipmentSlot, BuildEquipment, BuildVote,
    BuildComment, RingHiddenEffect, BuildFavorite
)

# Pool de stats roleables compartido por TODAS las gemas menores (Fierce/Arcane),
# igual al usado en el seed (seed_trove_data.LESSER_GEM_STATS_UNIVERSAL). El 3er
# stat de daño (Physical/Magic) viene garantizado aparte por ser Fierce/Arcane.
LESSER_GEM_STAT_OPTIONS = [
    "Critical Hit", "Critical Damage", "Max Health", "Max Health %",
    "Health Regen", "Attack Speed", "Movement Speed", "Energy Regen", "Light",
]


def how_it_works(request):
    """Página estática que explica las mecánicas del juego a alguien nuevo."""
    return render(request, "builder/how_it_works.html")


def signup(request):
    """Registro de usuario nuevo. Al crear la cuenta, inicia sesión automaticamente."""
    if request.user.is_authenticated:
        return redirect("builder:build_list")

    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            if _rate_limited_by_ip(request, "signup", seconds=15):
                messages.warning(request, "Espera unos segundos antes de crear otra cuenta.")
                return render(request, "registration/signup.html", {"form": form})
            user = form.save()
            auth_login(request, user)
            messages.success(request, f"¡Bienvenido, {user.username}! Tu cuenta se creó correctamente.")
            return redirect("builder:build_list")
    else:
        form = SignupForm()

    return render(request, "registration/signup.html", {"form": form})


# Estructura real de slots de gema: 4 grandes (Empowered/Class, uno por
# elemento: Water/Air/Fire/Cosmic) + 8 pequeñas (Lesser Fierce/Arcane, 2 por
# elemento). Posiciones 1-4 = grandes, 5-12 = pequeñas.
BIG_SLOT_NUMBERS = list(range(1, 5))
SMALL_SLOT_NUMBERS = list(range(5, 13))
BIG_SLOT_COUNT = len(BIG_SLOT_NUMBERS)


SORT_OPTIONS = {
    "recent": "Más recientes",
    "votes": "Más votadas",
}


def _rate_limited(request, action, seconds):
    """
    Antispam simple: True si este usuario ya hizo `action` hace menos de
    `seconds` segundos (y en ese caso, reinicia el contador). Se guarda en
    el cache de Django (en memoria), no en la base de datos, para no pesar
    la tabla de comentarios/votos con esto.
    """
    key = f"ratelimit:{action}:{request.user.id}"
    if cache.get(key):
        return True
    cache.set(key, True, timeout=seconds)
    return False


def _rate_limited_by_ip(request, action, seconds):
    """Igual que _rate_limited, pero por IP — para acciones de usuarios
    todavia no logueados, como el registro de cuenta."""
    ip = request.META.get("REMOTE_ADDR", "unknown")
    key = f"ratelimit:{action}:{ip}"
    if cache.get(key):
        return True
    cache.set(key, True, timeout=seconds)
    return False


def _apply_sort(builds, sort_key):
    """Ordena un queryset de builds por 'recent' (default, el de Build.Meta)
    o 'votes' (suma de votos, de mayor a menor)."""
    if sort_key == "votes":
        return builds.annotate(vote_score=Sum("votes__value")).order_by(
            "-vote_score", "-created_at"
        )
    return builds  # ya viene ordenado por -created_at desde Build.Meta.ordering


def _attach_my_votes(request, builds):
    """Le agrega el atributo .my_vote a cada build de la lista (o None)."""
    if request.user.is_authenticated and builds:
        my_votes = {
            v.build_id: v.value
            for v in BuildVote.objects.filter(user=request.user, build_id__in=[b.id for b in builds])
        }
        for b in builds:
            b.my_vote = my_votes.get(b.id)
    else:
        for b in builds:
            b.my_vote = None
    return builds


def _attach_my_favorites(request, builds):
    """Le agrega el atributo .my_favorite (True/False) a cada build de la lista."""
    if request.user.is_authenticated and builds:
        favorited_ids = set(
            BuildFavorite.objects.filter(
                user=request.user, build_id__in=[b.id for b in builds]
            ).values_list("build_id", flat=True)
        )
        for b in builds:
            b.my_favorite = b.id in favorited_ids
    else:
        for b in builds:
            b.my_favorite = False
    return builds


BUILDS_PER_PAGE = 12


def _paginate(request, queryset):
    """Pagina un queryset (12 por pagina) y le agrega .my_vote/.my_favorite a la pagina actual."""
    paginator = Paginator(queryset, BUILDS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = _attach_my_votes(request, list(page_obj.object_list))
    page_obj.object_list = _attach_my_favorites(request, page_obj.object_list)
    return page_obj


def build_list(request):
    """Explorar builds publicas, con filtros simples por clase y tag."""
    builds = Build.objects.filter(is_public=True).select_related("primary_class", "owner")

    class_slug = request.GET.get("class")
    tag = request.GET.get("tag")
    search = request.GET.get("q")
    sort = request.GET.get("sort") if request.GET.get("sort") in SORT_OPTIONS else "recent"

    if class_slug:
        builds = builds.filter(primary_class__slug=class_slug)
    if tag:
        builds = builds.filter(tags__contains=[tag])
    if search:
        builds = builds.filter(Q(name__icontains=search) | Q(description__icontains=search))

    builds = _apply_sort(builds, sort)

    page_obj = _paginate(request, builds)
    extra_qs = request.GET.copy()
    extra_qs.pop("page", None)

    context = {
        "builds": page_obj.object_list,
        "page_obj": page_obj,
        "querystring": extra_qs.urlencode(),
        "classes": GameClass.objects.all(),
        "tag_choices": Build.TAG_CHOICES,
        "sort_options": SORT_OPTIONS,
        "current_sort": sort,
        "mine": False,
    }
    return render(request, "builder/build_list.html", context)


@login_required
def my_builds(request):
    """Solo las builds del usuario logueado, publicas y privadas por igual."""
    builds = Build.objects.filter(owner=request.user).select_related("primary_class", "owner")
    sort = request.GET.get("sort") if request.GET.get("sort") in SORT_OPTIONS else "recent"
    builds = _apply_sort(builds, sort)
    page_obj = _paginate(request, builds)

    context = {
        "builds": page_obj.object_list,
        "page_obj": page_obj,
        "querystring": f"sort={sort}",
        "classes": GameClass.objects.all(),
        "tag_choices": Build.TAG_CHOICES,
        "sort_options": SORT_OPTIONS,
        "current_sort": sort,
        "mine": True,
    }
    return render(request, "builder/build_list.html", context)


@login_required
def my_favorites(request):
    """Builds (propias o ajenas) que el usuario logueado marcó como favoritas."""
    builds = Build.objects.filter(favorited_by__user=request.user).select_related(
        "primary_class", "owner"
    )
    sort = request.GET.get("sort") if request.GET.get("sort") in SORT_OPTIONS else "recent"
    builds = _apply_sort(builds, sort)
    page_obj = _paginate(request, builds)

    context = {
        "builds": page_obj.object_list,
        "page_obj": page_obj,
        "querystring": f"sort={sort}",
        "classes": GameClass.objects.all(),
        "tag_choices": Build.TAG_CHOICES,
        "sort_options": SORT_OPTIONS,
        "current_sort": sort,
        "mine": False,
        "favorites_mode": True,
    }
    return render(request, "builder/build_list.html", context)


@login_required
def build_favorite_toggle(request, slug):
    """Marca/desmarca una build como favorita del usuario logueado. Solo POST."""
    build = get_object_or_404(Build, slug=slug)
    if not build.is_public and build.owner_id != request.user.id:
        return HttpResponseForbidden("No puedes marcar como favorita una build privada ajena.")

    if request.method != "POST":
        return redirect(build.get_absolute_url())

    if _rate_limited(request, "favorite", seconds=1):
        referer = request.META.get("HTTP_REFERER")
        if referer and url_has_allowed_host_and_scheme(
            referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(referer)
        return redirect(build.get_absolute_url())

    existing = BuildFavorite.objects.filter(build=build, user=request.user).first()
    if existing:
        existing.delete()
    else:
        BuildFavorite.objects.create(build=build, user=request.user)

    referer = request.META.get("HTTP_REFERER")
    if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(referer)
    return redirect(build.get_absolute_url())


def user_profile(request, username):
    """Perfil publico de un usuario: sus builds publicas (o todas, si es su propio perfil)."""
    profile_user = get_object_or_404(User, username=username)

    if request.user.is_authenticated and request.user.id == profile_user.id:
        builds = Build.objects.filter(owner=profile_user)
    else:
        builds = Build.objects.filter(owner=profile_user, is_public=True)

    builds = builds.select_related("primary_class", "owner")
    sort = request.GET.get("sort") if request.GET.get("sort") in SORT_OPTIONS else "recent"
    builds = _apply_sort(builds, sort)
    page_obj = _paginate(request, builds)

    context = {
        "profile_user": profile_user,
        "builds": page_obj.object_list,
        "page_obj": page_obj,
        "querystring": f"sort={sort}",
        "classes": GameClass.objects.all(),
        "tag_choices": Build.TAG_CHOICES,
        "sort_options": SORT_OPTIONS,
        "current_sort": sort,
        "mine": False,
        "is_own_profile": request.user.is_authenticated and request.user.id == profile_user.id,
        "public_build_count": Build.objects.filter(owner=profile_user, is_public=True).count(),
    }
    return render(request, "builder/user_profile.html", context)


def class_list(request):
    """Catálogo de las clases jugables, con su rol, tipo de daño y subclase."""
    classes = GameClass.objects.select_related("subclass").order_by("name")
    return render(request, "builder/class_list.html", {"classes": classes})


def class_detail(request, class_slug):
    """Ficha de una clase: subclase (Mastery), gemas de clase y Efectos Ocultos de anillo."""
    game_class = get_object_or_404(GameClass, slug=class_slug)
    subclass = getattr(game_class, "subclass", None)
    class_gems = game_class.class_gems.all()

    ring_hidden_effects = list(game_class.ring_hidden_effects.all())
    has_own_dodge_variant = any(e.availability == "shared_dodge" for e in ring_hidden_effects)
    if not has_own_dodge_variant:
        shared_dodge = RingHiddenEffect.objects.filter(
            game_class__isnull=True, availability="shared_dodge"
        ).first()
        if shared_dodge:
            ring_hidden_effects.append(shared_dodge)

    public_builds = Build.objects.filter(
        primary_class=game_class, is_public=True
    ).select_related("owner").order_by("-created_at")[:6]

    return render(request, "builder/class_detail.html", {
        "game_class": game_class,
        "subclass": subclass,
        "class_gems": class_gems,
        "ring_hidden_effects": ring_hidden_effects,
        "public_builds": public_builds,
    })


def build_detail(request, slug):
    build = get_object_or_404(Build, slug=slug)
    if not build.is_public and build.owner != request.user:
        return render(request, "builder/not_found.html", status=404)

    slots_by_number = {bg.slot_number: bg for bg in build.gem_slots.select_related("gem")}
    big_slots = [slots_by_number.get(i) for i in BIG_SLOT_NUMBERS]
    small_slots = [slots_by_number.get(i) for i in SMALL_SLOT_NUMBERS]

    # Gemas grandes compatibles con la clase de esta build: su Class Gem
    # exclusiva (si existe) + todas las Empowered universales.
    class_gem = Gem.objects.filter(restricted_to_class=build.primary_class).first()
    universal_big_gems = Gem.objects.filter(
        damage_variant="universal", restricted_to_class__isnull=True
    ).order_by("name")

    # Ring Hidden Effects que le aplican a esta clase: los suyos propios +
    # el "Rushed Escape" compartido (solo si la clase no tiene su propia
    # variante, como Shadow Hunter con "Casual Escape").
    ring_hidden_effects = list(build.primary_class.ring_hidden_effects.all())
    has_own_dodge_variant = any(e.availability == "shared_dodge" for e in ring_hidden_effects)
    if not has_own_dodge_variant:
        shared_dodge = RingHiddenEffect.objects.filter(
            game_class__isnull=True, availability="shared_dodge"
        ).first()
        if shared_dodge:
            ring_hidden_effects.append(shared_dodge)

    user_vote = None
    is_favorited = False
    if request.user.is_authenticated:
        vote = build.votes.filter(user=request.user).first()
        user_vote = vote.value if vote else None
        is_favorited = BuildFavorite.objects.filter(build=build, user=request.user).exists()

    return render(request, "builder/build_detail.html", {
        "build": build,
        "big_slots": big_slots,
        "small_slots": small_slots,
        "class_gem": class_gem,
        "universal_big_gems": universal_big_gems,
        "ring_hidden_effects": ring_hidden_effects,
        "user_vote": user_vote,
        "is_favorited": is_favorited,
        "upvotes": build.votes.filter(value=1).count(),
        "downvotes": build.votes.filter(value=-1).count(),
        "comments": build.comments.select_related("user"),
    })


@login_required
def build_vote(request, slug):
    """
    Vota +1 o -1 en una build. Si el usuario ya habia votado lo mismo,
    el voto se quita (toggle). Si habia votado lo contrario, se cambia.
    Solo acepta POST.
    """
    build = get_object_or_404(Build, slug=slug)
    if request.method != "POST":
        return redirect(build.get_absolute_url())

    value = request.POST.get("value")
    if value not in ("1", "-1"):
        return redirect(build.get_absolute_url())
    value = int(value)

    if _rate_limited(request, "vote", seconds=1):
        messages.warning(request, "Estás votando muy rápido, espera un segundo.")
        referer = request.META.get("HTTP_REFERER")
        if referer and url_has_allowed_host_and_scheme(
            referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(referer)
        return redirect(build.get_absolute_url())

    existing = BuildVote.objects.filter(build=build, user=request.user).first()
    if existing and existing.value == value:
        existing.delete()
    elif existing:
        existing.value = value
        existing.save(update_fields=["value"])
    else:
        BuildVote.objects.create(build=build, user=request.user, value=value)

    # Vuelve a donde se voto (lista con sus filtros, o el detalle), no siempre
    # al detalle, para que votar desde la lista no te saque de ahi.
    referer = request.META.get("HTTP_REFERER")
    if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(referer)
    return redirect(build.get_absolute_url())


@login_required
def build_duplicate(request, slug):
    """
    Crea una copia editable de una build (propia o de otro usuario) en la
    cuenta del usuario logueado: copia clase(s), subclase, tags, gemas y
    equipo. La copia siempre nace privada, para que el dueño la revise y
    ajuste antes de decidir si la hace pública.
    """
    source = get_object_or_404(Build, slug=slug)
    if not source.is_public and source.owner_id != request.user.id:
        return HttpResponseForbidden("No puedes duplicar una build privada ajena.")

    if request.method != "POST":
        return redirect(source.get_absolute_url())

    base_name = f"{source.name} (copia)"
    base_slug = slugify(base_name) + "-" + str(request.user.id)
    new_slug = base_slug
    suffix = 2
    while Build.objects.filter(slug=new_slug).exists():
        new_slug = f"{base_slug}-{suffix}"
        suffix += 1

    new_build = Build.objects.create(
        owner=request.user,
        name=base_name,
        slug=new_slug,
        primary_class=source.primary_class,
        secondary_class=source.secondary_class,
        subclass=source.subclass,
        description=source.description,
        tags=source.tags,
        is_public=False,
    )

    for bg in source.gem_slots.all():
        BuildGem.objects.create(
            build=new_build, gem_id=bg.gem_id, slot_number=bg.slot_number,
            rank=bg.rank, chosen_stats=bg.chosen_stats,
        )
    for eq in source.equipment.all():
        BuildEquipment.objects.create(
            build=new_build, slot_id=eq.slot_id, chosen_stats=eq.chosen_stats,
        )

    messages.success(
        request,
        f"Se creó una copia privada: '{new_build.name}'. Edítala y publícala cuando quieras."
    )
    return redirect(new_build.get_absolute_url())


@login_required
def build_delete(request, slug):
    """
    Elimina una build. SOLO el dueño puede borrarla — esto se valida en el
    servidor (no solo ocultando el boton en el template), asi que aunque
    alguien arme la peticion a mano no puede borrar una build ajena.
    """
    build = get_object_or_404(Build, slug=slug)

    if build.owner_id != request.user.id:
        return HttpResponseForbidden("No puedes eliminar la build de otro usuario.")

    if request.method != "POST":
        return redirect(build.get_absolute_url())

    build.delete()
    messages.success(request, f"Build '{build.name}' eliminada.")
    return redirect("builder:build_list")


@login_required
def build_add_comment(request, slug):
    """Publica un comentario en una build. Cualquier usuario logueado puede
    comentar en cualquier build a la que tenga acceso (publica, o la propia)."""
    build = get_object_or_404(Build, slug=slug)
    if not build.is_public and build.owner_id != request.user.id:
        return HttpResponseForbidden("No puedes comentar en una build privada ajena.")

    if request.method != "POST":
        return redirect(build.get_absolute_url())

    text = request.POST.get("text", "").strip()
    if not text:
        return redirect(build.get_absolute_url())

    if _rate_limited(request, "comment", seconds=10):
        messages.warning(request, "Espera unos segundos antes de comentar de nuevo.")
        return redirect(build.get_absolute_url())

    BuildComment.objects.create(build=build, user=request.user, text=text[:1000])
    return redirect(build.get_absolute_url())


@login_required
def build_delete_comment(request, comment_id):
    """Borra un comentario. El autor siempre puede borrar el suyo. Ademas, el
    dueño de la build puede moderar (borrar) cualquier comentario publicado
    en SU build, aunque no sea el autor — para poder quitar spam o abuso."""
    comment = get_object_or_404(BuildComment, id=comment_id)
    is_author = comment.user_id == request.user.id
    is_build_owner = comment.build.owner_id == request.user.id
    if not is_author and not is_build_owner:
        return HttpResponseForbidden("No puedes eliminar este comentario.")

    if request.method != "POST":
        return redirect(comment.build.get_absolute_url())

    build_url = comment.build.get_absolute_url()
    comment.delete()
    return redirect(build_url)


EQUIPMENT_SLOT_TYPES = ["weapon", "hat", "face", "ring"]


def _save_gems_and_equipment(build, request, errors):
    """
    Borra las gemas y el equipo actuales de la build y los vuelve a crear
    desde el POST. Se usa tanto al crear como al editar una build.
    `errors` se modifica in-place agregando los mensajes de validacion.
    """
    build.gem_slots.all().delete()
    build.equipment.all().delete()

    gem_ids = request.POST.getlist("gem_id")
    gem_ranks = request.POST.getlist("gem_rank")
    gem_stat1s = request.POST.getlist("gem_stat1")
    gem_stat2s = request.POST.getlist("gem_stat2")
    for slot, (gem_id, rank, stat1, stat2) in enumerate(
        zip(gem_ids, gem_ranks, gem_stat1s, gem_stat2s), start=1
    ):
        if not gem_id:
            continue
        gem = Gem.objects.get(id=gem_id)
        # Las Class Gems solo son válidas para su clase (restricción real del juego).
        # Las gemas genéricas (lesser/empowered) se pueden equipar en cualquier clase.
        if gem.restricted_to_class_id and str(gem.restricted_to_class_id) != str(build.primary_class_id):
            errors.append(
                f"{gem.name} es una Class Gem exclusiva de {gem.restricted_to_class.name}, "
                f"no se puede usar con {build.primary_class.name}."
            )
            continue
        # Slots 1-4 son "grandes" (Empowered/Class, universal). Slots 5-12 son
        # "pequeños" (Lesser Fierce/Arcane). Es una restricción real del juego:
        # una gema menor no cabe en un slot Empoderado y viceversa.
        is_big_slot = slot <= BIG_SLOT_COUNT
        is_big_gem = gem.damage_variant == "universal"
        if is_big_slot and not is_big_gem:
            errors.append(
                f"{gem.name} es una gema menor (pequeña) y no cabe en un slot "
                f"grande (Empoderado)."
            )
            continue
        if not is_big_slot and is_big_gem:
            errors.append(
                f"{gem.name} es una gema Empoderada/Class (grande) y no cabe en "
                f"un slot pequeño (Lesser)."
            )
            continue

        # Los 2 stats adicionales de una gema menor: deben venir del pool
        # valido y no repetirse entre si (una gema nunca tiene el mismo
        # stat dos veces).
        chosen_stats = []
        if not is_big_slot:
            picked = [s for s in (stat1, stat2) if s]
            invalid = [s for s in picked if s not in LESSER_GEM_STAT_OPTIONS]
            if invalid:
                errors.append(
                    f"{gem.name}: stat '{invalid[0]}' no es valido para una gema menor."
                )
            elif len(picked) != len(set(picked)):
                errors.append(
                    f"{gem.name}: no puedes elegir el mismo stat dos veces en la misma gema."
                )
            else:
                chosen_stats = picked

        BuildGem.objects.create(
            build=build, gem_id=gem_id, slot_number=slot, rank=rank or 1,
            chosen_stats=chosen_stats,
        )

    # Equipo: 4 tipos (Weapon/Hat/Face/Ring). Weapon/Hat/Face tienen tier
    # (Crystal o No-Crystal) y 3 stats variables reales (posiciones 2,3,4 en
    # No-Crystal o 3,4,5 en Crystal); Ring no tiene tier y solo 1 stat variable.
    for slot_type in EQUIPMENT_SLOT_TYPES:
        tier = request.POST.get(f"equip_tier_{slot_type}", "")
        stat1 = request.POST.get(f"equip_stat1_{slot_type}", "")
        stat2 = request.POST.get(f"equip_stat2_{slot_type}", "")
        stat3 = request.POST.get(f"equip_stat3_{slot_type}", "") if slot_type != "ring" else ""
        if not stat1 and not stat2 and not stat3:
            continue  # no se configuro esta pieza, se omite

        try:
            equip_slot = EquipmentSlot.objects.get(slot_type=slot_type, tier=tier)
        except EquipmentSlot.DoesNotExist:
            errors.append(
                f"No se encontró la configuración de equipo para {slot_type} "
                f"(tier '{tier}')."
            )
            continue

        pool = {s for stats in equip_slot.rollable_stats_by_position.values() for s in stats}
        picked = [s for s in (stat1, stat2, stat3) if s]
        invalid = [s for s in picked if s not in pool]
        if invalid:
            errors.append(
                f"{equip_slot}: '{invalid[0]}' no es un stat válido para esta pieza."
            )
            continue
        if len(picked) != len(set(picked)):
            errors.append(f"{equip_slot}: no puedes elegir el mismo stat dos veces.")
            continue

        BuildEquipment.objects.create(build=build, slot=equip_slot, chosen_stats=picked)


def _build_form_context(build=None):
    """Contexto compartido por el formulario de crear y editar build."""
    equipment_catalog = {}
    for es in EquipmentSlot.objects.all():
        stats_pool = sorted({s for stats in es.rollable_stats_by_position.values() for s in stats})
        equipment_catalog.setdefault(es.slot_type, {})[es.tier] = {
            "id": es.id,
            "stats": stats_pool,
            "fixed": es.fixed_stats,
        }

    context = {
        "classes": GameClass.objects.all(),
        "big_gems": Gem.objects.filter(damage_variant="universal"),
        "small_gems": Gem.objects.filter(damage_variant__in=["fierce", "arcane"]),
        "subclasses": Subclass.objects.select_related("game_class").all(),
        "lesser_gem_stat_options": LESSER_GEM_STAT_OPTIONS,
        "equipment_catalog": equipment_catalog,
        "tag_choices": Build.TAG_CHOICES,
        "big_slot_numbers": BIG_SLOT_NUMBERS,
        "small_slot_numbers": SMALL_SLOT_NUMBERS,
        "build": build,
        "editing": build is not None,
    }

    if build is not None:
        context["existing_gems"] = {
            str(bg.slot_number): bg for bg in build.gem_slots.select_related("gem")
        }
        context["existing_equipment"] = {
            eq.slot.slot_type: eq for eq in build.equipment.select_related("slot")
        }

    return context


@login_required
def build_create(request):
    if request.method == "POST":
        name = request.POST["name"]
        primary_class_id = request.POST["primary_class"]

        if _rate_limited(request, "build_create", seconds=3):
            messages.warning(request, "Espera unos segundos antes de crear otra build.")
            return render(request, "builder/build_form.html", _build_form_context())

        errors = []

        # La subclase es la pasiva de OTRA clase; el juego nunca permite usar la
        # subclase de la propia clase principal.
        subclass_id = request.POST.get("subclass") or None
        if subclass_id:
            subclass = Subclass.objects.get(id=subclass_id)
            if str(subclass.game_class_id) == str(primary_class_id):
                errors.append(
                    f"No puedes usar '{subclass.name}' como subclase: es la pasiva "
                    f"de tu propia clase principal ({subclass.game_class.name})."
                )
                subclass_id = None

        build = Build.objects.create(
            owner=request.user,
            name=name,
            slug=slugify(name) + "-" + str(request.user.id),
            primary_class_id=primary_class_id,
            secondary_class_id=request.POST.get("secondary_class") or None,
            subclass_id=subclass_id,
            description=request.POST.get("description", ""),
            tags=request.POST.getlist("tags"),
            is_public=bool(request.POST.get("is_public")),
        )

        _save_gems_and_equipment(build, request, errors)

        if errors:
            for e in errors:
                messages.warning(request, e)

        return redirect(build.get_absolute_url())

    return render(request, "builder/build_form.html", _build_form_context())


@login_required
def build_edit(request, slug):
    """
    Edita una build existente. SOLO el dueño puede editarla (mismo tipo de
    proteccion que build_delete). El slug NO cambia aunque cambie el nombre,
    para que los links existentes a esta build sigan funcionando.
    """
    build = get_object_or_404(Build, slug=slug)
    if build.owner_id != request.user.id:
        return HttpResponseForbidden("No puedes editar la build de otro usuario.")

    if request.method == "POST":
        primary_class_id = request.POST["primary_class"]
        errors = []

        subclass_id = request.POST.get("subclass") or None
        if subclass_id:
            subclass = Subclass.objects.get(id=subclass_id)
            if str(subclass.game_class_id) == str(primary_class_id):
                errors.append(
                    f"No puedes usar '{subclass.name}' como subclase: es la pasiva "
                    f"de tu propia clase principal ({subclass.game_class.name})."
                )
                subclass_id = None

        build.name = request.POST["name"]
        build.primary_class_id = primary_class_id
        build.secondary_class_id = request.POST.get("secondary_class") or None
        build.subclass_id = subclass_id
        build.description = request.POST.get("description", "")
        build.tags = request.POST.getlist("tags")
        build.is_public = bool(request.POST.get("is_public"))
        build.save()

        _save_gems_and_equipment(build, request, errors)

        if errors:
            for e in errors:
                messages.warning(request, e)
        messages.success(request, "Build actualizada.")

        return redirect(build.get_absolute_url())

    return render(request, "builder/build_form.html", _build_form_context(build))



