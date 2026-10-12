"""Escritura en Webcar reproduciendo sus formularios (camino 2).

Webcar no tiene API de escritura: los cambios son formularios HTML que se envían
por POST a páginas `APPxx`, con el usuario (`oper`), un token de sesión (`c`) que
da el login y un token `segur` que hay que leer de la página justo antes de
enviar. Aquí se hace lo mismo que haría un empleado: entrar, abrir el
formulario, cambiar lo justo y guardar. Ver docs/Escritura.md.

Reglas:
- Nada se envía si `puede_escribir` no abre las tres puertas del `.env`.
- Cada escritura se envía UNA vez; no se reintenta un POST.
- Una acción solo se da por hecha si Webcar la confirma al volver a leer.
- Ni la contraseña ni el token `c` salen en logs ni en mensajes de error.
"""

import logging
import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from django.conf import settings

# Importar cliente registra el manejador «cp1252_o_latin1» que se usa aquí.
from .cliente import USER_AGENT, WebcarError

log = logging.getLogger(__name__)

# Webcar habla cp1252 en los dos sentidos: se lee y se envía igual que los CSV.
CODIFICACION = {"encoding": "cp1252", "errors": "cp1252_o_latin1"}


def puede_escribir(rentacar, tipo_accion):
    """Las tres puertas del `.env`: interruptor general, rentacar y acción."""
    return bool(
        settings.WEBCAR_ESCRITURA
        and rentacar.codigo in settings.WEBCAR_ESCRITURA_RENTACARS
        and (not settings.WEBCAR_ESCRITURA_ACCIONES or tipo_accion in settings.WEBCAR_ESCRITURA_ACCIONES)
    )


# --- formularios -----------------------------------------------------------

@dataclass
class Formulario:
    """Un <form> de Webcar tal como lo enviaría un navegador."""

    accion: str = ""
    campos: list = field(default_factory=list)  # [(nombre, valor)] en orden, sin botones
    casillas: dict = field(default_factory=dict)  # nombre → (valor, marcada)
    botones: list = field(default_factory=list)  # [(nombre, valor)] de los submit

    def valor(self, nombre, defecto=None):
        return next((v for n, v in self.campos if n == nombre), defecto)

    def marcada(self, nombre):
        return self.casillas.get(nombre, ("", False))[1]

    def cuerpo(self, cambios=None, desmarcar=(), boton=None):
        """Pares a enviar: todo lo que había, con `cambios`, sin las casillas de `desmarcar` y con el botón pulsado."""
        cambios = dict(cambios or {})
        pares = []
        for nombre, valor in self.campos:
            if nombre in desmarcar:
                continue
            pares.append((nombre, cambios.pop(nombre, valor)))
        pares += list(cambios.items())
        if boton:
            pares.append(boton)
        return pares


