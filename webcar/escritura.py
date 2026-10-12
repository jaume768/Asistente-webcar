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

import datetime
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
    limites: dict = field(default_factory=dict)  # nombre → maxlength (int)
    opciones: dict = field(default_factory=dict)  # nombre de un select → valores que admite

    def valor(self, nombre, defecto=None):
        return next((v for n, v in self.campos if n == nombre), defecto)

    def limite(self, nombre):
        return self.limites.get(nombre)

    def tiene(self, nombre):
        return nombre in self.casillas or any(n == nombre for n, _ in self.campos)

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
                if a.get("maxlength", "").isdigit():
                    self._f.limites[nombre] = int(a["maxlength"])
        elif tag == "select":
            self._cierra_select()
            self._select = {"nombre": nombre, "opciones": [], "activo": "disabled" not in a}
        elif tag == "option" and self._select is not None:
            self._cierra_opcion()
            self._opcion = {"valor": a.get("value") if "value" in a else None, "elegida": "selected" in a, "texto": ""}
        elif tag == "textarea":
            self._textarea = [nombre if "disabled" not in a else "", ""]
            if nombre and a.get("maxlength", "").isdigit():
                self._f.limites[nombre] = int(a["maxlength"])

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
        self._f.opciones[s["nombre"]] = [v for v, _ in s["opciones"]]


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

    def leer(self, pagina, params=None, *, por_post=False):
        """Pide una página con la sesión puesta y devuelve su HTML. Falla si Webcar la rechaza.

        Cuando el `segur` o la sesión no valen, Webcar manda la página igualmente
        pero con una redirección a la pantalla de login (`APP0`): eso es un rechazo.
        """
        datos = {**self._sesion(), **(params or {})}
        html_pagina = self._pedir(pagina, datos=datos) if por_post else self._pedir(pagina, params=datos)
        if re.search(r"HTTP-EQUIV=['\"]?REFRESH['\"]?[^>]*URL=APP0\b", html_pagina, flags=re.I):
            raise WebcarError(f"Webcar ha rechazado la petición a {pagina.rstrip('?')}: la sesión o el token han caducado.")
        return html_pagina

    def get_form(self, pagina, params=None, *, accion=None, con=None, por_post=False):
        """Pide una página y devuelve `(segur, formulario)` del formulario que va a `accion` y tiene el campo `con`.

        El `segur` es el de esa carga: hay que enviarlo en el POST siguiente.
        Con `por_post`, la página se pide por POST (así navega Webcar entre pantallas).
        """
        html_pagina = self.leer(pagina, params, por_post=por_post)
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


# --- altas: comprobaciones antes de enviar ----------------------------------
# Webcar recorta en silencio lo que no cabe y guarda códigos que no existen: se
# comprueba aquí y, si algo no encaja, no se envía nada.

def _segur(sesion):
    """Un `segur` del momento. Sale de Situación, que pesa poco (el listado de clientes son cientos de KB)."""
    return sesion.get_form("APP1")[0]


def _texto(valor):
    return " ".join(str(valor if valor is not None else "").split())


def _igual(a, b):
    return _texto(a).casefold() == _texto(b).casefold()


def _valida_campos(formulario, cambios, etiquetas):
    """Los campos que se van a cambiar tienen que existir en el formulario que ha mandado Webcar."""
    faltan = [etiquetas.get(c, c) for c in cambios if not formulario.tiene(c)]
    if faltan:
        raise WebcarError(f"El formulario de Webcar no tiene el campo «{', '.join(faltan)}»: ha cambiado y no se envía nada.")


def _valida_limites(formulario, cambios, etiquetas):
    for campo, valor in cambios.items():
        limite = formulario.limite(campo)
        if limite is not None and len(str(valor)) > limite:
            nombre = etiquetas.get(campo, campo)
            raise WebcarError(
                f"«{nombre}» admite como máximo {limite} caracteres "
                f"(has puesto {len(str(valor))})."
            )


def _valida_opciones(formulario, cambios, etiquetas):
    """En un desplegable solo vale uno de los valores que ofrece Webcar."""
    for campo, valor in cambios.items():
        opciones = formulario.opciones.get(campo)
        if opciones is not None and valor not in opciones:
            validas = ", ".join(o for o in opciones if o.strip())
            raise WebcarError(f"«{valor}» no es un valor válido para «{etiquetas.get(campo, campo)}». Valores: {validas[:300]}.")


def _valida(formulario, cambios, etiquetas):
    _valida_campos(formulario, cambios, etiquetas)
    _valida_limites(formulario, cambios, etiquetas)
    _valida_opciones(formulario, cambios, etiquetas)


