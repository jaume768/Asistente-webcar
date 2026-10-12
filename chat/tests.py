import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from django.test import TestCase, override_settings
from django.urls import reverse

from chat import acciones, agente, ayuda, herramientas
from chat.models import AccionPropuesta, Conversacion, Mensaje
from cuentas.models import Usuario
from webcar import almacen, cliente
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
        self.override = override_settings(DATOS_DIR=Path(self.tmp.name))
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
