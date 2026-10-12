"""Qué listados ofrece Webcar y cómo se relacionan.

Cada listado se pide a la API con su «fichero» (las mismas rutas dadas de alta
en saasia > Rutas de CSV) y se carga en DuckDB como una tabla con nombre y
columnas en snake_case sin acentos, para que el modelo escriba SQL sin
comillas raras.

Las relaciones y avisos vienen de `saasia/backend/generador_informes/webcar.py`,
comprobadas contra los datos de la demo (30-09-2026). Los cruces deben ser
LEFT JOIN: lo que no casa son registros dados de baja.
"""

import re
import unicodedata
from dataclasses import dataclass, field


def slug(texto):
    """«Fecha devolución» → «fecha_devolucion»; «CODIGO RESERVAS» → «codigo_reservas»."""
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    texto = re.sub(r"[^0-9a-zA-Z]+", "_", texto).strip("_").lower()
    if not texto:
        texto = "columna"
    if texto[0].isdigit():
        texto = f"c_{texto}"
    return texto


def columnas_unicas(nombres):
    """Slugs sin repetir: Webcar trae columnas duplicadas («Compañía / n.Póliza» ×2)."""
    vistos, salida = {}, []
    for nombre in nombres:
        base = slug(nombre)
        n = vistos.get(base, 0)
        vistos[base] = n + 1
        salida.append(base if n == 0 else f"{base}_{n + 1}")
    return salida


@dataclass(frozen=True)
class Listado:
    tabla: str  # nombre de la tabla en DuckDB
    fichero: str  # parámetro «fichero» de la API de Webcar
    cabecera: str  # primera columna tal como la manda Webcar
    descripcion: str
    caduca_min: int  # minutos antes de volver a descargar
    legibles: tuple = ()  # columnas con el nombre legible del registro
    relaciones: dict = field(default_factory=dict)  # columna → tabla destino (por su 1ª columna)
    aviso: str = ""


