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
