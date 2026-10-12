# CLAUDE.md — webcar-asistente

Instrucciones para Claude Code en este repositorio. Léelas antes de tocar nada.

## Qué es

Chat con IA para los usuarios de **Webcar Lite** (software de gestión de rent a
car de COR SOFT). Hace tres cosas:

1. Resuelve **dudas de uso** de Webcar Lite con la base de conocimiento (`conocimiento/`).
2. Responde **preguntas sobre los datos** del rentacar del usuario con SQL de solo lectura sobre DuckDB.
3. **Propone cambios** en Webcar que el usuario confirma con un botón. Hoy no se
   puede ejecutar ninguno: Webcar solo expone listados CSV de lectura (ver Fase 3).

Es un proyecto aparte de `saasia` (generacion.corsoft.es), pero reutiliza su
conocimiento de Webcar: limpieza de los CSV, relaciones entre listados, código
`codi`. Si cambia allí, revisar aquí.

## Arquitectura

```
asistente/   settings (todo por .env con python-decouple), urls
cuentas/     Usuario (AbstractUser) con rentacar y rol (A admin, O restringido, P partner)
webcar/      conector a Webcar
  cliente.py      URL con codi del día, descarga, normalizar() ← rarezas del CSV de Webcar
  esquema.py      LISTADOS: tabla ↔ fichero de la API, caducidad, relaciones y avisos
  almacen.py      DuckDB por rentacar (DATOS_DIR/<codigo>/webcar.duckdb), tipos, consultar()
  sql_guard.py    solo un SELECT, solo tablas conocidas, sin read_csv ni similares, LIMIT
  management/commands/refrescar_webcar.py
chat/
  agente.py       bucle tool-calling (chat completions, OpenAI o compatible)
  herramientas.py describir_tablas, consultar_datos, refrescar_listado, buscar_ayuda, proponer_accion
  acciones.py     tipos de acción, proponer() y resolver(); ejecutores = AccionNoDisponible
  ayuda.py        búsqueda por palabras en conocimiento/*.md
  models.py       Conversacion, Mensaje (historial tal cual va a la API), AccionPropuesta
  views.py        UI (Django templates + JS sin framework) y endpoints JSON (mensaje, borrar, resolver_accion)
conocimiento/  Markdown que usa buscar_ayuda
templates/     base (temas claro/oscuro por variables CSS), login, chat (_lateral, _entrada, _estilos)
docs/PLAN.md   fases, decisiones, preguntas abiertas
```

Flujo de un mensaje: `views.mensaje` → `agente.responder` → modelo → herramientas
(con `Contexto` de la sesión) → modelo … → respuesta. Todo se guarda en `Mensaje`.

## Arrancar en local

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # poner OPENAI_API_KEY y DJANGO_DEBUG=True
python manage.py migrate
python manage.py createsuperuser
python manage.py refrescar_webcar demo --crear "DEMO"   # baja los 20 listados de la demo
python manage.py runserver
```

Con Docker (`Dockerfile` + `docker-compose.yml`): gunicorn con un solo worker e
hilos (los locks de `almacen.py` son por proceso), estáticos con WhiteNoise, y
SQLite + DuckDB en el volumen `datos` (`/datos`). El `.env` se pasa con
`env_file`, no se copia a la imagen; tras cambiarlo, `docker compose up -d`.

```bash
cp .env.example .env            # poner OPENAI_API_KEY
docker compose up -d --build    # migra al arrancar; http://localhost:8000
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py refrescar_webcar demo --crear "DEMO"
docker compose run --rm --no-deps -e DATOS_DIR=/tmp/datos web python manage.py test
```

En /admin: crear un Usuario normal con rentacar = DEMO y rol Administrador, y
entrar con él en / (el superusuario sin rentacar no puede abrir conversaciones).

Tests: `python manage.py test` (no llaman a Webcar ni al LLM; el agente se
prueba con un cliente falso en `chat/tests.py`).

## Reglas del proyecto (no romper)

- **Aislamiento por rentacar**: el rentacar sale SIEMPRE de `request.user`, nunca
  de lo que diga el modelo ni de parámetros de la URL. Cada rentacar tiene su
  propio fichero DuckDB.
- **Solo lectura en datos**: todo SQL del modelo pasa por `sql_guard.validar` y se
  ejecuta con DuckDB `read_only=True` y `enable_external_access=False`. No
  añadir herramientas que ejecuten SQL sin pasar por ahí.
- **Cambios solo con confirmación humana**: el modelo solo crea `AccionPropuesta`.
  La ejecución está en `acciones.resolver`, llamada desde la vista con la sesión
  del usuario. Comprobar el rol al proponer Y al confirmar.
- **Nunca simular éxito**: si Webcar no confirma, la acción queda `fallida` con el
  motivo. Nada de "hecho" falso (misma regla que Auto Instagram en saasia).
- **Cifras solo de consultas**: el prompt lo exige; no relajarlo.
- Columnas de Webcar engañosas: en reservas, `pais_cliente`, `nif_cliente`, etc.
  traen el CÓDIGO del cliente; `matricula`/`modelo` traen el código del vehículo.
  Están en `esquema.py` (avisos). Ampliar ahí, no en el prompt.
- Códigos (00003, C-02, 0013) son VARCHAR: no cambiar la inferencia de tipos sin
  revisar los cruces.
- Idioma de código, comentarios, UI y mensajes: español.

## Formato de los CSV de Webcar (por si hay que tocar normalizar)

`https://lite.webcar.rent/webcar/appapi?codi=<AAMMDD*7-128>&ruta=<codigo>&fichero=<fichero>`
devuelve `text/plain; charset=iso-8859-1`, filas separadas por `\r`, `;` sin
comillas, entidades HTML a veces sin `;` (`Categor&iacutea`), texto doble
codificado (`EspaÃ±a`), `;` dentro de campos y saltos de línea en anotaciones.
Hay ejemplos en `webcar/tests.py`.

## Siguiente trabajo

Ver `docs/PLAN.md`. Prioridad actual: probar el agente con un modelo real contra
la demo y ajustar prompt/herramientas con preguntas reales (sección «Batería de
preguntas»).
