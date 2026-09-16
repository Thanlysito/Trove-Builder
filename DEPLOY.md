# Cómo poner Trove Builder en internet de verdad

Esto es opcional — tu proyecto sigue funcionando igual en tu PC
(`python manage.py runserver`) sin tocar nada de esto. Esta guía es para
cuando quieras que **otras personas** puedan entrar al sitio desde un link
real, no solo tú desde `127.0.0.1`.

Recomiendo **Railway** por ser el más simple para empezar. Render es la
alternativa más conocida, casi igual de fácil.

## Antes que nada: sube tu proyecto a GitHub

Ambos servicios funcionan conectando un repositorio de GitHub. Si tu
proyecto no está en GitHub todavía:

1. Crea un repositorio nuevo en github.com (puede ser privado).
2. Desde la carpeta de tu proyecto:
   ```
   git init
   git add .
   git commit -m "Primer commit"
   git branch -M main
   git remote add origin https://github.com/TU-USUARIO/TU-REPO.git
   git push -u origin main
   ```
   Gracias al `.gitignore` que ya tienes, `.env`, `db.sqlite3` y `venv/` NO
   se van a subir — así que tu base de datos real y tus contraseñas se
   quedan solo en tu PC. Perfecto, así debe ser.

## Opción A — Railway (recomendada)

1. Entra a [railway.app](https://railway.app) y crea una cuenta (puedes
   entrar directo con tu GitHub).
2. **New Project** → **Deploy from GitHub repo** → elige tu repositorio.
3. Railway detecta automáticamente que es Python y usa tu `Procfile` para
   saber cómo arrancar el sitio — no tienes que configurar nada de eso.
4. Ve a la pestaña **Variables** de tu proyecto y agrega estas (con TUS
   valores reales, los mismos que tienes en tu `.env` local):
   - `DJANGO_SECRET_KEY` → genera una nueva, diferente a la de tu PC
     (puedes usar `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
   - `DJANGO_DEBUG` → `False`
   - `EMAIL_HOST_USER` → tu Gmail de la app
   - `EMAIL_HOST_PASSWORD` → tu contraseña de aplicación de Gmail
5. Cuando Railway te asigne un dominio (algo como
   `tu-proyecto.up.railway.app`, lo ves en **Settings → Networking →
   Generate Domain**), agrega DOS variables más con ese dominio:
   - `DJANGO_ALLOWED_HOSTS` → `tu-proyecto.up.railway.app`
   - `DJANGO_CSRF_TRUSTED_ORIGINS` → `https://tu-proyecto.up.railway.app`
6. (Opcional pero recomendado) Agrega una base de datos Postgres real en
   vez de SQLite: **New** → **Database** → **Add PostgreSQL** dentro de tu
   mismo proyecto de Railway. Railway conecta la variable `DATABASE_URL`
   sola, automáticamente — no tienes que hacer nada más, tu `settings.py`
   ya sabe usarla si existe.
   - ¿Por qué? SQLite (el archivo `db.sqlite3`) funciona bien en tu PC,
     pero en muchos servicios de hosting el disco se borra en cada
     despliegue nuevo, así que perderías los datos. Postgres es una base
     de datos real que vive aparte, separada del código.
7. Railway hace el deploy solo. Cuando termine, entra al dominio que te
   dio y ya debería estar tu sitio andando.

## Opción B — Render

Los pasos son casi idénticos:

1. Cuenta en [render.com](https://render.com), conecta tu GitHub.
2. **New** → **Web Service** → elige tu repositorio.
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn trove_builder.wsgi`
5. Agrega las mismas variables de entorno del paso 4 de Railway (Render
   las llama "Environment Variables", en la misma pantalla de configuración
   del servicio). Para el dominio, Render define solo la variable
   `RENDER_EXTERNAL_HOSTNAME` — tu `settings.py` ya la detecta
   automáticamente, así que ahí no tienes que hacer nada extra.
6. Si quieres Postgres: **New** → **PostgreSQL**, y copia la
   "Internal Database URL" que te da a la variable `DATABASE_URL` de tu
   Web Service.

## Después del primer deploy

Para crear tu usuario administrador en el servidor (separado del que usas
en tu PC), la mayoría de estos servicios te dan una consola/shell dentro
del dashboard donde puedes correr:
```
python manage.py createsuperuser
```

## Resumen de variables de entorno para producción

| Variable | Valor |
|---|---|
| `DJANGO_SECRET_KEY` | una nueva, generada, distinta a la de tu PC |
| `DJANGO_DEBUG` | `False` |
| `DJANGO_ALLOWED_HOSTS` | tu dominio real, sin `https://` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | tu dominio real, con `https://` |
| `DATABASE_URL` | la pone el servicio solo, si usas Postgres |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | los mismos de tu `.env` local |
