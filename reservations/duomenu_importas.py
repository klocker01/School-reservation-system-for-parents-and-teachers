import hashlib
import json
import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Exists, OuterRef

from .importas import _eilutes_is_failo, _langelis, _svarus
from .models import (
    Cabinet, Child, Klase, Reservation, Subject, Teacher, VadovoRezervacija, WorkingHours,
)
from .rusiavimas import raktas as lt_raktas


# Skiltis "Importuoti duomenys": pilnas mokytoju sarasas is mokyklos lenteles
# (vardas, pavarde, el. pastas, dalykai, kabinetas, aukletojama klase).
# Paprastas mokytoju ikelimas (tik vardas, pavarde, el. pastas) - importas.py


def _lapai_is_failo(failas, vardas):
    """[(lapo pavadinimas, eilutes), ...] - Excel faile visi lapai,
    CSV faile vienas lapas be pavadinimo."""
    if (vardas or "").lower().endswith(".csv"):
        return [("", _eilutes_is_failo(failas, vardas))]

    import openpyxl

    knyga = openpyxl.load_workbook(failas, read_only=True, data_only=True)
    try:
        return [
            (lapas.title, [list(eil) for eil in lapas.iter_rows(values_only=True)])
            for lapas in knyga.worksheets
        ]
    finally:
        knyga.close()


# Mokytoju sarasas keliamas tik tiksliai tokios formos, kaip mokyklos lenteleje.
# Pries "Vardas" gali buti vienas stulpelis (pvz. eiles numeris) - jis praleidziamas.
# Jei forma kitokia - nieko nekeiciam, kad neprirasytume nesamoniu
MOKYTOJU_STULPELIAI = ("Vardas", "Pavardė", "El. paštas", "Dalykas", "Kabinetas", "Auklėjama klasė")

# laukų ilgiai kaip modeliuose
ILGIAI = {"vardas": 50, "pavarde": 50, "email": 254, "dalykas": 100, "kabinetas": 50, "klase": 50}


# antrastes lyginam nekreipdami demesio i didziasias raides ir tarpus: "El.paštas" = "el. paštas"
def _antraste(reiksme):
    return "".join(_svarus(reiksme).split()).casefold()


# tarpai suvienodinami: "  Jonas   Petras " -> "Jonas Petras"
def _tekstas(reiksme):
    return " ".join(_svarus(reiksme).split())


# kabinetai, dalykai, klases, vardai lyginami nekreipiant demesio i didziasias
# raides ir tarpus: "6 A" = "6a" - tai ta pati klase
def _raktas(pavadinimas):
    return "".join(pavadinimas.split()).casefold()


def _pagal_pavadinima(objektai):
    zodynas = {}
    for obj in objektai:
        zodynas.setdefault(_raktas(obj.pavadinimas), obj)
    return zodynas


def _pirma_netuscia(eilutes):
    for i, eilute in enumerate(eilutes):
        if any(_svarus(x) for x in eilute or ()):
            return i
    return None


# jei eilute yra tiksliai musu antraste - grazina stulpeli, nuo kurio ji prasideda
def _lenteles_pradzia(eilute):
    langeliai = [_antraste(x) for x in eilute or ()]
    laukiama = [_antraste(x) for x in MOKYTOJU_STULPELIAI]
    for pradzia in (0, 1):
        pabaiga = pradzia + len(laukiama)
        if langeliai[pradzia:pabaiga] == laukiama and not any(langeliai[pabaiga:]):
            return pradzia
    return None


# "Gramatikos ir literatūros mokytoja, klasės vadovė" -> du dalykai
def _dalykai(tekstas):
    dalykai, matyti = [], set()
    for dalis in re.split(r"[,;\n]", tekstas):
        dalis = " ".join(dalis.split())
        if not dalis or dalis.casefold() in matyti:
            continue
        matyti.add(dalis.casefold())
        dalykai.append(dalis[0].upper() + dalis[1:])
    return dalykai


