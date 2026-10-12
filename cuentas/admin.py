from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "email", "rentacar", "rol", "is_active", "is_superuser")
    list_filter = ("rentacar", "rol", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("Webcar", {"fields": ("rentacar", "rol", "codigo_webcar")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Webcar", {"fields": ("rentacar", "rol", "codigo_webcar")}),
    )
