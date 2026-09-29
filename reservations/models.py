from django.db import models
from django.db.models.functions import Cast, Lower
from django.contrib.auth.models import User


class Subject(models.Model):
    pavadinimas = models.CharField(max_length=100, verbose_name="Pavadinimas")

    class Meta:
        verbose_name = "Dalykas"
        verbose_name_plural = "Dalykai"

    def __str__(self):
        return self.pavadinimas



class Cabinet(models.Model):
    pavadinimas = models.CharField(max_length=50, verbose_name="Pavadinimas")

    class Meta:
        verbose_name = "Kabinetas"
        verbose_name_plural = "Kabinetai"

    def __str__(self):
        return self.pavadinimas



class Klase(models.Model):
    pavadinimas = models.CharField(max_length=20, verbose_name="Pavadinimas")

    # adminas paskiria viena aukletoja klasei
    aukletojas = models.ForeignKey(
        "Teacher",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auklejamos_klases",
        verbose_name="Klasės auklėtojas",
    )

    class Meta:
        # "natūralus" rūšiavimas: pirma pagal skaičių (6F, 9D, 10S, 11V), o ne
        # kaip tekstas (10S, 11V, 6F, 9D); esant vienodam skaičiui - pagal raidę,
        # nekreipiant dėmesio į didžiąsias/mažąsias. SQLite CAST("10S" AS INTEGER)
        # paima pradžios skaitmenis = 10, klasė be skaičiaus gauna 0 ir eina pirma.
        # PASTABA: Postgres toks CAST mestų klaidą - pereinant reiktų perdaryti
        ordering = (
            Cast("pavadinimas", output_field=models.IntegerField()).asc(),
            Lower("pavadinimas").asc(),
        )
        verbose_name = "Klasė"
        verbose_name_plural = "Klasės"

    def __str__(self):
        return self.pavadinimas


