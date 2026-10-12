# Escritura en Webcar desde el agente (camino 2)

Cómo hacer que el asistente ejecute cambios en Webcar Lite **automatizando el
propio ERP** (reproduciendo sus formularios), mientras COR SOFT no exponga una
API de escritura. Documento de implementación: léelo entero antes de empezar.

> Resumen: Webcar **no tiene API de escritura**. Crear/editar/anular/facturar/
> check-out son formularios HTML que se envían por `POST` a páginas `APPxx`,
> protegidos por una sesión (login con contraseña) y un **token `segur` que
> cambia en cada carga de página**. Automatizar = iniciar sesión, leer el
> formulario para sacar el `segur` fresco y enviar el mismo `POST` que haría un
> empleado.

Todo lo de aquí se ha comprobado leyendo (sin enviar nada) los formularios de la
empresa **DEMO** en `https://lite.webcar.rent/DEMO/`.

---

## 1. Cómo funciona la escritura en Webcar

### Parámetros de sesión

- **`oper`**: número de usuario de Webcar (en la DEMO, `046` = JAUME).
- **`c`**: token de sesión que devuelve el login (en la DEMO, `*456246306`).
  Va en la URL de cada página y en cada formulario. **Es la credencial**: con
  `oper` + `c` válidos se puede leer y escribir.
- **`segur`**: token por página (CSRF). Cambia en **cada** carga (se vieron
  701981, 736681, 69747…). Cada `POST` de escritura tiene que llevar el `segur`
  de la página que se acaba de pedir, no uno viejo.
- **`ruta`**: el código del rentacar (en la DEMO, `DEMO` en la URL / `demo` en
  la API CSV). Es el mismo `Rentacar.codigo` que ya usamos.

### Login

La pantalla `APP0?control=<oper>` tiene un formulario que hace `POST` a `APP00`:

| Campo | Valor |
| --- | --- |
| `oper` (hidden) | número de usuario, p. ej. `046` |
| `oficina` (hidden) | `00` |
| `c` (password) | la contraseña del usuario (DEMO: `5624`) |

La respuesta es la página ya autenticada, de la que se extrae el token de
sesión `c=*...` (aparece en los enlaces y formularios). **A partir de ahí, ese
`c` identifica la sesión.**

> ⚠️ Confirma este paso lo PRIMERO (es el único que no se ha ejecutado, solo
> observado). Haz un login real contra la DEMO y comprueba que el `c` devuelto
> sirve para pedir una página interna.

### Codificación

Webcar es **iso-8859-1 (cp1252)**. Los `POST` deben enviarse latin-1 y las
respuestas leerse latin-1 (igual que ya hace `webcar/cliente.py` al normalizar
los CSV). Las entidades HTML en la respuesta (`Categor&iacutea`) se desescapan
igual que allí.

### Patrón general de una escritura

```
1. Sesión: tener oper + c válidos (si no, login → POST APP00).
2. GET de la página del formulario (p. ej. el editor de la reserva) con oper+c.
3. Parsear de esa respuesta: el token `segur` fresco y los valores actuales de
   los campos (para no pisar lo que ya había).
4. Construir el body con TODOS los campos ocultos (incluido el segur nuevo) +
   los campos que cambian.
5. POST (application/x-www-form-urlencoded, latin-1) a la acción del formulario.
6. Parsear la respuesta para confirmar el resultado (nº de contrato, el valor ya
   cambiado, etc.). Si no se confirma → la acción queda «fallida».
```

---

## 2. Formularios por acción (DEMO, v1.12)

Páginas y campos reales. Los `select` llevan el **código** como value
(categoría `C-02`, lugar `L-03`, vehículo `0013`, usuario `U-046`, forma de pago
`G-01`, serie `R-2`). El agente ya conoce esos códigos vía `consultar_datos`.

### 2.1 Crear reserva (reserva exprés) — `POST APP1?`

Es el primer paso: abre el editor con la reserva ya creada.

| Campo | Qué es |
| --- | --- |
| `oper`, `c`, `segur` | sesión + token |
| `CATEGORIA` | categoría `C-xx` |
| fecha (input date) | fecha de entrega |
| `TIEMPO` | días (`1`..`30`, o `M1`/`P1`… para mañana/pasado) |
| `cliente` | nombre nuevo, `+busqueda`, `I-motivo`, `+hotel-hab` o código con ceros |

La respuesta es el editor `APP21` de la reserva nueva (trae su `clave`, p. ej.
`004292`).

### 2.2 Editor de reserva (completar / anular) — `POST APP21?`

El formulario grande del editor. Para **anular**: poner `matriu1` (Activo) a
desmarcado y Guardar.

| Campo | Qué es |
| --- | --- |
| `oper`, `c`, `clave`, `segur`, `prog`, `dia`, `filtro`, `nuevo` | ocultos (reenviar tal cual) |
| `cotiza` (checkbox) | marcar = cotización |
| `matriu1` (checkbox) | **Activo**. Desmarcar = anular |
| `matriu2` | código de cliente |
| `MATRIU3` | categoría `C-xx` |
| `matriu4` / `matriu5` | fecha / hora entrega |
| `MATRIU21` | lugar entrega `L-xx` |
| `matriu6` / `matriu7` | fecha / hora devolución |
| `MATRIU22` | lugar devolución `L-xx` |
| `MATRIU8` | vehículo (código `00xx`) |
| `matriu16` | precio alquiler (se recalcula solo si se deja) |
| `EXTRAS1`..`EXTRAS6` | extras `Z-xxx` |
| `MATRIU14` / `MATRIU15` | partner / usuario entrada `U-xxx` |
| `MATRIU10` | oficina `O-xx` |
| `matriu13` | vuelo / anotaciones entrega |
| `histori` / `historia` | anotaciones / conductores adicionales |
| `MATRIU26` / `matriu27` / `matriu28` | forma `G-xx` / fecha / importe cobro 1 |
| `MATRIU29` / `matriu30` / `matriu31` | cobro 2 |
| `matriu18C` / `matriu18I` | concepto / importe adicional |
| `MATRIU34` / `MATRIU35` | entrega / devolución programada a usuario |
| `masvehic` | nº de vehículos (reserva múltiple) |
| submit `Guardar` | graba |

