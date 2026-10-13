import csv
import io
import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .models import Teacher, LeistinasEmail


# antrasciu pradzios, kurias atpazistame stulpeliuose. Lyginama pagal
# pradzia, kad tiktu ir "El. pašto adresas", "Pavardės" ir pan.
VARDO_ANTRASTES = ("vard", "first name", "firstname", "name")
PAVARDES_ANTRASTES = ("pavard", "last name", "lastname", "surname")
# ne "past", kad nepagautu stulpelio "Pastabos"
EMAIL_ANTRASTES = ("el. pa", "el.pa", "el pa", "e. pa", "paštas", "pastas", "pašto", "pasto", "email", "e-mail")


def _svarus(reiksme):
    if reiksme is None:
        return ""
    # Excel skaicius atiduoda kaip float - 1.0 paverciam i "1"
    if isinstance(reiksme, float) and reiksme.is_integer():
        reiksme = int(reiksme)
    return str(reiksme).strip()


def _langelis(eilute, i):
    # openpyxl tuscias eilutes kartais grazina trumpesnes
    return _svarus(eilute[i]) if i < len(eilute) else ""


# is pirmos eilutes bandome suprasti, kuriame stulpelyje kas guli.
# Jei antrasciu nera, imame tris pirmus netuscius stulpelius is eiles
def rasti_stulpelius(eilute):
    zemelapis = {}
    for i, langelis in enumerate(eilute):
        tekstas = _svarus(langelis).lower()
        if not tekstas:
            continue
        if tekstas.startswith(PAVARDES_ANTRASTES) and "pavarde" not in zemelapis:
            zemelapis["pavarde"] = i
        elif tekstas.startswith(VARDO_ANTRASTES) and "vardas" not in zemelapis:
            zemelapis["vardas"] = i
        elif tekstas.startswith(EMAIL_ANTRASTES) and "email" not in zemelapis:
            zemelapis["email"] = i

    if len(zemelapis) == 3:
        return zemelapis
    return None


def _eilutes_is_failo(failas, vardas, visi_lapai=False):
    """Grazina eiluciu sarasa - kiekviena eilute yra langeliu sarasas.
    visi_lapai=True - Excel faile skaitomi visi lapai, ne tik aktyvus."""
    vardas = (vardas or "").lower()

    if vardas.endswith(".csv"):
        turinys = failas.read()
        if isinstance(turinys, bytes):
            turinys = turinys.decode("utf-8-sig", errors="replace")
        # bandome atspeti skirtuka - lietuviskame Excel dazniausiai kabliataskis
        try:
            skirtukas = csv.Sniffer().sniff(turinys[:1000], delimiters=",;\t").delimiter
        except csv.Error:
            skirtukas = ","
        return [eil for eil in csv.reader(io.StringIO(turinys), delimiter=skirtukas)]

    # xlsx
    import openpyxl

    knyga = openpyxl.load_workbook(failas, read_only=True, data_only=True)
    lapai = knyga.worksheets if visi_lapai else [knyga.active]
    eilutes = []
    for lapas in lapai:
        eilutes.extend(list(eil) for eil in lapas.iter_rows(values_only=True))
    return eilutes


