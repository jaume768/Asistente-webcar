# webcar-asistente

Chat con IA para usuarios de Webcar Lite: resuelve dudas de uso, responde
preguntas sobre los datos del rentacar y propone cambios que el usuario confirma.

- Guía para desarrollar (y para Claude Code): [CLAUDE.md](CLAUDE.md)
- Fases, seguridad y pendientes: [docs/PLAN.md](docs/PLAN.md)

## Puesta en marcha rápida

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # OPENAI_API_KEY, DJANGO_DEBUG=True
python manage.py migrate
python manage.py createsuperuser
python manage.py refrescar_webcar demo --crear "DEMO"
python manage.py runserver
```

Crea en /admin un usuario con rentacar «DEMO» y entra en http://localhost:8000.