### 2.3 Emitir contrato / factura — `POST APP21?` con `clave=F<id>`

| Campo | Qué es |
| --- | --- |
| `oper`, `c`, `clave`=`F004292`, `segur`, `ndias` | ocultos |
| `MATRIU9` | serie (`R-2` = contratos C, `R-1` = facturas A…) |
| `matriu17` | combustible (p. ej. `FULL`) |
| `matriu19` | fecha factura/contrato |
| `matriu20` | nº factura/contrato |
| submit `Factura / contrato` | emite |

### 2.4 Confirmar / Cancelar / Check-out (mails) — `POST APP1H?`

| Campo | Qué es |
| --- | --- |
| `oper`, `c`, `clave`, `segur` | ocultos |
| submit `mail1` | **Confirma** (email de confirmación) |
| submit `mail2` | **Cancela** |
| submit `mail3` | **Check-out** |
| `mail1p`, `mail1pimporte`, `mail1pporcen` | enlace de pago TPV (importe / %) |
| `mail1pcobro`, `mail1psolocobro` (checkbox) | opciones del cobro |
| `textomail` | texto del mensaje |

### 2.5 Check-in / check-out desde Situación (OK) — `POST APP1?`

| Campo | Qué es |
| --- | --- |
| `oper`, `c`, `segur`, `dia`, `oficina` | sesión + contexto |
| `clave` | nº de reserva |
| `estado` | `E` (entregas) / `D` (devoluciones) |

### 2.6 Inmovilizar un vehículo

No es un formulario propio: es una reserva exprés (2.1) con `cliente = I-motivo`
sobre la matrícula. El vehículo va en el editor como cualquier reserva.

---

## 3. Interruptores en `.env` (lo que pediste)

Tres puertas, **todas** tienen que abrirse para que una acción se ejecute. Si el
interruptor general está en `off`, el agente **sigue proponiendo** (el usuario ve
la tarjeta) pero al confirmar sale «escritura desactivada»: así se puede probar
en seco sin tocar Webcar.

Añadir a `.env.example` y `.env`:

```dotenv
# --- Escritura en Webcar (camino 2) -----------------------------------------
# Interruptor MAESTRO. off = el agente solo propone, nunca ejecuta.
WEBCAR_ESCRITURA=off
# Qué rentacars pueden ejecutar (códigos separados por coma). Vacío = ninguno.
# Para pruebas, solo la demo:
WEBCAR_ESCRITURA_RENTACARS=demo
# Qué acciones se permiten (vacío = todas las implementadas). Para empezar,
# una sola de bajo riesgo:
WEBCAR_ESCRITURA_ACCIONES=anular_reserva
```

En `settings.py`:

```python
WEBCAR_ESCRITURA = config("WEBCAR_ESCRITURA", default="off") == "on"
WEBCAR_ESCRITURA_RENTACARS = config("WEBCAR_ESCRITURA_RENTACARS", default="", cast=Csv())
WEBCAR_ESCRITURA_ACCIONES = config("WEBCAR_ESCRITURA_ACCIONES", default="", cast=Csv())
```

Puerta (en `webcar/escritura.py`):

```python
def puede_escribir(rentacar, tipo_accion):
    return (
        settings.WEBCAR_ESCRITURA
        and rentacar.codigo in settings.WEBCAR_ESCRITURA_RENTACARS
        and (not settings.WEBCAR_ESCRITURA_ACCIONES or tipo_accion in settings.WEBCAR_ESCRITURA_ACCIONES)
    )
```

### Credenciales de Webcar por rentacar

Para iniciar sesión hace falta `oper` + contraseña de cada rentacar. Añadir al
modelo `Rentacar`:

```python
oper_webcar = models.CharField(max_length=10, blank=True)       # p. ej. 046
password_webcar = models.CharField(max_length=128, blank=True)  # ver nota de seguridad
```

> **Seguridad**: la contraseña da acceso total al ERP del cliente. Para las
> pruebas con la DEMO vale guardarla en claro, pero antes de cualquier rentacar
> real hay que cifrarla (p. ej. con una clave en `.env` y `cryptography.Fernet`)
> y NO loguearla nunca. Déjalo anotado como TODO en `docs/PLAN.md`.

Para la demo, rellenar por el admin de Django o un comando:
`oper_webcar=046`, `password_webcar=5624`.

---

## 4. Qué implementar (estructura)

1. **`webcar/escritura.py`** (nuevo):
   - `class SesionWebcar`: `login()` (POST APP00 → guarda `c` y cookies con una
     `requests.Session`), `get_form(pagina, params)` → `(segur, campos_actuales)`,
     `enviar(pagina, campos)` → respuesta (texto latin-1, entidades desescapadas).
   - Reutiliza de `webcar/cliente.py`: `WEBCAR_API_URL` base del host, el
     desescape de entidades y el manejo de cp1252.
   - `puede_escribir(rentacar, tipo_accion)` (puerta de arriba).
   - Una función por acción que arma los campos: `anular_reserva(sesion, params)`,
     `crear_reserva(...)`, `registrar_cobro(...)`, `asignar_matricula(...)`,
     `inmovilizar(...)`. Empieza **solo por `anular_reserva`**.

