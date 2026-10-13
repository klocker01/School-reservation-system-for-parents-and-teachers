from django.contrib import admin, messages
from django.contrib.admin.utils import NotRelationField, get_fields_from_path
from django.contrib.admin.views.main import ChangeList
from django import forms
from django.core.exceptions import FieldDoesNotExist, PermissionDenied, ValidationError
from django.db import models, transaction
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce, Concat
from django.shortcuts import render, redirect
from django.urls import path
from datetime import datetime, timedelta

from .importas import importuoti_mokytojus, importuoti_tevu_emailus
from .duomenu_importas import (
    MOKYTOJU_STULPELIAI, nuskaityti_mokytoju_sarasa, perziureti_importa, vykdyti_importa,
)

from .models import (
    Subject, Cabinet, Klase, Teacher, WorkingHours, Break, Reservation, Profile, Child, LeistinasEmail,
    Vadovas, VadovoLaikas, VadovoPertrauka, VadovoRezervacija, DuomenuImportas,
)
from .rusiavimas import lt, raktas


# Paspaudus stulpelio antraste Django teksta rikiuoja pagal simboliu kodus
# (C, S, Z su varnele - saraso gale, 10S pries 6F). Cia visi tekstiniai laukai
# perrikiuojami lietuviskai (zr. rusiavimas.py)
def lt_tvarka(modelis, laukas):
    if not isinstance(laukas, str):
        return laukas
    pavadinimas = laukas.removeprefix("-")
    try:
        galutinis = get_fields_from_path(modelis, pavadinimas)[-1]
    except (FieldDoesNotExist, NotRelationField):
        return laukas
    if not isinstance(galutinis, (models.CharField, models.TextField)):
        return laukas
    return lt(pavadinimas).desc() if laukas.startswith("-") else lt(pavadinimas).asc()


class LtChangeList(ChangeList):
    def get_ordering(self, request, queryset):
        return [lt_tvarka(self.model, laukas) for laukas in super().get_ordering(request, queryset)]


# visi admin sarasai paveldi is cia, kad rikiavimas butu lietuviskas
class RikiuojamasAdmin(admin.ModelAdmin):
    def get_changelist(self, request, **kwargs):
        return LtChangeList


# stulpeliai is keliu reiksmiu (dalykai, klases, mokytojai) rikiuojami pagal
# pirma reiksme - ta pacia, kuri sarase rodoma pirma. Tusti eina gale
def pagal_pirma(anotacija):
    return lt(anotacija).asc(nulls_last=True)


@admin.register(Subject)
class SubjectAdmin(RikiuojamasAdmin):
    list_display = ("pavadinimas",)
    search_fields = ("pavadinimas",)


@admin.register(Cabinet)
class CabinetAdmin(RikiuojamasAdmin):
    list_display = ("pavadinimas",)
    search_fields = ("pavadinimas",)


# adminas tvarko klases čia
@admin.register(Klase)
class KlaseAdmin(RikiuojamasAdmin):
    list_display = ("pavadinimas", "aukletojas")
    list_select_related = ("aukletojas",)
    search_fields = ("pavadinimas",)
    fields = ("pavadinimas", "aukletojas")


# forma mokytoju sarasui ikelti
class MokytojuImportoForma(forms.Form):
    failas = forms.FileField(
        label="Failas",
    )


