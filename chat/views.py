import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import acciones, agente
from webcar.models import Rentacar

from .models import AccionPropuesta, Conversacion, Mensaje

log = logging.getLogger(__name__)


def _rentacar(usuario):
    if usuario.rentacar_id:
        return usuario.rentacar
    # Un operador de COR SOFT puede no tener rentacar propio: empieza en el primero.
    if usuario.acceso_todos_rentacars:
        r = Rentacar.objects.filter(activo=True).first()
        if r:
            return r
    raise Http404("Tu usuario no tiene rentacar asignado (admin › Usuarios).")


def _conversacion(request, pk):
    return get_object_or_404(Conversacion, pk=pk, usuario=request.user)


def _grupos(usuario):
    """Conversaciones del lateral por antigüedad: [(etiqueta, [conversaciones])]."""
    hoy = timezone.localdate()
    grupos = {}
    for c in Conversacion.objects.filter(usuario=usuario)[:50]:
        dias = (hoy - timezone.localtime(c.actualizada).date()).days
        etiqueta = "Hoy" if dias <= 0 else "Ayer" if dias == 1 else "Últimos 7 días" if dias <= 7 else "Anteriores"
        grupos.setdefault(etiqueta, []).append(c)
    return list(grupos.items())


def _accion_json(a):
    rentacar = a.rentacar or a.conversacion.rentacar
    return {"id": str(a.id), "tipo": a.tipo, "resumen": a.resumen, "estado": a.estado, "resultado": a.resultado,
            "rentacar": rentacar.nombre}


def _mensaje_json(m):
    return {"id": m.id, "rol": m.rol, "contenido": m.contenido, "herramienta": m.nombre_herramienta,
            "tool_calls": m.tool_calls}


@login_required
def inicio(request):
    return render(request, "chat/inicio.html", {"grupos": _grupos(request.user)})


@login_required
@require_POST
def nueva(request):
    c = Conversacion.objects.create(usuario=request.user, rentacar=_rentacar(request.user))
    return redirect("chat:conversacion", pk=c.pk)


@login_required
def conversacion(request, pk):
    c = _conversacion(request, pk)
    mensajes = [
        m for m in c.mensajes.all()
        if m.rol != Mensaje.Rol.HERRAMIENTA and (m.contenido or m.tool_calls or m.rol == "user")
    ]
    return render(request, "chat/conversacion.html", {
        "conversacion": c,
        "grupos": _grupos(request.user),
        "mensajes_json": [_mensaje_json(m) for m in mensajes],
        "acciones_json": [_accion_json(a) for a in c.acciones.all()],
        # Solo un operador de COR SOFT ve el desplegable para cambiar de rentacar.
        "rentacars": Rentacar.objects.filter(activo=True) if request.user.acceso_todos_rentacars else None,
    })


@login_required
@require_POST
def cambiar_rentacar(request, pk):
    c = _conversacion(request, pk)
    if not request.user.acceso_todos_rentacars:
        return JsonResponse({"error": "Sin permiso."}, status=403)
    obj = get_object_or_404(Rentacar, codigo=request.POST.get("codigo", ""), activo=True)
    c.rentacar = obj
    c.save(update_fields=["rentacar"])
    return JsonResponse({"rentacar": obj.nombre, "codigo": obj.codigo})


@login_required
@require_POST
def borrar(request, pk):
    # Se lleva por CASCADE sus mensajes y sus acciones propuestas.
    _conversacion(request, pk).delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def mensaje(request, pk):
    c = _conversacion(request, pk)
    try:
        texto = json.loads(request.body or "{}").get("texto", "").strip()
    except json.JSONDecodeError:
        return HttpResponseBadRequest("JSON no válido")
    if not texto:
        return HttpResponseBadRequest("Mensaje vacío")
    antes = c.mensajes.order_by("-id").values_list("id", flat=True).first() or 0
    try:
        agente.responder(c, request.user, texto)
    except agente.AgenteError as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    except Exception:  # noqa: BLE001
        log.exception("Fallo del agente")
        return JsonResponse({"error": "Ha fallado el asistente. Inténtalo de nuevo."}, status=500)
    nuevos = c.mensajes.filter(id__gt=antes)
    return JsonResponse({
        "mensajes": [_mensaje_json(m) for m in nuevos],
        "acciones": [_accion_json(a) for a in c.acciones.all()],
        "rentacar": c.rentacar.codigo,
    })


@login_required
@require_POST
def resolver_accion(request, pk, decision):
    accion = get_object_or_404(AccionPropuesta, pk=pk, conversacion__usuario=request.user)
    if decision not in {"confirmar", "rechazar"}:
        raise Http404
    try:
        accion = acciones.resolver(accion, request.user, confirmar=decision == "confirmar")
    except (ValueError, PermissionError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_accion_json(accion))
