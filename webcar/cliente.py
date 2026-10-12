"""Descarga y limpieza de los listados CSV de Webcar.

La lógica de limpieza viene de saasia (`generador_informes/descarga.py`), que
ya resolvió las rarezas del formato. Resumen de lo que manda Webcar:

- latin-1 / cp1252, filas separadas solo por «\\r», separador «;», sin comillas;
- acentos como entidades HTML, a veces sin «;» final («Categor&iacutea»);
- textos ya estropeados de origen («EspaÃ±a»);
- «;» dentro de un campo («Calle X; 38») y saltos de línea dentro de
  anotaciones, que parten un registro en varias líneas.
"""

import codecs
import html
import io
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

log = logging.getLogger(__name__)

USER_AGENT = "webcar-asistente/0.1"


class WebcarError(RuntimeError):
    """Error legible para el usuario o el agente."""


def codi_del_dia(fecha=None):
    """Parámetro «codi» que exige Webcar: AAMMDD × 7 − 128.

    OJO (seguridad): es predecible. Con la fórmula y el código del rentacar
    cualquiera puede bajar sus datos. Ver docs/PLAN.md › Seguridad.
    """
    fecha = fecha or timezone.localdate()
    return int(fecha.strftime("%y%m%d")) * 7 - 128


def url_listado(fichero, codigo_rentacar, fecha=None):
    base = urlparse(settings.WEBCAR_API_URL)
    params = [
        (k, v)
        for k, v in parse_qsl(base.query, keep_blank_values=True)
        if k not in {"codi", "ruta", "fichero"}
    ]
    params += [
        ("codi", str(codi_del_dia(fecha))),
        ("ruta", codigo_rentacar),
        ("fichero", fichero),
    ]
    return urlunparse(base._replace(query=urlencode(params)))


def descargar(fichero, codigo_rentacar):
    """Bytes crudos del listado y su charset declarado."""
    url = url_listado(fichero, codigo_rentacar)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=settings.WEBCAR_TIMEOUT_SECONDS) as resp:
            tipo = resp.headers.get_content_type()
            charset = resp.headers.get_content_charset()
            if tipo in {"text/html", "application/xhtml+xml"}:
                raise WebcarError("Webcar devolvió una página HTML en vez del CSV (¿código de rentacar incorrecto?).")
            datos = resp.read(settings.WEBCAR_MAX_BYTES + 1)
    except HTTPError as exc:
        raise WebcarError(f"Webcar respondió {exc.code} al pedir {fichero}.") from exc
    except URLError as exc:
        raise WebcarError(f"No se pudo conectar con Webcar: {exc.reason}") from exc
    if len(datos) > settings.WEBCAR_MAX_BYTES:
        raise WebcarError(f"El listado {fichero} supera el tamaño máximo permitido.")
    if not datos.strip():
        raise WebcarError(f"El listado {fichero} ha llegado vacío.")
    return datos, charset


# --- limpieza --------------------------------------------------------------

def _cp1252_o_latin1(exc):
    """Lo que cp1252 no define se lee (y se vuelve a escribir) como latin-1, byte a byte."""
    trozo = exc.object[exc.start:exc.end]
    if isinstance(exc, UnicodeEncodeError):
        return trozo.encode("latin-1", errors="replace"), exc.end
    return trozo.decode("latin-1"), exc.end


codecs.register_error("cp1252_o_latin1", _cp1252_o_latin1)

LATIN1 = {"iso-8859-1", "iso8859-1", "latin-1", "latin1", "l1", "windows-1252", "cp1252"}

# «;» pegado a una palabra y seguido de espacio y más texto: está dentro de un
# campo («Untersteinstr; 38»), no separa columnas.
_SEPARADOR_EN_TEXTO = re.compile(r"(?<=[^\W_]);(?= +[^ ;])")


def _quita_separadores_de_mas(linea, separadores):
    sobran = linea.count(";") - separadores
    if sobran <= 0:
        return linea
    candidatos = list(_SEPARADOR_EN_TEXTO.finditer(linea))
    if len(candidatos) < sobran:
        return linea
    for m in reversed(candidatos[:sobran]):
        linea = linea[: m.start()] + "," + linea[m.end():]
    return linea


def _arregla_doble_codificacion(linea):
    if "Ã" not in linea and "Â" not in linea:
        return linea
    campos = []
    for campo in linea.split(";"):
        if "Ã" in campo or "Â" in campo:
            try:
                campo = campo.encode("cp1252").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        campos.append(campo)
    return ";".join(campos)


def normalizar(datos, charset=None):
    """Bytes de Webcar → texto CSV limpio (UTF-8, «\\n», mismo nº de columnas)."""
    if (charset or "latin-1").strip().lower() in LATIN1:
        texto = datos.decode("cp1252", errors="cp1252_o_latin1")
    else:
        texto = datos.decode("utf-8", errors="replace")
    salida = io.StringIO()
    separadores = None
    pendiente = None  # registro al que aún le faltan campos
    ultimo = None  # último registro completo, aún sin escribir
    for linea in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if "&" in linea:
            linea = html.unescape(linea)
        linea = _arregla_doble_codificacion(linea)
        if separadores is None:
            if not linea.strip():
                continue
            separadores = linea.count(";")
            salida.write(linea + "\n")
            continue
        if not linea.strip() and pendiente is None:
            continue
        # Una línea sin ningún «;» tras un registro completo es la continuación
        # de su último campo (anotaciones con salto de línea).
        if pendiente is None and ultimo is not None and ";" not in linea:
            ultimo = f"{ultimo} {linea.strip()}"
            continue
        linea = _quita_separadores_de_mas(linea, separadores)
        if pendiente is not None:
            unida = _quita_separadores_de_mas(f"{pendiente} {linea}", separadores)
            if unida.count(";") <= separadores:
                pendiente = unida
            else:
                salida.write(pendiente + "\n")
                pendiente = linea
        else:
            # Empieza un registro nuevo: el anterior ya no puede continuar.
            if ultimo is not None:
                salida.write(ultimo + "\n")
                ultimo = None
            pendiente = linea
        if pendiente.count(";") >= separadores:
            if ultimo is not None:
                salida.write(ultimo + "\n")
            ultimo, pendiente = pendiente, None
    for resto in (ultimo, pendiente):
        if resto is not None and resto.strip():
            salida.write(resto + "\n")
    return salida.getvalue()