@admin.register(Teacher)
class TeacherAdmin(RikiuojamasAdmin):
    change_list_template = "admin/reservations/teacher/change_list.html"
    list_display = ("vardas", "pavarde", "dalykai_text", "klases_text", "kabinetas", "email")
    search_fields = ("vardas", "pavarde", "email")
    list_filter = ("kabinetas", "klases")
    fields = ("vardas", "pavarde", "kabinetas", "dalykai", "klases", "email")
    filter_horizontal = ("dalykai", "klases")

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("kabinetas")
            .prefetch_related("dalykai", "klases")
            .annotate(
                pirmas_dalykas=Subquery(
                    Subject.objects.filter(teacher=OuterRef("pk"))
                    .order_by(lt("pavadinimas")).values("pavadinimas")[:1]
                ),
                pirma_klase=Subquery(
                    Klase.objects.filter(teacher=OuterRef("pk"))
                    .order_by(lt("pavadinimas")).values("pavadinimas")[:1]
                ),
            )
        )

    # savas adresas mokytoju sarasui ikelti
    def get_urls(self):
        urls = super().get_urls()
        savi = [
            path(
                "importuoti/",
                self.admin_site.admin_view(self.importo_puslapis),
                name="reservations_teacher_importuoti",
            ),
        ]
        return savi + urls

    def importo_puslapis(self, request):
        if request.method == "POST":
            forma = MokytojuImportoForma(request.POST, request.FILES)
            if forma.is_valid():
                failas = request.FILES["failas"]
                ataskaita = importuoti_mokytojus(failas, failas.name)

                if ataskaita["sukurta"] or ataskaita["atnaujinta"]:
                    messages.success(
                        request,
                        f"Sukurta nauju: {ataskaita['sukurta']}, "
                        f"atnaujinta: {ataskaita['atnaujinta']}, "
                        f"praleista: {ataskaita['praleista']}"
                    )
                else:
                    messages.warning(
                        request,
                        f"Naujų mokytojų nepridėta. Praleista eilučių: {ataskaita['praleista']}"
                    )

                # klaidas rodome po viena, kad butu aisku kurioje eiluteje kas negerai
                for klaida in ataskaita["klaidos"][:15]:
                    messages.error(request, klaida)
                if len(ataskaita["klaidos"]) > 15:
                    messages.error(
                        request,
                        f"...ir dar {len(ataskaita['klaidos']) - 15} klaidos"
                    )

                return redirect("admin:reservations_teacher_changelist")
        else:
            forma = MokytojuImportoForma()

        return render(request, "admin/reservations/teacher/importuoti.html", {
            "forma": forma,
            "opts": self.model._meta,
            "title": "Įkelti mokytojų sąrašą",
        })

    # sudeti visus mokytojo dalykus i viena teksta
    def dalykai_text(self, obj):
        dal = obj.dalykai.all()
        if not dal:
            return "-"
        return ", ".join([d.pavadinimas for d in dal])

    dalykai_text.short_description = "Dalykai"
    dalykai_text.admin_order_field = pagal_pirma("pirmas_dalykas")

    # sudeti visas mokytojo klases i viena teksta
    def klases_text(self, obj):
        kl = obj.klases.all()
        if not kl:
            return "-"
        return ", ".join([k.pavadinimas for k in kl])

    klases_text.short_description = "Klasės"
    klases_text.admin_order_field = pagal_pirma("pirma_klase")


# kol adminas perziuri pakeitimus, patikrintos failo eilutes laikomos sesijoje
IMPORTO_RAKTAS = "duomenu_importas"


