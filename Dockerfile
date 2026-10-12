FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Los estáticos van dentro de la imagen (los sirve WhiteNoise). /datos es el
# volumen con SQLite y los DuckDB: se crea aquí para que herede el propietario.
RUN python manage.py collectstatic --noinput \
    && useradd --create-home app \
    && mkdir -p /datos \
    && chown app:app /datos

USER app
EXPOSE 8000

# Un solo worker con hilos: los locks de webcar/almacen.py son por proceso y
# DuckDB solo admite un proceso escritor por fichero.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn asistente.wsgi:application --bind 0.0.0.0:8000 --workers 1 --threads 8 --timeout 120 --access-logfile -"]
