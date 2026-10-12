# webcar-asistente

Chat con IA para los usuarios de **Webcar Lite** (el programa de gestión de
alquiler de vehículos de COR SOFT). Se le escribe en lenguaje normal y hace tres
cosas:

1. **Resuelve dudas de uso** de Webcar Lite («¿cómo inmovilizo un coche que va a la ITV?»).
2. **Responde preguntas sobre los datos** del rentacar («¿qué coches salen mañana y desde dónde?»).
3. **Hace cambios en Webcar**, siempre con confirmación: anular reservas y dar de
   alta clientes, lugares y reservas.

Más detalle para desarrollar en [CLAUDE.md](CLAUDE.md), el plan y los pendientes
en [docs/PLAN.md](docs/PLAN.md) y cómo se escribe en Webcar en
[docs/Escritura.md](docs/Escritura.md).

## Qué sabe hacer

### Dudas de uso

Busca en la base de conocimiento (`conocimiento/*.md`) y contesta con lo que
dice la documentación. Si no lo encuentra, lo dice. Para ampliar lo que sabe
basta con añadir ficheros Markdown a esa carpeta.

### Preguntas sobre los datos

El asistente descarga los listados de Webcar del rentacar (reservas, clientes,
vehículos, categorías, lugares, oficinas, facturas, incidencias, multas…, 20 en
total), los guarda en una base de datos local y consulta sobre ellos. Ejemplos:

- ¿Cuántos vehículos tengo y cuántos por categoría?
- Dame la información de las últimas 3 reservas.
- ¿Qué clientes tienen importe pendiente de cobro?
- ¿Qué partner trajo más reservas este año?

Cómo funciona:

- **Solo lectura**: el modelo escribe consultas SQL, que se validan (un único
  `SELECT`, solo tablas conocidas) y se ejecutan sobre una copia local. No puede
  modificar nada por esta vía.
- **Datos al día**: cada listado se vuelve a descargar cuando se pregunta por él
  y su copia ha caducado: reservas a los 5 minutos, clientes y facturas a los
  30, vehículos e incidencias a la hora y el resto una vez al día. Si dices que
  los datos no están al día, los descarga en el momento.
- **Cada usuario ve solo su rentacar**: el rentacar sale de la sesión, nunca de
  lo que diga el modelo.
- Las cifras salen siempre de una consulta; el asistente no las inventa.

### Cambios en Webcar

El asistente **propone** el cambio y aparece una tarjeta con todo lo que se va a
escribir. No pasa nada hasta que una persona pulsa **Confirmar** (o **Rechazar**).

| Qué | Cómo pedirlo | Datos |
| --- | --- | --- |
| **Anular (desactivar) una reserva** | «Anula la reserva 004292, el cliente ha cancelado» | Número de reserva y motivo |
| **Dar de alta un cliente** | «Crea un cliente llamado Ana Peña con NIF 12345678Z, teléfono 600000000, país España» | Obligatorios: nombre y NIF. Opcionales: domicilio, C.P., municipio, país, teléfono, whatsapp, email, fecha de nacimiento, licencia y sus fechas, oficina, tarifa, anotaciones |
| **Dar de alta un lugar** de entrega/devolución | «Crea el lugar Puerto de Alcudia, con precios a 24 horas» | Obligatorio: nombre. Opcionales: centro de stock, cálculo de precios (12/24 h), días mínimos, color, tarifa |
| **Crear una reserva** (exprés) | «Crea una reserva C-02 para el cliente 03527 mañana, 3 días» | Categoría, código del cliente, fecha de entrega y días (1 a 30) |

A tener en cuenta:

- **Reserva exprés**: es la misma que el formulario rápido de Situación. Crea la
  reserva con categoría, cliente, fecha y días; las horas y el lugar quedan con
  los valores por defecto de Webcar, sin vehículo asignado y sin precio. Se
  completa después en Webcar.
- **El cliente de una reserva tiene que existir**. Para uno nuevo, primero se da
  de alta el cliente (el asistente pide el NIF si falta) y, con el código que
  devuelve, se crea la reserva.
- **No duplica**: no crea un cliente si ya hay uno con ese NIF, ni un lugar con
  un nombre que ya existe, y no anula una reserva que ya está anulada.
- **Avisa en vez de recortar**: si un dato no cabe en el campo de Webcar (el
  nombre de un cliente admite 60 caracteres, el de un lugar 50…) o un código no
  existe (una categoría, una oficina), la acción falla con el motivo y no se
  envía nada.
