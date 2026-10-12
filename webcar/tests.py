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