class _LectorFormularios(HTMLParser):
    """Saca los formularios de una página con las mismas reglas que un navegador al enviarlos."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.formularios = []
        self._f = None
        self._select = None
        self._opcion = None
        self._textarea = None

    def handle_starttag(self, tag, attrs):
        if self._textarea is not None:  # HTML dentro de un textarea: es texto
            self._textarea[1] += self.get_starttag_text()
            return
        a = {k: v or "" for k, v in attrs}
        if tag == "form":
            self._cierra_select()
            self._f = Formulario(accion=a.get("action", ""))
            self.formularios.append(self._f)
            return
        if self._f is None:
            return
        nombre = a.get("name", "")
        if tag == "input":
            tipo = a.get("type", "text").lower()
            if tipo in {"submit", "image"}:
                self._f.botones.append((nombre, a.get("value", "")))
            elif tipo in {"button", "reset", "file"} or not nombre or "disabled" in a:
                pass
            elif tipo in {"checkbox", "radio"}:
                valor, marcada = a.get("value", "on"), "checked" in a
                if tipo == "checkbox":
                    self._f.casillas[nombre] = (valor, marcada)
                if marcada:
                    self._f.campos.append((nombre, valor))
            else:
                self._f.campos.append((nombre, a.get("value", "")))
        elif tag == "select":
            self._cierra_select()
            self._select = {"nombre": nombre, "opciones": [], "activo": "disabled" not in a}
        elif tag == "option" and self._select is not None:
            self._cierra_opcion()
            self._opcion = {"valor": a.get("value") if "value" in a else None, "elegida": "selected" in a, "texto": ""}
        elif tag == "textarea":
            self._textarea = [nombre if "disabled" not in a else "", ""]

    def handle_data(self, data):
        if self._textarea is not None:
            self._textarea[1] += data
        elif self._opcion is not None:
            self._opcion["texto"] += data

    def handle_endtag(self, tag):
        if tag == "textarea" and self._textarea is not None:
            nombre, texto = self._textarea
            self._textarea = None
            if self._f is not None and nombre:
                # Como el navegador: ignora el primer salto de línea y envía los demás como CRLF.
                texto = re.sub(r"\r\n|\r|\n", "\n", texto)
                texto = texto[1:] if texto.startswith("\n") else texto
                self._f.campos.append((nombre, texto.replace("\n", "\r\n")))
        elif self._textarea is not None:
            self._textarea[1] += f"</{tag}>"
        elif tag == "option":
            self._cierra_opcion()
        elif tag == "select":
            self._cierra_select()
        elif tag == "form":
            self._cierra_select()
            self._f = None

    def _cierra_opcion(self):
        if self._opcion is not None and self._select is not None:
            o = self._opcion
            valor = o["valor"] if o["valor"] is not None else " ".join(o["texto"].split())
            self._select["opciones"].append((valor, o["elegida"]))
        self._opcion = None

    def _cierra_select(self):
        self._cierra_opcion()
        s, self._select = self._select, None
        if s is None or self._f is None or not s["nombre"] or not s["activo"] or not s["opciones"]:
            return
        # Webcar marca SELECTED la opción vacía y además la real: el navegador se queda con la
        # ÚLTIMA marcada. Sin ninguna marcada, envía la primera.
        marcadas = [v for v, sel in s["opciones"] if sel]
        elegida = marcadas[-1] if marcadas else s["opciones"][0][0]
        self._f.campos.append((s["nombre"], elegida))


def leer_formularios(html_pagina):
    lector = _LectorFormularios()
    lector.feed(html_pagina)
    lector.close()
    return lector.formularios


def texto_visible(html_pagina, maximo=300):
    """Texto de una página sin etiquetas ni entidades, para mensajes de error."""
    sin_codigo = re.sub(r"<(script|style)\b.*?</\1>", " ", html_pagina, flags=re.S | re.I)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", sin_codigo)).split())[:maximo]


# --- sesión ----------------------------------------------------------------

class SesionWebcar:
    """Sesión de un usuario de Webcar: login, lectura de formularios y envío."""

    def __init__(self, ruta, oper, password):
        base = urlparse(settings.WEBCAR_API_URL)
        self.base = f"{base.scheme}://{base.netloc}/{ruta.upper()}/"
        self.oper = oper
        self._password = password
        self.c = None

    @classmethod
    def de_rentacar(cls, rentacar):
        if not rentacar.oper_webcar or not rentacar.password_webcar:
            raise WebcarError("Este rentacar no tiene usuario y contraseña de Webcar (admin › Rentacars).")
        return cls(rentacar.codigo, rentacar.oper_webcar, rentacar.password_webcar)

    def _pedir(self, pagina, params=None, datos=None):
        """GET (con `params`) o POST (con `datos`) a una página. Devuelve el HTML ya decodificado."""
        url = urljoin(self.base, pagina)
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params, **CODIFICACION)
        cuerpo = urlencode(datos, **CODIFICACION).encode("ascii") if datos is not None else None
        req = Request(url, data=cuerpo, headers={"User-Agent": USER_AGENT})
        # Los errores nombran solo la página: la URL lleva el token de sesión.
        try:
            with urlopen(req, timeout=settings.WEBCAR_TIMEOUT_SECONDS) as resp:
                crudo = resp.read(settings.WEBCAR_MAX_BYTES + 1)
        except HTTPError as exc:
            raise WebcarError(f"Webcar respondió {exc.code} en {pagina.rstrip('?')}.") from None
        except (URLError, TimeoutError) as exc:
            raise WebcarError(f"No se pudo conectar con Webcar ({pagina.rstrip('?')}): {getattr(exc, 'reason', exc)}") from None
        return crudo.decode(**CODIFICACION)

    def login(self):
        """Entra con usuario y contraseña y guarda el token de sesión `c`."""
        html_pagina = self._pedir("APP00", datos={"oper": self.oper, "oficina": "00", "c": self._password})
        # Si acepta la contraseña, redirige a APP1?oper=…&c=<token>.
        m = re.search(r"URL=APP1\?[^'\">]*?[?&]c=([^&'\">\s]+)", html_pagina, flags=re.I)
        if not m:
            raise WebcarError("Webcar no ha aceptado el usuario o la contraseña.")
        self.c = unescape(m.group(1))
        return self.c

    def _sesion(self):
        if not self.c:
            self.login()
        return {"oper": self.oper, "c": self.c}

    def get_form(self, pagina, params=None, *, accion=None, con=None, por_post=False):
        """Pide una página y devuelve `(segur, formulario)` del formulario que va a `accion` y tiene el campo `con`.

        El `segur` es el de esa carga: hay que enviarlo en el POST siguiente.
        Con `por_post`, la página se pide por POST (así navega Webcar entre pantallas).
        """
        datos = {**self._sesion(), **(params or {})}
        html_pagina = self._pedir(pagina, datos=datos) if por_post else self._pedir(pagina, params=datos)
        formularios = leer_formularios(html_pagina)
        for f in formularios:
            if accion and f.accion.rstrip("?").upper() != accion.rstrip("?").upper():
                continue
            if con and f.valor(con) is None and con not in f.casillas:
                continue
            segur = f.valor("segur")
            if not segur:
                continue
            return segur, f
        if any(f.accion.upper().startswith("APP00") for f in formularios):
            raise WebcarError("Webcar ha pedido iniciar sesión de nuevo.")
        raise WebcarError(f"No se ha encontrado el formulario esperado en {pagina.rstrip('?')}: «{texto_visible(html_pagina, 120)}»")

    def enviar(self, pagina, campos):
        """Envía un formulario (pares nombre-valor, ya con su `segur`). Devuelve el HTML de respuesta."""
        return self._pedir(pagina, datos=campos)


# --- acciones --------------------------------------------------------------

def _codigo_reserva(valor):
    """«4292» → «004292». Webcar numera las reservas con seis cifras."""
    codigo = str(valor or "").strip()
    if not re.fullmatch(r"\d{1,6}", codigo):
        raise WebcarError(f"«{codigo}» no es un número de reserva válido.")
    return codigo.zfill(6)


def _editor_reserva(sesion, reserva):
    """Abre el editor de una reserva (como el lápiz de Situación) y devuelve `(segur, formulario)`."""
    segur, _ = sesion.get_form("APP1")
    segur, formulario = sesion.get_form("APP21?", {"clave": reserva, "segur": segur}, accion="APP21", con="matriu1")
    # Con un número que no existe Webcar podría abrir un editor en blanco: no se toca.
    abierta = (formulario.valor("clave") or "").lstrip("+")
    if abierta != reserva or not formulario.valor("matriu2") or not formulario.valor("matriu25"):
        raise WebcarError(f"Webcar no ha abierto la reserva {reserva} (¿existe?).")
    return segur, formulario


def anular_reserva(sesion, params):
    """Anula una reserva: desmarca «Activo» en su editor y guarda, sin tocar nada más.

    Devuelve el texto de resultado solo si, al volver a abrirla, Webcar la da por anulada.
    """
    reserva = _codigo_reserva(params.get("reserva"))
    _, formulario = _editor_reserva(sesion, reserva)
    if not formulario.marcada("matriu1"):
        raise WebcarError(f"La reserva {reserva} ya figura anulada en Webcar; no se ha enviado nada.")
    # «Guardar» no tiene nombre: el navegador no envía nada por el botón.
    sesion.enviar(formulario.accion, formulario.cuerpo(desmarcar={"matriu1"}))
    log.info("Enviada la anulación de la reserva %s (oper %s)", reserva, sesion.oper)
    try:
        _, despues = _editor_reserva(sesion, reserva)
    except WebcarError as exc:
        raise WebcarError(
            f"Se ha enviado la anulación de la reserva {reserva}, pero no se ha podido comprobar el resultado ({exc}). "
            "Revísala en Webcar antes de repetir."
        ) from None
    if despues.marcada("matriu1"):
        raise WebcarError(f"Webcar no ha anulado la reserva {reserva}: sigue activa después de guardar.")
    return f"Reserva {reserva} anulada en Webcar (comprobado al volver a abrirla)."
