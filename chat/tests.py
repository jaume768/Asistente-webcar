import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import duckdb

from django.test import TestCase, override_settings
from django.urls import reverse

from chat import acciones, agente, ayuda, herramientas
from chat.models import AccionPropuesta, Conversacion, Mensaje
from cuentas.models import Usuario
from webcar import almacen, cliente, escritura
from webcar.models import Rentacar
from webcar.tests import CATEG, CLIEN, RESER


def _llamada(nombre, args, id_="c1"):
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=nombre, arguments=json.dumps(args)))


class ClienteFalso:
    """Imita client.chat.completions.create devolviendo respuestas en cola."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.peticiones = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.peticiones.append(kwargs)
        contenido, llamadas = self.respuestas.pop(0)
        msg = SimpleNamespace(content=contenido, tool_calls=llamadas)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


class Base(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Escritura apagada diga lo que diga el .env: ningún test puede llegar a Webcar.
        self.override = override_settings(DATOS_DIR=Path(self.tmp.name), WEBCAR_ESCRITURA=False)
        self.override.enable()
        self.r = Rentacar.objects.create(codigo="test", nombre="Test Rent")
        for tabla, datos in [("categorias", CATEG), ("clientes", CLIEN), ("reservas", RESER)]:
            almacen.cargar_listado(self.r, tabla, cliente.normalizar(datos, "latin-1"))
        self.u = Usuario.objects.create_user("ana", password="x", rentacar=self.r, rol=Usuario.Rol.RESTRINGIDO)
        self.c = Conversacion.objects.create(usuario=self.u, rentacar=self.r)
        self.ctx = herramientas.Contexto(self.u, self.r, self.c)

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()


class HerramientasTests(Base):
    def test_consultar_datos(self):
        res = herramientas.consultar_datos(self.ctx, "select count(*) as n from reservas where cliente <> '00001'")
        self.assertEqual(res["filas"], [[2]])

    def test_consultar_rechaza_escritura(self):
        res = herramientas.consultar_datos(self.ctx, "drop table reservas")
        self.assertIn("error", res)

    def test_describir(self):
        res = herramientas.describir_tablas(self.ctx, ["reservas"])
        rel = {r["columna"]: r["tabla"] for r in res["reservas"]["relaciones"]}
        self.assertEqual(rel["cliente"], "clientes")
        self.assertEqual(res["reservas"]["clave"], "codigo_reservas")

    def test_describir_sigue_si_un_listado_no_carga(self):
        vehic = "CODIGO VEHICULOS;Matr&iacutecula\r0013;1234ABC\r".encode("latin-1")
        conectar = duckdb.connect

        def falla_al_escribir(*args, **kwargs):
            if not kwargs.get("read_only"):
                raise duckdb.InvalidInputException("CSV Error on Line: 2\n0013;1234ABC")
            return conectar(*args, **kwargs)

        with mock.patch.object(cliente, "descargar", return_value=(vehic, "latin-1")):
            with mock.patch.object(almacen.duckdb, "connect", falla_al_escribir):
                res = herramientas.describir_tablas(self.ctx, ["vehiculos", "categorias"])
        self.assertIn("vehiculos", res["vehiculos"]["error"])
        self.assertNotIn("1234ABC", json.dumps(res))
        self.assertEqual(res["categorias"]["clave"], "codigo_categorias")

    def test_ayuda(self):
        res = ayuda.buscar("cómo inmovilizo un coche para la ITV")
        self.assertTrue(res)
        self.assertIn("I-PASAR ITV", " ".join(r["texto"] for r in res))


class AccionesTests(Base):
    def test_propuesta_y_confirmacion_honesta(self):
        res = herramientas.proponer_accion(self.ctx, "anular_reserva", {"reserva": "004286", "motivo": "cliente cancela"})
        self.assertIn("NO está hecho", res["nota"])
        a = AccionPropuesta.objects.get(pk=res["propuesta_id"])
        a = acciones.resolver(a, self.u, confirmar=True)
        # Sin API de escritura nunca se marca como hecha.
        self.assertEqual(a.estado, AccionPropuesta.Estado.FALLIDA)

    def test_partner_no_puede_proponer(self):
        self.u.rol = Usuario.Rol.PARTNER
        self.u.save()
        res = herramientas.proponer_accion(self.ctx, "anular_reserva", {"reserva": "1", "motivo": "x"})
        self.assertIn("error", res)

    def test_parametros_obligatorios(self):
        res = herramientas.proponer_accion(self.ctx, "registrar_cobro", {"reserva": "004286"})
        self.assertIn("Faltan", res["error"])

    def test_no_se_resuelve_dos_veces(self):
        a = acciones.proponer(self.c, self.u, "anular_reserva", {"reserva": "1", "motivo": "x"})
        acciones.resolver(a, self.u, confirmar=False)
        with self.assertRaises(ValueError):
            acciones.resolver(a, self.u, confirmar=True)

    # --- escritura en Webcar: las tres puertas y la regla de no simular éxito ---

    ESCRITURA_ABIERTA = {
        "WEBCAR_ESCRITURA": True,
        "WEBCAR_ESCRITURA_RENTACARS": ["test"],
        "WEBCAR_ESCRITURA_ACCIONES": ["anular_reserva"],
    }

    def _confirmar_anulacion(self):
        a = acciones.proponer(self.c, self.u, "anular_reserva", {"reserva": "004286", "motivo": "cliente cancela"})
        return acciones.resolver(a, self.u, confirmar=True)

    def test_escritura_desactivada_no_llama_a_webcar(self):
        self.r.oper_webcar, self.r.password_webcar = "046", "secreta"
        self.r.save()
        cerradas = [
            {**self.ESCRITURA_ABIERTA, "WEBCAR_ESCRITURA": False},
            {**self.ESCRITURA_ABIERTA, "WEBCAR_ESCRITURA_RENTACARS": ["demo"]},
            {**self.ESCRITURA_ABIERTA, "WEBCAR_ESCRITURA_ACCIONES": ["crear_reserva"]},
        ]
        for puertas in cerradas:
            with self.settings(**puertas), mock.patch.object(escritura, "urlopen") as red:
                a = self._confirmar_anulacion()
            self.assertEqual(a.estado, AccionPropuesta.Estado.FALLIDA)
            self.assertIn("Escritura desactivada", a.resultado)
            red.assert_not_called()

    def test_confirmada_solo_si_webcar_confirma(self):
        self.r.oper_webcar, self.r.password_webcar = "046", "secreta"
        self.r.save()
        with self.settings(**self.ESCRITURA_ABIERTA):
            with mock.patch.object(escritura, "anular_reserva", return_value="Reserva 004286 anulada en Webcar.") as anular:
                a = self._confirmar_anulacion()
            self.assertEqual(a.estado, AccionPropuesta.Estado.CONFIRMADA)
            self.assertEqual(a.resultado, "Reserva 004286 anulada en Webcar.")
            self.assertEqual(anular.call_args.args[1], {"reserva": "004286", "motivo": "cliente cancela"})
            self.assertEqual(anular.call_args.args[0].oper, "046")
            # El listado de reservas se vuelve a descargar en la siguiente consulta.
            self.assertTrue(almacen.caducado(self.r, "reservas"))
            self.assertFalse(almacen.caducado(self.r, "clientes"))

            fallo = cliente.WebcarError("Webcar no ha anulado la reserva 004286: sigue activa después de guardar.")
            with mock.patch.object(escritura, "anular_reserva", side_effect=fallo):
                a = self._confirmar_anulacion()
            self.assertEqual(a.estado, AccionPropuesta.Estado.FALLIDA)
            self.assertIn("sigue activa", a.resultado)

    def test_sin_credenciales_de_webcar_queda_fallida(self):
        with self.settings(**self.ESCRITURA_ABIERTA), mock.patch.object(escritura, "urlopen") as red:
            a = self._confirmar_anulacion()
        self.assertEqual(a.estado, AccionPropuesta.Estado.FALLIDA)
        self.assertIn("usuario y contraseña de Webcar", a.resultado)
        red.assert_not_called()

    def test_acciones_sin_ejecutor_siguen_sin_ejecutarse(self):
        with self.settings(**{**self.ESCRITURA_ABIERTA, "WEBCAR_ESCRITURA_ACCIONES": []}):
            a = acciones.proponer(self.c, self.u, "asignar_matricula", {"reserva": "004286", "matricula": "0013"})
            a = acciones.resolver(a, self.u, confirmar=True)
        self.assertEqual(a.estado, AccionPropuesta.Estado.FALLIDA)
        self.assertIn("todavía no ofrece", a.resultado)


class AgenteTests(Base):
    def test_bucle_con_herramienta(self):
        falso = ClienteFalso([
            (None, [_llamada("consultar_datos", {"sql": "select count(*) from reservas"})]),
            ("Hay 3 reservas.", None),
        ])
        final = agente.responder(self.c, self.u, "¿Cuántas reservas hay?", client=falso)
        self.assertEqual(final.contenido, "Hay 3 reservas.")
        roles = list(self.c.mensajes.values_list("rol", flat=True))
        self.assertEqual(roles, ["user", "assistant", "tool", "assistant"])
        herramienta = self.c.mensajes.get(rol="tool")
        self.assertIn("[[3]]", herramienta.contenido.replace(" ", ""))
        # El segundo turno lleva al modelo el resultado de la herramienta.
        self.assertEqual(falso.peticiones[1]["messages"][-1]["role"], "tool")

    def test_limite_de_pasos(self):
        with self.settings(AGENTE_MAX_PASOS=2):
            falso = ClienteFalso([(None, [_llamada("buscar_ayuda", {"consulta": "x"}, f"c{i}")]) for i in range(2)])
            final = agente.responder(self.c, self.u, "bucle", client=falso)
        self.assertIn("No he podido terminar", final.contenido)


class VistasTests(Base):
    def test_aislamiento_entre_usuarios(self):
        otro = Usuario.objects.create_user("eve", password="x", rentacar=self.r)
        self.client.force_login(otro)
        r = self.client.get(reverse("chat:conversacion", args=[self.c.pk]))
        self.assertEqual(r.status_code, 404)

    def test_pagina_conversacion(self):
        self.client.force_login(self.u)
        r = self.client.get(reverse("chat:conversacion", args=[self.c.pk]))
        self.assertEqual(r.status_code, 200)

    def test_borrar_conversacion(self):
        Mensaje.objects.create(conversacion=self.c, rol="user", contenido="hola")
        acciones.proponer(self.c, self.u, "anular_reserva", {"reserva": "004286", "motivo": "cliente"})
        self.client.force_login(self.u)
        self.assertEqual(self.client.get(reverse("chat:borrar", args=[self.c.pk])).status_code, 405)
        r = self.client.post(reverse("chat:borrar", args=[self.c.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Conversacion.objects.filter(pk=self.c.pk).exists())
        self.assertFalse(Mensaje.objects.exists())
        self.assertFalse(AccionPropuesta.objects.exists())

    def test_no_se_borra_la_de_otro(self):
        otro = Usuario.objects.create_user("eve", password="x", rentacar=self.r)
        self.client.force_login(otro)
        r = self.client.post(reverse("chat:borrar", args=[self.c.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Conversacion.objects.filter(pk=self.c.pk).exists())

    def test_inicio_y_lateral(self):
        self.c.titulo = "Coches de mañana"
        self.c.save()
        self.client.force_login(self.u)
        r = self.client.get(reverse("chat:inicio"))
        self.assertContains(r, "Coches de mañana")
        self.assertContains(r, reverse("chat:borrar", args=[self.c.pk]))