2. **`chat/acciones.py`**: cambiar los ejecutores `_no_disponible` por los reales.
   El `ejecutar` de cada `TipoAccion` llama a `webcar/escritura.py`. En
   `resolver()`, antes de ejecutar: si `not puede_escribir(...)` → dejar la
   acción en estado `fallida` con «escritura desactivada para este rentacar/acción».
   Mantener la regla de oro: **nunca** marcar `confirmada` si Webcar no lo confirma.

3. **`asistente/settings.py`**: las tres vars nuevas + `Csv` ya importado.

4. **`webcar/models.py`**: los dos campos de credenciales en `Rentacar`
   (+ migración).

5. **Tests** (`webcar/tests.py`): con respuestas HTML grabadas de la DEMO
   (fixtures), NO en vivo. Verificar que `get_form` saca el `segur`, que el body
   del POST lleva todos los ocultos, y que `puede_escribir` respeta las tres
   puertas. Para la prueba en vivo, una sección manual (abajo).

6. **CLAUDE.md / docs/PLAN.md**: marcar Fase 3 en progreso y anotar los TODO de
   seguridad (cifrar contraseñas, token de sesión en vez del `codi` predecible).

---

## 5. Primera prueba de humo (manual, contra la DEMO)

Hazlo con `WEBCAR_ESCRITURA=on`, `WEBCAR_ESCRITURA_RENTACARS=demo`,
`WEBCAR_ESCRITURA_ACCIONES=anular_reserva` y las credenciales demo puestas.

1. **Login**: `SesionWebcar(oper=046, password=5624).login()` y comprobar que
   devuelve un `c` que sirve para pedir `APP1`.
2. Crea una reserva de prueba desde la propia web DEMO (o reutiliza una de
   pruebas) y anótala.
3. Desde el chat: «anula la reserva NNNN, prueba» → confirmar la tarjeta.
4. Comprobar en Webcar que la reserva queda anulada (gris) y que la acción en el
   admin está `confirmada` con el resultado.
5. Repetir con `WEBCAR_ESCRITURA=off` y verificar que al confirmar sale
   «escritura desactivada» y Webcar NO cambia.

Solo cuando `anular_reserva` funcione de punta a punta, añade la siguiente acción.

---

## 6. Avisos

- **Frágil**: son los mismos formularios de la UI; cualquier cambio de
  maquetación en Webcar rompe esto. Ponlo detrás de tests y trátalo como
  integración, no como API estable. Lo ideal sigue siendo que COR SOFT exponga
  la API5 (ver `docs/PLAN.md`); esto es el puente mientras tanto.
- **Idempotencia**: si un POST se reintenta, el contador de Webcar puede saltar.
  Enviar cada acción UNA vez y guardar el resultado en `AccionPropuesta`; no
  reintentar automáticamente un POST de escritura.
- **Confirmación humana**: no la quites. El agente propone; la persona confirma;
  solo entonces se ejecuta y con las tres puertas abiertas.
- **Solo DEMO por ahora**: la lista `WEBCAR_ESCRITURA_RENTACARS` es la que limita
  a quién. Déjala en `demo` hasta que el flujo esté probado.

---

## 7. Comprobado en vivo contra la DEMO (13-10-2026)

Hecho con `webcar/escritura.py`, usuario 046, reserva de prueba 004292. Lo que
sigue corrige o precisa lo de arriba.

**Login**
- `POST APP00` con `oper`, `oficina=00`, `c=<contraseña>` devuelve una página con
  `<META HTTP-EQUIV='REFRESH' CONTENT='0;URL=APP1?oper=046&c=<token>&verifactu=*'>`.
  De ahí sale el token `c`. Con contraseña incorrecta la página dice
  «PASSWORD INCORRECTO REPITA LA ENTRADA POR FAVOR.» y no hay redirección.
- **No hay cookies**: la sesión es solo `oper` + `c`. No hace falta
  `requests.Session`; se usa `urllib`, como en `webcar/cliente.py`.
- El token `c` salió igual en sesiones distintas: trátalo como la contraseña.

**`segur`**
- No cambia en cada carga sino con la hora (mismo valor en `APP1` y en el editor
  pedidos seguidos; crece durante el día y vuelve a empezar a medianoche). Se lee
  siempre del formulario que se va a enviar.

**Editor de reserva (`APP21`)**
- Se abre por `GET APP21?oper=…&c=…&clave=004292&segur=…` (el lápiz de Situación
  hace lo mismo por `POST`, con `cliente` y `prog=APP1`, que no hacen falta).
- En el formulario la clave va como `+004292` (con `+`), y hay ocultos repetidos
  (`MATRIU9` cuatro veces). Hay que reenviarlos todos, en orden.
- **Los `select` traen dos opciones `SELECTED`**: la vacía y la real. El navegador
  envía la última; quedarse con la primera vaciaría categoría, vehículo, extras y
  cobros al guardar.
- El botón «Guardar» no tiene `name`: no se envía nada por él. El campo `matriu24`
  está `disabled` y tampoco se envía.
- No hay JavaScript que toque el formulario. El cuerpo que arma `escritura.py`
  se comparó par a par con el `FormData` de Chrome sobre la misma página: idéntico.

**Anular**
- Enviar el formulario entero sin `matriu1` anula la reserva, aunque tenga
  contrato emitido (la 004292 tenía el C-50995). Al volver a abrirla, «Activo»
  sale desmarcado y el resto de campos queda igual.