def nuskaityti_mokytoju_sarasa(failas, failo_vardas):
    """Perskaito ir patikrina mokytoju lentele. Duomenu bazes nelieczia.

    Grazina {"eilutes": [...], "klaidos": [...], "lapas": "..."}. Jei yra bent
    viena klaida - importuoti negalima."""

    rezultatas = {"eilutes": [], "klaidos": [], "lapas": ""}
    klaidos = rezultatas["klaidos"]

    try:
        lapai = _lapai_is_failo(failas, failo_vardas)
    except Exception as e:
        klaidos.append(f"Failo nepavyko perskaityti – įkelkite .xlsx arba .csv failą ({e})")
        return rezultatas

    tinkami = []
    for pavadinimas, eilutes in lapai:
        i = _pirma_netuscia(eilutes)
        if i is not None and _lenteles_pradzia(eilutes[i]) is not None:
            tinkami.append((pavadinimas, eilutes, i))

    if not tinkami:
        klaidos.append(
            "Netinkama failo forma. Pirmoje lentelės eilutėje turi būti tiksliai šie stulpeliai: "
            + " | ".join(MOKYTOJU_STULPELIAI)
        )
        # parodom ka radom, kad butu aisku kas negerai
        for pavadinimas, eilutes in lapai[:5]:
            i = _pirma_netuscia(eilutes)
            if i is None:
                continue
            rasta = " | ".join(_tekstas(x) for x in eilutes[i] if _svarus(x))
            if len(rasta) > 200:
                rasta = rasta[:200] + "…"
            kur = f"Lape „{pavadinimas}“ {i + 1}" if pavadinimas else f"{i + 1}"
            klaidos.append(f"{kur} eilutėje rasta: {rasta}")
        return rezultatas

    if len(tinkami) > 1:
        vardai = ", ".join(f"„{t[0]}“" for t in tinkami)
        klaidos.append(f"Faile yra keli lapai su mokytojų lentele ({vardai}) – palikite tik vieną")
        return rezultatas

    pavadinimas, eilutes, i = tinkami[0]
    rezultatas["lapas"] = pavadinimas
    pradzia = _lenteles_pradzia(eilutes[i])

    emailu_eilutes = {}
    klasiu_eilutes = {}

    for nr, eilute in enumerate(eilutes[i + 1:], start=i + 2):
        langeliai = [_langelis(eilute or (), pradzia + j) for j in range(len(MOKYTOJU_STULPELIAI))]
        if not any(langeliai):
            continue

        vardas, pavarde, email, dalykai, kabinetas, klase = langeliai
        vardas, pavarde, kabinetas, klase = _tekstas(vardas), _tekstas(pavarde), _tekstas(kabinetas), _tekstas(klase)
        email = email.lower()
        dalykai = _dalykai(dalykai)
        kas = f"{vardas} {pavarde}".strip() or email

        eilutes_klaidos = []
        if not vardas:
            eilutes_klaidos.append("trūksta vardo")
        if not pavarde:
            eilutes_klaidos.append("trūksta pavardės")
        if not email:
            eilutes_klaidos.append("trūksta el. pašto")
        else:
            try:
                validate_email(email)
            except ValidationError:
                eilutes_klaidos.append(f"netinkamas el. paštas „{email}“")

        for laukas, reiksme, pavad in (
            ("vardas", vardas, "vardas"), ("pavarde", pavarde, "pavardė"), ("email", email, "el. paštas"),
            ("kabinetas", kabinetas, "kabineto pavadinimas"), ("klase", klase, "klasės pavadinimas"),
        ):
            if len(reiksme) > ILGIAI[laukas]:
                eilutes_klaidos.append(f"per ilgas {pavad} (daugiausia {ILGIAI[laukas]} simbolių)")
        for dalykas in dalykai:
            if len(dalykas) > ILGIAI["dalykas"]:
                eilutes_klaidos.append(f"per ilgas dalyko pavadinimas „{dalykas[:30]}…“")

        if email and email in emailu_eilutes:
            eilutes_klaidos.append(f"el. paštas {email} jau yra {emailu_eilutes[email]} eilutėje")
        elif email:
            emailu_eilutes[email] = nr

        if klase:
            jau = klasiu_eilutes.get(_raktas(klase))
            if jau:
                eilutes_klaidos.append(f"klasė „{klase}“ jau priskirta auklėtojui {jau} eilutėje")
            else:
                klasiu_eilutes[_raktas(klase)] = nr

        if eilutes_klaidos:
            klaidos.append(f"{nr} eilutė ({kas}): " + "; ".join(eilutes_klaidos))
            continue

        rezultatas["eilutes"].append({
            "nr": nr,
            "vardas": vardas,
            "pavarde": pavarde,
            "email": email,
            "dalykai": dalykai,
            "kabinetas": kabinetas,
            "klase": klase,
        })

    if not rezultatas["eilutes"] and not klaidos:
        klaidos.append("Lentelėje nėra nė vieno mokytojo")

    return rezultatas