- **El motivo de una anulación** se guarda en el asistente, no en Webcar.
- **Asignar matrícula, registrar un cobro e inmovilizar un vehículo** se pueden
  proponer, pero todavía no se ejecutan: la tarjeta queda «fallida» con el aviso.

Estados de una tarjeta:

| Estado | Significado |
| --- | --- |
| Pendiente | Esperando a que alguien confirme o rechace |
| Confirmada | Hecho en Webcar **y comprobado** volviendo a leerlo (indica el código creado) |
| Rechazada | Alguien pulsó Rechazar; no se hizo nada |
| Fallida | No se hizo, o no se pudo comprobar. El texto dice por qué y si hay que revisarlo en Webcar |

#### Cómo escribe en Webcar

Webcar no tiene API de escritura, así que el asistente hace lo mismo que haría
un empleado en la web: inicia sesión con un usuario de Webcar, abre el
formulario, cambia solo lo necesario y guarda. Las reglas:

- Nunca se ejecuta nada sin confirmación humana; el modelo solo propone.
- Cada cambio se envía una vez, sin reintentos.
- Una acción solo queda «confirmada» si, al volver a leer Webcar, el cambio
  está ahí y coincide con lo pedido. Si no se puede comprobar, queda «fallida».
- En Webcar todo queda hecho por el usuario configurado para el rentacar; quién
  lo confirmó en el asistente queda guardado en la propuesta.

#### Activar la escritura

Por defecto está **apagada**: el asistente propone, pero al confirmar responde
«escritura desactivada» y no toca Webcar. Para activarla hacen falta dos cosas.

1. Tres interruptores en el `.env` (los tres tienen que permitirlo):

   ```dotenv
   WEBCAR_ESCRITURA=on                    # interruptor general (off = solo propone)
   WEBCAR_ESCRITURA_RENTACARS=demo        # qué rentacars pueden ejecutar
   WEBCAR_ESCRITURA_ACCIONES=anular_reserva,crear_reserva,crear_cliente,crear_lugar
   ```

   Después de cambiar el `.env`: `docker compose up -d`.

2. El usuario de Webcar del rentacar, en **/admin › Rentacars › Escritura en
   Webcar**: número de usuario (`oper`) y contraseña.

> La contraseña se guarda sin cifrar. Hoy está pensado solo para la empresa
> DEMO de Webcar; antes de usarlo con un rentacar real hay que cifrarla (ver
> [docs/PLAN.md](docs/PLAN.md) › Seguridad).

### La interfaz

- Conversaciones en el panel lateral, agrupadas por fecha; se pueden **borrar**
  (con confirmación) y el panel se puede ocultar.
- **Tema claro y oscuro**, con el botón de sol/luna; recuerda la elección.
- Las respuestas llevan tablas que se desplazan en horizontal, botón de copiar
  y los pasos que ha dado el asistente plegados en una línea.
- Roles: administrador y restringido pueden proponer cambios; un partner solo
  consulta.

## Puesta en marcha

### Con Docker

```bash
cp .env.example .env            # poner OPENAI_API_KEY
docker compose up -d --build    # migra al arrancar; http://localhost:8000
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py refrescar_webcar demo --crear "DEMO"
```

La base de datos (SQLite) y los datos de cada rentacar (DuckDB) quedan en el
volumen `datos`. El servicio solo escucha en `127.0.0.1:8000`. Tras cambiar
código: `docker compose up -d --build`; tras cambiar el `.env`: `docker compose up -d`.

### Sin Docker

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # OPENAI_API_KEY, DJANGO_DEBUG=True
python manage.py migrate
python manage.py createsuperuser
python manage.py refrescar_webcar demo --crear "DEMO"
python manage.py runserver
```

### Usuarios

Entra en `/admin` con el superusuario y crea un usuario normal con rentacar
«DEMO» y rol Administrador; con él se entra en http://localhost:8000. El
superusuario, al no tener rentacar, no puede abrir conversaciones.

Para añadir otro rentacar: `refrescar_webcar <código de Webcar> --crear "Nombre"`
y asignarlo a sus usuarios en `/admin`.

### Modelo

Usa la API de chat completions de OpenAI o cualquier proveedor compatible
(`OPENAI_BASE_URL`). El modelo se elige con `OPENAI_MODEL`; los de la familia
gpt-6 necesitan además `OPENAI_REASONING_EFFORT=none`.

## Tests

```bash
docker compose run --rm --no-deps -e DATOS_DIR=/tmp/datos web python manage.py test
```

No se conectan a Webcar ni al modelo: el agente se prueba con un cliente falso y
la escritura con páginas grabadas de la DEMO (`webcar/tests_datos/`).
