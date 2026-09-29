from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.urls import reverse

from .models import LeistinasEmail, Teacher, Vadovas


ATMETIMO_ZINUTE = (
    "Su adresu {email} prisijungti negalima – jis nėra įtrauktas į mokyklos sąrašą. "
    "Prieigą suteikia Herojaus administracija, kreipkitės gimnazija@herojus.lt"
)


# keturi keliai patekti i sistema: baltasis sarasas, mokytojo ar vadovo adresas
# arba admino paskyra (kad neuzsirakintume patys)
def ar_leidziamas_email(email):
    email = (email or "").strip().lower()
    if not email:
        return False

    if LeistinasEmail.objects.filter(email__iexact=email).exists():
        return True

    if Teacher.objects.filter(email__iexact=email).exists():
        return True

    if Vadovas.objects.filter(email__iexact=email).exists():
        return True

    if User.objects.filter(email__iexact=email, is_staff=True).exists():
        return True

    return False


class BaltojoSarasoAdapter(DefaultSocialAccountAdapter):

    # allauth iskviecia si metoda po to, kai Google patvirtina tapatybe,
    # bet dar pries prijungiant vartotoja - patogiausia vieta sustabdyti
    def pre_social_login(self, request, sociallogin):
        email = sociallogin.user.email
        if not email:
            email = sociallogin.account.extra_data.get("email", "")

        if ar_leidziamas_email(email):
            return

        messages.error(request, ATMETIMO_ZINUTE.format(email=email or "šiuo adresu"))
        raise ImmediateHttpResponse(redirect(reverse("account_login")))