def _sarasas(pavadinimai):
    return ", ".join(sorted(pavadinimai, key=lt_raktas)) or "—"


def mokytoju_importo_planas(eilutes):
    """Palygina patikrintas failo eilutes su duomenu baze ir grazina, kas
    butu padaryta. Nieko nekeicia.

    Taisykles:
      - mokytojas atpazistamas pagal el. pasta; jei tokio nera - pagal varda ir
        pavarde tarp mokytoju be el. pasto; kitaip kuriamas naujas
      - tuscias Dalyko, Kabineto ar Klases langelis esamu duomenu neliecia
      - Dalykas pakeicia mokytojo dalykus tais, kurie parasyti faile
      - Klase gauna faile nurodyta aukletoja, kitos jo klases neliecamos
      - niekas netrinama, mokytojai, kuriu faile nera, lieka kaip buvo"""

    planas = {
        "nauji": [], "atnaujinami": [], "nepakite": 0,
        "nauji_kabinetai": [], "nauji_dalykai": [], "naujos_klases": [],
        "klasiu_pokyciai": [], "klaidos": [], "ispejimai": [],
    }

    mokytojai = list(Teacher.objects.select_related("kabinetas").prefetch_related("dalykai").order_by("id"))
    pagal_email, pagal_varda = {}, {}
    for m in mokytojai:
        if m.email.strip():
            pagal_email.setdefault(m.email.strip().lower(), []).append(m)
        pagal_varda.setdefault((_raktas(m.vardas), _raktas(m.pavarde)), []).append(m)

    kabinetai = _pagal_pavadinima(Cabinet.objects.order_by("id"))
    dalykai = _pagal_pavadinima(Subject.objects.order_by("id"))
    klases = _pagal_pavadinima(Klase.objects.select_related("aukletojas").order_by("id"))

    nauji_kabinetai, nauji_dalykai, naujos_klases = {}, {}, {}

    # 1. kiekvienai eilutei randam mokytoja
    irasai = []
    rasti_eilutese = {}
    for e in eilutes:
        rasti = pagal_email.get(e["email"], [])
        if len(rasti) > 1:
            planas["klaidos"].append(
                f"{e['nr']} eilutė: sistemoje yra {len(rasti)} mokytojai su el. paštu {e['email']} – "
                "palikite vieną ir kelkite failą iš naujo"
            )
            continue

        bendravardziai = pagal_varda.get((_raktas(e["vardas"]), _raktas(e["pavarde"])), [])
        if not rasti:
            rasti = [m for m in bendravardziai if not m.email.strip()]
            if len(rasti) > 1:
                planas["klaidos"].append(
                    f"{e['nr']} eilutė: sistemoje yra {len(rasti)} mokytojai „{e['vardas']} {e['pavarde']}“ "
                    "be el. pašto – neaišku kurį atnaujinti, palikite vieną ir kelkite failą iš naujo"
                )
                continue

        mokytojas = rasti[0] if rasti else None
        if mokytojas is not None:
            # dvi failo eilutes negali atnaujinti to paties mokytojo
            jau = rasti_eilutese.get(mokytojas.id)
            if jau:
                planas["klaidos"].append(
                    f"{e['nr']} eilutė: mokytojas „{mokytojas}“ jau atnaujinamas pagal {jau} eilutę"
                )
                continue
            rasti_eilutese[mokytojas.id] = e["nr"]
        if mokytojas is None and bendravardziai:
            kiti = ", ".join(m.email for m in bendravardziai)
            planas["ispejimai"].append(
                f"{e['nr']} eilutė: mokytojas „{e['vardas']} {e['pavarde']}“ sistemoje jau yra su kitu "
                f"el. paštu ({kiti}) – bus sukurtas dar vienas su {e['email']}"
            )

        if e["kabinetas"] and _raktas(e["kabinetas"]) not in kabinetai:
            nauji_kabinetai.setdefault(_raktas(e["kabinetas"]), e["kabinetas"])
        for d in e["dalykai"]:
            if _raktas(d) not in dalykai:
                nauji_dalykai.setdefault(_raktas(d), d)
        if e["klase"] and _raktas(e["klase"]) not in klases:
            naujos_klases.setdefault(_raktas(e["klase"]), e["klase"])

        irasai.append({"eilute": e, "mokytojas": mokytojas, "pakeitimai": []})

    # 2. klasiu aukletojai po importo - kad matytusi ir tie, kurie klase praras
    def kas(irasas):
        return irasas["mokytojas"].id if irasas["mokytojas"] else ("naujas", irasas["eilute"]["email"])

    klasiu_pavadinimai = {k: kl.pavadinimas for k, kl in klases.items()}
    aukletojai_po = {k: kl.aukletojas_id for k, kl in klases.items()}
    for irasas in irasai:
        e = irasas["eilute"]
        if not e["klase"]:
            continue
        k = _raktas(e["klase"])
        klasiu_pavadinimai.setdefault(k, e["klase"])
        aukletojai_po[k] = kas(irasas)
        kl = klases.get(k)
        if kl is None or irasas["mokytojas"] is None or kl.aukletojas_id != irasas["mokytojas"].id:
            planas["klasiu_pokyciai"].append({
                "klase": klasiu_pavadinimai[k],
                "buvo": str(kl.aukletojas) if kl and kl.aukletojas else "—",
                "bus": f"{e['vardas']} {e['pavarde']}",
                "nauja": kl is None,
            })

    def klases_po(kieno):
        return [klasiu_pavadinimai[k] for k, a in aukletojai_po.items() if a == kieno]

    # 3. ka keisim kiekvienam mokytojui
    for irasas in irasai:
        e, m = irasas["eilute"], irasas["mokytojas"]

        if m is None:
            irasas["klases"] = _sarasas(klases_po(kas(irasas)))
            planas["nauji"].append(irasas)
            continue

        pakeitimai = irasas["pakeitimai"]
        if m.vardas != e["vardas"]:
            pakeitimai.append(("Vardas", m.vardas, e["vardas"]))
        if m.pavarde != e["pavarde"]:
            pakeitimai.append(("Pavardė", m.pavarde, e["pavarde"]))
        if not m.email.strip():
            pakeitimai.append(("El. paštas", "—", e["email"]))
        if e["dalykai"]:
            esami = [d.pavadinimas for d in m.dalykai.all()]
            if {_raktas(d) for d in esami} != {_raktas(d) for d in e["dalykai"]}:
                pakeitimai.append(("Dalykai", _sarasas(esami), _sarasas(e["dalykai"])))
        if e["kabinetas"]:
            esamas = m.kabinetas.pavadinimas if m.kabinetas else ""
            if _raktas(esamas) != _raktas(e["kabinetas"]):
                pakeitimai.append(("Kabinetas", esamas or "—", e["kabinetas"]))
        pries = [kl.pavadinimas for kl in klases.values() if kl.aukletojas_id == m.id]
        po = klases_po(m.id)
        if sorted(pries, key=lt_raktas) != sorted(po, key=lt_raktas):
            pakeitimai.append(("Auklėjama klasė", _sarasas(pries), _sarasas(po)))

        if pakeitimai:
            planas["atnaujinami"].append(irasas)
        else:
            planas["nepakite"] += 1

    planas["nauji_kabinetai"] = sorted(nauji_kabinetai.values(), key=lt_raktas)
    planas["nauji_dalykai"] = sorted(nauji_dalykai.values(), key=lt_raktas)
    planas["naujos_klases"] = sorted(naujos_klases.values(), key=lt_raktas)
    planas["esamos_klases"] = sorted((kl.pavadinimas for kl in klases.values()), key=lt_raktas)
    planas["klasiu_pokyciai"].sort(key=lambda p: lt_raktas(p["klase"]))
    return planas


