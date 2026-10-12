# Webcar Lite: resumen operativo

Webcar Lite es el back-office de un rent a car: reservas, contratos, flota,
clientes, cobros, facturas e informes. Menús: Situación, Clientes, Ficheros,
Informes y Varios. Revisado sobre la empresa DEMO, versión 1.12.

## Menús y para qué sirve cada uno

- Situación: el día a día. Reserva exprés, entregas (E), devoluciones (D), Planning, Mi programación y Cierre diario.
- Clientes: fichas de clientes con sus reservas, facturas, fotos; Newsletter.
- Ficheros: Categorías, Vehículos, Tarifas, Extras y Otros (Forma de pago, Incid-Vehículos, Lugares, Centros Stock).
- Informes: Producción, Ocupación, Cobros pendientes, Comisiones, Reservas, Generador y Registro horario.
- Varios: Configuración, Usuarios, Series, Oficinas, Contabilidad y VeriFactu.

En todas las listas: botón rosa Nuevo para crear, lápiz para editar, Inactivos
para ver lo dado de baja, icono PDF para imprimir. Nada se borra: se desmarca Activo.

## Reserva exprés: qué escribir en el campo Cliente

En Situación se elige Categoría, Fecha, Días y se escribe en Cliente:

- Un nombre: crea un cliente nuevo y abre la reserva.
- `+` y un texto o número (`+Laurent`, `+659360217`): busca clientes existentes y deja elegir.
- `I` o `I-motivo` (`I-PASAR ITV`): inmoviliza el vehículo (taller, ITV) y lo bloquea en el planning.
- `+partner-habitación` (`+hotel meliá-208`): busca el partner, crea el cliente y asocia la reserva al partner.
- Código de cliente con todos los ceros (`03520`): reserva directamente para ese cliente.

Para consultar disponibilidad sin reservar: fecha y días, Cliente vacío y
pulsar Reservar. El desplegable de categorías muestra los libres entre paréntesis.

## Colores en Situación

- Verde azulado: entrega pendiente (el coche sale ese día).
- Rosa / fucsia: devolución pendiente (el coche vuelve ese día).
- Verde o rosa pálido: ya despachado (se pulsó OK).
- Gris: reserva entrada ese día. Gris muy claro: reserva anulada.
- Rojo: vehículo inmovilizado. Salmón: reserva de la web sin revisar. Morado: cotización.

## Colores en el Planning

Barra azul: reserva sin contrato. Barra verde azulada: reserva con contrato
emitido. Celda gris: día libre (clic para reservar). Números en amarillo:
pendiente de pago. Total naranja (5/5): categoría llena. Total rojo (5/3):
sobreventa. Total en negrita: hay reservas sin vehículo asignado.

## Iconos de cada fila en Situación

ⓘ: anotaciones. ✓ antes del cliente: ficha completa para Hospedajes. E en
círculo: lleva extras. Impresora: copia del contrato en PDF. QR: enviar el
check-in online (punto rojo = el cliente ya lo rellenó). Lápiz: abrir la
reserva. OK: marcar entregado o devuelto. Relojito: tarea asignada a un usuario.
En Cobrado, la letra es el canal del cobro: E efectivo, B banco.

## Flujo de una reserva

1. Crear con la reserva exprés o desde una celda gris del Planning.
2. Completar: matrícula, extras, vuelo/anotaciones, cobro; Guardar. El precio se recalcula (ⓘ explica el cálculo).
3. Confirmar al cliente con el botón Confirma (email), opcionalmente con enlace de pago TPV.
4. Check-in online: botón QR, por WhatsApp, email o SMS.
5. Emitir contrato: elegir Serie (C contratos, A facturas de alquiler) y combustible, botón «Factura / contrato».
6. Entrega: OK en la fila de Situación del día de salida.
7. Devolución: revisar kms y combustible, cobrar pendiente, OK; Check-out envía el email de cierre.
8. Cierre diario de caja al final del día.

Casos especiales: cambio de vehículo (hora del cambio en el contrato, genera
contrato nuevo serie CAMB); prolongación (cerrar antes el contrato); cotización
(casilla Cotización, sale en morado); anular (desmarcar Activo).

## Cierre diario

Situación → Cierre diario: facturas del día (importe, IVA, cobrado,
pendiente) y relación de cobros por forma de pago. Movimientos permite apuntar
entradas y salidas de caja.

## Tarifas, temporadas y precios

Ficheros → Tarifas: cada tarifa (GENERAL/WEB, BASIC −10 %…) tiene temporadas
(calendario) sin huecos ni solapes salvo ofertas, y cada temporada precios por
categoría y tramo de días (1–3, 4–7, 8–999). Las ofertas pueden llevar código promocional.

## Perfiles de usuario

A administrador (todo), O restringido (día a día), H solo control horario,
P partner (mete reservas de sus clientes y cobra comisión).

## VeriFactu

Varios → VeriFactu abre la plataforma puente que envía las facturas a
Hacienda. Si alguna se rechaza, Situación muestra en rojo «VERIFACTU: Facturas
pendientes de subsanar» con el enlace ACCEDER.

## Post-its

El post-it rosa de arriba deja notas al equipo. Empezar con `*` la marca como urgente (rojo).
