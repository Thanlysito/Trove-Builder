"""
Migracion de datos para los "builds vivos":

1. Crea la version del juego "Rematch" (15 sep 2026) y la marca como actual.
2. Ata cada build existente a esa version y guarda su estado actual como
   revision 1, para que ninguna build se quede sin historial.

La logica del snapshot esta copiada aqui a proposito (no se importa de
models.py): una migracion debe seguir funcionando igual aunque el modelo
cambie en el futuro.
"""
import datetime

from django.db import migrations


def _snapshot(build):
    return {
        "name": build.name,
        "primary_class": build.primary_class.slug if build.primary_class_id else None,
        "secondary_class": build.secondary_class.slug if build.secondary_class_id else None,
        "subclass": build.subclass.name if build.subclass_id else None,
        "description": build.description,
        "tags": list(build.tags or []),
        "language": build.language,
        "gems": [
            {"slot": bg.slot_number, "gem": bg.gem.slug, "rank": bg.rank,
             "stats": list(bg.chosen_stats or [])}
            for bg in build.gem_slots.select_related("gem").order_by("slot_number")
        ],
        "equipment": [
            {"slot_type": eq.slot.slot_type, "tier": eq.slot.tier,
             "stats": list(eq.chosen_stats or [])}
            for eq in build.equipment.select_related("slot").order_by("slot__slot_type")
        ],
        "items": {
            kind: (getattr(build, kind).source_path if getattr(build, f"{kind}_id") else None)
            for kind in ("ally", "emblem", "flask", "banner")
        },
    }


def forwards(apps, schema_editor):
    GameVersion = apps.get_model("builder", "GameVersion")
    Build = apps.get_model("builder", "Build")
    BuildRevision = apps.get_model("builder", "BuildRevision")

    GameVersion.objects.filter(is_current=True).update(is_current=False)
    rematch, _ = GameVersion.objects.update_or_create(
        name="Rematch",
        defaults={
            "released_on": datetime.date(2026, 9, 15),
            "patch_notes_url": "https://trovegame.com/patch-notes/patch-notes-rematch/",
            "is_current": True,
            "notes": "Rework de PvP: CTF, Bomber Royale, Deathmatch y Team Deathmatch en una sola cola.",
        },
    )

    for build in Build.objects.all().iterator():
        build.game_version = rematch
        build.status = "current"
        build.verified_at = build.updated_at
        build.save(update_fields=["game_version", "status", "verified_at"])
        if not BuildRevision.objects.filter(build=build).exists():
            BuildRevision.objects.create(
                build=build, number=1, game_version=rematch,
                author_id=build.owner_id, data=_snapshot(build),
            )


def backwards(apps, schema_editor):
    apps.get_model("builder", "BuildRevision").objects.all().delete()
    apps.get_model("builder", "Build").objects.update(game_version=None, verified_at=None)
    apps.get_model("builder", "GameVersion").objects.filter(name="Rematch").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("builder", "0021_build_versioning"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