# trumpas plano "atspaudas" - patvirtinant tikrinam, ar per ta laika
# duomenu bazeje niekas nepasikeite ir bus padaryta tai, kas buvo parodyta
def _plano_parasas(planas):
    santrauka = {
        "nauji": [i["eilute"] for i in planas["nauji"]],
        "atnaujinami": [(i["mokytojas"].id, i["eilute"], i["pakeitimai"]) for i in planas["atnaujinami"]],
        "klases": planas["klasiu_pokyciai"],
        "dublikatai": planas["dublikatai"],
        "kiti": [planas[k] for k in ("nauji_kabinetai", "nauji_dalykai", "naujos_klases", "klaidos", "ispejimai")],
    }
    return hashlib.sha256(json.dumps(santrauka, sort_keys=True, default=str).encode()).hexdigest()


def _sudaryti(eilutes):
    # kviesti tik transakcijoje - dublikatai cia pat sujungiami
    dublikatai, klaidos, ispejimai = sujungti_dublikatus()
    planas = mokytoju_importo_planas(eilutes)
    planas["dublikatai"] = dublikatai
    planas["klaidos"] = klaidos + planas["klaidos"]
    planas["ispejimai"] = ispejimai + planas["ispejimai"]
    planas["parasas"] = _plano_parasas(planas)
    return planas


