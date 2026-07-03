from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django import forms
from django.utils import timezone
from datetime import datetime, timedelta
from django.db import IntegrityError
from django.db.models import Q #su db padeda
from django.contrib import messages


from .models import Teacher, Reservation, WorkingHours, Break, Profile, Child, Klase, Cabinet


class ChildForm(forms.ModelForm):
    class Meta:
        model = Child
        fields = ["first_name", "last_name", "klase"]

    # klase bus dropdownas su klasem is DB
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["klase"].queryset = Klase.objects.all()
        self.fields["klase"].empty_label = "-- pasirink klasę --"
        self.fields["klase"].required = True


class WorkingHoursForm(forms.ModelForm):
    # mokytojas formoje "tipas" nepasirenka, jis gali pridėti tik individualius pokalbius
    # Dalykininku pokalbius prideda tik adminas per admin panelę
    class Meta:
        model = WorkingHours
        fields = ["date", "start_time", "end_time", "interval", "cabinet"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cabinet"].required = False
        self.fields["cabinet"].empty_label = "-- mokytojo numatytas kabinetas --"


class BreakForm(forms.ModelForm):
    class Meta:
        model = Break
        fields = ["start_time", "end_time", "description"]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }


def get_teacher_for_user(user):
    #Jeigu user ne mokytojas
    if not user.email:
        return None
    try:
        return Teacher.objects.get(email__iexact=user.email)
    except Teacher.DoesNotExist:
        return None


# pagrindinis – du pokalbiu tipai
@login_required
def home(request):
    siandien = timezone.localdate()
    tipas = request.GET.get("tipas")

    # jei tipas pasirinktas rodome datos
    if tipas in ("individualus", "dalykininku"):
        from django.db.models import Count
        profilis, _ = Profile.objects.get_or_create(user=request.user)
        aktyvus_vaikas = profilis.active_child

        wh_qs = WorkingHours.objects.filter(date__gte=siandien, tipas=tipas)

        if tipas == "individualus":
            if aktyvus_vaikas and aktyvus_vaikas.klase and aktyvus_vaikas.klase.aukletojas:
                wh_qs = wh_qs.filter(mokytojai=aktyvus_vaikas.klase.aukletojas)
            else:
                wh_qs = wh_qs.none()
        else:
            if aktyvus_vaikas and aktyvus_vaikas.klase:
                mokytojai_ids = (
                    Teacher.objects
                    .annotate(klases_kiekis=Count("klases"))
                    .filter(
                        Q(klases_kiekis=0) | Q(klases=aktyvus_vaikas.klase)
                    )
                    .values_list("id", flat=True)
                )
                wh_qs = wh_qs.filter(mokytojai__id__in=mokytojai_ids)

        datos = (
            wh_qs
            .values_list("date", flat=True)
            .distinct()
            .order_by("date")
        )
        return render(request, "reservations/home.html", {
            "tipas": tipas,
            "datos": datos,
        })

    # jei tipas nepasirinktas – rodome du mygtukus
    return render(request, "reservations/home.html", {"tipas": None})


# (papildoma apsauga) ar laikas telpa i darbo laikus ir ne per pertrauka
def laikas_leistinas(mokytojas, data, laikas, tipas="individualus"):
    # filtruojame tik pagal konkretu tipas, kad dalykininku blokai
    # neužblokuotų individualiu rezervacijų ir atvirkščiai
    darbo_laikai = (
        WorkingHours.objects
        .filter(mokytojai=mokytojas, date=data, tipas=tipas)
        .prefetch_related("breaks")
    )

    telpa = False
    for d in darbo_laikai:
        if d.start_time <= laikas < d.end_time:
            telpa = True
            break

    if not telpa:
        return False

    for d in darbo_laikai:
        for p in d.breaks.all():
            if p.start_time <= laikas < p.end_time:
                return False

    return True



