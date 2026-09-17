"""
Sincroniza Allies, Emblems y Flasks reales del juego contra la Kiwi API de
Better Trove Tools (api.aallyn.net), que expone estos datos ya parseados
del cliente de Trove. Es publica y no requiere token para los endpoints
de /v1/codexes/* (rotan a un limite mas generoso por IP: 150 req/min).

Fuente / referencia de la API: https://docs.aallyn.net/llms.txt

Uso:
    python manage.py sync_trove_codex
    python manage.py sync_trove_codex --kind ally      # solo un tipo
    python manage.py sync_trove_codex --dry-run        # no escribe en DB

Notas:
- Ally viene de su propio tipo de codex ("ally").
- Emblem y Flask NO son tipos de codex propios ni categorias separadas: en
  los archivos del juego ambos viven bajo la misma carpeta
  "prefabs/item/flask/..." y la categoria generica "Items" de la Kiwi API.
  Se distinguen solo porque el "name" de cada Emblem viene prefijado con
  "Emblem: " (ej. "Emblem: Beamer Emblem") mientras que un Flask real no
  trae ese prefijo (ej. "Elysian Flask"). Confirmado inspeccionando datos
  reales con --inspect.
- La API no expone URLs de icono directamente, asi que icon_url queda en
  blanco por ahora; se puede completar despues cruzando con trovesaurus.com
  si hace falta.
"""
import time

import requests
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from builder.models import EquipmentItem

API_BASE = "https://api.aallyn.net"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 20


class Command(BaseCommand):
    help = "Sincroniza Ally / Emblem / Flask desde la Kiwi API (api.aallyn.net)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--kind",
            choices=["ally", "emblem", "flask"],
            help="Sincronizar solo un tipo en vez de los tres.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Descarga y muestra el resumen pero no escribe en la base de datos.",
        )
        parser.add_argument(
            "--inspect",
            action="store_true",
            help="Muestra 15 paths/categorias de ejemplo dentro de item/Equipment y termina "
                 "(para averiguar el patron real cuando el filtro de path no encuentra nada).",
        )

    def handle(self, *args, **options):
        if options["inspect"]:
            self._inspect()
            return

        kinds = [options["kind"]] if options["kind"] else ["ally", "emblem", "flask"]
        dry_run = options["dry_run"]

        flask_folder_items = None  # cache: se pide una sola vez si hace falta emblem y/o flask

        for kind in kinds:
            if kind == "ally":
                entries = self._fetch_codex_type("ally")
            else:
                if flask_folder_items is None:
                    all_items = self._fetch_codex_type("item", category="Items")
                    flask_folder_items = [
                        e for e in all_items
                        if e.get("path", "").startswith("prefabs/item/flask/")
                    ]
                if kind == "emblem":
                    entries = [e for e in flask_folder_items if e.get("name", "").startswith("Emblem: ")]
                else:  # flask
                    entries = [e for e in flask_folder_items if not e.get("name", "").startswith("Emblem: ")]

            self.stdout.write(f"{kind}: {len(entries)} entradas encontradas")

            if dry_run:
                continue

            created, updated = self._save_entries(kind, entries)
            self.stdout.write(self.style.SUCCESS(
                f"{kind}: {created} creadas, {updated} actualizadas"
            ))

    # -- helpers ------------------------------------------------------

    def _get(self, path, params=None):
        url = f"{API_BASE}{path}"
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def _fetch_codex_type(self, codex_type, category=None):
        entries = []
        offset = 0
        while True:
            params = {"limit": PAGE_SIZE, "offset": offset}
            if category:
                params["category"] = category
            data = self._get(f"/v1/codexes/{codex_type}", params=params)
            page = data.get("items", [])
            entries.extend(page)
            total = data.get("total", len(entries))
            offset += PAGE_SIZE
            if total > PAGE_SIZE:
                self.stdout.write(f"  ...{min(offset, total)}/{total}", ending="\r")
            if offset >= total or not page:
                break
            time.sleep(0.2)  # sencillo, evita golpear el rate limit por IP
        if total > PAGE_SIZE:
            self.stdout.write("")  # salto de linea despues del progreso
        return entries

    def _save_entries(self, kind, entries):
        created = updated = 0
        used_slugs = set(
            EquipmentItem.objects.filter(kind=kind).values_list("slug", flat=True)
        )
        for entry in entries:
            data_blob = entry.get("data") or {}
            name = entry.get("name") or entry.get("path")
            if kind == "emblem" and name.startswith("Emblem: "):
                name = name[len("Emblem: "):]
            defaults = {
                "name": name,
                "category": entry.get("category") or "",
                "description": entry.get("description") or "",
                "tradable": bool(entry.get("tradable")),
                "mastery": entry.get("mastery"),
                "power_rank": entry.get("power_rank"),
                "stats": data_blob.get("stats", []),
                "abilities": data_blob.get("abilities", []),
                "raw_data": data_blob,
            }
            obj, was_created = EquipmentItem.objects.update_or_create(
                kind=kind, source_path=entry["path"], defaults=defaults
            )
            if was_created or not obj.slug:
                obj.slug = self._unique_slug(obj.name, used_slugs)
                used_slugs.add(obj.slug)
                obj.save(update_fields=["slug"])
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated

    def _unique_slug(self, name, used_slugs):
        base = slugify(name) or "item"
        slug = base
        i = 2
        while slug in used_slugs:
            slug = f"{base}-{i}"
            i += 1
        return slug

    def _inspect(self):
        self.stdout.write("--- primeras 15 entradas de item?category=Equipment ---")
        data = self._get("/v1/codexes/item", params={"category": "Equipment", "limit": 15})
        for e in data.get("items", []):
            self.stdout.write(f"  path={e.get('path')!r}  category={e.get('category')!r}  name={e.get('name')!r}")
        self.stdout.write(f"  total en categoria Equipment: {data.get('total')}")

        for term in ("Emblem", "Flask"):
            self.stdout.write(f"\n--- busqueda type=item q={term} ---")
            data = self._get("/v1/codexes/search", params={"type": "item", "q": term, "limit": 10})
            items = data.get("items", [])
            if not items:
                self.stdout.write("  (sin resultados)")
            for e in items:
                self.stdout.write(f"  path={e.get('path')!r}  category={e.get('category')!r}  name={e.get('name')!r}")
