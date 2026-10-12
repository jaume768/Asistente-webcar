"""DuckDB por rentacar: carga de listados, caducidad y consultas de solo lectura.

Cada rentacar tiene `DATOS_DIR/<codigo>/webcar.duckdb`. Una tabla por listado,
con columnas en snake_case. Los tipos se deducen con cuidado: los códigos
(«00003», «C-02») se quedan como texto aunque parezcan números, para no perder
ceros y que los cruces sigan funcionando.
"""

import csv
import io
import logging
import re
import threading
from datetime import timedelta

import duckdb
from django.conf import settings
from django.utils import timezone

from . import cliente, esquema
from .models import Descarga

log = logging.getLogger(__name__)

_locks = {}
_locks_guard = threading.Lock()

_ENTERO = re.compile(r"^-?\d+$")
_DECIMAL = re.compile(r"^-?\d+\.\d+$")
_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FECHA_HORA = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}(:\d{2})?)?$")


def _lock(codigo):
    with _locks_guard:
        return _locks.setdefault(codigo, threading.Lock())


def ruta_db(codigo):
    carpeta = settings.DATOS_DIR / codigo
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / "webcar.duckdb"


def _tipo_columna(valores, es_codigo=False):
    """Tipo DuckDB para una columna de texto. Ante la duda, VARCHAR.

    Los códigos (primera columna y columnas que apuntan a otro listado) son
    siempre texto. Una columna de dígitos donde la mayoría lleva ceros a la
    izquierda («00101») también es un código, aunque Webcar mezcle importes
    como «00» o «00.1» en columnas numéricas.
    """
    if es_codigo:
        return "VARCHAR"
    llenos = [v for v in valores if v != ""]
    if not llenos:
        return "VARCHAR"
    if all(_FECHA.match(v) for v in llenos):
        return "DATE"
    if all(_FECHA_HORA.match(v) for v in llenos):
        return "TIMESTAMP"
    if not all(_ENTERO.match(v) or _DECIMAL.match(v) for v in llenos):
        return "VARCHAR"
    con_ceros = sum(1 for v in llenos if len(v.lstrip("-").split(".")[0]) > 1 and v.lstrip("-").startswith("0"))
    if con_ceros > len(llenos) / 2:
        return "VARCHAR"
    if all(_ENTERO.match(v) for v in llenos):
        return "BIGINT"
    return "DOUBLE"


def _filas(texto_csv):
    lector = csv.reader(io.StringIO(texto_csv), delimiter=";", quoting=csv.QUOTE_NONE)
    cabecera = next(lector)
    # Webcar suele terminar las filas con «;»: la última columna vacía sobra.
    while cabecera and cabecera[-1].strip() == "":
        cabecera.pop()
    n = len(cabecera)
    filas = []
    for fila in lector:
        if not any(c.strip() for c in fila):
            continue
        fila = [c.strip() for c in fila[:n]] + [""] * max(0, n - len(fila))
        filas.append(fila)
    return cabecera, filas


