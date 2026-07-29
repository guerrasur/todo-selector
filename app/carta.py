"""Emparejar las cartas de los portales entre si.

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

SON N CARTAS, NO DOS. Rappi Turbo y Rappi Común son dos tiendas distintas
del mismo portal, con cartas que NO son iguales (2026-07-29): un plato
puede estar en una y no en la otra, y llamarse distinto en cada una. Asi
que esto empareja una LISTA de plataformas y no un par fijo. `emparejar()`
(dos listas) sigue existiendo y es el caso particular de `emparejar_n()`.

OJO CON LAS DOS TIENDAS DE RAPPI: sus nombres se parecen MUCHO mas entre si
que los de portales distintos (mismo portal, mismo estilo de carga), asi que
las variantes que no son el mismo plato puntúan todavia mas alto. Nada de lo
que sale de aca apaga nada: es una propuesta para la pantalla de asociacion,
y el vinculo lo confirma el usuario una vez y queda guardado.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Arriba de esto se da por seguro y se empareja solo.
UMBRAL_SEGURO = 0.82
# Abajo de esto ni se propone: es ruido.
UMBRAL_PROPUESTA = 0.55

# Tiendas del MISMO portal. Rappi Turbo y Rappi Común se cargan desde el
# mismo panel, asi que el mismo plato suele estar escrito igual en las dos:
# una diferencia real de texto es mucho mas probable que sea otro plato y no
# la misma cosa dicha distinto. Entre portales, en cambio, el mismo plato se
# llama distinto todo el tiempo ("Tarta de choclo" / "Tarta de choclo y
# queso"), y por eso ahi 0.82 alcanza.
#
# Ejemplo de por que hace falta: "Tarta de verdura" contra "Tarta de verdura
# chica" puntua 0.91 (contencion, sobra una palabra). Entre PedidosYa y
# Rappi eso se empareja solo y esta bien. Entre las dos tiendas de Rappi
# seria apagar la tarta grande creyendo que apagas la chica, con el agravante
# de que nadie lo mira: la carta de la tienda Común se revisa mucho menos.
# Con 0.95 pasan las tildes y las mayusculas (normalizan a 1.0) y no pasa
# ninguna palabra de mas.
TIENDAS_DEL_MISMO_PORTAL = ({"rappi", "rappi_comun"},)
UMBRAL_SEGURO_MISMO_PORTAL = 0.95


def _umbral(plataforma: str, ya_en_el_grupo) -> float:
    """Cuanto hay que puntuar para sumarse SOLO a este grupo."""
    for familia in TIENDAS_DEL_MISMO_PORTAL:
        if plataforma in familia and familia & set(ya_en_el_grupo):
            return UMBRAL_SEGURO_MISMO_PORTAL
    return UMBRAL_SEGURO


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


# El orden en que se cruzan las cartas. PedidosYa primero porque es de
# donde sale el nombre canonico; Rappi Turbo antes que Común porque es la
# tienda que ya venia cargada en los catalogos existentes.
ORDEN = ("pedidosya", "rappi", "rappi_comun")


def _ordenar(plataformas) -> list[str]:
    conocidas = [p for p in ORDEN if p in plataformas]
    return conocidas + [p for p in plataformas if p not in ORDEN]


@dataclass
class Emparejamiento:
    """Un producto, con el nombre que tiene en cada plataforma.

    `nombres` es la fuente de verdad y tiene una entrada por plataforma en
    la que ese producto existe. `pedidosya` y `rappi` quedan como atajos
    porque son el par que usa media app.
    """
    nombres: dict[str, str] = field(default_factory=dict)
    # De cuanto fue el emparejamiento con el que cada plataforma se sumo al
    # grupo. La primera en entrar no se emparejo con nadie y no figura.
    confianzas: dict[str, float] = field(default_factory=dict)
    # Otros candidatos que puntuaron parecido, por plataforma. Si hay alguno,
    # la decision es del usuario: pasa con "Tarta de verdura chica", que en
    # Rappi tiene una "individual" y una "porción".
    alternativas_por: dict[str, list[str]] = field(default_factory=dict)
    # Cuanto tenia que puntuar cada plataforma para entrar sola. No es igual
    # para todas: dos tiendas del mismo portal se exigen mas (ver _umbral).
    exigido: dict[str, float] = field(default_factory=dict)

    @property
    def pedidosya(self) -> str | None:
        return self.nombres.get("pedidosya")

    @property
    def rappi(self) -> str | None:
        return self.nombres.get("rappi")

    @property
    def plataformas(self) -> list[str]:
        return _ordenar(self.nombres)

    @property
    def confianza(self) -> float:
        """El eslabon mas debil del grupo.

        Con dos cartas es el unico emparejamiento que hubo, asi que da lo
        mismo que antes. Con tres, un grupo vale lo que vale su union mas
        floja: si la tienda Común entro con 0.6, el grupo entero es dudoso
        aunque PedidosYa y Turbo se hayan emparejado clavados.
        """
        if not self.confianzas:
            return 0.0
        return round(min(self.confianzas.values()), 3)

    @property
    def alternativas(self) -> list[str]:
        """Todas las alternativas juntas, de cualquier plataforma."""
        return [n for lista in self.alternativas_por.values() for n in lista]

    @property
    def seguro(self) -> bool:
        """Se empareja solo, sin preguntar.

        Tiene que serlo CADA union: un grupo de tres donde PedidosYa y Turbo
        se emparejaron clavados pero la tienda Común entro raspando no es
        seguro, porque lo que esta en duda es a que producto se le va a
        apagar el toggle en esa tercera tienda.
        """
        if len(self.nombres) < 2:
            return False        # existe en un solo portal: no hay que cruzar

        for plataforma, punto in self.confianzas.items():
            # Un nombre identico no lo discute una alternativa peor:
            # "Tarta de verdura" = "Tarta de verdura" aunque exista la "chica".
            if punto >= 1.0:
                continue
            if punto < self.exigido.get(plataforma, UMBRAL_SEGURO):
                return False
            if self.alternativas_por.get(plataforma):
                return False
        return True

    @property
    def nombre(self) -> str:
        """El canonico: el de PedidosYa si existe, si no el primero que haya."""
        for plataforma in self.plataformas:
            return self.nombres[plataforma]
        return ""


def emparejar_n(cartas: dict[str, list[str]]) -> list[Emparejamiento]:
    """Cruza las cartas de todas las plataformas que le pases.

    Va de a una plataforma, sumandola a los grupos que ya se armaron. Un
    nombre nuevo se compara contra TODOS los nombres del grupo y se queda
    con el mejor: asi la tienda Común puede engancharse por como se llama
    el plato en Turbo aunque en PedidosYa se llame completamente distinto
    ("Agua chica" en PedidosYa, "Manantial sin gas 500 ml" en las dos de
    Rappi).

    Devuelve un Emparejamiento por producto. Los que existen en una sola
    plataforma quedan con un solo nombre, que es informacion util: es el
    chip gris "—" de la pantalla.
    """
    grupos: list[Emparejamiento] = []

    for plataforma in _ordenar(cartas):
        items = cartas.get(plataforma) or []

        if not grupos:
            grupos = [Emparejamiento(nombres={plataforma: n}) for n in items]
            continue

        # Se procesan de mayor a menor parecido para que un nombre corto no
        # le robe el candidato a uno largo ("Tarta de verdura" vs "chica").
        # El desempate va por posicion en las listas y no por nombre: ante
        # dos candidatos que puntúan igual, gana el que el portal muestra
        # primero. Es arbitrario igual, pero es estable y no depende de
        # como ordene el alfabeto los acentos.
        candidatos = []
        for i, grupo in enumerate(grupos):
            if plataforma in grupo.nombres:
                continue
            for j, nuevo in enumerate(items):
                punto = max(parecido(conocido, nuevo)
                            for conocido in grupo.nombres.values())
                if punto >= UMBRAL_PROPUESTA:
                    candidatos.append((punto, i, j, nuevo))
        candidatos.sort(key=lambda c: (-c[0], c[1], c[2]))

        tomados_grupo, tomados_nombre = {}, set()
        for punto, i, _, nuevo in candidatos:
            if i in tomados_grupo or nuevo in tomados_nombre:
                continue
            tomados_grupo[i] = (nuevo, punto)
            tomados_nombre.add(nuevo)

        for i, (nuevo, punto) in tomados_grupo.items():
            grupo = grupos[i]
            # Lo que quedo suelto y tambien puntuaba alto contra este grupo.
            # Con una sola alternativa razonable ya deja de ser seguro: la
            # decision pasa a ser del usuario. Las alternativas se buscan
            # SIEMPRE con el umbral bajo, aunque para entrar se exija el
            # alto: cuantos mas competidores se marquen, menos se empareja
            # solo, y eso es el lado seguro del error.
            otros = [o for o in items
                     if o != nuevo and o not in tomados_nombre
                     and max(parecido(conocido, o)
                             for conocido in grupo.nombres.values()) >= UMBRAL_SEGURO]
            grupo.exigido[plataforma] = _umbral(plataforma, grupo.nombres)
            grupo.nombres[plataforma] = nuevo
            grupo.confianzas[plataforma] = round(punto, 3)
            if otros:
                grupo.alternativas_por[plataforma] = otros

        grupos += [Emparejamiento(nombres={plataforma: n})
                   for n in items if n not in tomados_nombre]

    return grupos


def emparejar(items_py: list[str], items_rappi: list[str]) -> list[Emparejamiento]:
    """Cruza dos cartas. Es el caso de siempre: PedidosYa contra Rappi."""
    return emparejar_n({"pedidosya": items_py, "rappi": items_rappi})


def resumen(pares: list[Emparejamiento], plataformas=None) -> dict:
    """Para la UI y para el log: en que estado quedo el cruce.

    `plataformas` es sobre cuales se leyo (aunque alguna no haya devuelto
    nada): la pantalla dibuja una columna por cada una y necesita saberlo
    incluso cuando la lectura de esa tienda fallo.

    Las claves `solo_pedidosya`, `solo_rappi` y los `pedidosya`/`rappi` de
    cada fila se mantienen: la pantalla vieja (la que quedo cacheada en el
    navegador de alguien) las sigue leyendo.
    """
    if plataformas is None:
        plataformas = _ordenar({p for e in pares for p in e.nombres})
    else:
        plataformas = _ordenar(plataformas)

    seguros = [p for p in pares if p.seguro]
    dudosos = [p for p in pares if len(p.nombres) > 1 and not p.seguro]

    def mostrar(p):
        salida = {"nombres": dict(p.nombres),
                  "pedidosya": p.pedidosya, "rappi": p.rappi,
                  "confianza": p.confianza,
                  "confianzas": dict(p.confianzas),
                  # Cuanto necesitaba cada una para entrar sola. La pantalla
                  # lo usa para venir con las columnas seguras ya tildadas y
                  # la dudosa NO, asi el usuario acepta lo que esta bien sin
                  # arrastrar lo que esta en duda.
                  "exigido": dict(p.exigido)}
        if p.alternativas:
            salida["alternativas"] = p.alternativas
            salida["alternativas_por"] = {k: list(v) for k, v
                                          in p.alternativas_por.items()}
        return salida

    def solo_de(plataforma):
        return [p.nombres[plataforma] for p in pares
                if len(p.nombres) == 1 and plataforma in p.nombres]

    salida = {
        "total": len(pares),
        "plataformas": plataformas,
        "emparejados": len(seguros),
        "a_confirmar": [mostrar(p) for p in dudosos],
        "solo": {plat: solo_de(plat) for plat in plataformas},
        "pares": [mostrar(p) for p in seguros],
    }
    # Los dos de siempre, tambien sueltos.
    salida["solo_pedidosya"] = salida["solo"].get("pedidosya", [])
    salida["solo_rappi"] = salida["solo"].get("rappi", [])
    return salida