- Una reserva anulada: desaparece de Situación y del listado CSV de reservas
  (la demo pasó de 4.175 a 4.174); en Informes › Reservas sale en gris bajo
  «Presenta registros inactivos»; su editor ya no trae el formulario de contrato
  y el vehículo pasa a ser un campo desactivado más un oculto.
- Por eso, tras anular, el asistente caduca su copia local de `reservas`.

**Prueba de humo (sección 5)**: con el interruptor en `off`, la tarjeta queda
«fallida: escritura desactivada» y Webcar no cambia; con `on`, queda
«confirmada» y la reserva anulada. Hecha desde el chat con el usuario `demo`.

---

# Alta de clientes, lugares y reservas (crear)

Investigado en vivo sobre la DEMO el 13-10-2026. Patrón idéntico a
`anular_reserva`: `SesionWebcar` (login + `get_form` + `enviar`), formulario
reenviado entero, y la acción solo queda hecha si al **volver a leer** aparece
el registro. En las altas, el nº lo asigna Webcar, así que la confirmación es
**buscar el registro recién creado y leer su código**.

Nota: durante la investigación se creó en la DEMO un cliente de prueba
(`03527` PRUEBA ASISTENTE) y un lugar de prueba (`06` PRUEBA ASISTENTE L).
Se pueden borrar/inactivar; no molestan.

## A) Abrir el editor en blanco

Los tres editores se abren posteando el botón **Nuevo**, que manda `clave=NUEVO`:

```
POST APP2?    oper,c,segur,clave=NUEVO   → editor de cliente
POST APP541?  oper,c,segur,clave=NUEVO   → editor de lugar
```

Con los helpers actuales:

```python
segur, _ = sesion.get_form("APP2")
_, f = sesion.get_form("APP2?", {"clave": "NUEVO", "segur": segur},
                       accion="APP2", con="matriu2", por_post=True)
```

El `get_form` ya soporta `por_post=True`. `f` trae todos los campos del editor
(con su `segur` propio); se reenvían con `f.cuerpo(cambios)` como en anular. El
botón **Guardar** no tiene `name`, así que no se pasa `boton` (igual que anular).

## B) Campos del editor de CLIENTE (`APP2?`)

| Campo Webcar | Significado | Obligatorio |
| --- | --- | --- |
| `matriu1` (checkbox) | Activo (viene marcado) | |
| `matriu2` | Nombre y apellidos | sí |
| `matriu3` | Domicilio | sí |
| `matriu23` | C.P. | sí |
| `matriu4` | Municipio | sí |
| `matriu5` | País | sí |
| `matriu6` | N.I.F. | sí |
| `matriu7` | Teléfono | sí |
| `matriu8` | Whatsapp | |
| `matriu9` | Email | sí |
| `MATRIU20-1/-2/-3` | Fecha nacimiento (día / mes / año, sin ceros) | sí |
| `matriu10` | Nº Licencia | sí |
| `MATRIU21-1/-2/-3` | Fecha expedición carnet | sí |
| `MATRIU22-1/-2/-3` | Fecha caducidad carnet | |
| `matriu16` | Domicilio vacacional | |
| `matriu12` | Anotaciones | |
| `matriu24` (checkbox) | Autoriza envío de ofertas | |
| `MATRIU11` | Oficina (`O-xx`) | |
| `matriu13/14/15` | Razón social (3 líneas) | |
| `matriu17` | Alerta en contrato | |
| `matriu18` | Número | |
| `MATRIU19` | Tarifa (`T-xx`) | |

Webcar: si falta teléfono guarda el whatsapp; si es español y falta licencia
guarda el DNI. Los `*` del formulario son los obligatorios.

**Confirmación**: al Guardar, Webcar vuelve al listado. Se busca por NIF y se lee
el código de la fila (cada fila es un form con `cliente=<código>`):

```python
POST APP2?  oper,c,segur,inactivos=,filtro=<NIF>  → fila con cliente=03527
```

## C) Campos del editor de LUGAR (`APP541?`)

| Campo Webcar | Significado | Obligatorio |
| --- | --- | --- |
| `matriu2` | Lugar entrega/devolución (nombre) | sí |
| `matriu18` / `matriu19` | Nombre en inglés / alemán | |
| `MATRIU3` | Centro de stock (`K-xx`) | |
| `matriu4` | Días mínimo reserva | |
| `matriu5` | Release reserva | |
| `matriu7` | Color en planning (hex `XXXXXX`) | |
| `MATRIU8` | Cálculo precios (`12`/`24`) | |
| `MATRIU22` | Tarifa (`T-xx`) | |
| `MATRIU23` | Envía a la oficina (`O-xx`) | |
| `matriu9` / `matriu10` | Latitud / Longitud | |
| `matriu20` / `matriu21` | Desde / Hasta día apertura (date) | |
| `matriu11`..`matriu14` | Horas de apertura (turnos 1 y 2) | |
| `matriu15/16/17` | Hospedajes: código / domicilio / población | |

**Confirmación**: se vuelve a leer el listado `APP541` y se busca la fila por el
nombre; su código va en el campo `clave=<código>` de la fila.

## D) Crear RESERVA (reserva exprés, `POST APP1?`)

El form exprés de Situación (`action="?"` → postea a `APP1?`) crea la reserva y
**abre su editor**, que ya trae el nuevo número en el hidden `clave`.

| Campo | Significado |
| --- | --- |
| `oper`, `c`, `segur`, `expres`="" | sesión + token |
| `CATEGORIA` | categoría `C-xx` |
| `desdedia` | fecha de entrega `AAAA-MM-DD` |
| `TIEMPO` | días: `1`..`30` o `M1`/`M2`/`M3`/`M7`/`P1`/`P2`/`P3`/`P7` |
| `CLIENTE` | **código con ceros** (p. ej. `03527`), nombre nuevo, `+búsqueda` o `I-motivo` |
| submit `reservar`=`Reservar` | crea |