# Skiltis "Importuoti duomenys" - pilnas mokytoju sarasas is mokyklos lenteles.
# Saraso cia nera: paspaudus skilti iskart atsidaro failo ikelimas
@admin.register(DuomenuImportas)
class DuomenuImportasAdmin(admin.ModelAdmin):
    # importas kuria, keicia ir (sujungdamas dublikatus) trina mokytojus ir klases
    TEISES = [
        f"reservations.{veiksmas}_{modelis}"
        for modelis in ("teacher", "klase") for veiksmas in ("add", "change", "delete")
    ]

    def _gali(self, request):
        return request.user.has_perms(self.TEISES)

    def has_view_permission(self, request, obj=None):
        return self._gali(request)

    def has_change_permission(self, request, obj=None):
        return self._gali(request)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        info = self.opts.app_label, self.opts.model_name
        return [
            path("", self.admin_site.admin_view(self.ikelimas), name="%s_%s_changelist" % info),
            path("patvirtinti/", self.admin_site.admin_view(self.patvirtinimas), name="%s_%s_patvirtinti" % info),
        ]

    def _puslapis(self, request, sablonas, **kontekstas):
        if not self._gali(request):
            raise PermissionDenied
        return render(request, f"admin/reservations/duomenuimportas/{sablonas}", {
            **self.admin_site.each_context(request),
            "opts": self.opts,
            "title": "Importuoti duomenys",
            **kontekstas,
        })

    def _ikelimo_puslapis(self, request, forma, klaidos=()):
        return self._puslapis(
            request, "importuoti.html", forma=forma, klaidos=klaidos, stulpeliai=MOKYTOJU_STULPELIAI,
        )

    def _perziura(self, request, planas, duomenys, zinute=""):
        return self._puslapis(
            request, "perziura.html", planas=planas, failas=duomenys["failas"],
            lapas=duomenys["lapas"], zinute=zinute,
        )

    # 1 zingsnis: failas perskaitomas ir patikrinamas, parodoma kas bus pakeista.
    # Duomenu baze dar nelieciama
    def ikelimas(self, request):
        if not self._gali(request):
            raise PermissionDenied

        if request.method != "POST":
            return self._ikelimo_puslapis(request, MokytojuImportoForma())

        if "tik_dublikatai" in request.POST:
            eilutes, failas, lapas = [], "", ""
        else:
            forma = MokytojuImportoForma(request.POST, request.FILES)
            if not forma.is_valid():
                return self._ikelimo_puslapis(request, forma)
            failas = request.FILES["failas"]
            nuskaityta = nuskaityti_mokytoju_sarasa(failas, failas.name)
            if nuskaityta["klaidos"]:
                return self._ikelimo_puslapis(request, forma, nuskaityta["klaidos"])
            eilutes, failas, lapas = nuskaityta["eilutes"], failas.name, nuskaityta["lapas"]

        planas = perziureti_importa(eilutes)
        if planas["klaidos"]:
            return self._ikelimo_puslapis(request, MokytojuImportoForma(), planas["klaidos"])

        duomenys = {"eilutes": eilutes, "failas": failas, "lapas": lapas, "parasas": planas["parasas"]}
        request.session[IMPORTO_RAKTAS] = duomenys
        return self._perziura(request, planas, duomenys)

    # 2 zingsnis: adminas patvirtino - irasom
    def patvirtinimas(self, request):
        if not self._gali(request):
            raise PermissionDenied

        if request.method != "POST":
            return redirect("admin:reservations_duomenuimportas_changelist")

        duomenys = request.session.get(IMPORTO_RAKTAS)
        if not duomenys:
            messages.error(request, "Įkelto failo duomenų nebėra – įkelkite failą iš naujo. Niekas nepakeista.")
            return redirect("admin:reservations_duomenuimportas_changelist")

        planas = vykdyti_importa(duomenys["eilutes"], duomenys["parasas"])

        if not planas["ivykdyta"]:
            if planas["klaidos"]:
                del request.session[IMPORTO_RAKTAS]
                return self._ikelimo_puslapis(request, MokytojuImportoForma(), planas["klaidos"])
            # kol adminas ziurejo, kazkas pakeite duomenis - parodom nauja plana
            duomenys["parasas"] = planas["parasas"]
            request.session[IMPORTO_RAKTAS] = duomenys
            return self._perziura(
                request, planas, duomenys,
                "Kol peržiūrėjote, duomenys sistemoje pasikeitė. Niekas nepakeista – patikrinkite dar kartą.",
            )

        del request.session[IMPORTO_RAKTAS]
        messages.success(
            request,
            f"Duomenys įrašyti: naujų mokytojų {len(planas['nauji'])}, "
            f"atnaujinta {len(planas['atnaujinami'])}, nepakito {planas['nepakite']}, "
            f"sujungta dublikatų {len(planas['dublikatai'])}"
        )
        return redirect("admin:reservations_duomenuimportas_changelist")


class BreakInline(admin.TabularInline):
    model = Break
    extra = 1
    fields = ("start_time", "end_time", "description", "pasalintas_laikas")


# Trinant laiko bloka per admin panele kartu trinamos ir jo rezervacijos - kaip
# ir trinant is mokytojo/vadovo grafiko. Rezervacijos su bloku tiesiogiai
# nesusietos (tik per data ir laika), tai tikrinam, kad laiko nedengtu kitas
# to paties mokytojo/vadovo blokas - tokios rezervacijos turi likti
def _istrinti_nepadengtas(rezervacijos, kiti_blokai):
    kiti = list(kiti_blokai)
    for r in rezervacijos:
        if not any(k.start_time <= r.time < k.end_time for k in kiti):
            r.delete()


def istrinti_darbo_laiko_rezervacijas(wh):
    for mokytojas in wh.mokytojai.all():
        _istrinti_nepadengtas(
            Reservation.objects.filter(
                teacher=mokytojas, date=wh.date, tipas=wh.tipas,
                time__gte=wh.start_time, time__lt=wh.end_time,
            ),
            WorkingHours.objects.filter(mokytojai=mokytojas, date=wh.date, tipas=wh.tipas).exclude(id=wh.id),
        )


def istrinti_vadovo_laiko_rezervacijas(blokas):
    _istrinti_nepadengtas(
        VadovoRezervacija.objects.filter(
            vadovas_id=blokas.vadovas_id, date=blokas.date,
            time__gte=blokas.start_time, time__lt=blokas.end_time,
        ),
        VadovoLaikas.objects.filter(vadovas_id=blokas.vadovas_id, date=blokas.date).exclude(id=blokas.id),
    )


