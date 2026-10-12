# Páginas grabadas de la DEMO de Webcar

Respuestas tal cual las devolvió `https://lite.webcar.rent/DEMO/` (bytes en
cp1252), para los tests de `webcar/escritura.py`. El token de sesión está
sustituido por `*000000000` y no hay contraseñas. Los datos son los de la
empresa de demostración y los registros de prueba creados el 12 y 13-10-2026.

| Fichero | Qué es |
| --- | --- |
| `login_ok.html`, `login_malo.html` | Respuesta de `POST APP00` con contraseña buena y mala |
| `app1.html`, `app1_expres.html` | Situación (`APP1`); de aquí sale el `segur` y el formulario exprés |
| `editor_004292_activa.html`, `editor_004292_anulada.html` | Editor de la reserva 004292 antes y después de anularla |
| `cliente_nuevo.html` | Editor de cliente en blanco (`POST APP2?` con `clave=NUEVO`) |
| `clientes_filtrado_vacio.html`, `clientes_filtrado_nif.html`, `clientes_filtrado_codigo.html` | Buscador de clientes sin resultados, por NIF `TEST00002A` y por código `03527` |
| `cliente_03528.html` | Ficha del cliente 03528 tal como la guardó Webcar |
| `lugares_antes_sin_segur.html` | Listado de lugares antes del alta, pedido sin `segur`: trae la redirección a `APP0` con la que Webcar rechaza la petición |
| `lugares_despues.html`, `lugar_nuevo.html` | Listado con el lugar 07 y editor de lugar en blanco |
| `expres_respuesta.html` | Respuesta de Webcar a la reserva exprés que creó la 004294 (una redirección) |
| `reservas_cliente_antes.html`, `reservas_cliente_despues.html` | Reservas del cliente 03527 antes y después de esa exprés |
| `editor_004294_nueva.html` | Editor de la reserva 004294 recién creada |