**Confirmación**: en la respuesta hay un form a `APP21` con `clave=<nº reserva>`.
Si `CLIENTE` es una búsqueda ambigua, Webcar muestra «Seleccionar» en vez del
editor → error pidiendo el código del cliente.

> La exprés crea la reserva con categoría + cliente + fecha + días (y la tarifa
> por defecto). Completar vehículo, lugares, extras o cobro es otra acción
> (`editar_reserva`), fuera del alcance de ahora.

## E) Código para `webcar/escritura.py` (al final, junto a `anular_reserva`)

```python
def _partes_fecha(valor):
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(valor or "").strip())
    if not m:
        raise WebcarError(f"«{valor}» no es una fecha AAAA-MM-DD válida.")
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


def _cliente_por_nif(sesion, nif):
    """Código del cliente cuyo NIF coincide, o None. Cada fila es un form con `cliente`."""
    segur, _ = sesion.get_form("APP2")
    html = sesion.enviar("APP2?", [("oper", sesion.oper), ("c", sesion.c),
                                   ("segur", segur), ("inactivos", ""), ("filtro", nif)])
    codigos = {f.valor("cliente") for f in leer_formularios(html) if f.valor("cliente")}
    codigos = {c for c in codigos if re.fullmatch(r"\d{3,6}", c or "")}
    return sorted(codigos)[-1] if codigos else None


def crear_cliente(sesion, params):
    """Da de alta un cliente. Devuelve su código solo si aparece al volver a leer."""
    nombre = str(params.get("nombre") or "").strip()
    nif = str(params.get("nif") or "").strip()
    if not nombre or not nif:
        raise WebcarError("Un cliente necesita al menos nombre y NIF.")
    if _cliente_por_nif(sesion, nif):
        raise WebcarError(f"Ya existe un cliente con el NIF {nif}; no se ha creado otro.")
    segur, _ = sesion.get_form("APP2")
    _, f = sesion.get_form("APP2?", {"clave": "NUEVO", "segur": segur},
                           accion="APP2", con="matriu2", por_post=True)
    cambios = {campo: str(params[log]) for log, campo in _CLIENTE_CAMPOS.items()
               if params.get(log) not in (None, "")}
    for log, base in _CLIENTE_FECHAS.items():
        if params.get(log):
            dia, mes, anio = _partes_fecha(params[log])
            cambios[f"{base}-1"], cambios[f"{base}-2"], cambios[f"{base}-3"] = dia, mes, anio
    sesion.enviar(f.accion, f.cuerpo(cambios))
    log.info("Enviada alta de cliente «%s» (oper %s)", nombre, sesion.oper)
    codigo = _cliente_por_nif(sesion, nif)
    if not codigo:
        raise WebcarError(f"Se ha enviado el alta de «{nombre}» pero no aparece en Webcar. Revísalo.")
    return f"Cliente {codigo} «{nombre}» creado en Webcar."


# --- lugares ---------------------------------------------------------------

_LUGAR_CAMPOS = {
    "nombre": "matriu2", "nombre_ingles": "matriu18", "nombre_aleman": "matriu19",
    "centro_stock": "MATRIU3", "dias_minimo": "matriu4", "release": "matriu5",
    "color": "matriu7", "calculo_precios": "MATRIU8", "tarifa": "MATRIU22",
    "envia_oficina": "MATRIU23", "latitud": "matriu9", "longitud": "matriu10",
}


def _lugar_por_nombre(sesion, nombre):
    """Código del lugar cuyo nombre coincide, o None. El código va en `clave` de su fila."""
    html = sesion._pedir("APP541", params=sesion._sesion())
    objetivo = " ".join(nombre.split()).lower()
    for fila in re.split(r"(?i)<tr\b", html):
        m = re.search(r'name=["\']?clave["\']?\s+value=["\']?([0-9]+)', fila, re.I)
        if m and objetivo in " ".join(texto_visible(fila, 300).split()).lower():
            return m.group(1)
    return None


def crear_lugar(sesion, params):
    """Da de alta un lugar de entrega/devolución."""
    nombre = str(params.get("nombre") or "").strip()
    if not nombre:
        raise WebcarError("Un lugar necesita al menos el nombre.")
    if _lugar_por_nombre(sesion, nombre):
        raise WebcarError(f"Ya existe un lugar «{nombre}».")
    segur, _ = sesion.get_form("APP541")
    _, f = sesion.get_form("APP541?", {"clave": "NUEVO", "segur": segur},
                           accion="APP541", con="matriu2", por_post=True)
    cambios = {campo: str(params[log]) for log, campo in _LUGAR_CAMPOS.items()
               if params.get(log) not in (None, "")}
    sesion.enviar(f.accion, f.cuerpo(cambios))
    log.info("Enviada alta de lugar «%s» (oper %s)", nombre, sesion.oper)
    codigo = _lugar_por_nombre(sesion, nombre)
    if not codigo:
        raise WebcarError(f"Se ha enviado el alta del lugar «{nombre}» pero no aparece en Webcar. Revísalo.")
    return f"Lugar {codigo} «{nombre}» creado en Webcar."


# --- reservas (exprés) -----------------------------------------------------

_DIAS_EXPRES = {str(n) for n in range(1, 31)} | {"M1", "M2", "M3", "M7", "P1", "P2", "P3", "P7"}


def crear_reserva(sesion, params):
    """Crea una reserva exprés (categoría + cliente + fecha + días). Devuelve su número."""
    categoria = str(params.get("categoria") or "").strip().upper()
    cliente = str(params.get("cliente") or "").strip()
    fecha = str(params.get("fecha_entrega") or "").strip()
    dias = str(params.get("dias") or "1").strip()
    if not re.fullmatch(r"C-\d{2}", categoria):
        raise WebcarError("La categoría debe ser un código C-xx (p. ej. C-02).")
    if not cliente:
        raise WebcarError("Indica el cliente: código con ceros (p. ej. 03527) o nombre nuevo.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
        raise WebcarError("La fecha de entrega debe ser AAAA-MM-DD.")
    if dias not in _DIAS_EXPRES:
        raise WebcarError("«dias» debe ser 1..30 o M1/M2/M3/M7/P1/P2/P3/P7.")
    _, f = sesion.get_form("APP1", con="CATEGORIA")
    cuerpo = f.cuerpo({"CATEGORIA": categoria, "desdedia": fecha, "TIEMPO": dias, "CLIENTE": cliente},
                      boton=("reservar", "Reservar"))
    html = sesion.enviar("APP1?", cuerpo)
    if "APP21" not in html.upper() and "SELECCIONAR" in html.upper():
        raise WebcarError("Webcar ha pedido elegir cliente; usa el código del cliente (p. ej. 03527).")
    editor = next((g for g in leer_formularios(html)
                   if g.accion.rstrip("?").upper() == "APP21" and g.valor("clave")), None)
    clave = (editor.valor("clave") if editor else "").lstrip("+")
    if not re.fullmatch(r"\d{3,6}", clave or ""):
        raise WebcarError(f"No se ha podido confirmar la reserva creada: «{texto_visible(html, 120)}»")
    return f"Reserva {clave} creada en Webcar (categoría {categoria}, cliente {cliente}, {fecha}, {dias})."
```

