import uuid

from django.conf import settings
from django.db import models


class Conversacion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversaciones")
    rentacar = models.ForeignKey("webcar.Rentacar", on_delete=models.CASCADE, related_name="conversaciones")
    titulo = models.CharField(max_length=120, blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-actualizada"]

    def __str__(self):
        return self.titulo or f"Conversación {self.creada:%d-%m-%Y %H:%M}"


class Mensaje(models.Model):
    """Un mensaje del historial en el formato de la API (role + content/tool_calls).

    Se guarda tal cual se manda al modelo para poder reconstruir el contexto.
    Los mensajes `tool` y los del asistente con `tool_calls` no se pintan en la
    UI salvo como traza plegada.
    """

    class Rol(models.TextChoices):
        USUARIO = "user"
        ASISTENTE = "assistant"
        HERRAMIENTA = "tool"

    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name="mensajes")
    rol = models.CharField(max_length=10, choices=Rol.choices)
    contenido = models.TextField(blank=True)
    tool_calls = models.JSONField(null=True, blank=True)
    tool_call_id = models.CharField(max_length=80, blank=True)
    nombre_herramienta = models.CharField(max_length=60, blank=True)
    tokens_entrada = models.PositiveIntegerField(default=0)
    tokens_salida = models.PositiveIntegerField(default=0)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["creado", "id"]

    def para_api(self):
        m = {"role": self.rol, "content": self.contenido or ""}
        if self.rol == self.Rol.ASISTENTE and self.tool_calls:
            m["tool_calls"] = self.tool_calls
            if not self.contenido:
                m["content"] = None
        if self.rol == self.Rol.HERRAMIENTA:
            m["tool_call_id"] = self.tool_call_id
        return m


class AccionPropuesta(models.Model):
    """Un cambio que el agente quiere hacer en Webcar.

    El agente NUNCA ejecuta: crea la propuesta y el usuario la confirma o la
    rechaza desde la UI. Solo entonces `chat/acciones.py` llama a Webcar.
    """

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente"
        CONFIRMADA = "confirmada"  # confirmada y ejecutada con éxito
        RECHAZADA = "rechazada"
        FALLIDA = "fallida"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name="acciones")
    tipo = models.CharField(max_length=40)
    parametros = models.JSONField(default=dict)
    resumen = models.TextField(help_text="Lo que se le enseña al usuario para confirmar.")
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)
    resultado = models.TextField(blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    resuelta = models.DateTimeField(null=True, blank=True)
    resuelta_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-creada"]

    def __str__(self):
        return f"{self.tipo} ({self.estado})"
