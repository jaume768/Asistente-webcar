"""Filtro del SQL que escribe el modelo antes de tocar DuckDB.

Defensa en profundidad: además de esto, la conexión se abre `read_only` y sin
acceso externo. Aquí se exige UNA sola sentencia SELECT (con CTE/UNION si
quiere), solo sobre tablas conocidas del rentacar y sin funciones que lean
ficheros o la red.
"""

import sqlglot
from sqlglot import exp

from . import esquema


class SQLNoPermitido(ValueError):
    pass


FUNCIONES_PROHIBIDAS = {
    "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto",
    "read_text", "read_blob", "parquet_scan", "glob", "sniff_csv", "duckdb_settings",
    "duckdb_extensions", "duckdb_secrets", "getenv", "pragma_storage_info",
}


def validar(sql, tablas_permitidas=None, limite=200):
    """Devuelve el SQL normalizado con LIMIT o lanza SQLNoPermitido."""
    tablas_permitidas = set(tablas_permitidas or esquema.POR_TABLA)
    try:
        sentencias = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise SQLNoPermitido(f"SQL no válido: {exc}") from exc
    if len(sentencias) != 1:
        raise SQLNoPermitido("Solo se permite una sentencia.")
    arbol = sentencias[0]
    if not isinstance(arbol, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SQLNoPermitido("Solo se permiten consultas SELECT.")

    for nodo in arbol.walk():
        if isinstance(nodo, (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop,
                             exp.Alter, exp.Command, exp.Copy, exp.Pragma, exp.Set)):
            raise SQLNoPermitido("Solo lectura: la consulta no puede modificar nada.")
        if isinstance(nodo, exp.Anonymous) and nodo.name.lower() in FUNCIONES_PROHIBIDAS:
            raise SQLNoPermitido(f"Función no permitida: {nodo.name}")
        if isinstance(nodo, exp.Func) and nodo.sql_name().lower() in FUNCIONES_PROHIBIDAS:
            raise SQLNoPermitido(f"Función no permitida: {nodo.sql_name()}")

    ctes = {c.alias_or_name.lower() for c in arbol.find_all(exp.CTE)}
    for tabla in arbol.find_all(exp.Table):
        if isinstance(tabla.this, exp.Func) or tabla.args.get("db") or tabla.args.get("catalog"):
            raise SQLNoPermitido("Solo se puede consultar las tablas del rentacar por su nombre.")
        nombre = tabla.name.lower()
        if nombre in ctes:
            continue
        if nombre not in tablas_permitidas:
            raise SQLNoPermitido(
                f"Tabla desconocida: {nombre}. Disponibles: {', '.join(sorted(tablas_permitidas))}"
            )

    if isinstance(arbol, exp.Select) and not arbol.args.get("limit"):
        arbol = arbol.limit(limite)
    return arbol.sql(dialect="duckdb")


def tablas_usadas(sql):
    """Tablas del rentacar que aparecen en un SQL ya validado (sin CTE)."""
    arbol = sqlglot.parse_one(sql, read="duckdb")
    ctes = {c.alias_or_name.lower() for c in arbol.find_all(exp.CTE)}
    return sorted({t.name.lower() for t in arbol.find_all(exp.Table)} - ctes)
