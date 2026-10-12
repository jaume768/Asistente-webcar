# Plan de webcar-asistente

Estado a 12-10-2026: esqueleto funcional. El conector a Webcar está probado contra
la demo (20 listados, 4.175 reservas, 3.514 clientes); las herramientas y el bucle
del agente están probados con tests; **falta la primera prueba con un modelo real**.

## Fases

| Fase | Qué | Estado |
| --- | --- | --- |
| 0 | Proyecto, usuarios por rentacar, conector Webcar → DuckDB, SQL seguro | Hecho |
| 1 | Asistente de ayuda (buscar_ayuda sobre `conocimiento/`) | Hecho v1 (búsqueda por palabras) |
| 2 | Consultas sobre datos (describir_tablas + consultar_datos) | Hecho v1, falta afinar con el modelo |
| 3 | Acciones con confirmación | Propuesta + confirmación hechas; ejecución bloqueada por falta de API |
| 4 | Producción: despliegue, límites, métricas | Pendiente |

### Fase 1 – Ayuda
- [ ] Exportar la «Guía Webcar Lite para empleados» a `conocimiento/guia-webcar-lite.md`.
- [ ] Añadir el control de versiones de Webcar (pantalla Versión) y la guía de implantación (impla.pdf) como Markdown.
- [ ] Si la base pasa de ~50 páginas: embeddings (p. ej. tabla en DuckDB con vectores) en vez de búsqueda por palabras.

### Fase 2 – Datos
- [ ] Probar la batería de preguntas (abajo) con el modelo elegido y anotar fallos.
- [ ] Añadir «país normalizado» de clientes (saasia lo calcula en `generador_informes/paises.py`).
- [ ] Vistas SQL de ayuda en DuckDB (p. ej. `reservas_detalle` con nombres ya cruzados) si el modelo se equivoca en los JOIN.
- [ ] Partners: filtrar `reservas` por `partner = usuario.codigo_webcar` (vista por usuario) antes de dejarles entrar.
- [ ] Refresco en segundo plano (cron/Celery) de reservas cada 5 min para que la primera pregunta no espere la descarga (~1 MB, unos segundos).

### Fase 3 – Acciones
Webcar solo expone listados CSV (lectura). Para ejecutar cambios hace falta que
COR SOFT exponga endpoints de escritura. Lo que se sabe:
- El control de versiones menciona una **API5 «importa reserva»** (devuelve además la URL del check-in online) y APIs para el frontend (disponibilidad, precios, entregas/devoluciones entre fechas).
- En Webcar › Varios › Configuración hay un botón **APIS** con los esquemas.

Pasos:
- [ ] Conseguir la documentación de APIS y decidir qué acciones se implementan primero.
- [ ] Implementar `ejecutar` en `chat/acciones.py` para `crear_reserva` con API5.
- [ ] Pedir endpoints para: anular reserva, asignar matrícula, registrar cobro, inmovilizar.
- [ ] Cada endpoint: token por rentacar, idempotencia (id de la propuesta), respuesta con el id creado.

### Fase 4 – Producción
- [x] Docker + gunicorn (un worker con hilos, WhiteNoise, SQLite/DuckDB en volumen).
- [ ] MySQL/Postgres y HTTPS con proxy delante (como saasia).
- [ ] Límite de mensajes/coste por usuario y día; mostrar tokens en admin.
- [ ] Respuesta en streaming (SSE) para no esperar con «Pensando…».
- [ ] Widget embebible en Webcar Lite (iframe con login por token).

## Seguridad (decidir antes de producción)

1. **El `codi` de Webcar es predecible** (AAMMDD × 7 − 128) y `ruta` es el código
   del rentacar. Cualquiera que conozca la fórmula puede descargar clientes,
   reservas y facturas de cualquier rentacar → riesgo RGPD. Propuesta: token
   secreto por rentacar en la API de Webcar y guardarlo cifrado en `Rentacar`.
2. **Privacidad con el LLM**: saasia promete que el modelo solo ve esquemas y
   agregados. Este asistente le enseña filas concretas (nombres, teléfonos) cuando
   la pregunta lo pide. Opciones: aceptarlo y avisar en el contrato/política;
   enmascarar columnas personales en consultar_datos; o usar un proveedor con
   garantías de no retención.
3. Prompt injection vía datos: textos libres de Webcar (anotaciones) llegan al
   modelo. Mitigado porque el modelo no puede ejecutar nada sin confirmación
   humana; mantener esa regla.

## Batería de preguntas para probar

Ayuda:
- ¿Cómo inmovilizo un coche que va a la ITV?
- ¿Qué significa una reserva en color salmón?
- ¿Cómo envío el check-in online al cliente?

Datos (demo):
- ¿Qué coches salen mañana y desde qué lugar? (debe cruzar lugares y vehículos)
- ¿Cuánto se facturó en septiembre por categoría?
- ¿Qué clientes tienen importe pendiente de cobro?
- ¿Qué vehículos tienen la ITV en los próximos 30 días? (incidencias)
- ¿Qué partner trajo más reservas este año?

Acciones:
- «Anula la 004292, el cliente ha cancelado» → tarjeta pendiente; al confirmar, «fallida: Webcar todavía no ofrece una API…».
- Un usuario partner pide anular → debe negarse.

## Decisiones tomadas

- Proyecto aparte de saasia, mismo stack (Django + DuckDB + OpenAI) para reutilizar conocimiento.
- Chat completions con tool calling: compatible con OpenAI y cualquier proveedor vía `OPENAI_BASE_URL`.
- Sin Celery en v1: los listados son pequeños (reservas demo ≈ 1 MB) y se descargan bajo demanda con caducidad por listado.
- UI con plantillas Django y JS mínimo; marked + DOMPurify servidos en local (`chat/static/chat`).

## Preguntas abiertas para Jaume

- ¿Quién mantiene el backend de Webcar y puede añadir endpoints de escritura?
- ¿Qué 5–10 acciones quiere primero?
- ¿Dónde vive el chat: web propia, widget dentro de Webcar o ambos?
- ¿Qué proveedor/modelo de IA y qué presupuesto por rentacar?
