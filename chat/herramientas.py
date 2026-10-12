"""Herramientas que el modelo puede llamar (tool calling).

Cada herramienta recibe un `Contexto` (usuario, rentacar, conversación) que el
modelo NO controla: el rentacar sale siempre de la sesión, nunca de los
argumentos. Así un usuario no puede pedir datos de otro rentacar.
"""

import datetime
import decimal
import json
import logging
from dataclasses import dataclass

from django.conf import settings

from webcar import almacen, esquema, sql_guard
from webcar.cliente import WebcarError

from . import acciones, ayuda

log = logging.getLogger(__name__)


@dataclass
class Contexto:
    usuario: object
    rentacar: object
    conversacion: object


def _json(valor):
    if isinstance(valor, (datetime.date, datetime.datetime)):
        return valor.isoformat()
    if isinstance(valor, decimal.Decimal):
        return float(valor)
    return str(valor)


# --- implementaciones -------------------------------------------------------

def describir_tablas(ctx, tablas):
    errores = almacen.asegurar(ctx.rentacar, tablas)
    cargadas = almacen.columnas(ctx.rentacar)
    salida = {}
    for tabla in tablas:
        lst = esquema.listado(tabla)
        if tabla not in cargadas:
            salida[tabla] = {"error": errores.get(tabla, "No cargada")}
            continue
        cols = cargadas[tabla]
        por_original = {orig: col for col, orig, _ in cols}
        salida[tabla] = {
            "descripcion": lst.descripcion,
            "columnas": [{"columna": c, "original": o, "tipo": t} for c, o, t in cols],
            "clave": cols[0][0],
            "relaciones": [
                {
                    "columna": por_original[orig],
                    "tabla": destino,
                    "columna_destino": cargadas.get(destino, [("?",)])[0][0],
                }
                for orig, destino in lst.relaciones.items()
                if orig in por_original
            ],
            "aviso": lst.aviso or None,
        }
    return salida


def consultar_datos(ctx, sql):
    try:
        seguro = sql_guard.validar(sql, limite=settings.AGENTE_MAX_FILAS)
    except sql_guard.SQLNoPermitido as exc:
        return {"error": str(exc)}
    # Las tablas que use la consulta tienen que estar frescas.
    usadas = sql_guard.tablas_usadas(seguro)
    errores = almacen.asegurar(ctx.rentacar, usadas)
    try:
        nombres, filas, truncado = almacen.consultar(ctx.rentacar, seguro, settings.AGENTE_MAX_FILAS)
    except Exception as exc:  # noqa: BLE001 — el error vuelve al modelo para que corrija
        return {"error": f"Error de SQL: {exc}", "sql": seguro}
    return {
        "sql": seguro,
        "columnas": nombres,
        "filas": [[_json(v) if v is not None and not isinstance(v, (int, float, str)) else v for v in f] for f in filas],
        "n_filas": len(filas),
        "truncado": truncado,
        "avisos_descarga": errores or None,
    }


def refrescar_listado(ctx, tabla):
    try:
        n = almacen.cargar_listado(ctx.rentacar, tabla)
    except (WebcarError, KeyError) as exc:
        return {"error": str(exc)}
    return {"tabla": tabla, "filas": n}


def buscar_ayuda(ctx, consulta):
    resultados = ayuda.buscar(consulta)
    return {"resultados": resultados} if resultados else {"resultados": [], "nota": "Sin resultados en la base de conocimiento."}


def proponer_accion(ctx, tipo, parametros, explicacion=""):
    try:
        propuesta = acciones.proponer(ctx.conversacion, ctx.usuario, tipo, parametros)
    except (PermissionError, acciones.ParametrosInvalidos) as exc:
        return {"error": str(exc)}
    return {
        "propuesta_id": str(propuesta.id),
        "resumen": propuesta.resumen,
        "estado": "pendiente de confirmación por el usuario",
        "nota": "NO está hecho. El usuario debe pulsar Confirmar en la tarjeta.",
    }


# --- definiciones para el modelo -------------------------------------------

_TABLAS = list(esquema.POR_TABLA)

DEFINICIONES = [
    {
        "type": "function",
        "function": {
            "name": "describir_tablas",
            "description": "Columnas, tipos, clave y relaciones de las tablas de Webcar. Úsala antes de escribir SQL sobre una tabla que no conoces.",
            "parameters": {
                "type": "object",
                "properties": {"tablas": {"type": "array", "items": {"type": "string", "enum": _TABLAS}}},
                "required": ["tablas"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_datos",
            "description": (
                "Ejecuta UNA consulta SELECT (DuckDB) de solo lectura sobre los datos del rentacar. "
                "Usa LEFT JOIN para cruzar códigos con nombres. Devuelve como máximo "
                f"{settings.AGENTE_MAX_FILAS} filas: agrega en SQL en vez de traer filas sueltas."
            ),
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "refrescar_listado",
            "description": "Vuelve a descargar un listado de Webcar ahora mismo (si el usuario dice que los datos no están al día).",
            "parameters": {
                "type": "object",
                "properties": {"tabla": {"type": "string", "enum": _TABLAS}},
                "required": ["tabla"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_ayuda",
            "description": "Busca en la documentación de uso de Webcar Lite (pantallas, botones, colores, procedimientos).",
            "parameters": {
                "type": "object",
                "properties": {"consulta": {"type": "string"}},
                "required": ["consulta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "proponer_accion",
            "description": (
                "Propone un cambio en Webcar. NO lo ejecuta: crea una tarjeta que el usuario confirma. "
                "Comprueba antes con consultar_datos que los códigos existen. Pasa solo los datos que ha dado "
                "el usuario: no rellenes por tu cuenta los parámetros opcionales. Tipos: "
                + "; ".join(f"{t.clave}: {t.descripcion} Parámetros: {json.dumps(t.esquema['properties'], ensure_ascii=False)}"
                            for t in acciones.TIPOS.values())
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": list(acciones.TIPOS)},
                    "parametros": {"type": "object"},
                    "explicacion": {"type": "string"},
                },
                "required": ["tipo", "parametros"],
            },
        },
    },
]

IMPLEMENTACIONES = {
    "describir_tablas": describir_tablas,
    "consultar_datos": consultar_datos,
    "refrescar_listado": refrescar_listado,
    "buscar_ayuda": buscar_ayuda,
    "proponer_accion": proponer_accion,
}


def ejecutar(ctx, nombre, argumentos_json):
    funcion = IMPLEMENTACIONES.get(nombre)
    if not funcion:
        return {"error": f"Herramienta desconocida: {nombre}"}
    try:
        args = json.loads(argumentos_json or "{}")
    except json.JSONDecodeError:
        return {"error": "Argumentos JSON no válidos"}
    try:
        return funcion(ctx, **args)
    except TypeError as exc:
        return {"error": f"Argumentos incorrectos: {exc}"}
    except Exception as exc:  # noqa: BLE001
        log.exception("Fallo en herramienta %s", nombre)
        return {"error": f"Fallo interno en {nombre}: {exc}"}
