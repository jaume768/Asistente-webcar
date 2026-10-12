from django import forms
from django.contrib import admin

from .models import Descarga, Rentacar


class DescargaInline(admin.TabularInline):
    model = Descarga
    extra = 0
    readonly_fields = ("listado", "filas", "bytes", "descargado")
    can_delete = False


class RentacarForm(forms.ModelForm):
    class Meta:
        model = Rentacar
        fields = "__all__"
        # Editable, pero sin enseñarla en pantalla.
        widgets = {"password_webcar": forms.PasswordInput(render_value=True)}


@admin.register(Rentacar)
class RentacarAdmin(admin.ModelAdmin):
    form = RentacarForm
    list_display = ("nombre", "codigo", "activo", "oper_webcar", "creado")
    search_fields = ("nombre", "codigo")
    fieldsets = [
        (None, {"fields": ["codigo", "nombre", "activo"]}),
        ("Escritura en Webcar", {
            "fields": ["oper_webcar", "password_webcar"],
            "description": "Usuario con el que se ejecutan los cambios confirmados. "
                           "Solo actúa si el .env lo permite (WEBCAR_ESCRITURA…).",
        }),
    ]
    inlines = [DescargaInline]
