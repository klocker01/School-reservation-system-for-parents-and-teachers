from datetime import datetime, timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone

from .models import (
    Cabinet, Teacher, Vadovas, VadovoLaikas, VadovoPertrauka, VadovoRezervacija,
)
from .views import (
    laiko_laukas, datos_laukas, laikai_is_eiles, get_teacher_for_user, trumpas_vardas,
    mokytojo_laikai_pas_vadova, tevu_laikai_pas_mokytoja, kertasi,
)


class VadovoLaikasForm(forms.ModelForm):
    # vadovas neturi numatyto kabineto - ji butina pasirinkti kiekvienam blokui
    class Meta:
        model = VadovoLaikas
        fields = ["date", "start_time", "end_time", "interval", "cabinet"]
        widgets = {
            "date": datos_laukas(),
            "start_time": laiko_laukas(),
            "end_time": laiko_laukas(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cabinet"].required = True
        self.fields["cabinet"].queryset = Cabinet.objects.order_by("pavadinimas")
        self.fields["cabinet"].empty_label = "-- pasirinkite kabinetą --"


class VadovoPertraukaForm(forms.ModelForm):
    class Meta:
        model = VadovoPertrauka
        fields = ["start_time", "end_time", "description"]
        widgets = {
            "start_time": laiko_laukas(),
            "end_time": laiko_laukas(),
        }


def get_vadovas_for_user(user):
    if not user.is_authenticated or not user.email:
        return None
    return Vadovas.objects.filter(email__iexact=user.email).first()


# sudaro vieno vadovo laiko bloko laikus. mokytojas - jei perduotas, jo
# rezervacijos pazymimos "mine"; rodyti_vardus - vadovas mato kas uzsiregistravo,
# mokytojai kitu mokytoju vardu nemato, tik "Užimta"
def vadovo_bloko_laikai(blokas, mokytojas=None, rodyti_vardus=False):
    siandien = timezone.localdate()
    dabar = timezone.localtime()

    rezervacijos = {
        r.time: r
        for r in VadovoRezervacija.objects.filter(
            vadovas_id=blokas.vadovas_id,
            date=blokas.date,
            time__gte=blokas.start_time,
            time__lt=blokas.end_time,
        ).select_related("mokytojas")
    }
    pertraukos = list(blokas.breaks.all())

    laikai = []
    einamas = datetime.combine(blokas.date, blokas.start_time)
    pabaiga = datetime.combine(blokas.date, blokas.end_time)

    while einamas < pabaiga:
        laikas = einamas.time()
        einamas += timedelta(minutes=blokas.interval)

        if any(p.start_time <= laikas < p.end_time for p in pertraukos):
            continue

        if blokas.date == siandien and timezone.make_aware(datetime.combine(blokas.date, laikas)) < dabar:
            continue

        rez = rezervacijos.get(laikas)
        if not rez:
            laikai.append({"time": laikas.strftime("%H:%M"), "status": "free", "by": ""})
        elif mokytojas and rez.mokytojas_id == mokytojas.id:
            laikai.append({
                "time": laikas.strftime("%H:%M"),
                "status": "mine",
                "by": "",
                "rezervacija_id": rez.id,
            })
        else:
            kas = trumpas_vardas(rez.mokytojas.vardas, rez.mokytojas.pavarde) if rodyti_vardus else "Užimta"
            laikai.append({"time": laikas.strftime("%H:%M"), "status": "busy", "by": kas})

    return laikai


# randa bloka, kuriam priklauso laikas - laikas turi buti bloko ribose,
# ant intervalu tinklelio ir ne per pertrauka
def rasti_vadovo_bloka(vadovas, data, laikas):
    t = datetime.combine(data, laikas)
    for blokas in VadovoLaikas.objects.filter(vadovas=vadovas, date=data).prefetch_related("breaks"):
        pradzia = datetime.combine(data, blokas.start_time)
        pabaiga = datetime.combine(data, blokas.end_time)
        if not (pradzia <= t < pabaiga):
            continue
        if (t - pradzia) % timedelta(minutes=blokas.interval):
            continue
        if any(p.start_time <= laikas < p.end_time for p in blokas.breaks.all()):
            continue
        return blokas
    return None


# Vadovo grafikas

def atgal_i_vadovo_grafika(data=None):
    url = reverse("vadovas_dashboard")
    if data:
        url += f"#d-{data.isoformat()}"
    return redirect(url)


@login_required
def vadovas_dashboard(request):
    vadovas = get_vadovas_for_user(request.user)
    if not vadovas:
        return redirect("home")

    siandien = timezone.localdate()
    dabar = timezone.localtime()

    blokai = (
        VadovoLaikas.objects
        .filter(vadovas=vadovas, date__gte=siandien)
        .select_related("cabinet")
        .prefetch_related("breaks")
        .order_by("date", "start_time")
    )

    dienos = []
    for blokas in blokai:
        if not dienos or dienos[-1]["date"] != blokas.date:
            dienos.append({"date": blokas.date, "blokai": []})

        pertraukos = list(blokas.breaks.all())

        rezervaciju = VadovoRezervacija.objects.filter(
            vadovas=vadovas, date=blokas.date,
            time__gte=blokas.start_time, time__lt=blokas.end_time,
        ).count()

        laikai = vadovo_bloko_laikai(blokas, rodyti_vardus=True)

        for p in pertraukos:
            if not p.pasalintas_laikas:
                continue
            if blokas.date == siandien and p.start_time < dabar.time():
                continue
            laikai.append({
                "time": p.start_time.strftime("%H:%M"),
                "status": "removed",
                "break_id": p.id,
            })
        laikai.sort(key=lambda x: x["time"])

        dienos[-1]["blokai"].append({
            "wh": blokas,
            "slots": laikai,
            "pertraukos": [p for p in pertraukos if not p.pasalintas_laikas],
            "rezervaciju": rezervaciju,
        })

    return render(request, "reservations/vadovas_dashboard.html", {
        "vadovas": vadovas,
        "dienos": dienos,
        "wh_form": VadovoLaikasForm(),
    })


@login_required
def vadovas_add_laikas(request):
    vadovas = get_vadovas_for_user(request.user)
    if not vadovas:
        return redirect("home")

    if request.method != "POST":
        return redirect("vadovas_dashboard")

    forma = VadovoLaikasForm(request.POST)
    if not forma.is_valid():
        if "cabinet" in forma.errors:
            messages.error(request, "Pasirinkite kabinetą, kuriame vyks pokalbiai")
        else:
            messages.error(request, "Neteisingi duomenys")
        return redirect("vadovas_dashboard")

    blokas = forma.save(commit=False)
    blokas.vadovas = vadovas

    if blokas.start_time >= blokas.end_time:
        messages.error(request, "Pabaigos laikas turi būti vėliau, nei pradžios laikas")
        return redirect("vadovas_dashboard")

    if blokas.date < timezone.localdate():
        messages.error(request, "Negalima pridėti praeities datų")
        return redirect("vadovas_dashboard")

    kitas = VadovoLaikas.objects.filter(
        vadovas=vadovas,
        date=blokas.date,
        start_time__lt=blokas.end_time,
        end_time__gt=blokas.start_time,
    ).first()
    if kitas:
        messages.error(
            request,
            f"Laikas {blokas.start_time.strftime('%H:%M')}–{blokas.end_time.strftime('%H:%M')} "
            f"kertasi su jau esamu laiku "
            f"({kitas.start_time.strftime('%H:%M')}–{kitas.end_time.strftime('%H:%M')})"
        )
        return redirect("vadovas_dashboard")

    blokas.save()

    # viena pertrauka is tos pacios formos - nebutina (kaip ir mokytoju grafike)
    bs = request.POST.get("break_start", "").strip().replace(".", ":")
    be = request.POST.get("break_end", "").strip().replace(".", ":")

    if bs and be:
        try:
            ps = datetime.strptime(bs, "%H:%M").time()
            pe = datetime.strptime(be, "%H:%M").time()
            if ps < pe and ps >= blokas.start_time and pe <= blokas.end_time:
                VadovoPertrauka.objects.create(laikas=blokas, start_time=ps, end_time=pe)
            else:
                messages.warning(request, "Pertrauka neišsaugota – ji turi būti darbo laiko ribose")
        except ValueError:
            messages.warning(request, "Pertrauka neišsaugota – neteisingas laiko formatas")
    elif bs or be:
        messages.warning(request, "Pertrauka neišsaugota – nurodykite ir pradžią, ir pabaigą")

    messages.success(request, "Laikas pridėtas")
    return atgal_i_vadovo_grafika(blokas.date)


@login_required
def vadovas_delete_laikas(request, laikas_id):
    vadovas = get_vadovas_for_user(request.user)
    if not vadovas:
        return redirect("home")

    blokas = get_object_or_404(VadovoLaikas, id=laikas_id, vadovas=vadovas)

    if request.method == "POST":
        data = blokas.date
        VadovoRezervacija.objects.filter(
            vadovas=vadovas, date=blokas.date,
            time__gte=blokas.start_time, time__lt=blokas.end_time,
        ).delete()
        blokas.delete()
        messages.success(request, "Laikas ištrintas")
        return atgal_i_vadovo_grafika(data)

    return redirect("vadovas_dashboard")


@login_required
def vadovas_delete_slot(request, laikas_id):
    vadovas = get_vadovas_for_user(request.user)
    if not vadovas:
        return redirect("home")

    blokas = get_object_or_404(VadovoLaikas, id=laikas_id, vadovas=vadovas)

    if request.method != "POST":
        return atgal_i_vadovo_grafika(blokas.date)

    try:
        laikas = datetime.strptime(request.POST.get("time", ""), "%H:%M").time()
    except ValueError:
        messages.error(request, "Neteisingas laikas")
        return atgal_i_vadovo_grafika(blokas.date)

    pradzia = datetime.combine(blokas.date, blokas.start_time)
    pabaiga = datetime.combine(blokas.date, blokas.end_time)
    t = datetime.combine(blokas.date, laikas)
    if not (pradzia <= t < pabaiga) or (t - pradzia) % timedelta(minutes=blokas.interval):
        messages.error(request, "Toks laikas šiame bloke neegzistuoja")
        return atgal_i_vadovo_grafika(blokas.date)

    if VadovoRezervacija.objects.filter(vadovas=vadovas, date=blokas.date, time=laikas).exists():
        messages.error(
            request,
            f"Laikas {laikas.strftime('%H:%M')} jau rezervuotas – jo pašalinti negalima",
        )
        return atgal_i_vadovo_grafika(blokas.date)

    if blokas.breaks.filter(start_time__lte=laikas, end_time__gt=laikas).exists():
        messages.warning(request, f"Laikas {laikas.strftime('%H:%M')} jau pašalintas")
        return atgal_i_vadovo_grafika(blokas.date)

    VadovoPertrauka.objects.create(
        laikas=blokas,
        start_time=laikas,
        end_time=min(t + timedelta(minutes=blokas.interval), pabaiga).time(),
        description="Pašalintas laikas",
        pasalintas_laikas=True,
    )
    messages.success(request, f"Laikas {laikas.strftime('%H:%M')} pašalintas")
    return atgal_i_vadovo_grafika(blokas.date)


@login_required
def vadovas_add_break(request, laikas_id):
    vadovas = get_vadovas_for_user(request.user)
    if not vadovas:
        return redirect("home")

    blokas = get_object_or_404(VadovoLaikas, id=laikas_id, vadovas=vadovas)

    if request.method != "POST":
        return atgal_i_vadovo_grafika(blokas.date)

    forma = VadovoPertraukaForm(request.POST)
    if not forma.is_valid():
        messages.error(request, "Neteisingi pertraukos duomenys")
        return atgal_i_vadovo_grafika(blokas.date)

    pertrauka = forma.save(commit=False)

    if pertrauka.start_time >= pertrauka.end_time:
        messages.error(request, "Pertraukos pabaiga turi būti vėliau, nei pradžia")
        return atgal_i_vadovo_grafika(blokas.date)

    if pertrauka.start_time < blokas.start_time or pertrauka.end_time > blokas.end_time:
        messages.error(request, "Pertrauka turi būti darbo laiko ribose")
        return atgal_i_vadovo_grafika(blokas.date)

    if VadovoRezervacija.objects.filter(
        vadovas=vadovas, date=blokas.date,
        time__gte=pertrauka.start_time, time__lt=pertrauka.end_time,
    ).exists():
        messages.error(request, "Pasirinktu laiko intervalu jau yra rezervacijos")
        return atgal_i_vadovo_grafika(blokas.date)

    pertrauka.laikas = blokas
    pertrauka.save()
    messages.success(request, "Pertrauka pridėta")
    return atgal_i_vadovo_grafika(blokas.date)


@login_required
def vadovas_delete_break(request, break_id):
    vadovas = get_vadovas_for_user(request.user)
    if not vadovas:
        return redirect("home")

    pertrauka = get_object_or_404(VadovoPertrauka, id=break_id, laikas__vadovas=vadovas)
    data = pertrauka.laikas.date

    if request.method == "POST":
        pertrauka.delete()
        if pertrauka.pasalintas_laikas:
            messages.success(request, f"Laikas {pertrauka.start_time.strftime('%H:%M')} grąžintas")
        else:
            messages.success(request, "Pertrauka ištrinta")

    return atgal_i_vadovo_grafika(data)


# Mokytojo skiltis - pokalbiai su vadovu

@login_required
def pokalbiai_vadovas(request):
    mokytojas = get_teacher_for_user(request.user)
    if not mokytojas:
        return redirect("home")

    siandien = timezone.localdate()
    dabar = timezone.localtime()

    # jei vadovas kartu yra ir mokytojas, pats pas save registruotis negali
    vadovai = Vadovas.objects.exclude(email__iexact=request.user.email)

    duomenys = []
    for vadovas in vadovai:
        blokai = (
            VadovoLaikas.objects
            .filter(vadovas=vadovas, date__gte=siandien)
            .select_related("cabinet")
            .prefetch_related("breaks")
            .order_by("date", "start_time")
        )

        dienos = []
        for blokas in blokai:
            laikai = vadovo_bloko_laikai(blokas, mokytojas=mokytojas)
            if not laikai:
                continue
            if not dienos or dienos[-1]["date"] != blokas.date:
                dienos.append({"date": blokas.date, "blokai": []})
            dienos[-1]["blokai"].append({"wh": blokas, "slots": laikai})

        if dienos:
            duomenys.append({"vadovas": vadovas, "dienos": dienos})

    mano = []
    for r in (
        VadovoRezervacija.objects
        .filter(mokytojas=mokytojas, date__gte=siandien)
        .select_related("vadovas", "cabinet")
        .order_by("date", "time")
    ):
        rez_dt = timezone.make_aware(datetime.combine(r.date, r.time))
        if rez_dt < dabar:
            continue
        mano.append({"r": r, "can_cancel": (rez_dt - dabar) >= timedelta(hours=24)})

    return render(request, "reservations/pokalbiai_vadovas.html", {
        "mokytojas": mokytojas,
        "data": duomenys,
        "mano": mano,
    })


@login_required
def pokalbiai_vadovas_rezervuoti(request, vadovas_id):
    mokytojas = get_teacher_for_user(request.user)
    if not mokytojas:
        return redirect("home")

    if request.method != "POST":
        return redirect("pokalbiai_vadovas")

    vadovas = get_object_or_404(Vadovas, id=vadovas_id)
    if vadovas.email.lower() == (request.user.email or "").lower():
        return redirect("pokalbiai_vadovas")

    try:
        data = datetime.strptime(request.POST.get("date", ""), "%Y-%m-%d").date()
        laikas = datetime.strptime(request.POST.get("time", ""), "%H:%M").time()
    except ValueError:
        return redirect("pokalbiai_vadovas")

    atgal = redirect(f"{reverse('pokalbiai_vadovas')}#v-{vadovas.id}-{data.isoformat()}")

    if timezone.make_aware(datetime.combine(data, laikas)) < timezone.localtime():
        messages.error(request, "Šis laikas jau praėjo")
        return atgal

    blokas = rasti_vadovo_bloka(vadovas, data, laikas)
    if not blokas:
        messages.error(request, "Toks laikas neegzistuoja")
        return atgal

    if VadovoRezervacija.objects.filter(vadovas=vadovas, date=data, time=laikas).exists():
        messages.error(request, "Šis laikas jau užimtas")
        return atgal

    # mokytojas negali buti dviejose vietose tuo paciu metu
    pradzia = datetime.combine(data, laikas)
    if kertasi(pradzia, blokas.interval, mokytojo_laikai_pas_vadova(mokytojas, data)):
        messages.error(request, "Tuo laiku jau esate užsiregistravę pas kitą vadovą")
        return atgal

    if kertasi(pradzia, blokas.interval, tevu_laikai_pas_mokytoja(mokytojas, data)):
        messages.error(request, "Tuo laiku pas jus jau užsiregistravę tėvai")
        return atgal

    # jei vadovas kartu yra ir mokytojas - tuo metu pas ji neturi buti tevu
    vadovas_mokytojas = Teacher.objects.filter(email__iexact=vadovas.email).first()
    if vadovas_mokytojas and kertasi(pradzia, blokas.interval, tevu_laikai_pas_mokytoja(vadovas_mokytojas, data)):
        messages.error(request, "Šis laikas jau užimtas")
        return atgal

    # pas ta pati vadova per diena - ne daugiau 3 laiku ir tik is eiles
    jau_turi = list(
        VadovoRezervacija.objects
        .filter(mokytojas=mokytojas, vadovas=vadovas, date=data)
        .values_list("time", flat=True)
    )
    visi = sorted(set(jau_turi + [laikas]))

    if len(visi) > 3:
        messages.error(request, "Galima rezervuoti ne daugiau nei 3 laikus pas vieną vadovą per dieną")
        return atgal

    if not laikai_is_eiles(data, visi, blokas.interval):
        messages.error(request, "Laikai turi eiti iš eilės be tarpų")
        return atgal

    if request.POST.get("confirm") != "yes":
        return render(request, "reservations/pokalbiai_vadovas_confirm.html", {
            "vadovas": vadovas,
            "date": data.strftime("%Y-%m-%d"),
            "time": laikas.strftime("%H:%M"),
            "kabinetas": blokas.cabinet,
        })

    try:
        VadovoRezervacija.objects.create(
            vadovas=vadovas,
            mokytojas=mokytojas,
            date=data,
            time=laikas,
            cabinet=blokas.cabinet,
        )
        messages.success(request, "Rezervacija sėkmingai sukurta")
    except IntegrityError:
        messages.error(request, "Šis laikas jau užimtas")

    return atgal


@login_required
def pokalbiai_vadovas_atsaukti(request, rezervacija_id):
    mokytojas = get_teacher_for_user(request.user)
    if not mokytojas:
        return redirect("home")

    rezervacija = get_object_or_404(VadovoRezervacija, id=rezervacija_id, mokytojas=mokytojas)

    if request.method == "POST":
        rez_dt = timezone.make_aware(datetime.combine(rezervacija.date, rezervacija.time))
        if rez_dt - timezone.localtime() < timedelta(hours=24):
            messages.error(request, "Rezervacijos nebegalima atšaukti (<24h)")
        else:
            rezervacija.delete()
            messages.success(request, "Rezervacija atšaukta")

    return redirect("pokalbiai_vadovas")