def importuoti_mokytojus(failas, failo_vardas):
    """Perskaito faila ir sukuria arba atnaujina mokytojus pagal el. pasta.

    Grazina zodyna su suvestine: sukurta, atnaujinta, praleista, klaidos.
    Dalykai, klases ir kabinetai neliecami - jie tvarkomi rankomis."""

    ataskaita = {"sukurta": 0, "atnaujinta": 0, "praleista": 0, "klaidos": []}

    try:
        eilutes = _eilutes_is_failo(failas, failo_vardas)
    except Exception as e:
        ataskaita["klaidos"].append(f"Failo nepavyko perskaityti: {e}")
        return ataskaita

    if not eilutes:
        ataskaita["klaidos"].append("Failas tuščias")
        return ataskaita

    zemelapis = rasti_stulpelius(eilutes[0])
    if zemelapis:
        duomenu_eilutes = eilutes[1:]
        pirma_eilute = 2
    else:
        # antrasciu neradome - imame numatyta tvarka ir skaitome nuo pirmos eilutes
        zemelapis = {"vardas": 0, "pavarde": 1, "email": 2}
        duomenu_eilutes = eilutes
        pirma_eilute = 1

    # jei pirmas stulpelis yra eiles numeris, viska pastumiam per viena
    if duomenu_eilutes:
        pirmas = _langelis(duomenu_eilutes[0], 0)
        if pirmas.isdigit() and zemelapis == {"vardas": 0, "pavarde": 1, "email": 2}:
            zemelapis = {"vardas": 1, "pavarde": 2, "email": 3}

    for nr, eilute in enumerate(duomenu_eilutes, start=pirma_eilute):
        if not eilute:
            continue

        vardas = _langelis(eilute, zemelapis["vardas"])
        pavarde = _langelis(eilute, zemelapis["pavarde"])
        email = _langelis(eilute, zemelapis["email"]).lower()

        # visiskai tuscia eilute - tyliai praleidziam
        if not vardas and not pavarde and not email:
            continue

        if not email:
            ataskaita["klaidos"].append(f"{nr} eilutė: nėra el. pašto ({vardas} {pavarde})")
            ataskaita["praleista"] += 1
            continue

        if "@" not in email:
            ataskaita["klaidos"].append(f"{nr} eilutė: netinkamas el. paštas „{email}“")
            ataskaita["praleista"] += 1
            continue

        if not vardas or not pavarde:
            ataskaita["klaidos"].append(f"{nr} eilutė: trūksta vardo arba pavardės ({email})")
            ataskaita["praleista"] += 1
            continue

        esamas = Teacher.objects.filter(email__iexact=email).first()

        if esamas:
            if esamas.vardas != vardas or esamas.pavarde != pavarde:
                esamas.vardas = vardas
                esamas.pavarde = pavarde
                esamas.save()
                ataskaita["atnaujinta"] += 1
            else:
                ataskaita["praleista"] += 1
        else:
            Teacher.objects.create(vardas=vardas, pavarde=pavarde, email=email)
            ataskaita["sukurta"] += 1

    return ataskaita


# viename langelyje gali buti ir daugiau teksto ("Jonas <jonas@gmail.com>")
# ar keli adresai per kabliataski - is visur istraukiam tik pacius adresus
EMAIL_RASTI = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def importuoti_tevu_emailus(failas, failo_vardas):
    """Is failo istraukia tik el. pasto adresus (vardai, klases ir kiti
    stulpeliai ignoruojami) ir prideda juos i tevu baltaji sarasa.

    Adresai lyginami mazosiomis raidemis, tai tas pats adresas faile keliskart
    ar jau esantis sarase antra karta nepridedamas."""

    ataskaita = {"prideta": 0, "jau_buvo": 0, "pasikartojo": 0, "klaidos": []}

    try:
        eilutes = _eilutes_is_failo(failas, failo_vardas, visi_lapai=True)
    except Exception as e:
        ataskaita["klaidos"].append(f"Failo nepavyko perskaityti: {e}")
        return ataskaita

    rasti = []
    matyti = set()
    for eilute in eilutes:
        for langelis in eilute or []:
            tekstas = _svarus(langelis)
            if "@" not in tekstas:
                continue
            for email in EMAIL_RASTI.findall(tekstas):
                email = email.strip(".").lower()
                try:
                    validate_email(email)
                except ValidationError:
                    ataskaita["klaidos"].append(f"Netinkamas el. paštas „{email}“")
                    continue
                if email in matyti:
                    ataskaita["pasikartojo"] += 1
                    continue
                matyti.add(email)
                rasti.append(email)

    if not rasti:
        ataskaita["klaidos"].append("Faile nerasta nė vieno el. pašto adreso")
        return ataskaita

    esami = {e.lower() for e in LeistinasEmail.objects.values_list("email", flat=True)}
    nauji = [e for e in rasti if e not in esami]
    ataskaita["jau_buvo"] = len(rasti) - len(nauji)

    # ignore_conflicts - jei tuo pat metu kas nors prideda ta pati adresa
    LeistinasEmail.objects.bulk_create(
        [LeistinasEmail(email=e) for e in nauji],
        ignore_conflicts=True,
    )
    ataskaita["prideta"] = len(nauji)

    return ataskaita
