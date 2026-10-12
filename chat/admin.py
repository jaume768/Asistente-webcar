from django.contrib import admin

from .models import AccionPropuesta, Conversacion, Mensaje


class MensajeInline(admin.TabularInline):
    model = Mensaje
    extra = 0
    fields = ("rol", "nombre_herramienta", "contenido", "tokens_entrada", "tokens_salida", "creado")
    readonly_fields = fields
    can_delete = False


@admin.register(Conversacion)
class ConversacionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "usuario", "rentacar", "actualizada")
    list_filter = ("rentacar",)
    inlines = [MensajeInline]


@admin.register(AccionPropuesta)
class AccionPropuestaAdmin(admin.ModelAdmin):
    list_display = ("tipo", "resumen", "estado", "conversacion", "creada", "resuelta_por")
    list_filter = ("estado", "tipo")
    readonly_fields = [f.name for f in AccionPropuesta._meta.fields]