def cargar_listado(rentacar, tabla, texto_csv=None):
    """Descarga (si no se da el texto) y reemplaza la tabla en DuckDB."""
    lst = esquema.listado(tabla)
    if texto_csv is None:
        datos, charset = cliente.descargar(lst.fichero, rentacar.codigo)
        texto_csv = cliente.normalizar(datos, charset)
    cabecera, filas = _filas(texto_csv)
    if cabecera[:1] != [lst.cabecera]:
        raise cliente.WebcarError(
            f"El listado {tabla} no tiene la cabecera esperada ({lst.cabecera}); llegó «{cabecera[:1]}»."
        )
    columnas = esquema.columnas_unicas(cabecera)
    claves = {0} | {i for i, nombre in enumerate(cabecera) if nombre in lst.relaciones}
    tipos = [
        _tipo_columna([f[i] for f in filas], es_codigo=i in claves)
        for i in range(len(columnas))
    ]
    # CSV limpio en disco: DuckDB lo lee de golpe (executemany era 40 s en reservas).
    limpio = ruta_db(rentacar.codigo).with_name(f"{tabla}.csv")
    with open(limpio, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f, delimiter=";", quoting=csv.QUOTE_ALL)
        escritor.writerow(columnas)
        escritor.writerows(filas)

    with _lock(rentacar.codigo):
        con = duckdb.connect(str(ruta_db(rentacar.codigo)))
        try:
            staging = f"_staging_{tabla}"
            con.execute(f"DROP TABLE IF EXISTS {staging}")
            tipos_csv = "{" + ", ".join(f"'{c}': 'VARCHAR'" for c in columnas) + "}"
            con.execute(
                f"CREATE TABLE {staging} AS SELECT * FROM read_csv(?, delim=';', quote='\"', "
                f"header=true, columns={tipos_csv}, nullstr='')",
                [str(limpio)],
            )
            select = ", ".join(
                c if t == "VARCHAR" else f"TRY_CAST({c} AS {t}) AS {c}"
                for c, t in zip(columnas, tipos)
            )
            con.execute(f"CREATE OR REPLACE TABLE {tabla} AS SELECT {select} FROM {staging}")
            con.execute(f"DROP TABLE {staging}")
            # Diccionario de columnas originales para enseñárselo al modelo.
            con.execute(
                "CREATE TABLE IF NOT EXISTS _columnas (tabla VARCHAR, columna VARCHAR, original VARCHAR, tipo VARCHAR)"
            )
            con.execute("DELETE FROM _columnas WHERE tabla = ?", [tabla])
            con.executemany(
                "INSERT INTO _columnas VALUES (?, ?, ?, ?)",
                [[tabla, c, o, t] for c, o, t in zip(columnas, cabecera, tipos)],
            )
        finally:
            con.close()

    Descarga.objects.update_or_create(
        rentacar=rentacar,
        listado=tabla,
        defaults={"filas": len(filas), "bytes": len(texto_csv.encode()), "descargado": timezone.now()},
    )
    log.info("Cargado %s/%s: %s filas", rentacar.codigo, tabla, len(filas))
    return len(filas)


def caducado(rentacar, tabla):
    lst = esquema.listado(tabla)
    d = Descarga.objects.filter(rentacar=rentacar, listado=tabla).first()
    return d is None or timezone.now() - d.descargado > timedelta(minutes=lst.caduca_min)


def asegurar(rentacar, tablas):
    """Descarga las tablas que faltan o han caducado. Devuelve errores por tabla."""
    errores = {}
    for tabla in tablas:
        if caducado(rentacar, tabla):
            try:
                cargar_listado(rentacar, tabla)
            except cliente.WebcarError as exc:
                errores[tabla] = str(exc)
    return errores


def columnas(rentacar):
    """{tabla: [(columna, original, tipo)]} de lo que hay cargado."""
    db = ruta_db(rentacar.codigo)
    if not db.exists():
        return {}
    with _lock(rentacar.codigo):
        con = duckdb.connect(str(db), read_only=True)
        try:
            existe = con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = '_columnas'"
            ).fetchone()[0]
            if not existe:
                return {}
            salida = {}
            for tabla, col, orig, tipo in con.execute(
                "SELECT tabla, columna, original, tipo FROM _columnas ORDER BY tabla, rowid"
            ).fetchall():
                salida.setdefault(tabla, []).append((col, orig, tipo))
            return salida
        finally:
            con.close()


def consultar(rentacar, sql, max_filas):
    """Ejecuta un SELECT ya validado. Devuelve (columnas, filas, truncado)."""
    with _lock(rentacar.codigo):
        con = duckdb.connect(
            str(ruta_db(rentacar.codigo)),
            read_only=True,
            config={"enable_external_access": False},
        )
        try:
            cur = con.execute(sql)
            nombres = [d[0] for d in cur.description]
            filas = cur.fetchmany(max_filas + 1)
        finally:
            con.close()
    truncado = len(filas) > max_filas
    return nombres, filas[:max_filas], truncado
