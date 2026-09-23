from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _


class SignupForm(UserCreationForm):
    """
    Igual que el registro estandar de Django, pero pidiendo tambien el email
    (requerido) para que la recuperacion de contraseña tenga a donde enviar
    el link de reseteo.
    """
    email = forms.EmailField(required=True, help_text=_("Necesario para poder recuperar tu contraseña."))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user
