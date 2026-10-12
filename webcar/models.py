from django.db import models


class Rentacar(models.Model):
    """Una empresa cliente de Webcar Lite.

    `codigo` es la «ruta» de Webcar (en la demo, «demo»): con él se piden sus
    listados. Cada rentacar tiene su propio fichero DuckDB y nadie ve los datos
    de otro.
    """

    codigo = models.CharField(
        "código Webcar",
        max_length=40,
        unique=True,
        help_text="El parámetro «ruta» de Webcar. Por ejemplo: demo",
    )
    nombre = models.CharField(max_length=120)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"


class Descarga(models.Model):
    """Última descarga de cada listado de un rentacar (para la caducidad)."""

    rentacar = models.ForeignKey(Rentacar, on_delete=models.CASCADE, related_name="descargas")
    listado = models.CharField(max_length=40)
    filas = models.PositiveIntegerField(default=0)
    bytes = models.PositiveIntegerField(default=0)
    descargado = models.DateTimeField()

    class Meta:
        unique_together = [("rentacar", "listado")]

    def __str__(self):
        return f"{self.rentacar.codigo}/{self.listado} @ {self.descargado:%d-%m %H:%M}"
