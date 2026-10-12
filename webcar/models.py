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
    # Usuario de Webcar con el que el asistente ejecuta los cambios confirmados
    # (docs/Escritura.md). TODO: cifrar la contraseña antes de un rentacar real.
    oper_webcar = models.CharField(
        "usuario de Webcar (oper)", max_length=10, blank=True, help_text="Número de usuario en Webcar. Por ejemplo: 046"
    )
    password_webcar = models.CharField(
        "contraseña de Webcar", max_length=128, blank=True, help_text="Se guarda en claro: solo para la DEMO."
    )
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