# pagalbine – ar laikai eina is eiles pagal intervala
def laikai_is_eiles(data, laikai, intervalas=10):
    for i in range(1, len(laikai)):
        pries = datetime.combine(data, laikai[i - 1])
        dab = datetime.combine(data, laikai[i])
        if (dab - pries) != timedelta(minutes=intervalas):
            return False
    return True


# sudaro laiku sarasa is perduotu darbo laiku (WorkingHours) bloku
# naudojama tiek tevu rezervacijos puslapyje (visi bloko tos dienos/tipo laikai),
# tiek mokytojo savo grafiko kortelėje (vienas konkretus blokas)
# request_user - jei perduotas, tos rezervacijos kurios priklauso siam vartotojui pažymimos "mine"
def sudaryti_laikus(mokytojas, pasirinkta_data, darbo_laikai, request_user=None, show_names=True):
    siandien = timezone.localdate()
    dabar = timezone.localtime()

    rezervacijos = {}
    for rez in Reservation.objects.filter(teacher=mokytojas, date=pasirinkta_data).select_related("child", "cabinet"):
        rezervacijos[rez.time] = rez

    laikai = []

    for darbo in darbo_laikai:
        pertraukos = list(darbo.breaks.all())
        einamas = datetime.combine(pasirinkta_data, darbo.start_time)
        pabaiga = datetime.combine(pasirinkta_data, darbo.end_time)

        while einamas < pabaiga:
            laikas = einamas.time()

            # pertrauka
            pertrauka = False
            for p in pertraukos:
                if p.start_time <= laikas < p.end_time:
                    pertrauka = True
                    break
            if pertrauka:
                einamas += timedelta(minutes=darbo.interval)
                continue

            # praeitas laikas siandien
            if pasirinkta_data == siandien:
                dt = timezone.make_aware(datetime.combine(pasirinkta_data, laikas))
                if dt < dabar:
                    einamas += timedelta(minutes=darbo.interval)
                    continue

            rez = rezervacijos.get(laikas)

            if rez:
                if request_user and rez.user == request_user:
                    laikai.append({
                        "time": laikas.strftime("%H:%M"),
                        "status": "mine",
                        "reservation_id": rez.id
                    })
                else:
                    if not show_names:
                        # tevams kito vaiko/tevo vardas nerodomas - tik "Uzimta"
                        kas = "Užimta"
                    elif rez.reserved_first_name:
                        if rez.reserved_class:
                            kas = f"{rez.reserved_first_name} {rez.reserved_last_name} ({rez.reserved_class})"
                        else:
                            kas = f"{rez.reserved_first_name} {rez.reserved_last_name}"
                    elif rez.child:
                        klase_str = rez.child.klase.pavadinimas if rez.child.klase else "?"
                        kas = f"{rez.child.first_name} {rez.child.last_name} ({klase_str})"
                    else:
                        kas = "Užimta"

                    # mokytojui parodome, jei sitam laikui priskirtas kitas kabinetas,
                    # nei jo numatytasis (kabinetas buvo nurodytas kuriant darbo laika)
                    if show_names and rez.cabinet_id and rez.cabinet_id != mokytojas.kabinetas_id:
                        kas = f"{kas} · kabinetas: {rez.cabinet.pavadinimas}"

                    laikai.append({
                        "time": laikas.strftime("%H:%M"),
                        "status": "busy",
                        "by": kas
                    })
            else:
                laikai.append({
                    "time": laikas.strftime("%H:%M"),
                    "status": "free",
                    "by": ""
                })
            einamas += timedelta(minutes=darbo.interval)

    # dublikatai
    matyti = set()
    tvarkingi = []
    for x in laikai:
        if x["time"] not in matyti:
            matyti.add(x["time"])
            tvarkingi.append(x)

    tvarkingi.sort(key=lambda x: x["time"])
    return tvarkingi


