from django.core.management.base import BaseCommand, CommandError

from webcar import almacen, esquema
from webcar.cliente import WebcarError
from webcar.models import Rentacar


class Command(BaseCommand):
    help = "Descarga de Webcar los listados de un rentacar (todos o los indicados) y los carga en DuckDB."

    def add_arguments(self, parser):
        parser.add_argument("codigo", help="Código Webcar del rentacar (p. ej. demo)")
        parser.add_argument("tablas", nargs="*", help=f"Tablas. Por defecto todas: {', '.join(esquema.POR_TABLA)}")
        parser.add_argument("--crear", metavar="NOMBRE", help="Crea el rentacar si no existe, con este nombre")

    def handle(self, codigo, tablas, crear=None, **_):
        r = Rentacar.objects.filter(codigo=codigo).first()
        if not r:
            if not crear:
                raise CommandError(f"No existe el rentacar {codigo}. Usa --crear 'Nombre'.")
            r = Rentacar.objects.create(codigo=codigo, nombre=crear)
        fallos = 0
        for tabla in tablas or list(esquema.POR_TABLA):
            try:
                n = almacen.cargar_listado(r, tabla)
                self.stdout.write(f"{tabla:18} {n:>7} filas")
            except (WebcarError, KeyError) as exc:
                fallos += 1
                self.stderr.write(f"{tabla:18} ERROR: {exc}")
        if fallos:
            raise CommandError(f"{fallos} listados con error")
