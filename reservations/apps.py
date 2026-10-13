from django.apps import AppConfig
from django.db import connections
from django.db.backends.signals import connection_created


class ReservationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reservations'
    verbose_name = 'Rezervacijos'

    def ready(self):
        
        import reservations.signals

        # lietuviškas rikiavimas - kiekvienam naujam DB prisijungimui
        from .rusiavimas import registruoti_palyginima
        connection_created.connect(registruoti_palyginima, dispatch_uid="reservations_lt_palyginimas")
        # jei prisijungimas atsidarė dar prieš ready() - užregistruojam ir jam
        for jungtis in connections.all(initialized_only=True):
            if jungtis.connection is not None:
                registruoti_palyginima(None, jungtis)