# grafikas – filtruoja mokytojus pagal vaiko klase ir pokalbio tipa
@login_required
def teacher_schedule(request, date_str):
    try:
        pasirinkta_data = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return redirect("home")

    siandien = timezone.localdate()
    dabar = timezone.localtime()

    if pasirinkta_data < siandien:
        return redirect("home")

    profilis, _ = Profile.objects.get_or_create(user=request.user)
    aktyvus_vaikas = profilis.active_child

    # pokalbio tipas ateina is URL parametro
    tipas = request.GET.get("tipas", "individualus")
    if tipas not in ("individualus", "dalykininku"):
        tipas = "individualus"

    # filtro laukas
    paieska = request.GET.get("q")

    # bazinis filtras – mokytojai kurie turi darbo laiku sia data ir tipa
    mokytojai = (
        Teacher.objects
        .filter(working_hours__date=pasirinkta_data, working_hours__tipas=tipas)
        .distinct()
    )

    if tipas == "individualus":
        # individualus – rodome tik vaiko klasės auklėtoją
        if aktyvus_vaikas and aktyvus_vaikas.klase and aktyvus_vaikas.klase.aukletojas:
            mokytojai = mokytojai.filter(id=aktyvus_vaikas.klase.aukletojas.id)
        else:
            # vaikas nepasirinktas arba klasei nėra auklėtojo – nieko nerodome
            mokytojai = mokytojai.none()
    else:
        # dalykininku – filtruojame pagal klases kurias mokytojas moko
        if aktyvus_vaikas and aktyvus_vaikas.klase:
            from django.db.models import Count
            mokytojai = mokytojai.annotate(
                klases_kiekis=Count("klases")
            ).filter(
                Q(klases_kiekis=0) | Q(klases=aktyvus_vaikas.klase)
            ).distinct()

    # jei ivesta paieska – filtruojam
    if paieska:
        mokytojai = mokytojai.filter(
            Q(vardas__icontains=paieska) | #Tas pagaliukas yra OR operatorius
            Q(pavarde__icontains=paieska)
        )

    mokytojai = mokytojai.order_by("pavarde", "vardas")

    # mokytojai mato kitu tevu/vaiku vardus uzimtuose laikuose, tevai - ne
    ziurintis_mokytojas = get_teacher_for_user(request.user)
    rodyti_vardus = ziurintis_mokytojas is not None

    duomenys = []

    for mokytojas in mokytojai:
        darbo_laikai = (
            WorkingHours.objects
            .filter(mokytojai=mokytojas, date=pasirinkta_data, tipas=tipas)
            .prefetch_related("breaks")
        )

        tvarkingi = sudaryti_laikus(
            mokytojas, pasirinkta_data, darbo_laikai,
            request_user=request.user, show_names=rodyti_vardus,
        )

        pirmas_blokas = darbo_laikai.first()
        # kabinetas - jei darbo laiko blokui priskirtas savas kabinetas, rodome ji,
        # kitu atveju - mokytojo numatyta kabineta
        efektyvus_kabinetas = (pirmas_blokas.cabinet if pirmas_blokas and pirmas_blokas.cabinet else mokytojas.kabinetas)

        duomenys.append({
            "teacher": mokytojas,
            "kabinetas": efektyvus_kabinetas,
            "slots": tvarkingi,
            "intervalas": pirmas_blokas.interval if pirmas_blokas else 10,
        })

    return render(request, "reservations/teacher_schedule.html", {
        "date": pasirinkta_data.strftime("%Y-%m-%d"),
        "data": duomenys,
        "active_child": aktyvus_vaikas,
        "q": paieska,
        "tipas": tipas,
    })


