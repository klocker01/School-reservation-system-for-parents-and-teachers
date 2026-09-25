import csv
import io

from .models import Teacher


# antrasciu variantai, kuriuos atpazistame stulpeliuose
VARDO_ANTRASTES = ("vardas", "first name", "firstname", "name")
PAVARDES_ANTRASTES = ("pavarde", "pavardė", "last name", "lastname", "surname")
EMAIL_ANTRASTES = ("el. paštas", "el.paštas", "el pastas", "paštas", "pastas", "email", "e-mail")


def _svarus(reiksme):
    if reiksme is None:
        return ""
    return str(reiksme).strip()


# is pirmos eilutes bandome suprasti, kuriame stulpelyje kas guli.
# Jei antrasciu nera, imame tris pirmus netuscius stulpelius is eiles
def rasti_stulpelius(eilute):
    zemelapis = {}
    for i, langelis in enumerate(eilute):
        tekstas = _svarus(langelis).lower()
        if not tekstas:
            continue
        if tekstas in VARDO_ANTRASTES and "vardas" not in zemelapis:
            zemelapis["vardas"] = i
        elif tekstas in PAVARDES_ANTRASTES and "pavarde" not in zemelapis:
            zemelapis["pavarde"] = i
        elif tekstas in EMAIL_ANTRASTES and "email" not in zemelapis:
            zemelapis["email"] = i

    if len(zemelapis) == 3:
        return zemelapis
    return None


def _eilutes_is_failo(failas, vardas):
    """Grazina eiluciu sarasa - kiekviena eilute yra langeliu sarasas."""
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
    lapas = knyga.active
    return [list(eil) for eil in lapas.iter_rows(values_only=True)]


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
    else:
        # antrasciu neradome - imame numatyta tvarka ir skaitome nuo pirmos eilutes
        zemelapis = {"vardas": 0, "pavarde": 1, "email": 2}
        duomenu_eilutes = eilutes

    # jei pirmas stulpelis yra eiles numeris, viska pastumiam per viena
    if duomenu_eilutes:
        pirmas = _svarus(duomenu_eilutes[0][0]) if duomenu_eilutes[0] else ""
        if pirmas.isdigit() and zemelapis == {"vardas": 0, "pavarde": 1, "email": 2}:
            zemelapis = {"vardas": 1, "pavarde": 2, "email": 3}

    for nr, eilute in enumerate(duomenu_eilutes, start=2):
        if not eilute:
            continue

        try:
            vardas = _svarus(eilute[zemelapis["vardas"]])
            pavarde = _svarus(eilute[zemelapis["pavarde"]])
            email = _svarus(eilute[zemelapis["email"]]).lower()
        except IndexError:
            ataskaita["praleista"] += 1
            continue

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
