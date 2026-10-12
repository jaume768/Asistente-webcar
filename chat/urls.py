from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("nueva/", views.nueva, name="nueva"),
    path("c/<uuid:pk>/", views.conversacion, name="conversacion"),
    path("c/<uuid:pk>/mensaje/", views.mensaje, name="mensaje"),
    path("c/<uuid:pk>/borrar/", views.borrar, name="borrar"),
    path("accion/<uuid:pk>/<str:decision>/", views.resolver_accion, name="resolver_accion"),
]