# rezervacija
@login_required
def reserve_timeslot(request, teacher_id):
    if request.method != "POST":
        return redirect("home")

    mokytojas = get_object_or_404(Teacher, id=teacher_id)

    profilis, _ = Profile.objects.get_or_create(user=request.user)
    aktyvus_vaikas = profilis.active_child
    tipas = request.POST.get("tipas", "individualus")

    if not aktyvus_vaikas:
        messages.error(request, "Prieš rezervuodami, pasirinkite vaiką profilio skiltyje.")
        date_str = request.POST.get("date", "")
        return redirect(f"/schedule/{date_str}/?tipas={tipas}")

    datos_tekstas = request.POST.get("date")
    laiku_tekstas = request.POST.getlist("times")

    if not datos_tekstas or not laiku_tekstas:
        return redirect("home")

    try:
        data = datetime.strptime(datos_tekstas, "%Y-%m-%d").date()
    except ValueError:
        return redirect("home")

    siandien = timezone.localdate()
    dabar = timezone.localtime()

    if data < siandien:
        return redirect("home")

    try:
        laikai = sorted([datetime.strptime(t, "%H:%M").time() for t in laiku_tekstas])
    except:
        return redirect(f"/schedule/{datos_tekstas}/?tipas={tipas}")

    # max 3
    if len(laikai) > 3:
        messages.error(request, "Negalima daugiau, nei  3 rezervacijos")
        return redirect(f"/schedule/{datos_tekstas}/?tipas={tipas}")

    # randame intervala ir kabineta is darbo laiku
    intervalas = 10
    kabinetas = mokytojas.kabinetas
    if laikai:
        for wh in WorkingHours.objects.filter(mokytojai=mokytojas, date=data, tipas=tipas):
            if wh.start_time <= laikai[0] < wh.end_time:
                intervalas = wh.interval
                kabinetas = wh.cabinet or mokytojas.kabinetas
                break

    # is eiles pagal intervala
    if len(laikai) > 1 and not laikai_is_eiles(data, laikai, intervalas):
        messages.error(request, "Galima rezervuoti laikus tik iš eilės")
        return redirect(f"/schedule/{datos_tekstas}/?tipas={tipas}")

    # praeitis siandien
    if data == siandien:
        for t in laikai:
            if timezone.make_aware(datetime.combine(data, t)) < dabar:
                return redirect(f"/schedule/{datos_tekstas}/?tipas={tipas}")

    # telpa i darbo laika (tikriname tik to tipo darbo laikus)
    for t in laikai:
        if not laikas_leistinas(mokytojas, data, t, tipas):
            return redirect(f"/schedule/{datos_tekstas}/?tipas={tipas}")

    # uzimta pas ta pati mokytoja
    if Reservation.objects.filter(teacher=mokytojas, date=data, time__in=laikai).exists():
        return redirect(f"/schedule/{datos_tekstas}/?tipas={tipas}")

    # vienas tevas negali buti dviejose vietose tuo paciu metu –
    # tikriname ar sio vartotojo paskyra neturi rezervacijos tuo paciu laiku pas kita mokytoja
    if Reservation.objects.filter(user=request.user, date=data, time__in=laikai).exists():
        messages.error(request, "Tuo laiku jau turite rezervaciją pas kitą mokytoją")
        return redirect(f"/schedule/{datos_tekstas}/?tipas={tipas}")

    # pas ta pati mokytoja per diena max 3 – skaiciuojame pagal vaika
    jau_turi = list(
        Reservation.objects
        .filter(child=aktyvus_vaikas, teacher=mokytojas, date=data)
        .values_list("time", flat=True)
    )

    visi = sorted(set(jau_turi + laikai))

    if len(visi) > 3:
        messages.error(request, "Galima rezervuoti ne daugiau nei 3 laikus pas vieną mokytoją")
        return redirect(f"/schedule/{datos_tekstas}/?tipas={tipas}")

    # visi sio vaiko laikai pas si mokytoja sia diena turi eiti is eiles be tarpu
    if not laikai_is_eiles(data, visi, intervalas):
        messages.error(request, "Laikai turi eiti iš eilės be tarpų")
        return redirect(f"/schedule/{datos_tekstas}/?tipas={tipas}")

    patvirtinta = request.POST.get("confirm")

    # jei dar nepatvirtinta – rodome confirm puslapi
    if patvirtinta != "yes":
        return render(request, "reservations/confirm_reservation.html", {
            "teacher": mokytojas,
            "date": datos_tekstas,
            "times": [t.strftime("%H:%M") for t in laikai],
            "tipas": tipas,
            "kabinetas": kabinetas,
        })

    # kuriam
    klase_str = aktyvus_vaikas.klase.pavadinimas if aktyvus_vaikas.klase else ""

    try:
        for t in laikai:
            Reservation.objects.create(
                user=request.user,
                teacher=mokytojas,
                date=data,
                time=t,
                child=aktyvus_vaikas,
                reserved_first_name=aktyvus_vaikas.first_name,
                reserved_last_name=aktyvus_vaikas.last_name,
                reserved_class=klase_str,
                cabinet=kabinetas,
            )
        messages.success(request, "Rezervacija sėkmingai sukurta")
    except IntegrityError:
        return redirect(f"/schedule/{datos_tekstas}/?tipas={tipas}")

    return redirect(f"/schedule/{datos_tekstas}/?tipas={tipas}")