def perziureti_importa(eilutes):
    """Grazina, kas butu padaryta. Dublikatai sujungiami tik bandymui -
    transakcija atsaukiama, duomenu bazeje niekas nepasikeicia."""
    with transaction.atomic():
        planas = _sudaryti(eilutes)
        transaction.set_rollback(True)
    return planas


def vykdyti_importa(eilutes, parasas):
    """Sujungia dublikatus ir iraso faila. Viskas vienoje transakcijoje -
    arba pavyksta viskas, arba nepakeiciama nieko.

    Jei planas nebesutampa su parodytu (parasas kitoks) ar atsirado klaidu -
    nieko nedaro ir grazina nauja plana su "ivykdyta": False."""

    with transaction.atomic():
        planas = _sudaryti(eilutes)
        planas["ivykdyta"] = False
        if planas["klaidos"] or planas["parasas"] != parasas:
            transaction.set_rollback(True)
            return planas

        kabinetai = _pagal_pavadinima(Cabinet.objects.order_by("id"))
        dalykai = _pagal_pavadinima(Subject.objects.order_by("id"))
        klases = _pagal_pavadinima(Klase.objects.order_by("id"))

        def gauti(zodynas, modelis, pavadinimas):
            k = _raktas(pavadinimas)
            if k not in zodynas:
                zodynas[k] = modelis.objects.create(pavadinimas=pavadinimas)
            return zodynas[k]

        for irasas in planas["nauji"] + planas["atnaujinami"]:
            e = irasas["eilute"]
            m = irasas["mokytojas"] or Teacher()
            m.vardas = e["vardas"]
            m.pavarde = e["pavarde"]
            if not m.email.strip():
                m.email = e["email"]
            if e["kabinetas"]:
                m.kabinetas = gauti(kabinetai, Cabinet, e["kabinetas"])
            m.save()

            if e["dalykai"]:
                m.dalykai.set([gauti(dalykai, Subject, d) for d in e["dalykai"]])

            if e["klase"]:
                kl = gauti(klases, Klase, e["klase"])
                if kl.aukletojas_id != m.id:
                    kl.aukletojas = m
                    kl.save(update_fields=["aukletojas"])

        planas["ivykdyta"] = True
    return planas


# ---- Dublikatai ----
# Tas pats mokytojas ar klase sistemoje kelis kartus (pvz. sukurtas rankomis ir
# dar karta per ikelima). Dublikatas sujungiamas su paliekamu irasu: jo
# rezervacijos, darbo laikai, vaikai ir kt. perkeliami, tik tada dublikatas
# istrinamas. Tiesiog istrynus mokytoja kartu dingtu ir jo rezervacijos,
# o istrynus klase - vaikai liktu be klases

def _apie_mokytoja(m):
    return f"{m.vardas} {m.pavarde} ({m.email or 'be el. pašto'})"


def _perkelta(**kiekiai):
    return ", ".join(f"{pav}: {n}" for pav, n in kiekiai.items() if n) or "—"


def mokytoju_dublikatai():
    """[(paliekamas, [dublikatai]), ...] ir ispejimai.

    Dublikatai: tas pats el. pastas; arba tas pats vardas ir pavarde, kai
    el. pastas yra tik vienam (kitiems tuscias). Paliekamas tas, kuris turi
    el. pasta, o is ju - seniausias. Tas pats vardas su skirtingais el. pastais
    nesujungiamas - gal tai bendravardziai, o gal vienas adresas nebenaudojamas,
    to automatiskai nuspresti negalima."""

    pagal_email, be_email = {}, []
    for m in Teacher.objects.order_by("id"):
        email = m.email.strip().lower()
        if email:
            pagal_email.setdefault(email, []).append(m)
        else:
            be_email.append(m)

    grupes = list(pagal_email.values())
    pagal_varda = {}
    for g in grupes:
        for k in {(_raktas(m.vardas), _raktas(m.pavarde)) for m in g}:
            pagal_varda.setdefault(k, []).append(g)

    ispejimai = []
    for g in pagal_varda.values():
        if len(g) > 1:
            emailai = ", ".join(sorted(gr[0].email for gr in g))
            ispejimai.append(
                f"Mokytojas „{g[0][0].vardas} {g[0][0].pavarde}“ sistemoje yra kelis kartus su skirtingais "
                f"el. paštais ({emailai}) – nesujungta. Jei tai tas pats žmogus, nereikalingą ištrinkite rankomis"
            )

    likusieji = {}
    for m in be_email:
        k = (_raktas(m.vardas), _raktas(m.pavarde))
        su_emailu = pagal_varda.get(k, [])
        if len(su_emailu) == 1:
            su_emailu[0].append(m)
        elif not su_emailu:
            likusieji.setdefault(k, []).append(m)
    grupes += likusieji.values()

    rezultatas = []
    for g in grupes:
        if len(g) > 1:
            g.sort(key=lambda m: (not m.email.strip(), m.id))
            rezultatas.append((g[0], g[1:]))
    rezultatas.sort(key=lambda p: p[0].id)
    return rezultatas, ispejimai


