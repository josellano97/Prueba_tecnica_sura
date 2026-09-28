"""
Formularios de autenticación y administración.

Regla anti-escalamiento: un administrador que no es superusuario solo puede otorgar (por rol o
directamente) permisos que él mismo tiene. Así nadie puede darse más acceso del que ya tiene.
"""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password

from apps.tablero.models import Coordinador

from .roles import PERMISOS_ASIGNABLES, filtro_permisos, nombre_completo

Usuario = get_user_model()
DESCRIPCIONES = {p: d for _, p, d in PERMISOS_ASIGNABLES}


class FormularioLogin(AuthenticationForm):
    """Login nativo de Django con mensajes en español y atributos de accesibilidad."""

    error_messages = {
        "invalid_login": "Usuario o contraseña incorrectos. Verifique e intente de nuevo.",
        "inactive": "Esta cuenta está desactivada. Contacte al administrador.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"autocomplete": "username", "autofocus": True})
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})
        self.fields["username"].label = "Usuario"


class CasillasPermisos(forms.CheckboxSelectMultiple):
    """Muestra cada permiso con su descripción de negocio en lugar del nombre técnico."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcion = super().create_option(name, value, label, selected, index, subindex, attrs)
        permiso = getattr(value, "instance", None)
        if permiso is not None:
            opcion["label"] = DESCRIPCIONES.get(nombre_completo(permiso), str(permiso))
        return opcion


def _permisos_de(objetos) -> set[str]:
    return {nombre_completo(p) for p in objetos}


class _ControlEscalamiento:
    """Mezcla: valida que el editor tenga todos los permisos que intenta otorgar."""

    def _validar_otorgables(self, permisos: set[str]):
        editor = self.editor
        if editor.is_superuser:
            return
        ajenos = sorted(p for p in permisos if not editor.has_perm(p))
        if ajenos:
            raise forms.ValidationError(
                "No puede otorgar permisos que usted no tiene: " + ", ".join(DESCRIPCIONES.get(p, p) for p in ajenos))


class UsuarioForm(_ControlEscalamiento, forms.ModelForm):
    roles = forms.ModelMultipleChoiceField(queryset=Group.objects.order_by("name"), required=False,
                                           widget=forms.CheckboxSelectMultiple, label="Roles")
    permisos = forms.ModelMultipleChoiceField(queryset=Permission.objects.none(), required=False,
                                              widget=CasillasPermisos, label="Permisos adicionales",
                                              help_text="Opcional: permisos puntuales además de los del rol.")
    coordinador = forms.ModelChoiceField(queryset=Coordinador.objects.filter(activo=True), required=False,
                                         label="Coordinador asociado",
                                         help_text="Si el usuario no puede ver todos los clientes, verá solo los de este coordinador.")
    cargo = forms.CharField(max_length=120, required=False)
    contrasena1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                  required=False, strip=False)
    contrasena2 = forms.CharField(label="Confirmar contraseña", required=False, strip=False,
                                  widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = Usuario
        fields = ["username", "first_name", "last_name", "email", "is_active", "is_staff"]
        labels = {"username": "Usuario", "first_name": "Nombres", "last_name": "Apellidos", "email": "Correo",
                  "is_active": "Activo", "is_staff": "Acceso al panel de administración de Django"}
        help_texts = {"username": "Letras, números y @ . + - _ (máximo 150).",
                      "is_active": "Un usuario inactivo no puede iniciar sesión (se conserva su historial)."}

    def __init__(self, *args, editor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        self.es_nuevo = self.instance.pk is None
        self.fields["permisos"].queryset = filtro_permisos(Permission).select_related("content_type").order_by("content_type__app_label", "codename")
        self.fields["email"].required = True
        if not editor.is_superuser:
            del self.fields["is_staff"]          # solo un superusuario da acceso al admin de Django
        if self.es_nuevo:
            self.fields["contrasena1"].required = self.fields["contrasena2"].required = True
        else:
            self.fields["contrasena1"].label = "Nueva contraseña"
            self.fields["contrasena1"].help_text = "Déjela en blanco para no cambiarla."
            perfil = getattr(self.instance, "perfil", None)
            self.initial.update({"roles": self.instance.groups.all(),
                                 "permisos": self.instance.user_permissions.all(),
                                 "coordinador": perfil.coordinador if perfil else None,
                                 "cargo": perfil.cargo if perfil else ""})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if Usuario.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe un usuario con este correo.")
        return email

    def clean_is_active(self):
        activo = self.cleaned_data.get("is_active")
        if not self.es_nuevo and self.instance.pk == self.editor.pk and not activo:
            raise forms.ValidationError("No puede desactivar su propia cuenta.")
        return activo

    def clean(self):
        datos = super().clean()
        c1, c2 = datos.get("contrasena1"), datos.get("contrasena2")
        if c1 or c2:
            if c1 != c2:
                self.add_error("contrasena2", "Las contraseñas no coinciden.")
            else:
                try:
                    usuario_tmp = self.instance
                    for campo in ("username", "first_name", "last_name", "email"):
                        if datos.get(campo):
                            setattr(usuario_tmp, campo, datos[campo])
                    validate_password(c1, usuario_tmp)
                except forms.ValidationError as e:
                    self.add_error("contrasena1", e)
        otorgados = _permisos_de(datos.get("permisos") or [])
        for g in datos.get("roles") or []:
            otorgados |= _permisos_de(g.permissions.select_related("content_type"))
        actuales = set()
        if not self.es_nuevo:                    # solo se valida lo que se está agregando
            actuales = _permisos_de(self.instance.user_permissions.select_related("content_type"))
            for g in self.instance.groups.all():
                actuales |= _permisos_de(g.permissions.select_related("content_type"))
        try:
            self._validar_otorgables(otorgados - actuales)
        except forms.ValidationError as e:
            self.add_error(None, e)
        return datos

    def save(self, commit=True):
        usuario = super().save(commit=False)
        if self.cleaned_data.get("contrasena1"):
            usuario.set_password(self.cleaned_data["contrasena1"])
        usuario.save()
        usuario.groups.set(self.cleaned_data["roles"])
        # se conservan permisos directos no asignables desde aquí (p. ej. puestos desde el admin)
        no_gestionados = usuario.user_permissions.exclude(pk__in=self.fields["permisos"].queryset)
        usuario.user_permissions.set(list(no_gestionados) + list(self.cleaned_data["permisos"]))
        perfil = usuario.perfil
        perfil.coordinador = self.cleaned_data.get("coordinador")
        perfil.cargo = self.cleaned_data.get("cargo", "")
        perfil.save()
        return usuario


class RolForm(_ControlEscalamiento, forms.ModelForm):
    permisos = forms.ModelMultipleChoiceField(queryset=Permission.objects.none(), required=False,
                                              widget=CasillasPermisos, label="Permisos del rol")

    class Meta:
        model = Group
        fields = ["name"]
        labels = {"name": "Nombre del rol"}

    def __init__(self, *args, editor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        self.fields["permisos"].queryset = filtro_permisos(Permission).select_related("content_type").order_by("content_type__app_label", "codename")
        if self.instance.pk:
            self.initial["permisos"] = self.instance.permissions.all()

    def clean(self):
        datos = super().clean()
        try:
            actuales = _permisos_de(self.instance.permissions.select_related("content_type")) if self.instance.pk else set()
            self._validar_otorgables(_permisos_de(datos.get("permisos") or []) - actuales)
        except forms.ValidationError as e:
            self.add_error("permisos", e)
        return datos

    def save(self, commit=True):
        rol = super().save()
        no_gestionados = rol.permissions.exclude(pk__in=self.fields["permisos"].queryset)
        rol.permissions.set(list(no_gestionados) + list(self.cleaned_data["permisos"]))
        return rol
