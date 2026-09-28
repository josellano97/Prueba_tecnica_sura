"""Validación de los filtros del tablero: ningún parámetro de la URL llega sin validar a la consulta."""
from datetime import date

from django import forms

from .models import Coordinador, Sector
from .servicios.indicadores import CLASES, Filtros, clientes_visibles, etiqueta_larga, periodos_disponibles


class FiltroTableroForm(forms.Form):
    mes = forms.ChoiceField(required=False)
    coordinador = forms.ModelChoiceField(queryset=Coordinador.objects.none(), required=False)
    sector = forms.ModelChoiceField(queryset=Sector.objects.none(), required=False)
    clase = forms.TypedMultipleChoiceField(choices=[(c, c) for c in CLASES], coerce=int, required=False)

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.periodos = periodos_disponibles()
        self.fields["mes"].choices = [(p.isoformat()[:7], etiqueta_larga(p)) for p in self.periodos]
        # Solo se puede filtrar por coordinadores y sectores dentro del alcance del usuario.
        visibles = clientes_visibles(usuario)
        self.fields["coordinador"].queryset = Coordinador.objects.filter(clientes__in=visibles).distinct()
        self.fields["sector"].queryset = Sector.objects.filter(clientes__in=visibles).distinct()

    def filtros(self) -> Filtros:
        d = self.cleaned_data
        mes = date.fromisoformat(d["mes"] + "-01") if d.get("mes") else self.periodos[-1]
        return Filtros(
            mes=mes,
            coordinador_id=d["coordinador"].id if d.get("coordinador") else None,
            sector_id=d["sector"].id if d.get("sector") else None,
            clases=sorted(d["clase"]) if d.get("clase") else list(CLASES),
        )
