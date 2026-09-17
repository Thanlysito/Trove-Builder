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
- Ally: tipo de codex propio ("ally").
- Flask y Emblem SALEN DEL MISMO tipo de codex ("flask", ~49 entradas) -
  ese tipo en realidad mezcla ambos (confirmado viendo datos reales: trae
  "Arcane Emblem" junto con "Elysian Flask"). Se separan por el nombre:
  si termina en la palabra "Emblem" es un Emblem, si no, es un Flask real.
  (Ojo: esto reemplaza un intento anterior que buscaba "Emblem: " como
  prefijo dentro del tipo "item" - ese metodo quedo obsoleto y se limpia
  solo gracias al pruning de mas abajo.)
- Banner: no es un tipo propio, es un "style" (tipo "style"), casi
  siempre con category="Banner" (algunos viejos de evento quedan mal
  categorizados como "Equipment"), bajo los paths
  "prefabs/equipment/banner/..." o "prefabs/equipment/delve/...".
  Este comando combina la busqueda por categoria + por texto "Banner" y
  se queda con lo que tenga "banner" en el path.
- Cada sync PRUNEA (borra) los EquipmentItem de un kind que ya no
  aparezcan en la respuesta actual de la API. Esto limpia solo cualquier
  entrada obsoleta que haya quedado de una version anterior del comando
  con una logica de deteccion distinta.
  Todo esto se confirmo inspeccionando datos reales con --inspect.
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
            choices=["ally", "emblem", "flask", "banner"],
            help="Sincronizar solo un tipo en vez de los cuatro.",
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

        kinds = [options["kind"]] if options["kind"] else ["ally", "emblem", "flask", "banner"]
        dry_run = options["dry_run"]

        flask_codex_cache = None  # cache: type=flask, usado por "flask" y "emblem" (vienen mezclados)

        for kind in kinds:
            if kind == "ally":
                entries = self._fetch_codex_type("ally")
            elif kind in ("flask", "emblem"):
                if flask_codex_cache is None:
                    flask_codex_cache = self._fetch_codex_type("flask")
                is_emblem = lambda e: e.get("name", "").strip().endswith("Emblem")
                if kind == "emblem":
                    entries = [e for e in flask_codex_cache if is_emblem(e)]
                else:
                    entries = [e for e in flask_codex_cache if not is_emblem(e)]
            elif kind == "banner":
                by_category = self._fetch_codex_type("style", category="Banner")
                by_search = self._fetch_codex_type("style", search="Banner")
                merged = {e["path"]: e for e in by_category + by_search}
                entries = [e for e in merged.values() if "banner" in e.get("path", "").lower()]

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

    def _fetch_codex_type(self, codex_type, category=None, search=None):
        entries = []
        offset = 0
        total = 0
        while True:
            params = {"limit": PAGE_SIZE, "offset": offset}
            if category:
                params["category"] = category
            if search:
                params["search"] = search
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
        seen_paths = set()
        for entry in entries:
            data_blob = entry.get("data") or {}
            path = entry["path"]
            seen_paths.add(path)
            defaults = {
                "name": entry.get("name") or path,
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
                kind=kind, source_path=path, defaults=defaults
            )
            if was_created or not obj.slug:
                obj.slug = self._unique_slug(obj.name, used_slugs)
                used_slugs.add(obj.slug)
                obj.save(update_fields=["slug"])
            if was_created:
                created += 1
            else:
                updated += 1

        # Prunea cualquier registro de este kind que ya no venga en la
        # respuesta actual de la API (ej: quedo de una version anterior
        # del comando con otra logica de deteccion, o el item se elimino
        # del juego).
        deleted, _ = EquipmentItem.objects.filter(kind=kind).exclude(
            source_path__in=seen_paths
        ).delete()
        if deleted:
            self.stdout.write(self.style.WARNING(f"{kind}: {deleted} registros obsoletos borrados"))

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

        for term in ("Emblem", "Flask", "Banner"):
            self.stdout.write(f"\n--- busqueda type=item q={term} ---")
            data = self._get("/v1/codexes/search", params={"type": "item", "q": term, "limit": 10})
            items = data.get("items", [])
            if not items:
                self.stdout.write("  (sin resultados)")
            for e in items:
                self.stdout.write(f"  path={e.get('path')!r}  category={e.get('category')!r}  name={e.get('name')!r}")

        self.stdout.write("\n--- busqueda type=style q=Banner (por si son estilos, no items) ---")
        data = self._get("/v1/codexes/search", params={"type": "style", "q": "Banner", "limit": 10})
        items = data.get("items", [])
        if not items:
            self.stdout.write("  (sin resultados)")
        for e in items:
            self.stdout.write(f"  path={e.get('path')!r}  category={e.get('category')!r}  name={e.get('name')!r}")

        self.stdout.write("\n--- tipos de codex disponibles (/v1/codexes/types) ---")
        data = self._get("/v1/codexes/types")
        for row in data.get("items", []):
            self.stdout.write(f"  {row.get('type')}: {row.get('count')}")

        self.stdout.write("\n--- listado completo de type=flask (49 esperadas) ---")
        flask_entries = self._fetch_codex_type("flask")
        for e in sorted(flask_entries, key=lambda x: x.get("name", "")):
            tag = "EMBLEM" if e.get("name", "").strip().endswith("Emblem") else "flask "
            self.stdout.write(f"  [{tag}] {e.get('name')!r}  path={e.get('path')!r}")

        self.stdout.write("\n--- type=item search=Emblem, EXCLUYENDO paths ya cubiertos por type=flask ---")
        flask_paths = {e["path"] for e in flask_entries}
        item_emblem_hits = self._fetch_codex_type("item", search="Emblem")
        extra = [e for e in item_emblem_hits if e["path"] not in flask_paths]
        if not extra:
            self.stdout.write("  (ninguno - el tipo 'flask' ya cubre todos los Emblems)")
        for e in extra[:30]:
            self.stdout.write(f"  path={e.get('path')!r}  category={e.get('category')!r}  name={e.get('name')!r}")
