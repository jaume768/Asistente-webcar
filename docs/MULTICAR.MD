# Operador de COR SOFT: consultar todos los rentacars

Objetivo: que un operador de COR SOFT (p. ej. tú) pueda, desde el chat, mirar
cualquier rentacar —«del rentacar X, ¿qué coches se entregan mañana?»— mientras
cada cliente sigue viendo solo el suyo.

## Principio que NO se toca

El aislamiento sigue igual: el rentacar sale de la sesión (`Conversacion`), no de
lo que el modelo escriba. La diferencia es que un operador de COR SOFT **sí**
puede cambiar el rentacar activo, y el modelo solo puede pedir ese cambio a
través de una herramienta que **comprueba el permiso en el servidor**. Un usuario
normal ni ve la herramienta ni puede usar el endpoint de cambio.

Ojo: esto es un permiso NUEVO (`acceso_todos_rentacars`), distinto del rol
`ADMIN`. El `ADMIN` es el administrador de UNA empresa y sigue viendo solo la
suya. «Ver todos» es solo para operadores de COR SOFT.

## 1. Permiso en el usuario (`cuentas/models.py`)

```python
acceso_todos_rentacars = models.BooleanField(
    "operador COR SOFT (ve todos los rentacars)",
    default=False,
    help_text="Permite consultar cualquier rentacar desde el chat. Solo para personal de COR SOFT.",
)

def clean(self):
    super().clean()
    # Un operador de COR SOFT puede no tener rentacar propio.
    if not self.is_superuser and not self.acceso_todos_rentacars and not self.rentacar_id:
        raise ValidationError({"rentacar": "Un usuario normal necesita un rentacar."})

@property
def puede_proponer_acciones(self):
    return self.is_superuser or self.acceso_todos_rentacars or self.rol in {self.Rol.ADMIN, self.Rol.RESTRINGIDO}
```

Migración y mostrarlo en el admin (`cuentas/admin.py`, en `list_display`/`fieldsets`).

## 2. Herramienta `elegir_rentacar` (`chat/herramientas.py`)

Solo se ofrece a operadores; además se recomprueba el permiso al ejecutarla
(defensa en profundidad). Resuelve por código, por nombre exacto o por nombre
que contenga el texto.

```python
def elegir_rentacar(ctx, rentacar):
    if not getattr(ctx.usuario, "acceso_todos_rentacars", False):
        return {"error": "No tienes permiso para cambiar de rentacar."}
    from webcar.models import Rentacar
    q = str(rentacar or "").strip()
    if not q:
        return {"error": "Indica el nombre o el código del rentacar."}
    qs = Rentacar.objects.filter(activo=True)
    obj = (qs.filter(codigo__iexact=q).first()
           or qs.filter(nombre__iexact=q).first()
           or qs.filter(nombre__icontains=q).first())
    if not obj:
        disponibles = ", ".join(qs.order_by("nombre").values_list("nombre", flat=True)[:30])
        return {"error": f"No encuentro el rentacar «{q}». Disponibles: {disponibles}"}
    ctx.rentacar = obj                                   # el resto del turno va a este rentacar
    ctx.conversacion.rentacar = obj                       # y los mensajes siguientes también
    ctx.conversacion.save(update_fields=["rentacar"])
    return {"rentacar": obj.nombre, "codigo": obj.codigo,
            "nota": "Las siguientes consultas y acciones son de este rentacar."}
```

Definición para el modelo y registro:

```python
_ELEGIR_RENTACAR = {
    "type": "function",
    "function": {
        "name": "elegir_rentacar",
        "description": ("Cambia el rentacar sobre el que se consulta o se actúa. Úsalo cuando el "
                        "usuario nombre un rentacar (p. ej. «del rentacar X, …»). Solo operadores de COR SOFT."),
        "parameters": {"type": "object",
                       "properties": {"rentacar": {"type": "string", "description": "Nombre o código del rentacar"}},
                       "required": ["rentacar"]},
    },
}

def definiciones(usuario):
    """Herramientas disponibles para este usuario."""
    if getattr(usuario, "acceso_todos_rentacars", False):
        return DEFINICIONES + [_ELEGIR_RENTACAR]
    return DEFINICIONES

# añadir al dict:
IMPLEMENTACIONES["elegir_rentacar"] = elegir_rentacar
```

## 3. Bucle del agente (`chat/agente.py`)

Que el prompt y las herramientas se tomen de `ctx` en cada vuelta, para que un
cambio de rentacar a mitad del turno tenga efecto inmediato:

```python
# en responder(), dentro del for:
mensajes = [{"role": "system", "content": prompt_sistema(usuario, ctx.rentacar)}]
...
resp = client.chat.completions.create(
    model=settings.OPENAI_MODEL,
    messages=mensajes,
    tools=herramientas.definiciones(usuario),   # antes: herramientas.DEFINICIONES
    **extra,
)
```

(Se puede borrar la variable local `rentacar`; usar siempre `ctx.rentacar`.)

