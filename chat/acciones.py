"""Acciones que el agente puede PROPONER y el usuario confirma.

Cada acción declara sus parámetros (JSON Schema para el modelo), una función
que valida y resume la propuesta, y un ejecutor que llama a Webcar.

ESTADO ACTUAL: Webcar no tiene API de escritura. `anular_reserva`,
`crear_reserva` (exprés), `crear_cliente` y `crear_lugar` se ejecutan
reproduciendo los formularios de Webcar (`webcar/escritura.py`,
docs/Escritura.md) y solo si el `.env` abre las tres puertas de
`puede_escribir`; si no, la propuesta queda «fallida: escritura desactivada».
El resto de acciones siguen sin ejecutor: lanzan `AccionNoDisponible`.
Ver docs/PLAN.md › Fase 3.

Reglas que no se negocian:
- El modelo nunca ejecuta: solo crea `AccionPropuesta` en estado pendiente.
- La confirmación la hace una persona desde la UI, con su sesión.
- Se comprueba el rol del usuario al proponer Y al confirmar.
- Nunca se marca como hecha una acción que Webcar no ha confirmado.
"""

from dataclasses import dataclass
from typing import Callable

from django.utils import timezone

from webcar import escritura
from webcar.cliente import WebcarError
from webcar.models import Descarga

from .models import AccionPropuesta


class AccionNoDisponible(RuntimeError):
    pass


class ParametrosInvalidos(ValueError):
    pass


def _no_disponible(_rentacar, _params):
    raise AccionNoDisponible(
        "Webcar todavía no ofrece una API para hacer este cambio. "
        "Hazlo desde Webcar Lite; la propuesta queda registrada."
    )


def _anular_reserva(rentacar, params):
    resultado = escritura.anular_reserva(escritura.SesionWebcar.de_rentacar(rentacar), params)
    # La reserva anulada desaparece del listado: la copia local caduca ya para
    # que la siguiente pregunta no responda con datos de antes del cambio.
    Descarga.objects.filter(rentacar=rentacar, listado="reservas").delete()
    return resultado


def _crear_reserva(rentacar, params):
    resultado = escritura.crear_reserva(escritura.SesionWebcar.de_rentacar(rentacar), params)
    Descarga.objects.filter(rentacar=rentacar, listado="reservas").delete()
    return resultado


def _crear_cliente(rentacar, params):
    resultado = escritura.crear_cliente(escritura.SesionWebcar.de_rentacar(rentacar), params)
    Descarga.objects.filter(rentacar=rentacar, listado="clientes").delete()
    return resultado


def _crear_lugar(rentacar, params):
    resultado = escritura.crear_lugar(escritura.SesionWebcar.de_rentacar(rentacar), params)
    Descarga.objects.filter(rentacar=rentacar, listado="lugares").delete()
    return resultado


@dataclass(frozen=True)
class TipoAccion:
    clave: str
    descripcion: str
    esquema: dict
    resumir: Callable  # params -> texto para confirmar
    ejecutar: Callable = _no_disponible  # (rentacar, params) -> texto resultado


def _req(params, *claves):
    faltan = [c for c in claves if params.get(c) in (None, "")]
    if faltan:
        raise ParametrosInvalidos(f"Faltan parámetros: {', '.join(faltan)}")


def _resumen_crear_reserva(p):
    _req(p, "categoria", "cliente", "fecha_entrega", "dias")
    return f"Crear reserva de {p['categoria']} para «{p['cliente']}» con entrega el {p['fecha_entrega']} (duración: {p['dias']})"


def _detalle(p, ya_dichos):
    """El resto de datos que se van a escribir: quien confirma tiene que verlos todos."""
    resto = [f"{clave.replace('_', ' ')}: {valor}" for clave, valor in p.items() if clave not in ya_dichos and valor not in (None, "")]
    return f". Con {'; '.join(resto)}" if resto else ""


def _resumen_crear_cliente(p):
    _req(p, "nombre", "nif")
    return f"Dar de alta al cliente «{p['nombre']}» (NIF {p['nif']})" + _detalle(p, {"nombre", "nif"})


