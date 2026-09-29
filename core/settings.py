from pathlib import Path #Keliai
import os

BASE_DIR = Path(__file__).resolve().parent.parent #Kad leistu django rasti failus 

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

KEY_FAILAS = BASE_DIR / "secure_key.txt"
if KEY_FAILAS.exists():
    SECRET_KEY = KEY_FAILAS.read_text().strip()
elif DEBUG:
    SECRET_KEY = "tik-vietiniam-darbui-netinka-serveriui"
else:
    # serveryje be rakto nepasileidziam - kitaip sesijos butu pasirasytos viesu raktu
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("Nerastas secure_key.txt - serveryje jis butinas")

ALLOWED_HOSTS = ["registracija.herojus.lt",'localhost', '127.0.0.1']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',

    'crispy_forms',
    'reservations',
]

SITE_ID = 1

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"


ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_ALLOW_REGISTRATION = True  
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = True
ACCOUNT_LOGOUT_ON_GET = True
SOCIALACCOUNT_ONLY = True
ACCOUNT_PASSWORD_LOGIN = False #Patraukti ta nesamonia nereikalinga


SOCIALACCOUNT_ADAPTER = "reservations.adapters.BaltojoSarasoAdapter"

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"prompt": "select_account"},
    }
}


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', #Saugumui
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware', #Issaugoti prisijungimo busena
    'django.middleware.common.CommonMiddleware', 
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware', #Zinoti ar vartotas prisijunges, pvz user.is_authenticated views faile
    'allauth.account.middleware.AccountMiddleware',  
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'reservations.views.teacher_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            # skaitytojai nebelaukia kol baigsis rasymas
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            # jei baze uzimta, laukiam 20s vietoj 5
            "timeout": 20,
            # transakcija uzima rasymo teise is karto, ne viduryje darbo
            "transaction_mode": "IMMEDIATE",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [ #Cia nereikalinga projektui
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

LANGUAGE_CODE = 'lt'
TIME_ZONE = 'Europe/Vilnius'
USE_I18N = True
USE_TZ = True
FORMAT_MODULE_PATH = ['core.formats']
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'reservations/static'),
]
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- HTTPS ---
# Įjungiama tik tada, kai serveryje jau veikia sertifikatas.
# Kol dirbi lokaliai, DJANGO_HTTPS aplinkos kintamojo nėra ir viskas lieka išjungta.
HTTPS_ITAISYTA = os.environ.get("DJANGO_HTTPS") == "1"

if HTTPS_ITAISYTA:
    # nginx praneša Django, kad užklausa atėjo per https
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # visi http užklausimai peradresuojami į https
    SECURE_SSL_REDIRECT = True

    # slapukai keliauja tik šifruotu kanalu
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # be šito Django atmes POST formas su 403
    CSRF_TRUSTED_ORIGINS = ["https://registracija.herojus.lt"]

    # naršyklė pati eis per https kitą kartą (pradžioje trumpai, vėliau galima pailginti)
    SECURE_HSTS_SECONDS = 3600
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
