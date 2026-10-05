"""Importes exactos: entradas argentinas y precios publicados por el portal."""

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENTAVO = Decimal("0.01")
MAXIMO = Decimal("100000000")


def importe(valor, *, portal=False):
    if isinstance(valor, bool) or valor is None:
        raise ValueError("Ingresá un importe válido")
    texto = str(valor).strip().replace("$", "").replace("\u00a0", "").replace(" ", "")
    if "," in texto:
        if not re.fullmatch(r"\d+(?:\.\d{3})*,\d{1,2}", texto):
            raise ValueError("Usá un importe como 17500 o 17.500,50")
        texto = texto.replace(".", "").replace(",", ".")
    elif portal and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", texto):
        texto = texto.replace(".", "")
    elif not re.fullmatch(r"\d+(?:\.\d{1,2})?", texto):
        raise ValueError("Usá un importe como 17500 o 17.500,50")
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        raise ValueError("Importe inválido") from None
    if not numero.is_finite() or numero < 0 or numero > MAXIMO:
        raise ValueError("Importe fuera de rango")
    return numero.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def serializar(valor):
    return format(valor, ".2f")


def aumentar(actual, modo, cantidad, redondeo="centavos"):
    cantidad = importe(cantidad)
    if cantidad <= 0:
        raise ValueError("El aumento debe ser mayor que cero")
    if modo == "pesos":
        nuevo = actual + cantidad
    elif modo == "porcentaje":
        if cantidad > 1000:
            raise ValueError("El porcentaje máximo es 1000")
        nuevo = actual * (1 + cantidad / 100)
    else:
        raise ValueError("Tipo de aumento inválido")
    pasos = {"centavos": CENTAVO, "1": Decimal(1), "10": Decimal(10),
             "50": Decimal(50), "100": Decimal(100)}
    if redondeo not in pasos:
        raise ValueError("Redondeo inválido")
    paso = pasos[redondeo]
    nuevo = ((nuevo / paso).quantize(Decimal(1), rounding=ROUND_HALF_UP) * paso)
    if nuevo < actual:
        raise ValueError("El redondeo reduciría el precio; elegí un paso menor")
    return importe(serializar(nuevo))