def _resumen_crear_lugar(p):
    _req(p, "nombre")
    return f"Dar de alta el lugar «{p['nombre']}»" + _detalle(p, {"nombre"})


def _resumen_anular(p):
    _req(p, "reserva", "motivo")
    return f"Anular la reserva {p['reserva']} (motivo: {p['motivo']})"


def _resumen_matricula(p):
    _req(p, "reserva", "matricula")
    return f"Asignar el vehículo {p['matricula']} a la reserva {p['reserva']}"


def _resumen_cobro(p):
    _req(p, "reserva", "importe", "forma_pago")
    return f"Apuntar un cobro de {p['importe']} € ({p['forma_pago']}) en la reserva {p['reserva']}"


def _resumen_inmovilizar(p):
    _req(p, "matricula", "desde", "hasta", "motivo")
    return f"Inmovilizar {p['matricula']} del {p['desde']} al {p['hasta']} ({p['motivo']})"


_FECHA = {"type": "string", "description": "AAAA-MM-DD"}

TIPOS = {
    t.clave: t
    for t in [
        TipoAccion(
            "crear_reserva",
            "Crear una reserva exprés: solo categoría, cliente, fecha de entrega y duración. "
            "Horas, lugares, vehículo y extras quedan con los valores por defecto de Webcar.",
            {
                "type": "object",
                "properties": {
                    "categoria": {"type": "string", "description": "Código C-xx de la categoría"},
                    "cliente": {
                        "type": "string",
                        "description": "Código del cliente con sus cinco cifras (03527). Si es nuevo, dalo de alta antes con crear_cliente",
                    },
                    "fecha_entrega": _FECHA,
                    "dias": {"type": "string", "description": "Días de alquiler, de 1 a 30"},
                },
                "required": ["categoria", "cliente", "fecha_entrega", "dias"],
            },
            _resumen_crear_reserva,
            _crear_reserva,
        ),
        TipoAccion(
            "crear_cliente",
            "Dar de alta un cliente.",
            {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string", "maxLength": 60}, "nif": {"type": "string", "maxLength": 15},
                    "domicilio": {"type": "string", "maxLength": 60}, "cp": {"type": "string", "maxLength": 10},
                    "municipio": {"type": "string", "maxLength": 50}, "pais": {"type": "string", "maxLength": 60},
                    "telefono": {"type": "string", "maxLength": 20}, "whatsapp": {"type": "string", "maxLength": 20},
                    "email": {"type": "string", "maxLength": 65}, "fecha_nacimiento": _FECHA,
                    "licencia": {"type": "string", "maxLength": 30},
                    "fecha_expedicion": _FECHA, "fecha_caducidad": _FECHA,
                    "oficina": {"type": "string", "description": "Código O-xx"},
                    "tarifa": {"type": "string", "description": "Código T-xx"},
                    "anotaciones": {"type": "string", "maxLength": 150},
                },
                "required": ["nombre", "nif"],
            },
            _resumen_crear_cliente,
            _crear_cliente,
        ),
        TipoAccion(
            "crear_lugar",
            "Dar de alta un lugar de entrega/devolución.",
            {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string", "maxLength": 50},
                    "centro_stock": {"type": "string", "description": "Código K-xx"},
                    "calculo_precios": {"type": "string", "description": "12 o 24 (horas)"},
                    "dias_minimo": {"type": "string", "maxLength": 5},
                    "color": {"type": "string", "description": "Hexadecimal de seis cifras, sin #"},
                    "tarifa": {"type": "string", "description": "Código T-xx"},
                },
                "required": ["nombre"],
            },
            _resumen_crear_lugar,
            _crear_lugar,
        ),
        TipoAccion(
            "anular_reserva", "Anular una reserva existente.",
            {"type": "object", "properties": {"reserva": {"type": "string"}, "motivo": {"type": "string"}},
             "required": ["reserva", "motivo"]},
            _resumen_anular,
            _anular_reserva,
        ),
        TipoAccion(
            "asignar_matricula", "Asignar un vehículo concreto a una reserva.",
            {"type": "object", "properties": {"reserva": {"type": "string"}, "matricula": {"type": "string"}},
             "required": ["reserva", "matricula"]},
            _resumen_matricula,
        ),
        TipoAccion(
            "registrar_cobro", "Apuntar un cobro en una reserva.",
            {"type": "object", "properties": {
                "reserva": {"type": "string"}, "importe": {"type": "number"},
                "forma_pago": {"type": "string", "description": "Código G-xx"}, "fecha": _FECHA},
             "required": ["reserva", "importe", "forma_pago"]},
            _resumen_cobro,
        ),
        TipoAccion(
            "inmovilizar_vehiculo", "Bloquear un vehículo por taller, ITV, etc.",
            {"type": "object", "properties": {
                "matricula": {"type": "string"}, "desde": _FECHA, "hasta": _FECHA, "motivo": {"type": "string"}},
             "required": ["matricula", "desde", "hasta", "motivo"]},
            _resumen_inmovilizar,
        ),
    ]
}


