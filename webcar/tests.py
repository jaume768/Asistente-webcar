import re
import tempfile
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qsl, urlparse

import duckdb

from django.test import TestCase, override_settings

from webcar import almacen, cliente, escritura, sql_guard
from webcar.models import Rentacar

# Muestra con el formato real de Webcar: latin-1, «\r», entidades sin «;»,
# una anotación partida en dos líneas y un «;» dentro de un domicilio.
CATEG = (
    "CODIGO CATEGORIAS;Categor&iacutea;Precio dias/horas;Importe fianza;Tipo Hospedajes;Esquema desperfectos\r"
    "C-01;A-Panda o similares;D;400;AUTOBUS;F\r"
    "C-15;SUV AUTOM&#193;TICO;D;;TURISMO;F\r"
).encode("latin-1")

CLIEN = (
    "CODIGO CLIENTES;Nombre;Domicilio;Pa&iacutes\r"
    "00001;INMOVILIZADO;;\r"
    "03520;Sophie Laurent;Untersteinstr; 38;France\r"
    "03521;Marc Pons;Calle Mayor;Espa\xc3\xb1a\r"
).encode("latin-1")

RESER = (
    "CODIGO RESERVAS;Cliente;Categor&iacutea;Fecha entrega;Importe alquiler;Vuelo/anotaciones\r"
    "004286;03520;C-01;2026-09-28;377;VY1234\r"
    "004287;03521;C-15;2026-09-29;00;linea uno\rlinea dos\r"
    "004288;00001;C-01;2026-09-30;0.5;\r"
).encode("latin-1")


class NormalizarTests(TestCase):
    def test_entidades_y_saltos(self):
        texto = cliente.normalizar(CATEG, "iso-8859-1")
        self.assertIn("Categoría", texto)
        self.assertIn("SUV AUTOMÁTICO", texto)
        self.assertEqual(texto.count("\n"), 3)

    def test_separador_dentro_de_campo_y_doble_codificacion(self):
        texto = cliente.normalizar(CLIEN, "iso-8859-1")
        self.assertIn("Untersteinstr, 38", texto)
        self.assertIn("España", texto)

    def test_registro_partido(self):
        texto = cliente.normalizar(RESER, "iso-8859-1")
        self.assertIn("linea uno linea dos", texto)

    def test_codi(self):
        import datetime
        self.assertEqual(cliente.codi_del_dia(datetime.date(2026, 9, 21)), 1826319)


class TiposTests(TestCase):
    def test_codigos_e_importes(self):
        self.assertEqual(almacen._tipo_columna(["00003", "00010"]), "VARCHAR")
        self.assertEqual(almacen._tipo_columna(["377", "00", "0.5"]), "DOUBLE")
        self.assertEqual(almacen._tipo_columna(["12", "7"]), "BIGINT")
        self.assertEqual(almacen._tipo_columna(["2026-09-28", ""]), "DATE")
        self.assertEqual(almacen._tipo_columna(["2026-09-28", "2026-03-29 22:56"]), "TIMESTAMP")
        self.assertEqual(almacen._tipo_columna(["12"], es_codigo=True), "VARCHAR")


class SqlGuardTests(TestCase):
    def test_select_ok_con_limite(self):
        sql = sql_guard.validar("select * from reservas", limite=50)
        self.assertIn("LIMIT 50", sql)

    def test_cte_ok(self):
        sql_guard.validar("with x as (select cliente from reservas) select count(*) from x")

    def test_rechazos(self):
        for sql in [
            "delete from reservas",
            "select 1; select 2",
            "select * from read_csv('/etc/passwd')",
            "select * from otra_tabla",
            "copy reservas to 'x.csv'",
            "attach 'x.db'",
            "select * from main.reservas",
        ]:
            with self.subTest(sql=sql), self.assertRaises(sql_guard.SQLNoPermitido):
                sql_guard.validar(sql)

    def test_tablas_usadas(self):
        self.assertEqual(
            sql_guard.tablas_usadas("with x as (select * from clientes) select * from reservas join x on true"),
            ["clientes", "reservas"],
        )


class AlmacenTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.override = override_settings(DATOS_DIR=Path(self.tmp.name))
        self.override.enable()
        self.r = Rentacar.objects.create(codigo="test", nombre="Test")
        for tabla, datos in [("categorias", CATEG), ("clientes", CLIEN), ("reservas", RESER)]:
            almacen.cargar_listado(self.r, tabla, cliente.normalizar(datos, "latin-1"))

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()

    def test_cruce_y_tipos(self):
        cols, filas, _ = almacen.consultar(
            self.r,
            "select r.codigo_reservas, c.nombre, k.categoria, r.importe_alquiler "
            "from reservas r left join clientes c on r.cliente = c.codigo_clientes "
            "left join categorias k on r.categoria = k.codigo_categorias order by 1",
            10,
        )
        self.assertEqual(filas[0], ("004286", "Sophie Laurent", "A-Panda o similares", 377.0))
        self.assertEqual(len(filas), 3)

    def test_solo_lectura(self):
        with self.assertRaises(Exception):
            almacen.consultar(self.r, "delete from reservas", 10)

    def test_cabecera_incorrecta(self):
        with self.assertRaises(cliente.WebcarError):
            almacen.cargar_listado(self.r, "vehiculos", cliente.normalizar(CATEG, "latin-1"))

    def test_comillas_en_un_campo(self):
        # Lejos del inicio: DuckDB deduce el formato de las primeras ~20.000 líneas.
        filas = "".join(f"{n:05};Cliente {n};Calle {n};Espa\xc3\xb1a\r" for n in range(1, 21001))
        datos = ("CODIGO CLIENTES;Nombre;Domicilio;Pa&iacutes\r" + filas + '21001;Ana Ruiz;"CALLE MAYOR 58" N 28;Italia\r').encode("latin-1")
        self.assertEqual(almacen.cargar_listado(self.r, "clientes", cliente.normalizar(datos, "latin-1")), 21001)
        _, filas, _ = almacen.consultar(self.r, "select domicilio from clientes where codigo_clientes = '21001'", 10)
        self.assertEqual(filas, [('"CALLE MAYOR 58" N 28',)])

    def test_error_de_duckdb_no_ensena_la_fila(self):
        fallo = duckdb.InvalidInputException("CSV Error on Line: 3\n03520;Sophie Laurent")
        with mock.patch.object(almacen.duckdb, "connect", side_effect=fallo):
            with self.assertRaises(cliente.WebcarError) as ctx:
                almacen.cargar_listado(self.r, "clientes", cliente.normalizar(CLIEN, "latin-1"))
        self.assertNotIn("Sophie", str(ctx.exception))


# --- escritura (docs/Escritura.md) -----------------------------------------
# Páginas grabadas de la DEMO (bytes tal cual llegan, con el token de sesión
# cambiado por TOKEN). Ningún test se conecta a Webcar.

DATOS = Path(__file__).parent / "tests_datos"
TOKEN = "*000000000"
SEGUR_EDITOR = "1916481"  # el de la página grabada del editor


def grabada(nombre):
    return (DATOS / nombre).read_bytes()


class WebcarFalso:
    """Sustituye a `urlopen`: responde con páginas grabadas y apunta cada petición.

    `paginas` es {(método, página): [respuestas en orden]}; la última se repite.
    """

    def __init__(self, paginas):
        self.paginas = {k: list(v) for k, v in paginas.items()}
        self.peticiones = []  # (método, página, [(nombre, valor)], cuerpo crudo)

    def __call__(self, req, timeout=None):
        url = urlparse(req.full_url)
        metodo = "GET" if req.data is None else "POST"
        pagina = url.path.rsplit("/", 1)[-1].upper()
        crudo = url.query if req.data is None else req.data.decode("ascii")
        self.peticiones.append((metodo, pagina, parse_qsl(crudo, keep_blank_values=True, encoding="cp1252"), crudo))
        cola = self.paginas[(metodo, pagina)]
        return mock.MagicMock(**{"__enter__.return_value.read.return_value": cola.pop(0) if len(cola) > 1 else cola[0]})

    def enviados(self, pagina):
        return [p for p in self.peticiones if p[0] == "POST" and p[1] == pagina]