@admin.register(WorkingHours)
class WorkingHoursAdmin(RikiuojamasAdmin):
    list_display = ("date", "start_time", "end_time", "tipas", "kabinetas", "mokytojai_list")
    list_filter = ("date", "tipas", "cabinet")
    filter_horizontal = ("mokytojai",)
    inlines = [BreakInline]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("cabinet")
            .prefetch_related("mokytojai__kabinetas")
            .annotate(
                # kaip rodoma stulpelyje: bloko kabinetas, o jei jo nera - mokytojo numatytas
                kabineto_rikiavimas=Coalesce(
                    "cabinet__pavadinimas",
                    Subquery(
                        Cabinet.objects.filter(teacher__working_hours=OuterRef("pk"))
                        .order_by(lt("pavadinimas")).values("pavadinimas")[:1]
                    ),
                ),
                pirmas_mokytojas=Subquery(
                    Teacher.objects.filter(working_hours=OuterRef("pk"))
                    .order_by(lt("pavarde"), lt("vardas"))
                    .annotate(pavarde_vardas=Concat("pavarde", Value(" "), "vardas"))
                    .values("pavarde_vardas")[:1]
                ),
            )
        )

    # bloko kabinetas laukas tuscias, jei mokytojas pridedamas laika kabineto
    # nepasirinko - tada pokalbis vyksta mokytojo numatytame kabinete (kaip ir
    # rodoma svetaineje), tai ji ir parodom
    def kabinetas(self, obj):
        if obj.cabinet:
            return obj.cabinet.pavadinimas
        numatyti = sorted({m.kabinetas.pavadinimas for m in obj.mokytojai.all() if m.kabinetas}, key=raktas)
        if not numatyti:
            return "-"
        return ", ".join(numatyti) + " (numatytas)"

    kabinetas.short_description = "Kabinetas"
    kabinetas.admin_order_field = pagal_pirma("kabineto_rikiavimas")

    def mokytojai_list(self, obj):
        visi = obj.mokytojai.all()
        if not visi:
            return "-"
        return ", ".join([f"{m.vardas} {m.pavarde}" for m in visi])

    mokytojai_list.short_description = "Mokytojai"
    mokytojai_list.admin_order_field = pagal_pirma("pirmas_mokytojas")

    def delete_model(self, request, obj):
        with transaction.atomic():
            istrinti_darbo_laiko_rezervacijas(obj)
            super().delete_model(request, obj)

    # trinant kelis is saraso (veiksmas "Ištrinti pasirinktus")
    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            for wh in queryset:
                istrinti_darbo_laiko_rezervacijas(wh)
            super().delete_queryset(request, queryset)


# Vartotojo (tevu paskyros) stulpelis Django rikiuojamas pagal id, tai
# rodom ji per sia funkcija - rikiuojama pagal vartotojo varda, kuris ir rodomas
def tevu_paskyra(obj):
    return obj.user if obj.user else "-"

tevu_paskyra.short_description = "Tėvų paskyra"
tevu_paskyra.admin_order_field = lt("user__username")


@admin.register(Child)
class ChildAdmin(RikiuojamasAdmin):
    list_display = ("first_name", "last_name", "klase", tevu_paskyra)
    list_select_related = ("klase", "user")
    search_fields = ("first_name", "last_name", "user__email")
    list_filter = ("klase",)


@admin.register(Profile)
class ProfileAdmin(RikiuojamasAdmin):
    list_display = (tevu_paskyra, "active_child")
    list_select_related = ("user", "active_child__klase")
    search_fields = ("user__email",)


# tikrina ar laikas telpa i darbo laikus ir ne per pertrauka
def ar_admin_laikas_leistinas(mokytojas, data, laikas):
    darbo_laikai = (
        WorkingHours.objects
        .filter(mokytojai=mokytojas, date=data)
        .prefetch_related("breaks")
    )

    if not darbo_laikai.exists():
        return False

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


class ReservationAdminForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = (
            "teacher",
            "date",
            "time",
            "reserved_first_name",
            "reserved_last_name",
            "reserved_class",
            "user",
            "child",
            "cabinet",
        )

    # kai adminas kuria rezervacija – tikrinam laika
    def clean(self):
        duom = super().clean()

        teacher = duom.get("teacher")
        data = duom.get("date")
        time = duom.get("time")

        if not teacher or not data or not time:
            return duom

        if not ar_admin_laikas_leistinas(teacher, data, time):
            raise ValidationError("Laikas turi būti mokytojo darbo laiko ribose ir ne per pertrauką")

        return duom