# profilis
@login_required
def edit_profile(request):
    profilis, _ = Profile.objects.get_or_create(user=request.user)
    vaikai = Child.objects.filter(user=request.user).order_by("last_name", "first_name")

    edit_id = request.GET.get("edit")
    edit_child = None

    if edit_id:
        try:
            edit_child = Child.objects.get(id=int(edit_id), user=request.user)
        except:
            edit_child = None

    if edit_child:
        child_forma = ChildForm(instance=edit_child)
    else:
        child_forma = ChildForm()

    return render(request, "reservations/edit_profile.html", {
        "children": vaikai,
        "active_child": profilis.active_child,
        "child_form": child_forma,
        "edit_child": edit_child,
    })


@login_required
def add_child(request):
    if request.method != "POST":
        return redirect("edit_profile")

    profilis, _ = Profile.objects.get_or_create(user=request.user)
    child_id = request.POST.get("child_id")

    if child_id:
        try:
            vaikas = Child.objects.get(id=int(child_id), user=request.user)
        except:
            return redirect("edit_profile")

        forma = ChildForm(request.POST, instance=vaikas)
        if forma.is_valid():
            forma.save()
        return redirect("edit_profile")

    forma = ChildForm(request.POST)
    if forma.is_valid():
        vaikas = forma.save(commit=False)
        vaikas.user = request.user
        vaikas.save()

        if not profilis.active_child:
            profilis.active_child = vaikas
            profilis.save()

    return redirect("edit_profile")

# vaiko ištrynimas – tik savininkas gali ištrinti savo vaiką
@login_required
def delete_child(request, child_id):
    profilis, _ = Profile.objects.get_or_create(user=request.user)
    vaikas = get_object_or_404(Child, id=child_id, profile=profilis)

    if request.method == "POST":
        # jei trinamas vaikas buvo aktyvus, išvalome aktyvų vaiką
        if profilis.active_child == vaikas:
            profilis.active_child = None
            profilis.save()
        vaikas.delete()
        messages.success(request, "Vaikas ištrintas")
        return redirect("edit_profile")

    return redirect("edit_profile")

@login_required
def set_active_child(request, child_id):
    profilis, _ = Profile.objects.get_or_create(user=request.user)
    vaikas = get_object_or_404(Child, id=child_id, user=request.user)

    profilis.active_child = vaikas
    profilis.save()

    return redirect("edit_profile")


# mano rezervacijos
@login_required
def my_reservations(request):
    dabar = timezone.localtime()
    rezervacijos = Reservation.objects.filter(user=request.user).order_by("date", "time")

    sarasas = []
    for r in rezervacijos:
        rez_dt = timezone.make_aware(datetime.combine(r.date, r.time))
        galima_atsaukti = (rez_dt - dabar) >= timedelta(hours=24)
        sarasas.append({"r": r, "can_cancel": galima_atsaukti})

    return render(request, "reservations/my_reservations.html", {"items": sarasas})


