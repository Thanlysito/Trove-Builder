"""
Traduce automaticamente al ingles todo lo nuevo del sitio.

Lo corre GitHub Actions en cada push a main (ver
.github/workflows/traducciones.yml). Hace dos cosas:

1. INTERFAZ: textos marcados con {% translate %} / _("...") que estan en
   locale/en/LC_MESSAGES/django.po sin traduccion (o cuyo texto en español
   cambio). Los traduce y los guarda en el .po.

2. DATOS DEL JUEGO: descripciones de clases, gemas, subclases, Efectos
   Ocultos, etc. que carga seed_trove_data. Los que no tengan traduccion se
   guardan en locale/en/game_data.json.

Motor de traduccion:
- Gemini (IA de Google, plan gratuito) si existe la variable de entorno
  GEMINI_API_KEY. Traduce con contexto y respeta los terminos de Trove.
- Argos Translate (gratis, sin clave) como respaldo si Gemini no esta
  configurado, falla o se acaba la cuota del dia.

Reglas:
- Nunca toca una traduccion que ya existe: si corriges una a mano, se queda.
- Protege los marcadores (%(name)s, {type}): si una traduccion los rompe,
  ese texto queda sin traducir (se muestra en español) y se avisa.
- Las traducciones automaticas del .po quedan marcadas "auto (Gemini)" o
  "auto (Argos)" para que sepas cuales revisar.

Uso manual:
    pip install polib                    # Argos se instala solo si hace falta
    set GEMINI_API_KEY=...               # opcional
    python tools/auto_traducir.py
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import polib
import requests

# En GitHub Actions la salida no es una terminal y Python la guardaria hasta
# el final; asi cada linea aparece en el log apenas se imprime.
sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
PO_PATH = ROOT / "locale" / "en" / "LC_MESSAGES" / "django.po"
GAME_DATA_PATH = ROOT / "locale" / "en" / "game_data.json"

PLACEHOLDER = re.compile(r"%\(\w+\)[sd]|\{\w+\}")
# Para decidir que datos del juego estan en español (los que ya estan en
# ingles, como "+1 Jump", no hace falta traducirlos).
SPANISH = re.compile(
    r"[áéíóúñ¿¡]|\b(de|del|la|las|el|los|para|con|por|una|uno|tu|tus|sin|que|es|son|"
    r"al|más|mas|segun|según|cada|cuando|mientras|puede|daño|vida|enemigos?|aliados?|"
    r"a|y|o|en|se|su|sus)\b",
    re.IGNORECASE,
)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
BATCH_SIZE = 40

PROMPT = """You translate text for "Trove Builder", a fan-made character build website for the voxel MMO game Trove, from Spanish into natural, concise English, the way the Trove player community writes it.

Rules:
- Keep Trove game terms in their official English form: build, class, subclass, Mastery, Class Gem, Empowered, Lesser, Fierce, Arcane, Shadow, Radiant, Stellar, Crystal, Cosmic, Power Rank (PR), Delves, Geode, Uber, Flux, Cubits, Hidden Effect, Ring Polisher, Signatory, Mystic, Ally, Emblem, Flask, Banner, Lasermancy, Magic Find, Light, Physical Damage, Magic Damage, Critical Hit, Critical Damage, Max Health, Attack Speed, Movement Speed, Energy Regen, Health Regen, Dodge, DoT, cooldown, buff, debuff.
- Names of classes, abilities, gems, items and stats stay exactly as written (they are already the official English names).
- Keep every placeholder exactly as written, such as %(name)s, %(cls)s or {type}. Never translate, reorder inside, or remove them.
- Keep emoji and symbols (✓ ✗ — · ♥ ⚠) exactly. Replace Spanish quotes «text» with “text”.
- Keep numbers, percentages and units exactly.
- {context}
- If a text is already in English, return it unchanged.

Return ONLY a JSON object that maps each input key to its English translation, with the same keys.