class EscrituraTests(TestCase):
    def webcar(self, editor, login="login_ok.html"):
        falso = WebcarFalso({
            ("POST", "APP00"): [grabada(login)],
            ("GET", "APP1"): [grabada("app1.html")],
            ("GET", "APP21"): [grabada(n) for n in editor],
            ("POST", "APP21"): [b"<html></html>"],
        })
        parche = mock.patch.object(escritura, "urlopen", falso)
        parche.start()
        self.addCleanup(parche.stop)
        return falso

    def sesion(self):
        return escritura.SesionWebcar("demo", "046", "secreta")

    def test_login_guarda_el_token(self):
        falso = self.webcar(["editor_004292_activa.html"])
        s = self.sesion()
        self.assertEqual(s.login(), TOKEN)
        self.assertEqual(s.base, "https://lite.webcar.rent/DEMO/")
        self.assertEqual(falso.peticiones[0][:3], ("POST", "APP00", [("oper", "046"), ("oficina", "00"), ("c", "secreta")]))

    def test_login_rechazado(self):
        self.webcar(["editor_004292_activa.html"], login="login_malo.html")
        with self.assertRaises(cliente.WebcarError) as ctx:
            self.sesion().login()
        self.assertNotIn("secreta", str(ctx.exception))

    def test_get_form_saca_el_segur_y_los_campos(self):
        falso = self.webcar(["editor_004292_activa.html"])
        segur, f = self.sesion().get_form("APP21?", {"clave": "004292"}, accion="APP21", con="matriu1")
        self.assertEqual(segur, SEGUR_EDITOR)
        self.assertEqual(f.accion, "APP21?")
        self.assertTrue(f.marcada("matriu1"))
        self.assertEqual(f.valor("clave"), "+004292")
        # La sesión viaja en la petición.
        self.assertIn(("c", TOKEN), falso.peticiones[-1][2])
        # Webcar marca SELECTED la opción vacía y la real: vale la última, como en el navegador.
        self.assertEqual((f.valor("MATRIU3"), f.valor("MATRIU8"), f.valor("EXTRAS1")), ("C-02", "0013", "Z-005"))
        self.assertEqual(f.valor("EXTRAS2"), " ")
        # Textareas con acentos (cp1252), ocultos repetidos y campos desactivados.
        self.assertEqual(f.valor("histori"), "Reserva de prueba creada para la guía de empleados")
        self.assertEqual([v for n, v in f.campos if n == "MATRIU9"], ["R-2"] * 4)
        self.assertIsNone(f.valor("matriu24"))
        # «Guardar» no tiene nombre: no se envía nada por el botón.
        self.assertIn(("", " Guardar "), f.botones)

    def test_anular_envia_el_formulario_entero_sin_activo(self):
        falso = self.webcar(["editor_004292_activa.html", "editor_004292_anulada.html"])
        resultado = escritura.anular_reserva(self.sesion(), {"reserva": "4292", "motivo": "prueba"})
        self.assertIn("004292", resultado)
        (_, _, pares, crudo), = falso.enviados("APP21")  # un único POST
        pagina = grabada("editor_004292_activa.html").decode("cp1252")
        antes = next(f for f in escritura.leer_formularios(pagina) if "matriu1" in f.casillas)
        self.assertEqual(len(antes.campos), 55)
        self.assertEqual(pares, [p for p in antes.campos if p[0] != "matriu1"])
        nombres = [n for n, _ in pares]
        self.assertNotIn("matriu1", nombres)
        for oculto in ["matriu25", "MATRIU11", "matriu17", "MATRIU9", "matriu18", "matriu19", "matriu20",
                       "oper", "c", "cliente", "nuevo", "prog", "dia", "filtro", "clave", "segur"]:
            self.assertIn(oculto, nombres)
        enviado = dict(pares)
        self.assertEqual((enviado["oper"], enviado["c"], enviado["clave"], enviado["segur"]), ("046", TOKEN, "+004292", SEGUR_EDITOR))
        # En cp1252 y con el «+» de la clave escapado.
        self.assertIn("gu%EDa+de+empleados", crudo)
        self.assertIn("clave=%2B004292", crudo)

    def test_anular_no_confirma_si_webcar_la_deja_activa(self):
        falso = self.webcar(["editor_004292_activa.html"])
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura.anular_reserva(self.sesion(), {"reserva": "004292", "motivo": "prueba"})
        self.assertIn("sigue activa", str(ctx.exception))
        self.assertEqual(len(falso.enviados("APP21")), 1)  # no se reintenta

    def test_anular_una_ya_anulada_no_envia_nada(self):
        falso = self.webcar(["editor_004292_anulada.html"])
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura.anular_reserva(self.sesion(), {"reserva": "004292", "motivo": "prueba"})
        self.assertIn("ya figura anulada", str(ctx.exception))
        self.assertEqual(falso.enviados("APP21"), [])

    def test_no_toca_una_reserva_distinta_de_la_pedida(self):
        falso = self.webcar(["editor_004292_activa.html"])  # Webcar abre otra reserva
        for reserva in ["004000", "abc", ""]:
            with self.assertRaises(cliente.WebcarError):
                escritura.anular_reserva(self.sesion(), {"reserva": reserva, "motivo": "prueba"})
        self.assertEqual(falso.enviados("APP21"), [])

    def test_los_errores_no_ensenan_el_token(self):
        self.webcar(["editor_004292_activa.html"])
        s = self.sesion()
        s.login()
        with mock.patch.object(escritura, "urlopen", side_effect=escritura.URLError("sin red")):
            with self.assertRaises(cliente.WebcarError) as ctx:
                s.get_form("APP21?", {"clave": "004292"})
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_puede_escribir_tres_puertas(self):
        demo, otro = Rentacar(codigo="demo"), Rentacar(codigo="1048")
        abierto = {"WEBCAR_ESCRITURA": True, "WEBCAR_ESCRITURA_RENTACARS": ["demo"], "WEBCAR_ESCRITURA_ACCIONES": ["anular_reserva"]}
        with override_settings(**abierto):
            self.assertTrue(escritura.puede_escribir(demo, "anular_reserva"))
            self.assertFalse(escritura.puede_escribir(otro, "anular_reserva"))
            self.assertFalse(escritura.puede_escribir(demo, "crear_reserva"))
        with override_settings(**{**abierto, "WEBCAR_ESCRITURA": False}):
            self.assertFalse(escritura.puede_escribir(demo, "anular_reserva"))
        with override_settings(**{**abierto, "WEBCAR_ESCRITURA_RENTACARS": []}):
            self.assertFalse(escritura.puede_escribir(demo, "anular_reserva"))
        # Lista de acciones vacía = todas las implementadas.
        with override_settings(**{**abierto, "WEBCAR_ESCRITURA_ACCIONES": []}):
            self.assertTrue(escritura.puede_escribir(demo, "crear_reserva"))


