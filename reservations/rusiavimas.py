import re

from django.db.models.functions import Collate


# SQLite pats tekstą lygina pagal simbolių kodus, todėl Č, Š, Ž atsiduria
# sąrašo gale (po Z), mažosios raidės eina po visų didžiųjų, o klasės
# rikiuojamos kaip tekstas (10S pries 6F). Todėl kiekvienam DB prisijungimui
# užregistruojam savo palyginimą "lt" ir rikiuojant tekstą naudojam jį:
#   - lietuviška abėcėlė: C < Č < D, S < Š < T, Z < Ž, o ą, ę, ė, į, y, ų, ū
#     eina kartu su a, e, i, u (kaip žodynuose)
#   - didžiosios/mažosios nesvarbu
#   - skaičiai lyginami kaip skaičiai: 6F < 10S, kabinetas 101 < 321 < 1001
# PASTABA: Postgres tokio palyginimo nėra - pereinant reiktų perdaryti
PALYGINIMAS = "lt"

_PIRMINE = str.maketrans({
    "ą": "a", "ę": "e", "ė": "e", "į": "i", "y": "i", "ų": "u", "ū": "u",
    # ￿ didesnis už bet kurią raidę, tai "č..." eina po visų "c..."
    "č": "c￿", "š": "s￿", "ž": "z￿",
})

_SKAICIAI = re.compile(r"([0-9]+)")


def raktas(tekstas):
    mazosios = tekstas.casefold()
    dalys = []
    for dalis in _SKAICIAI.split(mazosios.translate(_PIRMINE)):
        if not dalis:
            continue
        # 0/1 priekyje - kad skaičius niekada nebūtų lyginamas su tekstu
        if dalis[0].isascii() and dalis[0].isdigit():
            dalys.append((0, int(dalis)))
        else:
            dalys.append((1, dalis))
    # jei pagal abėcėlę lygūs - lemia nosinės, po to didžiosios raidės
    return (dalys, mazosios, tekstas)


def palyginti(a, b):
    ra, rb = raktas(a), raktas(b)
    return (ra > rb) - (ra < rb)


def registruoti_palyginima(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        connection.connection.create_collation(PALYGINIMAS, palyginti)


# rikiavimas lietuviškai: .order_by(lt("pavarde")), Meta.ordering = (lt("pavarde"),)
def lt(laukas):
    return Collate(laukas, PALYGINIMAS)