def _partes_fecha(valor):
    """«1990-01-02» → («2», «1», «1990»): día y mes sin ceros, como los desplegables de Webcar."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(valor or "").strip())
    try:
        datetime.date(*map(int, m.groups()))
    except (AttributeError, ValueError):
        raise WebcarError(f"«{valor}» no es una fecha AAAA-MM-DD válida.") from None
    anio, mes, dia = m.groups()
    return str(int(dia)), str(int(mes)), anio


# --- clientes --------------------------------------------------------------

_CLIENTE_CAMPOS = {
    "nombre": "matriu2", "domicilio": "matriu3", "cp": "matriu23", "municipio": "matriu4",
    "pais": "matriu5", "nif": "matriu6", "telefono": "matriu7", "whatsapp": "matriu8",
    "email": "matriu9", "licencia": "matriu10", "oficina": "MATRIU11", "tarifa": "MATRIU19",
    "razon_social": "matriu13", "numero": "matriu18",
    "domicilio_vacacional": "matriu16", "anotaciones": "matriu12",
}
_CLIENTE_FECHAS = {
    "fecha_nacimiento": "MATRIU20", "fecha_expedicion": "MATRIU21", "fecha_caducidad": "MATRIU22",
}
_ETIQUETAS_CLIENTE = {
    **{campo: clave for clave, campo in _CLIENTE_CAMPOS.items()},
    **{f"{base}-{n}": clave for clave, base in _CLIENTE_FECHAS.items() for n in (1, 2, 3)},
}
# Fichas que se abren, como mucho, para comprobar un NIF.
_MAX_FICHAS = 10


def _nif(valor):
    return re.sub(r"[\s.\-]", "", str(valor or "")).upper()


def _buscar_clientes(sesion, texto):
    """Códigos de cliente que devuelve el buscador de Webcar, del más nuevo al más antiguo.

    El buscador mira varios campos y casa por trozos («9999» encuentra cinco
    clientes): sirve para acotar, no para identificar.
    """
    segur = _segur(sesion)  # antes de montar el cuerpo: es lo que inicia la sesión si hace falta
    html_pagina = sesion.enviar("APP2?", [
        ("oper", sesion.oper), ("c", sesion.c), ("segur", segur), ("inactivos", ""), ("filtro", texto),
    ])
    codigos = {f.valor("cliente") or "" for f in leer_formularios(html_pagina)}
    return sorted((c for c in codigos if re.fullmatch(r"\d{3,6}", c)), reverse=True)


def _ficha_cliente(sesion, codigo):
    """Formulario de la ficha de un cliente que ya existe, o None si Webcar no la abre."""
    _, f = sesion.get_form("APP2?", {"clave": codigo, "segur": _segur(sesion)}, accion="APP2", con="matriu2")
    if (f.valor("clave") or "").lstrip("+") != codigo or f.valor("nuevo") == "S" or not f.valor("matriu2"):
        return None
    return f


def _cliente_por_nif(sesion, nif):
    """`(código, ficha)` del cliente cuyo NIF es exactamente `nif`, o `(None, None)`."""
    for codigo in _buscar_clientes(sesion, nif)[:_MAX_FICHAS]:
        ficha = _ficha_cliente(sesion, codigo)
        if ficha and _nif(ficha.valor("matriu6")) == _nif(nif):
            return codigo, ficha
    return None, None


def crear_cliente(sesion, params):
    """Da de alta un cliente. Devuelve su código solo si, al volver a leer, está con ese nombre y NIF."""
    nombre = _texto(params.get("nombre"))
    nif = _texto(params.get("nif"))
    if not nombre or not nif:
        raise WebcarError("Un cliente necesita al menos nombre y NIF.")
    cambios = {
        campo: _texto(params[clave]) for clave, campo in _CLIENTE_CAMPOS.items() if params.get(clave) not in (None, "")
    }
    for clave, base in _CLIENTE_FECHAS.items():
        if params.get(clave):
            cambios[f"{base}-1"], cambios[f"{base}-2"], cambios[f"{base}-3"] = _partes_fecha(params[clave])
    existente, _ = _cliente_por_nif(sesion, nif)
    if existente:
        raise WebcarError(f"Ya existe el cliente {existente} con el NIF {nif}; no se ha creado otro.")
    _, f = sesion.get_form(
        "APP2?", {"clave": "NUEVO", "segur": _segur(sesion)}, accion="APP2", con="matriu2", por_post=True
    )
    if f.valor("nuevo") != "S":
        raise WebcarError("Webcar no ha abierto una ficha de cliente nueva; no se envía nada.")
    _valida(f, cambios, _ETIQUETAS_CLIENTE)
    sesion.enviar(f.accion, f.cuerpo(cambios))
    log.info("Enviada el alta de un cliente (oper %s)", sesion.oper)
    try:
        codigo, ficha = _cliente_por_nif(sesion, nif)
    except WebcarError as exc:
        raise WebcarError(
            f"Se ha enviado el alta de «{nombre}», pero no se ha podido comprobar el resultado ({exc}). "
            "Revísalo en Webcar antes de repetir."
        ) from None
    if not codigo:
        raise WebcarError(f"Se ha enviado el alta de «{nombre}», pero no aparece en Webcar con el NIF {nif}. Revísalo.")
    if not _igual(ficha.valor("matriu2"), nombre):
        raise WebcarError(
            f"Webcar ha guardado el cliente {codigo} con el nombre «{ficha.valor('matriu2')}», no «{nombre}». Revísalo."
        )
    return f"Cliente {codigo} «{nombre}» creado en Webcar (comprobado al abrir su ficha)."


# --- lugares ---------------------------------------------------------------

_LUGAR_CAMPOS = {
    "nombre": "matriu2", "nombre_ingles": "matriu18", "nombre_aleman": "matriu19",
    "centro_stock": "MATRIU3", "dias_minimo": "matriu4", "release": "matriu5",
    "color": "matriu7", "calculo_precios": "MATRIU8", "tarifa": "MATRIU22",
    "envia_oficina": "MATRIU23", "latitud": "matriu9", "longitud": "matriu10",
}
_ETIQUETAS_LUGAR = {campo: clave for clave, campo in _LUGAR_CAMPOS.items()}


def _lugares(sesion):
    """{código: nombre} de los lugares activos. En cada fila del listado, el código va en `clave` y el nombre en la 2ª celda."""
    html_pagina = sesion.leer("APP541", {"segur": _segur(sesion)})
    lugares = {}
    for fila in re.split(r"(?i)<tr\b", html_pagina):
        m = re.search(r"""name=["']?clave["']?\s+value=["']?(\d+)["']?""", fila, re.I)
        celdas = [texto_visible(c) for c in re.split(r"(?i)<td\b[^>]*>", fila)[1:]]
        if m and len(celdas) >= 2 and celdas[0] == m.group(1):
            lugares[m.group(1)] = celdas[1]
    return lugares