En `prompt_sistema(usuario, rentacar)`, para operadores, listar los rentacars y
dar la instrucción:

```python
def prompt_sistema(usuario, rentacar):
    tablas = "\n".join(f"- {l.tabla}: {l.descripcion}" for l in esquema.LISTADOS)
    base = f"""Eres el asistente de Webcar Lite ... para la empresa «{rentacar.nombre}».
... (igual que ahora) ..."""
    if getattr(usuario, "acceso_todos_rentacars", False):
        from webcar.models import Rentacar
        otros = Rentacar.objects.filter(activo=True).order_by("nombre")
        lista = "\n".join(f"- {r.nombre} (código {r.codigo})" for r in otros)
        base += f"""

Eres operador de COR SOFT: puedes consultar y actuar sobre CUALQUIER rentacar.
Ahora mismo trabajas sobre «{rentacar.nombre}». Rentacars disponibles:
{lista}
Cuando el usuario nombre un rentacar (p. ej. «del rentacar X, …»), llama primero a
elegir_rentacar con su nombre o código y luego consulta. Si no indica ninguno, usa
el actual o pregunta cuál. Al responder, di de qué rentacar son los datos."""
    return base
```

## 4. Rentacar inicial de la conversación (`chat/views.py`)

Un operador puede no tener rentacar propio: la conversación arranca en el primero
activo (o en el suyo si lo tiene).

```python
def _rentacar(usuario):
    if usuario.rentacar_id:
        return usuario.rentacar
    if getattr(usuario, "acceso_todos_rentacars", False):
        r = Rentacar.objects.filter(activo=True).order_by("nombre").first()
        if r:
            return r
    raise Http404("Tu usuario no tiene rentacar asignado (admin › Usuarios).")
```

## 5. Desplegable para cambiarlo con un clic (opcional pero cómodo)

Endpoint (solo operadores) y selector en la cabecera de la conversación:

```python
# chat/views.py
@login_required
@require_POST
def cambiar_rentacar(request, pk):
    c = _conversacion(request, pk)
    if not getattr(request.user, "acceso_todos_rentacars", False):
        return JsonResponse({"error": "Sin permiso."}, status=403)
    obj = get_object_or_404(Rentacar, codigo=request.POST.get("codigo"), activo=True)
    c.rentacar = obj
    c.save(update_fields=["rentacar"])
    return JsonResponse({"rentacar": obj.nombre, "codigo": obj.codigo})
```

```python
# chat/urls.py
path("c/<uuid:pk>/rentacar/", views.cambiar_rentacar, name="cambiar_rentacar"),
```

En la plantilla de la conversación, renderizar el `<select>` solo si
`request.user.acceso_todos_rentacars`, con las opciones de `Rentacar.objects.filter(activo=True)`
y la actual (`conversacion.rentacar`) seleccionada; al cambiar, `POST` al endpoint
y recargar.

## 6. Escritura en otro rentacar

`escritura.SesionWebcar.de_rentacar(rentacar)` ya usa las credenciales del
rentacar que reciba, y `puede_escribir(rentacar, accion)` sigue filtrando por
`WEBCAR_ESCRITURA_RENTACARS`. Es decir: un operador puede proponer cambios en el
rentacar activo, pero solo se ejecutan si ese rentacar está en la lista del
`.env`. Para pruebas, deja solo `demo` ahí.

## 7. Aislamiento: por qué sigue cerrado

- Un usuario normal: `definiciones(usuario)` NO incluye `elegir_rentacar`, y si
  aun así se invocara, la función devuelve «sin permiso». El endpoint
  `cambiar_rentacar` responde 403. Su `Conversacion.rentacar` es el suyo y no
  cambia. Igual que hasta ahora.
- Un operador: puede cambiar, y el cambio pasa siempre por la comprobación de
  `acceso_todos_rentacars` en el servidor. El modelo nunca consulta un rentacar
  que el usuario no pueda ver.

## 8. Tests (`chat/tests.py`)

- Usuario normal: `herramientas.definiciones(u)` no trae `elegir_rentacar`;
  `ejecutar(ctx, "elegir_rentacar", …)` devuelve error; `cambiar_rentacar` → 403.
- Operador (`acceso_todos_rentacars=True`): `elegir_rentacar` por código, por
  nombre exacto y por substring cambia `ctx.rentacar` y `conversacion.rentacar`;
  nombre inexistente devuelve error con la lista; tras elegir, `consultar_datos`
  usa el nuevo rentacar.
- Flujo con cliente falso: mensaje «del rentacar X, ¿qué entregas hay mañana?»
  → el agente llama `elegir_rentacar("X")` y luego `consultar_datos`.

## 9. Más adelante (fuera de alcance ahora)

- «En TODOS los rentacars, ¿cuántas entregas hay mañana?»: un fan-out que
  recorre los rentacars y agrega. Cada uno descarga su CSV la primera vez
  (unos segundos). Añadir como herramienta aparte `consultar_todos` si hace falta.