import tempfile
from pathlib import Path
from unittest import mock

import duckdb

from django.test import TestCase, override_settings

from webcar import almacen, cliente, sql_guard
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