## F) Cambios en `chat/acciones.py`

1. Importar/usar `escritura` (ya está). Añadir los ejecutores:

```python
def _crear_reserva(rentacar, params):
    r = escritura.crear_reserva(escritura.SesionWebcar.de_rentacar(rentacar), params)
    Descarga.objects.filter(rentacar=rentacar, listado="reservas").delete()  # la copia local caduca
    return r

def _crear_cliente(rentacar, params):
    r = escritura.crear_cliente(escritura.SesionWebcar.de_rentacar(rentacar), params)
    Descarga.objects.filter(rentacar=rentacar, listado="clientes").delete()
    return r

def _crear_lugar(rentacar, params):
    r = escritura.crear_lugar(escritura.SesionWebcar.de_rentacar(rentacar), params)
    Descarga.objects.filter(rentacar=rentacar, listado="lugares").delete()
    return r
```

2. Cambiar el `TipoAccion("crear_reserva", …)` para que case con la exprés
   (categoría + cliente + fecha + días) y enchufar su ejecutor; y añadir dos
   `TipoAccion` nuevos:

```python
TipoAccion(
    "crear_reserva", "Crear una reserva (exprés: categoría, cliente, fecha y días).",
    {"type": "object", "properties": {
        "categoria": {"type": "string", "description": "Código C-xx"},
        "cliente": {"type": "string", "description": "Código de cliente con ceros (03527), nombre nuevo o +búsqueda"},
        "fecha_entrega": _FECHA,
        "dias": {"type": "string", "description": "1..30 o M1/M2/M3/M7/P1/P2/P3/P7"}},
     "required": ["categoria", "cliente", "fecha_entrega", "dias"]},
    lambda p: (_req(p, "categoria", "cliente", "fecha_entrega", "dias")
               or f"Crear reserva de {p['categoria']} para «{p['cliente']}» el {p['fecha_entrega']} ({p['dias']} día/s)"),
    _crear_reserva,
),
TipoAccion(
    "crear_cliente", "Dar de alta un cliente.",
    {"type": "object", "properties": {
        "nombre": {"type": "string"}, "nif": {"type": "string"},
        "domicilio": {"type": "string"}, "cp": {"type": "string"}, "municipio": {"type": "string"},
        "pais": {"type": "string"}, "telefono": {"type": "string"}, "whatsapp": {"type": "string"},
        "email": {"type": "string"}, "fecha_nacimiento": _FECHA, "licencia": {"type": "string"},
        "fecha_expedicion": _FECHA, "fecha_caducidad": _FECHA,
        "oficina": {"type": "string", "description": "O-xx"}, "tarifa": {"type": "string", "description": "T-xx"}},
     "required": ["nombre", "nif"]},
    lambda p: (_req(p, "nombre", "nif") or f"Alta de cliente «{p['nombre']}» (NIF {p['nif']})"),
    _crear_cliente,
),
TipoAccion(
    "crear_lugar", "Dar de alta un lugar de entrega/devolución.",
    {"type": "object", "properties": {
        "nombre": {"type": "string"}, "centro_stock": {"type": "string", "description": "K-xx"},
        "calculo_precios": {"type": "string", "description": "12 o 24"},
        "dias_minimo": {"type": "string"}, "color": {"type": "string", "description": "hex XXXXXX"},
        "tarifa": {"type": "string", "description": "T-xx"}},
     "required": ["nombre"]},
    lambda p: (_req(p, "nombre") or f"Alta del lugar «{p['nombre']}»"),
    _crear_lugar,
),
```

> `_req` devuelve `None` cuando está todo, así que `_req(...) or "texto"` sirve
> de resumen en una línea. Si prefieres, saca cada resumen a su función como los
> demás.

3. En `.env`, para probar: `WEBCAR_ESCRITURA_ACCIONES=anular_reserva,crear_reserva,crear_cliente,crear_lugar`
   (o vacío = todas). Sigue valiendo `WEBCAR_ESCRITURA=on` y `WEBCAR_ESCRITURA_RENTACARS=demo`.

