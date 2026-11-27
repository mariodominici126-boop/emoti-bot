"""Actividades guiadas, locales y deterministas."""
from .base import Actividad, Paso
from .ordenar_ideas import OrdenarIdeas
from .respiracion import Respiracion

__all__ = ["Actividad", "OrdenarIdeas", "Paso", "Respiracion"]

CATALOGO = {
    Respiracion.nombre: Respiracion,
    OrdenarIdeas.nombre: OrdenarIdeas,
}