def proponer(conversacion, usuario, tipo, parametros):
    if not usuario.puede_proponer_acciones:
        raise PermissionError("Tu perfil no permite hacer cambios.")
    if tipo not in TIPOS:
        raise ParametrosInvalidos(f"Acción desconocida: {tipo}. Válidas: {', '.join(TIPOS)}")
    resumen = TIPOS[tipo].resumir(parametros or {})
    return AccionPropuesta.objects.create(
        conversacion=conversacion, rentacar=conversacion.rentacar, tipo=tipo,
        parametros=parametros or {}, resumen=resumen,
    )


def resolver(accion, usuario, confirmar):
    """Confirma (y ejecuta) o rechaza una propuesta pendiente."""
    if accion.estado != AccionPropuesta.Estado.PENDIENTE:
        raise ValueError("Esta propuesta ya está resuelta.")
    if accion.conversacion.usuario_id != usuario.id and not usuario.is_superuser:
        raise PermissionError("No es tu conversación.")
    if not usuario.puede_proponer_acciones:
        raise PermissionError("Tu perfil no permite hacer cambios.")
    # Se reserva la propuesta antes de ejecutar: con dos confirmaciones a la vez
    # (doble clic) solo una llega a Webcar. Una escritura no se envía dos veces.
    ahora = timezone.now()
    reservada = AccionPropuesta.objects.filter(
        pk=accion.pk, estado=AccionPropuesta.Estado.PENDIENTE, resuelta__isnull=True
    ).update(resuelta=ahora, resuelta_por=usuario)
    if not reservada:
        raise ValueError("Esta propuesta ya está resuelta o se está ejecutando.")
    accion.resuelta = ahora
    accion.resuelta_por = usuario
    if not confirmar:
        accion.estado = AccionPropuesta.Estado.RECHAZADA
        accion.save()
        return accion
    # El rentacar de la propuesta, no el activo ahora en la conversación (un
    # operador puede haberlo cambiado después de proponer).
    rentacar = accion.rentacar or accion.conversacion.rentacar
    tipo = TIPOS[accion.tipo]
    try:
        if tipo.ejecutar is _no_disponible:
            _no_disponible(rentacar, accion.parametros)
        if not escritura.puede_escribir(rentacar, accion.tipo):
            raise AccionNoDisponible(
                "Escritura desactivada para este rentacar o esta acción: no se ha cambiado nada en Webcar. "
                "Hazlo desde Webcar Lite; la propuesta queda registrada."
            )
        accion.resultado = tipo.ejecutar(rentacar, accion.parametros) or "Hecho."
        accion.estado = AccionPropuesta.Estado.CONFIRMADA
    except (AccionNoDisponible, WebcarError) as exc:
        accion.resultado = str(exc)
        accion.estado = AccionPropuesta.Estado.FALLIDA
    except Exception as exc:  # noqa: BLE001 — cualquier fallo de Webcar se registra
        accion.resultado = f"Error al ejecutar: {exc}"
        accion.estado = AccionPropuesta.Estado.FALLIDA
    accion.save()
    return accion