# atsaukimas
@login_required
def cancel_reservation(request, reservation_id):
    rezervacija = get_object_or_404(Reservation, id=reservation_id, user=request.user)

    rez_dt = timezone.make_aware(datetime.combine(rezervacija.date, rezervacija.time))
    dabar = timezone.localtime()

    # next_url – kur grįžti po atšaukimo arba klaidos
    next_url = request.POST.get("next") or request.GET.get("next") or ""

    if rez_dt - dabar < timedelta(hours=24):
        messages.error(request, "Rezervacijos nebegalima atšaukti (<24h)")
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect("my_reservations")

    if request.method == "POST":
        rezervacija.delete()
        messages.success(request, "Rezervacija atšaukta")
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect("my_reservations")

    return render(request, "reservations/cancel_reservation.html", {
        "r": rezervacija,
        "next_url": next_url,
    })


# Mokytojo grafikas 

@login_required
def teacher_dashboard(request):
    mokytojas = get_teacher_for_user(request.user)
    if not mokytojas:
        return redirect("home")

    siandien = timezone.localdate()

    darbo_laikai = (
        WorkingHours.objects
        .filter(mokytojai=mokytojas, date__gte=siandien)
        .prefetch_related("breaks", "mokytojai")
        .order_by("date", "start_time")
    )

    wh_forma = WorkingHoursForm()

    # kiekvienam darbo laiko blokui iskart sudedame ir laisvu/uzimtu laiku peržiūrą,
    # kad pertraukas butu galima tvarkyti tiesiai cia pat, prie to paties bloko
    blokai = []
    for wh in darbo_laikai:
        blokai.append({
            "wh": wh,
            "slots": sudaryti_laikus(mokytojas, wh.date, [wh]),
        })

    return render(request, "reservations/teacher_dashboard.html", {
        "mokytojas": mokytojas,
        "blokai": blokai,
        "wh_form": wh_forma,
    })


@login_required
def teacher_add_workinghours(request):
    mokytojas = get_teacher_for_user(request.user)
    if not mokytojas:
        return redirect("home")

    if request.method != "POST":
        return redirect("teacher_dashboard")

    forma = WorkingHoursForm(request.POST)
    if forma.is_valid():
        wh = forma.save(commit=False)
        # mokytojas gali pridėti tik individualius pokalbius
        wh.tipas = "individualus"

        if wh.start_time >= wh.end_time:
            messages.error(request, "Pabaigos laikas turi būti vėliau, nei pradžios laikas")
            return redirect("teacher_dashboard")

        if wh.date < timezone.localdate():
            messages.error(request, "Negalima pridėti praeities datų")
            return redirect("teacher_dashboard")

        # patikrinti ar naujasis laikas nesikerta su kitu tipas tuo paciu laiku
        persidengiantys = WorkingHours.objects.filter(
            mokytojai=mokytojas,
            date=wh.date,
            start_time__lt=wh.end_time,
            end_time__gt=wh.start_time,
        ).exclude(tipas=wh.tipas)

        if persidengiantys.exists():
            kitas = persidengiantys.first()
            messages.error(
                request,
                f"Laikas {wh.start_time.strftime('%H:%M')}–{wh.end_time.strftime('%H:%M')} "
                f"kertasi su kitu pokalbio tipu ({kitas.get_tipas_display()}: "
                f"{kitas.start_time.strftime('%H:%M')}–{kitas.end_time.strftime('%H:%M')})"
            )
            return redirect("teacher_dashboard")

        # patikrinti ar nesikerta su tuo paciu tipas
        persidengiantys_same = WorkingHours.objects.filter(
            mokytojai=mokytojas,
            date=wh.date,
            tipas=wh.tipas,
            start_time__lt=wh.end_time,
            end_time__gt=wh.start_time,
        )

        if persidengiantys_same.exists():
            kitas = persidengiantys_same.first()
            messages.error(
                request,
                f"Laikas {wh.start_time.strftime('%H:%M')}–{wh.end_time.strftime('%H:%M')} "
                f"kertasi su jau esamu tos pacios tipo laiku "
                f"({kitas.start_time.strftime('%H:%M')}–{kitas.end_time.strftime('%H:%M')})"
            )
            return redirect("teacher_dashboard")

        wh.save()
        wh.mokytojai.add(mokytojas)

        # viena pertrauka iš tos pačios formos – nebūtina
        bs = request.POST.get("break_start", "").strip()
        be = request.POST.get("break_end", "").strip()

        if bs and be:
            try:
                ps = datetime.strptime(bs, "%H:%M").time()
                pe = datetime.strptime(be, "%H:%M").time()
                desc = request.POST.get("break_desc", "").strip()

                if ps < pe and ps >= wh.start_time and pe <= wh.end_time:
                    Break.objects.create(working_hours=wh, start_time=ps, end_time=pe, description=desc)
                else:
                    messages.warning(request, "Pertrauka neišsaugota – neteisingas laikas")
            except ValueError:
                pass

        messages.success(request, "Darbo laikas pridėtas")
    else:
        messages.error(request, "Neteisingi duomenys")

    return redirect("teacher_dashboard")