def crear_lugar(sesion, params):
    """Da de alta un lugar de entrega/devolución. Devuelve su código solo si aparece en el listado con ese nombre."""
    nombre = _texto(params.get("nombre"))
    if not nombre:
        raise WebcarError("Un lugar necesita al menos el nombre.")
    cambios = {
        campo: _texto(params[clave]) for clave, campo in _LUGAR_CAMPOS.items() if params.get(clave) not in (None, "")
    }
    if "matriu7" in cambios and not re.fullmatch(r"[0-9A-Fa-f]{6}", cambios["matriu7"]):
        raise WebcarError("El color debe ser hexadecimal de seis cifras (p. ej. 3833FF).")
    antes = _lugares(sesion)
    repetido = next((c for c, n in antes.items() if _igual(n, nombre)), None)
    if repetido:
        raise WebcarError(f"Ya existe el lugar {repetido} «{nombre}»; no se ha creado otro.")
    _, f = sesion.get_form(
        "APP541?", {"clave": "NUEVO", "segur": _segur(sesion)}, accion="APP541", con="matriu2", por_post=True
    )
    if f.valor("nuevo") != "S":
        raise WebcarError("Webcar no ha abierto una ficha de lugar nueva; no se envía nada.")
    _valida(f, cambios, _ETIQUETAS_LUGAR)
    sesion.enviar(f.accion, f.cuerpo(cambios))
    log.info("Enviada el alta del lugar «%s» (oper %s)", nombre, sesion.oper)
    try:
        despues = _lugares(sesion)
    except WebcarError as exc:
        raise WebcarError(
            f"Se ha enviado el alta del lugar «{nombre}», pero no se ha podido comprobar el resultado ({exc}). "
            "Revísalo en Webcar antes de repetir."
        ) from None
    codigo = next((c for c, n in despues.items() if c not in antes and _igual(n, nombre)), None)
    if not codigo:
        raise WebcarError(f"Se ha enviado el alta del lugar «{nombre}», pero no aparece en Webcar. Revísalo.")
    return f"Lugar L-{codigo} «{nombre}» creado en Webcar (comprobado en el listado de lugares)."


