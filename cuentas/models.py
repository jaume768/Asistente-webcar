from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Usuario(AbstractUser):
    """Usuario del asistente, siempre ligado a un rentacar.

    El rol replica los perfiles de Webcar y decide qué puede hacer el agente en
    su nombre: consultar siempre; proponer acciones solo admin y restringido;
    un partner solo ve sus propias reservas (pendiente, ver docs/PLAN.md).
    """

    class Rol(models.TextChoices):
        ADMIN = "A", "Administrador"
        RESTRINGIDO = "O", "Restringido"
        PARTNER = "P", "Partner (comercial)"

    rentacar = models.ForeignKey(
        "webcar.Rentacar",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="usuarios",
    )
    rol = models.CharField(max_length=1, choices=Rol.choices, default=Rol.RESTRINGIDO)
    codigo_webcar = models.CharField(
        "código de usuario en Webcar",
        max_length=10,
        blank=True,
        help_text="Su código U-xxx en Webcar (para filtrar sus reservas o tareas).",
    )

    acceso_todos_rentacars = models.BooleanField(
        "operador COR SOFT (ve todos los rentacars)",
        default=False,
        help_text="Permite consultar cualquier rentacar desde el chat. Solo para personal de COR SOFT.",
    )

    def clean(self):
        super().clean()
        # Un operador de COR SOFT puede no tener rentacar propio.
        if not self.is_superuser and not self.acceso_todos_rentacars and not self.rentacar_id:
            raise ValidationError({"rentacar": "Un usuario normal necesita un rentacar."})

    @property
    def puede_proponer_acciones(self):
        return self.is_superuser or self.acceso_todos_rentacars or self.rol in {self.Rol.ADMIN, self.Rol.RESTRINGIDO}