@login_required
def teacher_delete_workinghours(request, wh_id):
    mokytojas = get_teacher_for_user(request.user)
    if not mokytojas:
        return redirect("home")

    wh = get_object_or_404(WorkingHours, id=wh_id, mokytojai=mokytojas)

    if request.method == "POST":
        # Istrinti susijusias rezervacijas
        Reservation.objects.filter(teacher=mokytojas, date=wh.date,
                                   time__gte=wh.start_time, time__lt=wh.end_time).delete()
        wh.mokytojai.remove(mokytojas)
        # Jei niekas kitas nepriskirtas – trinam patį įrašą
        if not wh.mokytojai.exists():
            wh.delete()
        messages.success(request, "Darbo laikas ištrintas")

    return redirect("teacher_dashboard")


@login_required
def teacher_add_break(request, wh_id):
    mokytojas = get_teacher_for_user(request.user)
    if not mokytojas:
        return redirect("home")

    wh = get_object_or_404(WorkingHours, id=wh_id, mokytojai=mokytojas)

    if request.method != "POST":
        return redirect("teacher_dashboard")

    forma = BreakForm(request.POST)
    if forma.is_valid():
        pertrauka = forma.save(commit=False)

        if pertrauka.start_time >= pertrauka.end_time:
            messages.error(request, "Pertraukos pabaiga turi būti vėliau, nei pradžia")
            return redirect("teacher_dashboard")

        if pertrauka.start_time < wh.start_time or pertrauka.end_time > wh.end_time:
            messages.error(request, "Pertrauka turi būti darbo laiko ribose")
            return redirect("teacher_dashboard")

        # apsauga – jei tuo laiku jau yra tevu rezervacija, pertraukos pridėti negalima
        uzimta = Reservation.objects.filter(
            teacher=mokytojas,
            date=wh.date,
            time__gte=pertrauka.start_time,
            time__lt=pertrauka.end_time,
        ).exists()

        if uzimta:
            messages.error(request, "Pasirinktu laiko intervalu jau yra rezervacijos")
            return redirect("teacher_dashboard")

        pertrauka.working_hours = wh
        pertrauka.save()
        messages.success(request, "Pertrauka pridėta")
    else:
        messages.error(request, "Neteisingi pertraukos duomenys")

    return redirect("teacher_dashboard")


@login_required
def teacher_delete_break(request, break_id):
    mokytojas = get_teacher_for_user(request.user)
    if not mokytojas:
        return redirect("home")

    pertrauka = get_object_or_404(Break, id=break_id, working_hours__mokytojai=mokytojas)

    if request.method == "POST":
        pertrauka.delete()
        messages.success(request, "Pertrauka ištrinta")

    return redirect("teacher_dashboard")


#ar mokytojas egzistuoja patikra
def teacher_context(request):
    if request.user.is_authenticated and request.user.email:
        is_teacher = Teacher.objects.filter(email__iexact=request.user.email).exists()
    else:
        is_teacher = False
    return {"is_teacher": is_teacher}