def klasiu_dublikatai():
    """[(paliekama, [dublikatai]), ...] - tas pats pavadinimas, nepaisant
    didziuju raidziu ir tarpu. Paliekama seniausia."""
    grupes = {}
    for kl in Klase.objects.select_related("aukletojas").order_by("id"):
        grupes.setdefault(_raktas(kl.pavadinimas), []).append(kl)
    return [(g[0], g[1:]) for g in grupes.values() if len(g) > 1]


def sujungti_dublikatus():
    """Sujungia ir istrina dublikatus. Kviesti tik transakcijoje.
    Grazina (ataskaita, klaidos, ispejimai)."""

    ataskaita, klaidos = [], []
    grupes, ispejimai = mokytoju_dublikatai()

    for palikti, dublikatai in grupes:
        for d in dublikatai:
            # rezervacija tuo paciu laiku pas abu - vieno laiko dviem tevams neperkelsi
            susikerta = Reservation.objects.filter(teacher=d).filter(
                Exists(Reservation.objects.filter(teacher=palikti, date=OuterRef("date"), time=OuterRef("time")))
            ).first()
            if susikerta:
                klaidos.append(
                    f"Mokytojo dublikatų {_apie_mokytoja(palikti)} ir {_apie_mokytoja(d)} sujungti negalima – "
                    f"abu turi rezervaciją {susikerta.date} {susikerta.time:%H:%M}. Vieną rezervaciją sutvarkykite rankomis"
                )
                continue

            darbo_laikai = list(WorkingHours.objects.filter(mokytojai=d))
            for wh in darbo_laikai:
                wh.mokytojai.add(palikti)
            perkelta = _perkelta(**{
                "rezervacijų": Reservation.objects.filter(teacher=d).update(teacher=palikti),
                "pokalbių su vadovu": VadovoRezervacija.objects.filter(mokytojas=d).update(mokytojas=palikti),
                "darbo laikų": len(darbo_laikai),
                "auklėjamų klasių": Klase.objects.filter(aukletojas=d).update(aukletojas=palikti),
            })
            palikti.dalykai.add(*d.dalykai.all())
            palikti.klases.add(*d.klases.all())
            if not palikti.kabinetas_id:
                palikti.kabinetas_id = d.kabinetas_id
            if not palikti.email.strip():
                palikti.email = d.email
            palikti.save()

            ataskaita.append({
                "tipas": "Mokytojas", "palikta": _apie_mokytoja(palikti),
                "istrinta": _apie_mokytoja(d), "perkelta": perkelta,
            })
            d.delete()

    # klases - po mokytoju, nes aukletojai ka tik galejo pasikeisti
    for palikti, dublikatai in klasiu_dublikatai():
        for d in dublikatai:
            mokytojai = list(Teacher.objects.filter(klases=d))
            for m in mokytojai:
                m.klases.add(palikti)
            perkelta = _perkelta(**{
                "vaikų": Child.objects.filter(klase=d).update(klase=palikti),
                "mokytojų, kurie moko šią klasę": len(mokytojai),
            })
            if d.aukletojas_id and not palikti.aukletojas_id:
                palikti.aukletojas_id = d.aukletojas_id
                palikti.save(update_fields=["aukletojas"])
            elif d.aukletojas_id and d.aukletojas_id != palikti.aukletojas_id:
                ispejimai.append(
                    f"Klasė „{palikti.pavadinimas}“: paliktas auklėtojas {palikti.aukletojas}, "
                    f"dublikato auklėtojas {d.aukletojas} nepriskirtas"
                )

            ataskaita.append({
                "tipas": "Klasė", "palikta": palikti.pavadinimas,
                "istrinta": d.pavadinimas, "perkelta": perkelta,
            })
            d.delete()

    return ataskaita, klaidos, ispejimai
