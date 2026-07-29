"""Emparejar la carta de PedidosYa con la de Rappi.

La idea es no mantener los nombres a mano. Cada portal dice como se llaman
SUS productos; acá se decide cuales son el mismo.

Por que hace falta emparejar y no alcanza con comparar strings (los
ejemplos salen de pruebas/carta_ejemplo.json):

    PedidosYa                Rappi
    Tarta de choclo          Tarta de choclo y queso
    Budin de pan             Budín de pan
    Gaseosa cola             Gaseosa cola 500 ml
    Agua chica               Manantial sin gas 500 ml

Los tres primeros se resuelven solos normalizando y mirando si uno contiene
al otro. El cuarto NO: "Agua chica" y "Manantial" no se parecen en nada, y
ninguna heuristica lo va a sacar. Por eso la salida separa lo seguro de lo
dudoso: la app propone, el usuario confirma una vez, y queda guardado.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Arriba de esto se da por seguro y se empareja solo.
UMBRAL_SEGURO = 0.82
# Abajo de esto ni se propone: es ruido.
UMBRAL_PROPUESTA = 0.55

# Palabras que no distinguen un producto de otro y solo ensucian la
# comparacion: un portal escribe "Ensalada mixta" y el otro "Mixta".
# OJO: "con" y "sin" NO van aca. Son lo unico que distingue "Agua chica
# con gas" de "Agua chica", y sacarlas hacia que una gaseosa comun
# emparejara con la version sin azucar.
RUIDO = {
    "ensalada", "el", "la", "los", "las", "de", "del", "y",
    "ml", "cc", "gr", "g", "kg", "l", "lt",
}


def normalizar(nombre: str) -> str:
    """Baja a minusculas, saca tildes, puntuacion y numeros sueltos."""
    texto = unicodedata.normalize("NFKD", nombre.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return " ".join(texto.split())


def _palabras_utiles(nombre: str) -> list[str]:
    """Las palabras que de verdad identifican al producto."""
    palabras = [p for p in normalizar(nombre).split()
                if p not in RUIDO and not p.isdigit()]
    # Si todo era ruido, mejor quedarse con algo que con nada.
    return palabras or normalizar(nombre).split()


def parecido(a: str, b: str) -> float:
    """0 a 1. Cuanto se parecen dos nombres de producto.

    Combina dos señales, y se queda con la mejor:
      - similitud de texto sobre los nombres normalizados
      - si las palabras utiles de uno estan todas adentro del otro
        ("Mixta" adentro de "Ensalada mixta")
    """
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    por_texto = SequenceMatcher(None, na, nb).ratio()

    pa, pb = set(_palabras_utiles(a)), set(_palabras_utiles(b))
    if not pa or not pb:
        return por_texto

    chico, grande = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    if chico <= grande:
        # Contenido entero. Cuanto mas sobra en el grande, menos seguro:
        # "Tarta de verdura" adentro de "Tarta de verdura individual"
        # tiene que puntuar mas bajo que adentro de "Tarta de verdura".
        sobra = len(grande) - len(chico)
        por_contencion = 0.97 - min(sobra, 4) * 0.06
    else:
        comunes = len(pa & pb)
        por_contencion = comunes / max(len(pa), len(pb))

    return max(por_texto, por_contencion)


@dataclass
class Emparejamiento:
    """Un producto, con el nombre que tiene en cada plataforma."""
    pedidosya: str | None = None
    rappi: str | None = None
    confianza: float = 0.0
    # Otros candidatos de Rappi que puntuaron parecido. Si hay mas de uno,
    # la decision es del usuario: pasa "Tarta de verdura chica", que en
    # Rappi tiene una "individual" y una "porción".
    alternativas: list[str] = field(default_factory=list)

    @property
    def seguro(self) -> bool:
        if self.pedidosya is None or self.rappi is None:
            return False
        # Un nombre identico no lo discute una alternativa peor:
        # "Tarta de verdura" = "Tarta de verdura" aunque exista la "chica".
        if self.confianza >= 1.0:
            return True
        return self.confianza >= UMBRAL_SEGURO and not self.alternativas

    @property
    def nombre(self) -> str:
        """El canonico: el de PedidosYa si existe, si no el de Rappi."""
        return self.pedidosya or self.rappi or ""


def emparejar(items_py: list[str], items_rappi: list[str]) -> list[Emparejamiento]:
    """Cruza las dos cartas.

    Devuelve un Emparejamiento por producto. Los que existen en una sola
    plataforma quedan con la otra en None, que es informacion util: hoy eso
    se mantiene a mano en seed.py.
    """
    libres = list(items_rappi)
    resultado = []

    # Se procesan de mayor a menor parecido para que un nombre corto no le
    # robe el candidato a uno largo ("Tarta de verdura" vs "... chica").
    candidatos = []
    for py in items_py:
        for rp in items_rappi:
            punto = parecido(py, rp)
            if punto >= UMBRAL_PROPUESTA:
                candidatos.append((punto, py, rp))
    candidatos.sort(key=lambda c: -c[0])

    tomados_py, tomados_rp = {}, set()
    for punto, py, rp in candidatos:
        if py in tomados_py or rp in tomados_rp:
            continue
        tomados_py[py] = (rp, punto)
        tomados_rp.add(rp)

    for py in items_py:
        if py in tomados_py:
            rp, punto = tomados_py[py]
            otros = [o for o in libres
                     if o != rp and o not in tomados_rp
                     and parecido(py, o) >= UMBRAL_SEGURO]
            resultado.append(Emparejamiento(pedidosya=py, rappi=rp,
                                            confianza=round(punto, 3),
                                            alternativas=otros))
        else:
            resultado.append(Emparejamiento(pedidosya=py, confianza=0.0))

    for rp in items_rappi:
        if rp not in tomados_rp:
            resultado.append(Emparejamiento(rappi=rp, confianza=0.0))

    return resultado


def resumen(pares: list[Emparejamiento]) -> dict:
    """Para la UI y para el log: en que estado quedo el cruce."""
    seguros = [p for p in pares if p.seguro]
    dudosos = [p for p in pares
               if p.pedidosya and p.rappi and not p.seguro]
    solo_py = [p for p in pares if p.pedidosya and not p.rappi]
    solo_rp = [p for p in pares if p.rappi and not p.pedidosya]

    def mostrar(p):
        salida = {"pedidosya": p.pedidosya, "rappi": p.rappi,
                  "confianza": p.confianza}
        if p.alternativas:
            salida["alternativas"] = p.alternativas
        return salida

    return {
        "total": len(pares),
        "emparejados": len(seguros),
        "a_confirmar": [mostrar(p) for p in dudosos],
        "solo_pedidosya": [p.pedidosya for p in solo_py],
        "solo_rappi": [p.rappi for p in solo_rp],
        "pares": [mostrar(p) for p in seguros],
    }