OK = b"<html></html>"  # lo que responda Webcar al guardar da igual: se comprueba volviendo a leer
CLIENTE = {
    "nombre": "PRUEBA ASISTENTE DOS Peña", "nif": "TEST00002A", "domicilio": "Calle de la Prueba 2",
    "cp": "07001", "municipio": "Palma", "pais": "España", "telefono": "600000002",
    "email": "prueba.asistente2@test.com", "fecha_nacimiento": "1990-01-02",
    "licencia": "LICPRUEBA2", "fecha_expedicion": "2012-03-04",
}
LUGAR = {"nombre": "PRUEBA ASISTENTE L2", "calculo_precios": "24", "color": "3833FF"}
RESERVA = {"categoria": "C-02", "cliente": "03527", "fecha_entrega": "2026-10-20", "dias": "1"}


def sin_redireccion(pagina):
    """El listado de lugares «de antes» se grabó sin `segur`: trae el contenido y una redirección al login."""
    limpia, quitadas = re.subn(rb"<META HTTP-EQUIV='REFRESH'[^>]*URL=APP0[^>]*>", b"", pagina)
    assert quitadas == 1
    return limpia


class AltasTests(TestCase):
    """Altas de cliente, lugar y reserva con las páginas que devolvió la DEMO al crearlas (13-10-2026)."""

    def webcar(self, **paginas):
        """`paginas`: POST_APP2=[...], GET_APP21=[...]… con nombres de fichero grabado o bytes."""
        mapa = {("POST", "APP00"): [grabada("login_ok.html")], ("GET", "APP1"): [grabada("app1_expres.html")]}
        for clave, respuestas in paginas.items():
            mapa[tuple(clave.split("_"))] = [r if isinstance(r, bytes) else grabada(r) for r in respuestas]
        falso = WebcarFalso(mapa)
        parche = mock.patch.object(escritura, "urlopen", falso)
        parche.start()
        self.addCleanup(parche.stop)
        return falso

    def sesion(self):
        return escritura.SesionWebcar("demo", "046", "secreta")

    def guardados(self, falso, pagina, campo="matriu2"):
        """POST que guardan un formulario (llevan el campo del nombre), no los de navegar o buscar."""
        return [p for p in falso.enviados(pagina) if any(n == campo for n, _ in p[2])]

    # --- lector: límites y opciones

    def test_el_lector_saca_maxlength_y_opciones(self):
        cliente_nuevo = next(
            f for f in escritura.leer_formularios(grabada("cliente_nuevo.html").decode("cp1252")) if f.tiene("matriu2")
        )
        self.assertEqual((cliente_nuevo.limite("matriu2"), cliente_nuevo.limite("matriu6")), (60, 15))
        self.assertEqual(cliente_nuevo.limite("matriu12"), 150)  # textarea
        self.assertIsNone(cliente_nuevo.limite("MATRIU11"))  # un select no tiene
        self.assertIn("O-01", cliente_nuevo.opciones["MATRIU11"])
        lugar_nuevo = next(
            f for f in escritura.leer_formularios(grabada("lugar_nuevo.html").decode("cp1252")) if f.tiene("matriu2")
        )
        self.assertEqual((lugar_nuevo.limite("matriu2"), lugar_nuevo.limite("matriu7")), (50, 6))  # maxlength=6 sin comillas
        self.assertEqual(lugar_nuevo.opciones["MATRIU8"], ["12", "24"])

    def test_valida_limites(self):
        f = escritura.Formulario(campos=[("matriu2", "")], limites={"matriu2": 5})
        escritura._valida_limites(f, {"matriu2": "12345", "otro": "x" * 99}, {})
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura._valida_limites(f, {"matriu2": "123456"}, {"matriu2": "nombre"})
        self.assertEqual(str(ctx.exception), "«nombre» admite como máximo 5 caracteres (has puesto 6).")

    def test_una_pagina_rechazada_no_se_usa(self):
        self.webcar(GET_APP541=["lugares_antes_sin_segur.html"])
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura._lugares(self.sesion())
        self.assertIn("rechazado", str(ctx.exception))

    # --- clientes

    def test_crear_cliente(self):
        falso = self.webcar(
            POST_APP2=["clientes_filtrado_vacio.html", "cliente_nuevo.html", OK, "clientes_filtrado_nif.html"],
            GET_APP2=["cliente_03528.html"],
        )
        resultado = escritura.crear_cliente(self.sesion(), CLIENTE)
        self.assertIn("Cliente 03528", resultado)
        (_, _, pares, crudo), = self.guardados(falso, "APP2")  # un único guardado
        enviado = dict(pares)
        self.assertEqual((enviado["matriu2"], enviado["matriu6"], enviado["matriu5"]), ("PRUEBA ASISTENTE DOS Peña", "TEST00002A", "España"))
        # Fechas en tres desplegables, sin ceros.
        self.assertEqual([enviado[f"MATRIU20-{n}"] for n in (1, 2, 3)], ["2", "1", "1990"])
        self.assertEqual([enviado[f"MATRIU21-{n}"] for n in (1, 2, 3)], ["4", "3", "2012"])
        # Lo que no se pide queda como venía, y los ocultos van todos (la clave la propone Webcar).
        self.assertEqual((enviado["matriu1"], enviado["MATRIU11"], enviado["matriu8"]), ("matriu1", "O-01", ""))
        self.assertEqual((enviado["oper"], enviado["c"], enviado["nuevo"], enviado["clave"]), ("046", TOKEN, "S", "+03529"))
        self.assertTrue(enviado["segur"].isdigit())
        self.assertNotIn("matriu24", enviado)  # casilla sin marcar

    def test_los_acentos_van_en_cp1252_no_en_utf8(self):
        falso = self.webcar(
            POST_APP2=["clientes_filtrado_vacio.html", "cliente_nuevo.html", OK, "clientes_filtrado_nif.html"],
            GET_APP2=["cliente_03528.html"],
        )
        escritura.crear_cliente(self.sesion(), CLIENTE)
        (_, _, _, cuerpo_enviado), = self.guardados(falso, "APP2")
        self.assertIn("matriu5=Espa%F1a", cuerpo_enviado)
        self.assertIn("matriu2=PRUEBA+ASISTENTE+DOS+Pe%F1a", cuerpo_enviado)
        self.assertNotIn("%C3%B1", cuerpo_enviado)
        self.assertNotIn("%C3", cuerpo_enviado)
        # Y al releer la ficha que guardó Webcar, vuelve bien.
        ficha = next(f for f in escritura.leer_formularios(grabada("cliente_03528.html").decode("cp1252")) if f.tiene("matriu2"))
        self.assertEqual((ficha.valor("matriu2"), ficha.valor("matriu5")), ("PRUEBA ASISTENTE DOS Peña", "España"))

    def test_cliente_con_nombre_demasiado_largo_no_se_envia(self):
        falso = self.webcar(POST_APP2=["clientes_filtrado_vacio.html", "cliente_nuevo.html"])
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura.crear_cliente(self.sesion(), {**CLIENTE, "nombre": "N" * 61})
        self.assertEqual(str(ctx.exception), "«nombre» admite como máximo 60 caracteres (has puesto 61).")
        self.assertEqual(self.guardados(falso, "APP2"), [])

    def test_cliente_con_valores_que_webcar_no_ofrece_no_se_envia(self):
        casos = [({"oficina": "O-99"}, "oficina"), ({"fecha_nacimiento": "2020-01-02"}, "fecha_nacimiento"),
                 ({"fecha_nacimiento": "1990-02-30"}, "no es una fecha")]
        for cambio, aviso in casos:
            falso = self.webcar(POST_APP2=["clientes_filtrado_vacio.html", "cliente_nuevo.html"])
            with self.assertRaises(cliente.WebcarError) as ctx:
                escritura.crear_cliente(self.sesion(), {**CLIENTE, **cambio})
            self.assertIn(aviso, str(ctx.exception))
            self.assertEqual(self.guardados(falso, "APP2"), [])

    def test_cliente_con_nif_que_ya_existe_no_se_duplica(self):
        falso = self.webcar(POST_APP2=["clientes_filtrado_nif.html"], GET_APP2=["cliente_03528.html"])
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura.crear_cliente(self.sesion(), {**CLIENTE, "nif": "test-00002a"})  # mismo NIF, escrito distinto
        self.assertIn("Ya existe el cliente 03528", str(ctx.exception))
        self.assertEqual(self.guardados(falso, "APP2"), [])

    def test_el_buscador_no_basta_para_dar_un_cliente_por_existente(self):
        # El buscador casa por trozos: devuelve el 03528, pero su NIF no es el pedido.
        self.webcar(POST_APP2=["clientes_filtrado_nif.html"], GET_APP2=["cliente_03528.html"])
        self.assertEqual(escritura._cliente_por_nif(self.sesion(), "TEST0000"), (None, None))

    def test_cliente_no_confirmado_si_no_aparece_o_no_coincide(self):
        # No aparece al buscarlo después de guardar.
        falso = self.webcar(POST_APP2=["clientes_filtrado_vacio.html", "cliente_nuevo.html", OK, "clientes_filtrado_vacio.html"])
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura.crear_cliente(self.sesion(), CLIENTE)
        self.assertIn("no aparece en Webcar", str(ctx.exception))
        self.assertEqual(len(self.guardados(falso, "APP2")), 1)  # no se reintenta
        # Aparece con ese NIF pero con otro nombre.
        self.webcar(
            POST_APP2=["clientes_filtrado_vacio.html", "cliente_nuevo.html", OK, "clientes_filtrado_nif.html"],
            GET_APP2=["cliente_03528.html"],
        )
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura.crear_cliente(self.sesion(), {**CLIENTE, "nombre": "Otra Persona"})
        self.assertIn("con el nombre «PRUEBA ASISTENTE DOS Peña»", str(ctx.exception))

    # --- lugares

    def lugares_antes(self):
        return sin_redireccion(grabada("lugares_antes_sin_segur.html"))

    def test_crear_lugar(self):
        falso = self.webcar(GET_APP541=[self.lugares_antes(), "lugares_despues.html"], POST_APP541=["lugar_nuevo.html", OK])
        resultado = escritura.crear_lugar(self.sesion(), LUGAR)
        self.assertIn("Lugar L-07 «PRUEBA ASISTENTE L2»", resultado)
        (_, _, pares, _), = self.guardados(falso, "APP541")
        enviado = dict(pares)
        self.assertEqual((enviado["matriu2"], enviado["MATRIU8"], enviado["matriu7"]), ("PRUEBA ASISTENTE L2", "24", "3833FF"))
        self.assertEqual((enviado["oper"], enviado["c"], enviado["nuevo"], enviado["matriu1"]), ("046", TOKEN, "S", "matriu1"))
        self.assertTrue(enviado["clave"].startswith("+"))
        # Los listados se piden con su `segur`.
        self.assertTrue(all(dict(p[2]).get("segur") for p in falso.peticiones if p[:2] == ("GET", "APP541")))

    def test_lista_de_lugares(self):
        self.webcar(GET_APP541=["lugares_despues.html"])
        lugares = escritura._lugares(self.sesion())
        self.assertEqual(lugares["01"], "Manacor oficina")
        self.assertEqual(lugares["07"], "PRUEBA ASISTENTE L2")
        self.assertEqual(len(lugares), 6)

    def test_lugar_repetido_o_demasiado_largo_no_se_envia(self):
        for params, aviso in [({"nombre": "prueba asistente l"}, "Ya existe el lugar 06"),
                              ({"nombre": "L" * 51}, "«nombre» admite como máximo 50 caracteres (has puesto 51)."),
                              ({"nombre": "Nuevo", "color": "rojo"}, "hexadecimal"),
                              ({"nombre": "Nuevo", "calculo_precios": "48"}, "calculo_precios")]:
            falso = self.webcar(GET_APP541=[self.lugares_antes()], POST_APP541=["lugar_nuevo.html"])
            with self.assertRaises(cliente.WebcarError) as ctx:
                escritura.crear_lugar(self.sesion(), params)
            self.assertIn(aviso, str(ctx.exception))
            self.assertEqual(self.guardados(falso, "APP541"), [])

    def test_lugar_no_confirmado_si_no_aparece(self):
        falso = self.webcar(GET_APP541=[self.lugares_antes()], POST_APP541=["lugar_nuevo.html", OK])
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura.crear_lugar(self.sesion(), LUGAR)
        self.assertIn("no aparece en Webcar", str(ctx.exception))
        self.assertEqual(len(self.guardados(falso, "APP541")), 1)

    # --- reserva exprés

    def webcar_reserva(self, reservas, respuesta="expres_respuesta.html", clientes="clientes_filtrado_codigo.html"):
        return self.webcar(POST_APP2=[clientes], GET_APP21=reservas, POST_APP1=[respuesta])

    def test_crear_reserva(self):
        falso = self.webcar_reserva(["reservas_cliente_antes.html", "reservas_cliente_despues.html", "editor_004294_nueva.html"])
        resultado = escritura.crear_reserva(self.sesion(), RESERVA)
        self.assertIn("Reserva 004294 creada", resultado)
        self.assertIn("del 2026-10-20 08:00 al 2026-10-20 20:00", resultado)
        (_, _, pares, _), = falso.enviados("APP1")  # un único POST
        self.assertEqual([n for n, _ in pares], ["oper", "c", "expres", "segur", "CATEGORIA", "desdedia", "TIEMPO", "CLIENTE", "reservar"])
        enviado = dict(pares)
        self.assertEqual(
            (enviado["CATEGORIA"], enviado["desdedia"], enviado["TIEMPO"], enviado["CLIENTE"], enviado["reservar"]),
            ("C-02", "2026-10-20", "1", "03527", "Reservar"),
        )

    def test_la_respuesta_de_la_expres_no_trae_el_editor(self):
        # Webcar responde con una redirección al editor: por eso el número se saca leyendo las reservas del cliente.
        respuesta = grabada("expres_respuesta.html").decode("cp1252")
        self.assertIn("URL=APP21?", respuesta)
        self.assertFalse(any("matriu1" in f.casillas for f in escritura.leer_formularios(respuesta)))
        self.webcar(GET_APP21=["reservas_cliente_antes.html", "reservas_cliente_despues.html"])
        s = self.sesion()
        self.assertEqual(escritura._reservas_de_cliente(s, "03527"), {"004293"})
        self.assertEqual(escritura._reservas_de_cliente(s, "03527"), {"004293", "004294"})

    def test_reserva_no_confirmada_si_el_cliente_no_tiene_una_nueva(self):
        # Aunque Webcar devuelva Situación, con los lápices de otras reservas (clave=004292).
        falso = self.webcar_reserva(["reservas_cliente_antes.html"], respuesta="app1.html")
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura.crear_reserva(self.sesion(), RESERVA)
        self.assertIn("no tiene ninguna reserva nueva", str(ctx.exception))
        self.assertNotIn("004292", str(ctx.exception))
        self.assertEqual(len(falso.enviados("APP1")), 1)  # no se reintenta

    def test_reserva_no_confirmada_si_no_coincide_con_lo_pedido(self):
        self.webcar_reserva(["reservas_cliente_antes.html", "reservas_cliente_despues.html", "editor_004294_nueva.html"])
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura.crear_reserva(self.sesion(), {**RESERVA, "fecha_entrega": "2026-10-21"})
        self.assertIn("004294", str(ctx.exception))
        self.assertIn("no coincide", str(ctx.exception))

    def test_reserva_con_datos_que_no_valen_no_se_envia(self):
        casos = [({"cliente": "3527"}, "cinco cifras"), ({"cliente": "Juan Nuevo"}, "cinco cifras"),
                 ({"categoria": "C-99"}, "no es un valor válido"), ({"categoria": "Fabia"}, "C-xx"),
                 ({"dias": "40"}, "entre 1 y 30"), ({"fecha_entrega": "20/10/2026"}, "no es una fecha")]
        for cambio, aviso in casos:
            falso = self.webcar_reserva(["reservas_cliente_antes.html"])
            with self.assertRaises(cliente.WebcarError) as ctx:
                escritura.crear_reserva(self.sesion(), {**RESERVA, **cambio})
            self.assertIn(aviso, str(ctx.exception))
            self.assertEqual(falso.enviados("APP1"), [])

    def test_reserva_para_un_cliente_que_no_existe_no_se_envia(self):
        falso = self.webcar_reserva(["reservas_cliente_antes.html"], clientes="clientes_filtrado_vacio.html")
        with self.assertRaises(cliente.WebcarError) as ctx:
            escritura.crear_reserva(self.sesion(), {**RESERVA, "cliente": "99999"})
        self.assertIn("No existe el cliente 99999", str(ctx.exception))
        self.assertEqual(falso.enviados("APP1"), [])