## G) Tests y prueba de humo

- Tests con páginas grabadas (como los de anular): guarda en `webcar/tests_datos/`
  un editor de cliente NUEVO, un listado de clientes filtrado, un editor de lugar
  y la respuesta de la exprés (sin token ni contraseña), y verifica que
  `crear_*` arma el POST y que la confirmación encuentra el código.
- En vivo (DEMO): «crea un cliente llamado … con NIF …», «crea el lugar …»,
  «crea una reserva C-02 para el cliente 03527 mañana 3 días». Comprueba el
  código devuelto en Webcar. Con `WEBCAR_ESCRITURA=off`, que no haga nada.

---

# Correcciones: codificación (acentos) y límites de tamaño (maxlength)

Tras las primeras altas de prueba se vieron dos cosas. Comprobado en la DEMO.

## 1. Acentos (país salía «EspaÃ±a»)

Era un artefacto de la **investigación manual** (el navegador envió el POST en
UTF-8). El código de `escritura.py` **ya envía cp1252** en `_pedir`
(`urlencode(datos, encoding="cp1252", …)`), que es lo que espera Webcar, así
que una alta real guarda «España» correctamente. Se reguardó el cliente de
prueba `03527` con cp1252 y el listado ya muestra «España».

Para que no vuelva a pasar inadvertido, añade un test de ida y vuelta con
acentos (sobre páginas grabadas) que verifique que `_pedir` percent-codifica
`ñ`/`á` como `%F1`/`%E1` (cp1252) y NO como `%C3%B1` (UTF-8):

```python
# en webcar/tests.py, con una SesionWebcar y urlopen monkeypatcheado que capture el body
self.assertIn("matriu5=Espa%F1a", cuerpo_enviado)
self.assertNotIn("%C3%B1", cuerpo_enviado)
```

Nota: al **releer** un formulario para editarlo (p. ej. anular), `_pedir` lo
decodifica cp1252 → `str` correcto y lo reenvía cp1252, así que un cliente con
tilde en una reserva también se reescribe bien.

## 2. Límites de tamaño (maxlength)

Cada campo tiene un `maxlength`. Hay que **validar** antes de enviar y avisar si
se pasa, en vez de dejar que Webcar lo recorte en silencio (eso es «simular
éxito» con un dato mal guardado). El nombre del lugar de prueba (18 caracteres)
no estaba recortado —el límite es 50—; si en alguna pantalla se ve abreviado es
cosa de la vista, no del dato.

**Cliente (`APP2`)** · **Lugar (`APP541`)** — maxlength reales:

| Cliente | máx | | Lugar | máx |
| --- | --- | --- | --- | --- |
| nombre `matriu2` | 60 | | nombre `matriu2` | 50 |
| domicilio `matriu3` | 60 | | inglés/alemán `matriu18/19` | 50 |
| cp `matriu23` | 10 | | días mínimo `matriu4` | 5 |
| municipio `matriu4` | 50 | | release `matriu5` | 5 |
| país `matriu5` | 60 | | color `matriu7` | 6 |
| nif `matriu6` | 15 | | latitud/longitud `matriu9/10` | 10 |
| teléfono `matriu7` | 20 | | hospedajes dir/pobl `matriu16/17` | 40 |
| whatsapp `matriu8` | 20 | | | |
| email `matriu9` | 65 | | | |
| licencia `matriu10` | 30 | | | |
| dom. vacacional `matriu16` | 80 | | | |
| anotaciones `matriu12` | 150 | | | |
| razón social `matriu13/14/15` | 55 | | | |
| alerta `matriu17` | 80 | | | |
| número `matriu18` | 40 | | | |

### Cambio en el lector de formularios (`webcar/escritura.py`)

Capturar el `maxlength` en el parser y exponerlo en `Formulario`:

```python
@dataclass
class Formulario:
    accion: str = ""
    campos: list = field(default_factory=list)
    casillas: dict = field(default_factory=dict)
    botones: list = field(default_factory=list)
    limites: dict = field(default_factory=dict)   # nombre → maxlength (int)

    def limite(self, nombre):
        return self.limites.get(nombre)
    # … resto igual …
```

En `_LectorFormularios.handle_starttag`, al registrar un `input` de texto y al
abrir un `textarea`, guardar su `maxlength` si lo trae:

```python
# input de texto (rama else, la que hace self._f.campos.append(...)):
else:
    self._f.campos.append((nombre, a.get("value", "")))
    if a.get("maxlength", "").isdigit():
        self._f.limites[nombre] = int(a["maxlength"])

# textarea (en la rama tag == "textarea"):
self._textarea = [nombre if "disabled" not in a else "", ""]
if nombre and a.get("maxlength", "").isdigit():
    self._f.limites[nombre] = int(a["maxlength"])
```

### Validación antes de enviar

Helper genérico y su uso en `crear_cliente` / `crear_lugar` (con el nombre
legible del campo para el mensaje):

```python
def _valida_limites(formulario, cambios, etiquetas):
    for campo, valor in cambios.items():
        limite = formulario.limite(campo)
        if limite is not None and len(str(valor)) > limite:
            nombre = etiquetas.get(campo, campo)
            raise WebcarError(
                f"«{nombre}» admite como máximo {limite} caracteres "
                f"(has puesto {len(str(valor))})."
            )
```

En `crear_cliente`, justo después de montar `cambios` y antes de `enviar`:

```python
_ETIQUETAS_CLIENTE = {v: k for k, v in _CLIENTE_CAMPOS.items()}
_valida_limites(f, cambios, _ETIQUETAS_CLIENTE)
```

En `crear_lugar`, igual con `{v: k for k, v in _LUGAR_CAMPOS.items()}`.