class Teacher(models.Model):
    vardas = models.CharField(max_length=50, verbose_name="Vardas")
    pavarde = models.CharField(max_length=50, verbose_name="Pavardė")

    # vienas mokytojas gali tureti kelis dalykus
    dalykai = models.ManyToManyField(Subject, blank=True, verbose_name="Dalykai")

    # adminas nurodo kurias klases mokytojas moko
    klases = models.ManyToManyField(Klase, blank=True, verbose_name="Klasės")

    kabinetas = models.ForeignKey(Cabinet, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Kabinetas")

    # Gmail adresas susietas su mokytoju (neprivalomas)
    email = models.EmailField(
        blank=True,
        default="",
        verbose_name="Mokytojo Gmail",
        help_text="Įvedųs email, mokytojas prisijungęs matys atskirą skydelį įrašynėti,trinti ar keisti savo laikus",
    )

    class Meta:
        ordering = ("pavarde", "vardas")
        verbose_name = "Mokytojas"
        verbose_name_plural = "Mokytojai"

    def __str__(self):
        return f"{self.vardas} {self.pavarde}"


class WorkingHours(models.Model):
    mokytojai = models.ManyToManyField(
        Teacher,
        related_name="working_hours",
        verbose_name="Mokytojai"
    )

    INTERVAL_CHOICES = [
        (15, "15 minučių"),
        (30, "30 minučių"),
        (45, "45 minutės"),
        (60, "60 minučių"),
    ]

    
    TIPAS_CHOICES = [
        ("individualus", "Individualus pokalbis"),
        ("dalykininku", "Dalykininku pokalbis"),
    ]

    date = models.DateField(verbose_name="Data")
    start_time = models.TimeField(verbose_name="Pradžia")
    end_time = models.TimeField(verbose_name="Pabaiga")
    interval = models.IntegerField(default=10, choices=INTERVAL_CHOICES, verbose_name="Laiko intervalas")
    tipas = models.CharField(
        max_length=20,
        choices=TIPAS_CHOICES,
        default="individualus",
        verbose_name="Pokalbio tipas",
    )

    # kabinetas siam konkreciam darbo laiko blokui. Jei nenurodytas,
    # naudojamas mokytojo profilyje priskirtas kabinetas
    cabinet = models.ForeignKey(
        "Cabinet",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Kabinetas",
        help_text="Jei nepasirinkta, bus naudojamas mokytojo numatytas kabinetas",
    )

    class Meta:
        ordering = ("date", "start_time")
        verbose_name = "Darbo laikas"
        verbose_name_plural = "Darbo laikai"

    def __str__(self):
        return f"{self.date} {self.start_time}-{self.end_time} ({self.tipas})"


class Break(models.Model):
    working_hours = models.ForeignKey(
        WorkingHours,
        on_delete=models.CASCADE,
        related_name="breaks",
        verbose_name="Darbo laikas",
    )
    start_time = models.TimeField(verbose_name="Pradžia")
    end_time = models.TimeField(verbose_name="Pabaiga")
    description = models.CharField(max_length=100, blank=True, verbose_name="Aprašymas")

    # mokytojas grafike gali pasalinti viena laika - tai irgi pertrauka,
    # tik vieno intervalo ilgio. Zyme reikalinga, kad skydelyje sie laikai
    # butu rodomi atskirai ("Pašalinti laikai") ir juos butu galima grazinti
    pasalintas_laikas = models.BooleanField(default=False, verbose_name="Pašalintas laikas")

    class Meta:
        ordering = ("start_time",)
        verbose_name = "Pertrauka"
        verbose_name_plural = "Pertraukos"

    def __str__(self):
        return f"{self.working_hours.date} {self.start_time}-{self.end_time}"


class Child(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="children", verbose_name="Tėvų paskyra")
    first_name = models.CharField(max_length=50, verbose_name="Vardas")
    last_name = models.CharField(max_length=50, verbose_name="Pavardė")

    # klase dabar yra ForeignKey i Klase modeli
    klase = models.ForeignKey(
        Klase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Klasė",
    )

    class Meta:
        ordering = ("last_name", "first_name")
        verbose_name = "Vaikas"
        verbose_name_plural = "Vaikai"

    def __str__(self):
        klase_str = self.klase.pavadinimas if self.klase else "?"
        return f"{self.first_name} {self.last_name} ({klase_str})"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="Vartotojas")
    active_child = models.ForeignKey(Child, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Aktyvus vaikas")

    class Meta:
        verbose_name = "Profilis"
        verbose_name_plural = "Profiliai"

    def __str__(self):
        return self.user.email


class Reservation(models.Model):
    # tevu rezervacija - user turi bus
    # admin rezervacija - user gali buti tuscias
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Tėvų paskyra")

    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, verbose_name="Mokytojas")
    date = models.DateField(verbose_name="Data")
    time = models.TimeField(verbose_name="Laikas")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Sukurta")

    child = models.ForeignKey(Child, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Vaikas")

    reserved_first_name = models.CharField(max_length=50, blank=True, verbose_name="Vaiko vardas")
    reserved_last_name = models.CharField(max_length=50, blank=True, verbose_name="Vaiko pavardė")
    reserved_class = models.CharField(max_length=20, blank=True, verbose_name="Klasė")

    # pokalbio tipas - fiksuojamas rezervavimo metu is darbo laiko bloko.
    # Reikalingas tam, kad mokytojo skydelyje individualiu ir dalykininku
    # pokalbiu rezervacijos nesimaisytu tarpusavyje
    tipas = models.CharField(
        max_length=20,
        choices=WorkingHours.TIPAS_CHOICES,
        default="individualus",
        verbose_name="Pokalbio tipas",
    )

    # kabinetas kuriame vyks pokalbis - paimamas is darbo laiko bloko (jei nustatytas)
    # arba is mokytojo profilio, ir issaugomas cia kaip fiksuotas irasas
    cabinet = models.ForeignKey(
        "Cabinet",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Kabinetas",
    )

    class Meta:
        unique_together = ("teacher", "date", "time")
        ordering = ("date", "time")
        verbose_name = "Rezervacija"
        verbose_name_plural = "Rezervacijos"

    def __str__(self):
        if self.reserved_first_name and self.reserved_last_name:
            if self.reserved_class:
                kas = f"{self.reserved_first_name} {self.reserved_last_name} ({self.reserved_class})"
            else:
                kas = f"{self.reserved_first_name} {self.reserved_last_name}"
        elif self.child:
            klase_str = self.child.klase.pavadinimas if self.child.klase else "?"
            kas = f"{self.child.first_name} {self.child.last_name} ({klase_str})"
        elif self.user:
            kas = self.user.email
        else:
            kas = "ADMIN"

        return f"{kas} -> {self.teacher} | {self.date} {self.time}"


class LeistinasEmail(models.Model):
    """Baltasis sarasas - tik sie adresai gali prisijungti prie sistemos.
    Mokytoju adresai tikrinami atskirai, ju cia dubliuoti nereikia."""

    email = models.EmailField(
        unique=True,
        verbose_name="El. paštas",
        help_text="Gmail adresas, kuriuo tėvas galės prisijungti",
    )
    pastaba = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Pastaba",
        help_text="Pvz. vaiko vardas ar klasė, kad būtų aišku kieno tai adresas",
    )
    pridetas = models.DateTimeField(auto_now_add=True, verbose_name="Pridėtas")

    class Meta:
        ordering = ("email",)
        verbose_name = "Tėvų el. paštas"
        verbose_name_plural = "Tėvų el. paštai"

    # visada saugom mazosiomis, kad palyginimas neapviltu
    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class Vadovas(models.Model):
    """Mokyklos vadovas (direktorius, pavaduotojas). Adminas priskiria el. pasta -
    prisijungus tuo adresu vartotojas mato vadovo grafika ir gali skirti laikus
    pokalbiams su mokytojais. Siuos laikus mato ir rezervuoja tik mokytojai."""

    vardas = models.CharField(max_length=50, verbose_name="Vardas")
    pavarde = models.CharField(max_length=50, verbose_name="Pavardė")
    email = models.EmailField(
        unique=True,
        verbose_name="Vadovo Gmail",
        help_text="Šiuo adresu prisijungęs vadovas matys savo grafiką ir galės skirti laikus mokytojams",
    )

    class Meta:
        ordering = ("pavarde", "vardas")
        verbose_name = "Vadovas"
        verbose_name_plural = "Vadovas"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.vardas} {self.pavarde}"


