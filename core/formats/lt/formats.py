# Lietuviski formatai - visur 24 val. laikas ir datos Y-m-d pavidalu.
# Django standartiniai lt formatai rodo sekundes ("H:i:s") ir datas
# "2026 m. rugsėjo 30 d." - lentelese tai per ilga, todel perrasom

DATE_FORMAT = "Y-m-d"
TIME_FORMAT = "H:i"
DATETIME_FORMAT = "Y-m-d H:i"
SHORT_DATE_FORMAT = "Y-m-d"
SHORT_DATETIME_FORMAT = "Y-m-d H:i"
MONTH_DAY_FORMAT = "F j"
YEAR_MONTH_FORMAT = "Y F"
FIRST_DAY_OF_WEEK = 1  # pirmadienis

# pirmas sarase formatas naudojamas ir admin laiko/datos mygtukams ("Dabar", "Šiandien"),
# todel laikas be sekundziu
DATE_INPUT_FORMATS = ["%Y-%m-%d", "%Y.%m.%d", "%d.%m.%Y"]
TIME_INPUT_FORMATS = ["%H:%M", "%H:%M:%S", "%H.%M"]
DATETIME_INPUT_FORMATS = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]

DECIMAL_SEPARATOR = ","
THOUSAND_SEPARATOR = " "
NUMBER_GROUPING = 3
