from django.db import models
from django.contrib.auth.models import User


class Subject(models.Model):
    pavadinimas = models.CharField(max_length=100)

    def __str__(self):
        return self.pavadinimas



class Cabinet(models.Model):
    pavadinimas = models.CharField(max_length=50)

    def __str__(self):
        return self.pavadinimas



class Klase(models.Model):
    pavadinimas = models.CharField(max_length=20)

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
        ordering = ("pavadinimas",)
        verbose_name = "Class"
        verbose_name_plural = "Classes"

    def __str__(self):
        return self.pavadinimas


class Teacher(models.Model):
    vardas = models.CharField(max_length=50)
    pavarde = models.CharField(max_length=50)

    # vienas mokytojas gali tureti kelis dalykus
    dalykai = models.ManyToManyField(Subject, blank=True)

    # adminas nurodo kurias klases mokytojas moko
    klases = models.ManyToManyField(Klase, blank=True, verbose_name="Klasės")

    kabinetas = models.ForeignKey(Cabinet, on_delete=models.SET_NULL, null=True, blank=True)

    # Gmail adresas susietas su mokytoju (neprivalomas)
    email = models.EmailField(
        blank=True,
        default="",
        verbose_name="Mokytojo Gmail",
        help_text="Įvedųs email, mokytojas prisijungęs matys atskirą skydelį įrašynėti,trinti ar keisti savo laikus",
    )

    class Meta:
        ordering = ("pavarde", "vardas")

    def __str__(self):
        return f"{self.vardas} {self.pavarde}"


class WorkingHours(models.Model):
    mokytojai = models.ManyToManyField(
        Teacher,
        related_name="working_hours",
        verbose_name="Teachers"
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

    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    interval = models.IntegerField(default=10, choices=INTERVAL_CHOICES)
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
        verbose_name = "Working hours"
        verbose_name_plural = "Working hours"

    def __str__(self):
        return f"{self.date} {self.start_time}-{self.end_time} ({self.tipas})"


class Break(models.Model):
    working_hours = models.ForeignKey(
        WorkingHours,
        on_delete=models.CASCADE,
        related_name="breaks"
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    description = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ("start_time",)

    def __str__(self):
        return f"{self.working_hours.date} {self.start_time}-{self.end_time}"


class Child(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="children")
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)

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

    def __str__(self):
        klase_str = self.klase.pavadinimas if self.klase else "?"
        return f"{self.first_name} {self.last_name} ({klase_str})"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    active_child = models.ForeignKey(Child, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.user.email


class Reservation(models.Model):
    # tevu rezervacija - user turi bus
    # admin rezervacija - user gali buti tuscias
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    date = models.DateField()
    time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    child = models.ForeignKey(Child, on_delete=models.SET_NULL, null=True, blank=True)

    reserved_first_name = models.CharField(max_length=50, blank=True)
    reserved_last_name = models.CharField(max_length=50, blank=True)
    reserved_class = models.CharField(max_length=20, blank=True)

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