class VadovoLaikas(models.Model):
    """Vadovo darbo laiko blokas pokalbiams su mokytojais. Skirtingai nei
    mokytojai, vadovas neturi numatyto kabineto, tai kabinetas nurodomas
    kiekvienam blokui atskirai."""

    vadovas = models.ForeignKey(Vadovas, on_delete=models.CASCADE, related_name="laikai", verbose_name="Vadovas")
    date = models.DateField(verbose_name="Data")
    start_time = models.TimeField(verbose_name="Pradžia")
    end_time = models.TimeField(verbose_name="Pabaiga")
    interval = models.IntegerField(
        default=15,
        choices=WorkingHours.INTERVAL_CHOICES,
        verbose_name="Laiko intervalas",
    )
    cabinet = models.ForeignKey(
        Cabinet,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Kabinetas",
    )

    class Meta:
        ordering = ("date", "start_time")
        verbose_name = "Vadovo laikas"
        verbose_name_plural = "Vadovo laikai"

    def __str__(self):
        return f"{self.vadovas} {self.date} {self.start_time}-{self.end_time}"


class VadovoPertrauka(models.Model):
    laikas = models.ForeignKey(VadovoLaikas, on_delete=models.CASCADE, related_name="breaks", verbose_name="Vadovo laikas")
    start_time = models.TimeField(verbose_name="Pradžia")
    end_time = models.TimeField(verbose_name="Pabaiga")
    description = models.CharField(max_length=100, blank=True, verbose_name="Aprašymas")
    # kaip ir mokytoju Break - vieno intervalo ilgio "pasalintas laikas"
    pasalintas_laikas = models.BooleanField(default=False, verbose_name="Pašalintas laikas")

    class Meta:
        ordering = ("start_time",)
        verbose_name = "Vadovo pertrauka"
        verbose_name_plural = "Vadovo pertraukos"

    def __str__(self):
        return f"{self.laikas.date} {self.start_time}-{self.end_time}"


class VadovoRezervacija(models.Model):
    """Mokytojo uzsiregistruotas laikas pokalbiui su vadovu."""

    vadovas = models.ForeignKey(Vadovas, on_delete=models.CASCADE, related_name="rezervacijos", verbose_name="Vadovas")
    mokytojas = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="vadovo_rezervacijos", verbose_name="Mokytojas")
    date = models.DateField(verbose_name="Data")
    time = models.TimeField(verbose_name="Laikas")
    # kabinetas fiksuojamas rezervavimo metu is vadovo laiko bloko
    cabinet = models.ForeignKey(Cabinet, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Kabinetas")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Sukurta")

    class Meta:
        unique_together = ("vadovas", "date", "time")
        ordering = ("date", "time")
        verbose_name = "Pokalbis su vadovu"
        verbose_name_plural = "Pokalbiai su vadovu"

    def __str__(self):
        return f"{self.mokytojas} -> {self.vadovas} | {self.date} {self.time}"