@admin.register(Reservation)
class ReservationAdmin(RikiuojamasAdmin):
    form = ReservationAdminForm
    list_display = (
        "id",
        "teacher",
        "date",
        "time",
        "reserved_first_name",
        "reserved_last_name",
        "reserved_class",
        tevu_paskyra,
        "child",
        "cabinet",
    )
    list_select_related = ("teacher", "user", "child__klase", "cabinet")
    list_filter = ("teacher", "date", "cabinet")
    search_fields = (
        "reserved_first_name",
        "reserved_last_name",
        "reserved_class",
        "user__email",
        "teacher__vardas",
        "teacher__pavarde",
    )
    ordering = ("-date", "-time")


# adminas cia deda tevu adresus, kuriems leidziama prisijungti
@admin.register(LeistinasEmail)
class LeistinasEmailAdmin(RikiuojamasAdmin):
    change_list_template = "admin/reservations/leistinasemail/change_list.html"
    list_display = ("email", "pastaba", "pridetas")
    search_fields = ("email", "pastaba")
    ordering = ("email",)

    # savas adresas tevu el. pastu sarasui ikelti
    def get_urls(self):
        urls = super().get_urls()
        savi = [
            path(
                "importuoti/",
                self.admin_site.admin_view(self.importo_puslapis),
                name="reservations_leistinasemail_importuoti",
            ),
        ]
        return savi + urls

    def importo_puslapis(self, request):
        if request.method == "POST":
            forma = MokytojuImportoForma(request.POST, request.FILES)
            if forma.is_valid():
                failas = request.FILES["failas"]
                ataskaita = importuoti_tevu_emailus(failas, failas.name)

                santrauka = (
                    f"Pridėta naujų: {ataskaita['prideta']}, "
                    f"jau buvo sąraše: {ataskaita['jau_buvo']}, "
                    f"pasikartojo faile: {ataskaita['pasikartojo']}"
                )
                if ataskaita["prideta"]:
                    messages.success(request, santrauka)
                else:
                    messages.warning(request, santrauka)

                for klaida in ataskaita["klaidos"][:15]:
                    messages.error(request, klaida)
                if len(ataskaita["klaidos"]) > 15:
                    messages.error(
                        request,
                        f"...ir dar {len(ataskaita['klaidos']) - 15} klaidos"
                    )

                return redirect("admin:reservations_leistinasemail_changelist")
        else:
            forma = MokytojuImportoForma()

        return render(request, "admin/reservations/leistinasemail/importuoti.html", {
            "forma": forma,
            "opts": self.model._meta,
            "title": "Įkelti tėvų el. paštų sąrašą",
        })


# adminas priskiria vadovo el. pasta - pagal ji sistema atpazista vadova
@admin.register(Vadovas)
class VadovasAdmin(RikiuojamasAdmin):
    list_display = ("vardas", "pavarde", "email")
    search_fields = ("vardas", "pavarde", "email")
    fields = ("vardas", "pavarde", "email")


class VadovoPertraukaInline(admin.TabularInline):
    model = VadovoPertrauka
    extra = 0
    fields = ("start_time", "end_time", "description", "pasalintas_laikas")


@admin.register(VadovoLaikas)
class VadovoLaikasAdmin(RikiuojamasAdmin):
    list_display = ("vadovas", "date", "start_time", "end_time", "interval", "cabinet")
    list_select_related = ("vadovas", "cabinet")
    list_filter = ("vadovas", "date")
    inlines = [VadovoPertraukaInline]

    def delete_model(self, request, obj):
        with transaction.atomic():
            istrinti_vadovo_laiko_rezervacijas(obj)
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            for blokas in queryset:
                istrinti_vadovo_laiko_rezervacijas(blokas)
            super().delete_queryset(request, queryset)


@admin.register(VadovoRezervacija)
class VadovoRezervacijaAdmin(RikiuojamasAdmin):
    list_display = ("vadovas", "mokytojas", "date", "time", "cabinet")
    list_select_related = ("vadovas", "mokytojas", "cabinet")
    list_filter = ("vadovas", "date")
    search_fields = ("mokytojas__vardas", "mokytojas__pavarde", "vadovas__pavarde")
    ordering = ("-date", "-time")
    