# --- reservas (exprés) -----------------------------------------------------

_ETIQUETAS_EXPRES = {"CATEGORIA": "categoria", "desdedia": "fecha_entrega", "TIEMPO": "dias", "CLIENTE": "cliente"}


def _reservas_de_cliente(sesion, cliente):
    """Números de las reservas activas de un cliente (pantalla «reservas/contratos de este cliente»)."""
    html_pagina = sesion.leer("APP21?", {"cliente": cliente, "segur": _segur(sesion)})
    return {
        f.valor("clave") for f in leer_formularios(html_pagina)
        if f.accion.rstrip("?").upper() == "APP21" and f.valor("cliente") == cliente
        and re.fullmatch(r"\d{6}", f.valor("clave") or "")
    }


def crear_reserva(sesion, params):
    """Crea una reserva exprés (categoría + cliente + fecha + días), como el formulario de Situación.

    El número lo pone Webcar y su respuesta al formulario no sirve para saberlo
    (Situación trae formularios con la clave de otras reservas). Se comprueba
    leyendo las reservas del cliente antes y después: devuelve el número solo si
    aparece una nueva y, al abrirla, tiene la categoría, la fecha y el cliente pedidos.
    """
    categoria = _texto(params.get("categoria")).upper()
    cliente = _texto(params.get("cliente"))
    fecha = _texto(params.get("fecha_entrega"))
    dias = _texto(params.get("dias") or "1")
    if not re.fullmatch(r"C-\d{2}", categoria):
        raise WebcarError("La categoría debe ser un código C-xx (p. ej. C-02).")
    # Con un nombre, Webcar daría de alta un cliente sin datos y no habría forma
    # segura de comprobar el resultado: el cliente tiene que existir ya.
    if not re.fullmatch(r"\d{5}", cliente):
        raise WebcarError(
            "Indica el código del cliente con sus cinco cifras (p. ej. 03527). Si es nuevo, dalo de alta antes."
        )
    _partes_fecha(fecha)
    if not re.fullmatch(r"[1-9]|[12]\d|30", dias):
        raise WebcarError("La duración debe ser un número de días entre 1 y 30.")
    if cliente not in _buscar_clientes(sesion, cliente):
        raise WebcarError(f"No existe el cliente {cliente} en Webcar; no se ha creado la reserva.")
    antes = _reservas_de_cliente(sesion, cliente)
    _, f = sesion.get_form("APP1", con="CATEGORIA")
    boton = ("reservar", "Reservar")
    if boton not in f.botones:
        raise WebcarError("El formulario de reserva exprés de Webcar ha cambiado; no se envía nada.")
    cambios = {"CATEGORIA": categoria, "desdedia": fecha, "TIEMPO": dias, "CLIENTE": cliente}
    _valida(f, cambios, _ETIQUETAS_EXPRES)
    # El formulario exprés se envía a la propia Situación (action="?").
    sesion.enviar("APP1?", f.cuerpo(cambios, boton=boton))
    log.info("Enviada una reserva exprés %s para el %s (oper %s)", categoria, fecha, sesion.oper)
    aviso = f"Revisa las reservas del cliente {cliente} en Webcar antes de repetir."
    try:
        nuevas = sorted(_reservas_de_cliente(sesion, cliente) - antes, reverse=True)
        abiertas = [(clave, _editor_reserva(sesion, clave)[1]) for clave in nuevas]
    except WebcarError as exc:
        raise WebcarError(f"Se ha enviado la reserva exprés, pero no se ha podido comprobar el resultado ({exc}). {aviso}") from None
    if not abiertas:
        raise WebcarError(f"Se ha enviado la reserva exprés, pero el cliente {cliente} no tiene ninguna reserva nueva. {aviso}")
    for clave, guardada in abiertas:
        if (guardada.marcada("matriu1") and guardada.valor("matriu2") == cliente
                and guardada.valor("MATRIU3") == categoria and guardada.valor("matriu4") == fecha):
            return (
                f"Reserva {clave} creada en Webcar: {categoria}, cliente {cliente}, "
                f"del {guardada.valor('matriu4')} {guardada.valor('matriu5')} al {guardada.valor('matriu6')} {guardada.valor('matriu7')} "
                "(comprobado al volver a abrirla)."
            )
    raise WebcarError(
        f"Webcar ha creado la reserva {abiertas[0][0]} para el cliente {cliente}, pero no coincide con lo pedido "
        f"({categoria}, entrega el {fecha}). Revísala."
    )
