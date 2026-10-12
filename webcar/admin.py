from django.contrib import admin

from .models import Descarga, Rentacar


class DescargaInline(admin.TabularInline):
    model = Descarga
    extra = 0
    readonly_fields = ("listado", "filas", "bytes", "descargado")
    can_delete = False


@admin.register(Rentacar)
class RentacarAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "activo", "creado")
    search_fields = ("nombre", "codigo")
    inlines = [DescargaInline]
