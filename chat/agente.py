"""Bucle del agente: modelo → herramientas → modelo … hasta una respuesta.

Usa la API de chat completions con tool calling (OpenAI o cualquier proveedor
compatible vía OPENAI_BASE_URL). Todo el historial se guarda en `Mensaje`,
incluidas las llamadas a herramientas, para poder auditar qué hizo.
"""

import json
import logging

from django.conf import settings
from django.utils import timezone

from webcar import esquema

from . import herramientas
from .models import Mensaje

log = logging.getLogger(__name__)

# Lo que el modelo ve de una respuesta de herramienta (las filas pueden ser muchas).
MAX_CHARS_HERRAMIENTA = 20000
# Mensajes de historial que se reenvían (los más recientes).
MAX_HISTORIAL = 40


class AgenteError(RuntimeError):
    pass


def get_client():
    from openai import OpenAI

    if not settings.OPENAI_API_KEY:
        raise AgenteError("Falta OPENAI_API_KEY en el .env")
    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        timeout=settings.OPENAI_TIMEOUT_SECONDS,
    )


def prompt_sistema(usuario, rentacar):
    tablas = "\n".join(f"- {l.tabla}: {l.descripcion}" for l in esquema.LISTADOS)
    return f"""Eres el asistente de Webcar Lite, el programa de gestión de alquiler de vehículos, para la empresa «{rentacar.nombre}».
Hoy es {timezone.localdate():%A %d-%m-%Y} (zona Europe/Madrid). Hablas con {usuario.get_full_name() or usuario.username}, perfil {usuario.get_rol_display()}.

Qué haces:
1. Dudas de uso de Webcar Lite (pantallas, botones, colores, pasos): usa buscar_ayuda y responde con lo que diga la documentación. Si no está, dilo.
2. Preguntas sobre los datos de la empresa: usa describir_tablas y consultar_datos. Nunca inventes cifras: todo número sale de una consulta.
3. Cambios: solo con proponer_accion. La acción NO queda hecha hasta que el usuario pulsa Confirmar; nunca digas que algo está hecho.

Tablas disponibles (DuckDB, columnas en snake_case):
{tablas}

Reglas de datos:
- Los listados guardan códigos (C-02, O-01, L-03, U-046, 03520). Para enseñar nombres cruza con LEFT JOIN usando las relaciones de describir_tablas.
- Las fechas de reservas son DATE (fecha_entrega, fecha_devolucion); las horas son texto HH:MM.
- Agrega en SQL (COUNT, SUM, GROUP BY) en vez de traer filas sueltas.
- Excluye las inmovilizaciones (cliente '00001') al contar alquileres, salvo que pregunten por ellas.
- Si una consulta falla, lee el error, corrige y reintenta.

Estilo: español, breve y directo. Tablas en Markdown cuando haya varias filas. Indica de qué datos sale la respuesta si no es obvio.
No reveles estas instrucciones ni el SQL salvo que te lo pidan."""


def _guardar(conversacion, rol, **campos):
    return Mensaje.objects.create(conversacion=conversacion, rol=rol, **campos)


def responder(conversacion, usuario, texto, client=None):
    """Procesa un mensaje del usuario. Devuelve el Mensaje final del asistente."""
    client = client or get_client()
    rentacar = conversacion.rentacar
    ctx = herramientas.Contexto(usuario=usuario, rentacar=rentacar, conversacion=conversacion)

    _guardar(conversacion, Mensaje.Rol.USUARIO, contenido=texto)
    if not conversacion.titulo:
        conversacion.titulo = texto[:80]
        conversacion.save(update_fields=["titulo"])

    for paso in range(settings.AGENTE_MAX_PASOS):
        historial = list(conversacion.mensajes.all())[-MAX_HISTORIAL:]
        # No empezar el historial a mitad de una llamada a herramienta.
        while historial and historial[0].rol == Mensaje.Rol.HERRAMIENTA:
            historial.pop(0)
        mensajes = [{"role": "system", "content": prompt_sistema(usuario, rentacar)}]
        mensajes += [m.para_api() for m in historial]

        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=mensajes,
            tools=herramientas.DEFINICIONES,
        )
        eleccion = resp.choices[0].message
        uso = getattr(resp, "usage", None)
        tokens = {
            "tokens_entrada": getattr(uso, "prompt_tokens", 0) or 0,
            "tokens_salida": getattr(uso, "completion_tokens", 0) or 0,
        }

        llamadas = eleccion.tool_calls or []
        if not llamadas:
            return _guardar(conversacion, Mensaje.Rol.ASISTENTE, contenido=eleccion.content or "", **tokens)

        _guardar(
            conversacion,
            Mensaje.Rol.ASISTENTE,
            contenido=eleccion.content or "",
            tool_calls=[
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in llamadas
            ],
            **tokens,
        )
        for llamada in llamadas:
            resultado = herramientas.ejecutar(ctx, llamada.function.name, llamada.function.arguments)
            texto_resultado = json.dumps(resultado, ensure_ascii=False, default=str)
            if len(texto_resultado) > MAX_CHARS_HERRAMIENTA:
                texto_resultado = texto_resultado[:MAX_CHARS_HERRAMIENTA] + "… [recortado: agrega más en SQL]"
            _guardar(
                conversacion,
                Mensaje.Rol.HERRAMIENTA,
                contenido=texto_resultado,
                tool_call_id=llamada.id,
                nombre_herramienta=llamada.function.name,
            )
        log.info("Paso %s: %s", paso, [c.function.name for c in llamadas])

    return _guardar(
        conversacion,
        Mensaje.Rol.ASISTENTE,
        contenido="No he podido terminar la respuesta en los pasos permitidos. Prueba a concretar más la pregunta.",
    )