Input:
{payload}"""

CONTEXT = {
    "ui": "These are short user-interface strings: buttons, labels, titles, form help and status messages. Keep them short.",
    "game": "These are game data: class and gem descriptions, passive abilities, ring Hidden Effects and stat bonuses. Keep the game-guide tone.",
}


# --------------------------------------------------------------------------
# Motores de traduccion
# --------------------------------------------------------------------------

def placeholders_ok(source, translated):
    return (
        isinstance(translated, str)
        and translated.strip() != ""
        and sorted(PLACEHOLDER.findall(source)) == sorted(PLACEHOLDER.findall(translated))
    )


class QuotaExhausted(RuntimeError):
    """Gemini dice que se acabo la cuota (o que este modelo no tiene cuota gratis)."""


class Gemini:
    name = "Gemini"

    def __init__(self, api_key):
        self.api_key = api_key
        forced = os.environ.get("GEMINI_MODEL")
        candidates = [forced] if forced else self._candidate_models()
        print(f"Modelos Gemini candidatos: {', '.join(candidates) or '(ninguno)'}")
        # Prueba cada modelo con una peticion minima y se queda con el primero
        # que responda: algunos modelos no tienen cuota en el plan gratuito.
        for name in candidates:
            self.model = name
            try:
                self._generate('Responde solo con este JSON: {"0": "ok"}', retries=0)
                print(f"Usando Gemini, modelo: {name}")
                return
            except Exception as exc:
                print(f"  {name} no disponible: {exc}")
        raise RuntimeError("ningun modelo Gemini respondio con esta clave")

    def _candidate_models(self):
        """Modelos 'flash' de la clave, del mas nuevo al mas viejo; 'lite' al final."""
        resp = requests.get(
            f"{GEMINI_URL}/models", headers={"x-goog-api-key": self.api_key},
            params={"pageSize": 200}, timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"no se pudo listar modelos (HTTP {resp.status_code}: {resp.text[:200]})")
        skip = ("image", "tts", "audio", "live", "embedding", "thinking", "exp", "latest")
        found = []
        for m in resp.json().get("models", []):
            name = m.get("name", "").split("/")[-1]
            if ("flash" in name and "generateContent" in m.get("supportedGenerationMethods", [])
                    and not any(x in name for x in skip)):
                version = tuple(int(n) for n in re.findall(r"\d+", name)[:3])
                # Orden: estables antes que preview, normales antes que lite, mas nuevos primero.
                found.append(("preview" in name, "lite" in name, tuple(-v for v in version), name))
        return [name for *_, name in sorted(found)][:6]

    def _generate(self, prompt, retries=2):
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        for attempt in range(retries + 1):
            resp = requests.post(
                f"{GEMINI_URL}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.api_key}, json=body, timeout=90,
            )
            if resp.status_code == 200:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
            detail = resp.text[:300].replace("\n", " ")
            if resp.status_code == 429 and ("PerDay" in detail or "limit: 0" in detail or attempt == retries):
                raise QuotaExhausted(f"HTTP 429: {detail}")
            if resp.status_code in (429, 500, 503) and attempt < retries:
                print(f"  Gemini respondio {resp.status_code}; reintento en 30s...")
                time.sleep(30)
                continue
            raise RuntimeError(f"HTTP {resp.status_code}: {detail}")
        raise RuntimeError("Gemini no respondio")

    def translate_batch(self, texts, kind):
        payload = {str(i): t for i, t in enumerate(texts)}
        prompt = PROMPT.replace("{context}", CONTEXT[kind]).replace(
            "{payload}", json.dumps(payload, ensure_ascii=False, indent=1))
        data = self._generate(prompt)
        return {texts[int(k)]: v for k, v in data.items() if k.isdigit() and int(k) < len(texts)}


class Argos:
    name = "Argos"

    def __init__(self):
        try:
            import argostranslate  # noqa: F401
        except ImportError:
            # Solo se instala si hace falta (es pesado). Version de PyTorch
            # para CPU, mucho mas liviana que la de GPU.
            import subprocess
            print("Instalando Argos Translate (respaldo)...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "torch",
                                   "--index-url", "https://download.pytorch.org/whl/cpu"])
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "argostranslate"])
        import argostranslate.package
        import argostranslate.translate

        codes = {lang.code for lang in argostranslate.translate.get_installed_languages()}
        if not {"es", "en"} <= codes:
            argostranslate.package.update_package_index()
            pkg = next(
                p for p in argostranslate.package.get_available_packages()
                if p.from_code == "es" and p.to_code == "en"
            )
            argostranslate.package.install_from_path(pkg.download())
        self._translate = lambda text: argostranslate.translate.translate(text, "es", "en")
        print("Usando Argos Translate.")

    def translate_batch(self, texts, kind):
        out = {}
        for text in texts:
            # Protege los marcadores con tokens que el traductor no toca.
            found = PLACEHOLDER.findall(text)
            protected = text
            for i, ph in enumerate(found):
                protected = protected.replace(ph, f"__{i}__", 1)
            result = self._translate(protected).strip()
            if all(result.count(f"__{i}__") == 1 for i in range(len(found))):
                for i, ph in enumerate(found):
                    result = result.replace(f"__{i}__", ph)
                out[text] = result
        return out


class Translator:
    """Usa Gemini si hay clave; si falla o no hay clave, cae en Argos."""

    def __init__(self):
        self.engines = []
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if key:
            try:
                self.engines.append(Gemini(key))
            except Exception as exc:  # clave invalida, sin red, etc.
                print(f"Gemini no disponible ({exc}); se usara Argos.")
        else:
            print("Sin GEMINI_API_KEY; se usara Argos.")
        self._argos = None

    def _get_argos(self):
        if self._argos is None:
            try:
                self._argos = Argos()
            except Exception as exc:
                print(f"Argos no disponible ({exc}).")
                self._argos = False
        return self._argos or None

    def translate(self, texts, kind):
        """Devuelve {texto: (traduccion, motor)} para los que se pudieron traducir."""
        results, pending = {}, list(texts)
        for engine in list(self.engines):
            total = (len(pending) + BATCH_SIZE - 1) // BATCH_SIZE
            for n, start in enumerate(range(0, len(pending), BATCH_SIZE), start=1):
                chunk = pending[start:start + BATCH_SIZE]
                print(f"  {engine.name}: lote {n}/{total} ({len(chunk)} textos)...")
                try:
                    got = engine.translate_batch(chunk, kind)
                except Exception as exc:
                    # Si falla un lote, no insiste con los demas: pasa al respaldo.
                    print(f"  {engine.name} fallo ({exc}); se deja de usar en esta ejecucion.")
                    self.engines.remove(engine)
                    break
                for src, dst in got.items():
                    if placeholders_ok(src, dst):
                        results[src] = (dst.strip(), engine.name)
                time.sleep(4)  # respeta el limite por minuto del plan gratuito
            pending = [t for t in pending if t not in results]
            if not pending:
                return results

        argos = self._get_argos() if pending else None
        if argos:
            for src, dst in argos.translate_batch(pending, kind).items():
                if placeholders_ok(src, dst):
                    results[src] = (dst, argos.name)
        return results


# --------------------------------------------------------------------------
# 1. Interfaz (django.po)
# --------------------------------------------------------------------------

def translate_po(translator):
    po = polib.pofile(str(PO_PATH))
    pending = [e for e in po if not e.obsolete and ("fuzzy" in e.flags or not e.translated())]
    if not pending:
        print("Interfaz: no hay textos nuevos.")
        return

    sources = []
    for e in pending:
        sources.append(e.msgid)
        if e.msgid_plural:
            sources.append(e.msgid_plural)
    done = translator.translate(sources, "ui")

    ok, failed = 0, []
    for e in pending:
        if e.msgid_plural:
            if e.msgid in done and e.msgid_plural in done:
                e.msgstr_plural = {0: done[e.msgid][0], 1: done[e.msgid_plural][0]}
                engine = done[e.msgid][1]
            else:
                failed.append(e.msgid)
                continue
        elif e.msgid in done:
            e.msgstr, engine = done[e.msgid]
        else:
            failed.append(e.msgid)
            continue
        if "fuzzy" in e.flags:
            e.flags.remove("fuzzy")
        e.previous_msgid = e.previous_msgid_plural = None
        e.tcomment = f"auto ({engine})"
        ok += 1
        print(f"  + {e.msgid!r} -> {e.msgstr or e.msgstr_plural!r}")

    po.save()
    print(f"Interfaz: {ok} textos traducidos.")
    for msgid in failed:
        print(f"  ! Sin traducir (queda en español): {msgid!r}")


# --------------------------------------------------------------------------
# 2. Datos del juego (game_data.json)
# --------------------------------------------------------------------------

def translate_game_data(translator):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trove_builder.settings")
    import django

    django.setup()
    from builder.game_text import collect_texts

    texts = {t for t in collect_texts() if SPANISH.search(t)}
    existing = {}
    if GAME_DATA_PATH.exists():
        existing = json.loads(GAME_DATA_PATH.read_text(encoding="utf-8"))

    # Conserva las traducciones existentes (incluidas las corregidas a mano) y
    # descarta las de textos que ya no existen en el juego.
    data = {k: v for k, v in existing.items() if k in texts}
    pending = sorted(texts - data.keys())
    if pending:
        done = translator.translate(pending, "game")
        for src, (dst, _engine) in done.items():
            data[src] = dst
        print(f"Datos del juego: {len(done)} de {len(pending)} textos nuevos traducidos.")
    else:
        print("Datos del juego: no hay textos nuevos.")

    if data != existing:
        GAME_DATA_PATH.write_text(
            json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )


def main():
    translator = Translator()
    translate_po(translator)
    translate_game_data(translator)
    return 0


if __name__ == "__main__":
    sys.exit(main())