# Orden = orden en que se presentan al modelo.
LISTADOS = [
    Listado(
        "reservas", "RESER.data", "CODIGO RESERVAS",
        "Reservas y contratos: fechas/horas de entrega y devolución, lugares, "
        "vehículo, importes, cobros, factura, extras, partner, usuario.",
        caduca_min=5,
        relaciones={
            "Cliente": "clientes",
            "Categoría": "categorias",
            "Matrícula": "vehiculos",
            "Modelo": "vehiculos",
            "Lugar entrega": "lugares",
            "Lugar devolución": "lugares",
            "Oficina": "oficinas",
            "Serie": "series",
            "Usuario": "usuarios",
            "Partner": "usuarios",
            "Entrega programada a": "usuarios",
            "Dev. programada a": "usuarios",
            "Forma cobro /1": "formas_pago",
            "Forma cobro /2": "formas_pago",
        },
        aviso=(
            "pais_cliente, domicilio_cliente, nif_cliente, telefono_cliente, "
            "fecha_nacimiento, direccion_vacacional y razon_social_facturas NO "
            "traen ese dato: traen el código del cliente; el dato real sale de "
            "clientes. «matricula» y «modelo» traen el código del vehículo "
            "(0013), no la matrícula: cruza con vehiculos. «extras» junta varios códigos Z-xxx sin separador. Las "
            "inmovilizaciones (taller, ITV) son reservas del cliente 00001 "
            "(INMOVILIZADO): exclúyelas al contar alquileres."
        ),
    ),
    Listado(
        "clientes", "CLIEN.data", "CODIGO CLIENTES",
        "Fichas de clientes: nombre, domicilio, país, NIF, teléfono, email, carnet, tarifa.",
        caduca_min=30,
        legibles=("Nombre",),
        relaciones={"CODIGO TARIFAS": "tarifas"},
        aviso=(
            "«pais» es texto libre (Alemania, Germany, Deutschland…): avisa de que "
            "puede salir repetido con distintas grafías."
        ),
    ),
    Listado(
        "vehiculos", "VEHIC.data", "CODIGO VEHICULOS",
        "Flota: categoría, modelo, matrícula, oficina, localización, kms, póliza, altas y bajas.",
        caduca_min=60,
        legibles=("Vehículo", "Matrícula"),
        relaciones={"Categoría": "categorias", "Oficina": "oficinas", "Localización": "centros_stock"},
    ),
    Listado(
        "categorias", "categ", "CODIGO CATEGORIAS",
        "Categorías de vehículo: nombre, precio por días/horas, fianza, tipo.",
        caduca_min=24 * 60,
        legibles=("Categoría",),
    ),
    Listado("oficinas", "ofici", "CODIGO OFICINAS", "Oficinas.", 24 * 60, ("Oficina",),
            {"Serie": "series", "Lugar defecto": "lugares", "Tarifa": "tarifas"}),
    Listado("usuarios", "usuar", "CODIGO USUARIOS",
            "Usuarios de Webcar: empleados y partners (hoteles, comerciales) con su comisión.",
            24 * 60, ("Nombre",), {"Oficina": "oficinas", "Tarifa partner-Booking": "tarifas"}),
    Listado("lugares", "lugar", "CODIGO LUGARES", "Lugares de entrega y devolución.",
            24 * 60, ("Lugar",), {"Centro de stock": "centros_stock"}),
    Listado("series", "serie", "CODIGO SERIES", "Series de facturas y contratos.", 24 * 60,
            ("Serie", "Nombre empresa")),
    Listado("formas_pago", "fpago", "CODIGO FORMAS DE PAGO", "Formas de pago.", 24 * 60,
            ("Forma",), {"Serie": "series"}),
    Listado("extras", "extra", "CODIGO EXTRAS", "Extras (silla bebé, seguros…).", 24 * 60,
            (), {"Categoría": "categorias", "Lugar entrega": "lugares"}),
    Listado("tarifas", "tarif", "CODIGO TARIFAS", "Tarifas.", 24 * 60, ("Tarifa",)),
    Listado("temporadas", "tarit", "CODIGO TEMPORADAS TARIFAS", "Temporadas de cada tarifa.",
            24 * 60, ("Temporada",), {"TARIFA": "tarifas", "Categoría oferta": "categorias"}),
    Listado("precios_tarifas", "tarip", "CODIGO TARIFAS PRECIOS",
            "Precios por tarifa, temporada, categoría y tramo de días.", 24 * 60, (),
            {"TARIFA": "tarifas", "Temporada": "temporadas", "Categoría": "categorias"}),
    Listado("cupos", "cupos", "CODIGO CUPOS", "Cupos de vehículos por categoría y fechas.",
            24 * 60, (), {"Categoría": "categorias"}),
    Listado("centros_stock", "cstoc", "CODIGO CENTROS DE STOCK", "Centros de stock.", 24 * 60,
            ("Centro de stock",)),
    Listado("tipos_incidencia", "tipin", "CODIGO TIPOS DE INCIDENCIAS", "Tipos de incidencia.",
            24 * 60, ("Tipo incidencia",)),
    Listado("incidencias", "INCID.data", "CODIGO INCIDENCIAS",
            "Incidencias de vehículos (ITV, reparaciones…).", 60, (),
            {"Vehículo": "vehiculos", "Matrícula": "vehiculos", "Tipo incidencia": "tipos_incidencia"}),
    Listado("facturas", "FACTU.data", "CODIGO FACTURAS DIRECTAS (FRA)",
            "Facturas directas (FRA).", 30, (),
            {"Cliente": "clientes", "Oficina": "oficinas", "Usuario": "usuarios",
             "Partner": "usuarios", "Forma cobro /1": "formas_pago",
             "Forma cobro /2": "formas_pago", "Serie factura": "series"},
            "«razon_social_facturas» es el código del cliente."),
    Listado("multas", "MULTA.data", "CODIGO MULTAS", "Expedientes de multas.", 60, (),
            {"Contrato": "reservas"}),
    Listado("registro_horas", "HORAS.data", "CODIGO REGISTRO OPERARIOS",
            "Fichajes de los operarios.", 60, (), {"Usuario": "usuarios"}),
]

POR_TABLA = {l.tabla: l for l in LISTADOS}
POR_FICHERO = {l.fichero: l for l in LISTADOS}
POR_CABECERA = {l.cabecera: l for l in LISTADOS}


def listado(tabla):
    try:
        return POR_TABLA[tabla]
    except KeyError:
        raise KeyError(f"Listado desconocido: {tabla}. Válidos: {', '.join(POR_TABLA)}") from None