Así, si alguien pide crear un cliente con un nombre de 70 caracteres, la acción
queda `fallida` con un mensaje claro y Webcar no guarda nada recortado.

> Opcional: reflejar los límites clave en los `esquema` de los `TipoAccion`
> (p. ej. `"nombre": {"type": "string", "maxLength": 60}`) para que el modelo
> ya intente ajustarse.

---

# Altas implementadas: lo comprobado en vivo (13-10-2026)

`crear_cliente`, `crear_lugar` y `crear_reserva` están en `webcar/escritura.py`
y probadas desde el chat contra la DEMO. Esta sección corrige las secciones E y
D de arriba donde la realidad era distinta; el código manda.

**Resultado de la prueba**

| Acción | Resultado en Webcar |
| --- | --- |
| `crear_cliente` | Cliente `03528` «PRUEBA ASISTENTE DOS Peña», NIF `TEST00002A`, país «España» (acentos bien) |
| `crear_lugar` | Lugar `07` «PRUEBA ASISTENTE L2» (`L-07` en los listados), precios a 24 h, color `3833FF` |
| `crear_reserva` | Reserva `004294`, C-02, cliente 03527, 20-10-2026 08:00–20:00 |
| las tres con `WEBCAR_ESCRITURA=off` | «fallida: escritura desactivada»; Webcar sin cambios |

Hay además una reserva `004293` (C-02, cliente 03527, 14–16 de octubre): es el
primer intento de la exprés, que Webcar sí creó pero el asistente dejó como
«fallida» porque no supo comprobarla (ver «Respuesta de la exprés»).

**Diferencias con las secciones D y E**

- **Respuesta de la exprés**: `POST APP1?` no devuelve el editor ni ningún
  formulario con la clave. Devuelve una página con
  `<META HTTP-EQUIV='REFRESH' CONTENT='0;URL=APP21?oper=…&c=…&segur=…&clave=004294&abreinmediato=*'>`;
  el editor lo ve el navegador después de seguir la redirección. Y si Webcar
  devolviera Situación, esta trae un formulario a `APP21` con `clave` por cada
  reserva del día (los lápices): tomar «el primer form a APP21 con clave» daría
  el número de otra reserva. Por eso `crear_reserva` no mira la respuesta: lee
  las reservas del cliente antes y después (`APP21?cliente=<código>`, «Acceso a
  las reservas/contratos de este cliente»), y la nueva la abre y la compara con
  lo pedido (activa, cliente, categoría y fecha de entrega).
- **Solo clientes que ya existen**: `crear_reserva` exige el código de cinco
  cifras y comprueba que existe. Con un nombre, Webcar daría de alta un cliente
  sin datos y no habría forma segura de saber qué reserva es la nueva. Para un
  cliente nuevo: primero `crear_cliente`, luego `crear_reserva`. Quedan fuera
  `+búsqueda`, `I-motivo` y los códigos `M1`/`P1` de duración.
- **El buscador de clientes casa por trozos y en varios campos** («9999»
  devuelve cinco clientes; un teléfono, dos). No sirve para identificar: tras
  buscar por NIF se abre cada ficha candidata (máximo 10) y se compara el NIF
  exacto, tanto para no duplicar como para confirmar el alta. Además se
  comprueba que el nombre guardado es el pedido.
- **Los listados piden `segur`**: `GET APP2` o `APP541` solo con `oper` y `c`
  devuelven el contenido pero con una redirección a `APP0` (login), es decir,
  Webcar da la petición por no válida. `SesionWebcar.leer` trata esa redirección
  como rechazo y todas las lecturas llevan `segur`. Para obtenerlo se usa
  Situación (`APP1`, ~17 KB), no el listado de clientes (~390 KB).
- **El editor NUEVO ya trae el código que tocará** (`clave=+03529`, `nuevo=S`) y
  abrirlo no consume número. La ficha de un cliente que existe tiene las fechas
  en un solo campo (`matriu20`), no en tres desplegables.
- **Lugares**: el código y el nombre salen de las dos primeras celdas de cada
  fila del listado. Se compara el nombre completo (no «contiene») y el lugar
  nuevo tiene que ser un código que antes no estaba.
- **Bug del código de la sección E**: en `crear_cliente`, el bucle
  `for log, base in _CLIENTE_FECHAS.items()` pisa el `log` del módulo y
  `log.info(...)` fallaría justo después de enviar el alta.
- **El token `c` cambia cada día** (el 12 acababa en 6, el 13 en 7) y se deriva
  de la contraseña: sigue equivaliendo a ella.

**Añadido sobre lo pedido**

- Además de `maxlength` (`Formulario.limites`, `_valida_limites`), el lector
  guarda los valores de cada desplegable (`Formulario.opciones`) y
  `_valida_opciones` rechaza los que Webcar no ofrece (oficina `O-99`, categoría
  `C-99`, año de nacimiento fuera de la lista…). `_valida_campos` rechaza
  cambiar un campo que el formulario ya no trae.
- La tarjeta de confirmación enseña todos los datos que se van a escribir, no
  solo el nombre.
- Los cuerpos de las tres altas se compararon par a par con el `FormData` de
  Chrome sobre los mismos formularios rellenos: idénticos.

**Pendiente**

- Webcar marca con `*` domicilio, C.P., municipio, país, teléfono, email,
  nacimiento, licencia y expedición, pero no lo exige en el servidor ni con
  `required`. El asistente solo exige nombre y NIF: decidir si pedir el resto.
- La exprés crea la reserva sin precio (0,00 €), con las horas y el lugar por
  defecto y sin vehículo. Completarla es otra acción (`editar_reserva`).

