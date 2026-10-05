"""Planes beta de precios: vista previa inmutable, lotes y resultados locales."""

import asyncio
import hashlib
import json
import logging
import secrets
import time
from datetime import datetime
from pathlib import Path

from . import config
from .database import DATOS
from plataformas.precios import importe, serializar, aumentar

log = logging.getLogger("precios")
RAPPI = {"rappi", "rappi_comun"}  # Allowlist, NO lista de tiendas activas.


def ahora():
    return datetime.now().isoformat(timespec="seconds")


class GestorPrecios:
    def __init__(self, worker, carpeta=None):
        self.worker = worker
        self.carpeta = Path(carpeta) if carpeta else DATOS / "precios"
        self.lecturas = {}
        self.planes = {}
        self.trabajos = {}
        self.tarea = None
        self.activo = None

    def tiendas(self):
        return [p for p in config.plataformas_activas() if p in RAPPI and all(self.contexto(p))]

    def validar_tiendas(self, tiendas):
        if not tiendas or len(tiendas) != len(set(tiendas)):
            raise ValueError("Elegí al menos una tienda, sin repetir")
        if any(p not in self.tiendas() for p in tiendas):
            raise ValueError("Precios beta solo admite tiendas Rappi configuradas")

    def contexto(self, plataforma):
        claves = ("rappi_brand_id", "rappi_store_id") if plataforma == "rappi" else (
            "rappi_brand_id", "rappi_comun_store_id")
        return [config.texto(c) for c in claves]

    async def _preparar(self, tienda):
        listo, motivo = await self.worker._preparar(tienda)
        if listo or self.worker.en_verificacion(tienda):
            return listo, motivo
        # La carta completamente plegada falla la preparación general porque
        # no hay toggles de producto visibles. Solo este flujo beta la abre.
        if self.worker.motivo_sesion.get(tienda) != "menu_no_cargo":
            return listo, motivo
        plat = self.worker.plataformas.get(tienda)
        if not plat or not plat.en_el_menu():
            return listo, motivo
        try:
            await plat.abrir_categorias_precios(lambda: not self.worker.en_verificacion(tienda))
        except Exception as e:
            return False, str(e)
        return await self.worker._preparar(tienda)

    def _guardar(self, trabajo):
        self.carpeta.mkdir(parents=True, exist_ok=True)
        ruta = self.carpeta / (trabajo["id"] + ".json")
        temporal = ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(trabajo, ensure_ascii=False, indent=2), encoding="utf-8")
        temporal.replace(ruta)

    def historial(self):
        salida = []
        if self.carpeta.exists():
            for archivo in sorted(self.carpeta.glob("*.json"), key=lambda p: p.stat().st_mtime,
                                  reverse=True)[:30]:
                try:
                    salida.append(self.estado(archivo.stem))
                except (ValueError, OSError, json.JSONDecodeError):
                    log.exception("No se pudo leer el resultado de precios %s", archivo.name)
        return salida

    def estado(self, identidad):
        if not identidad or any(c not in "0123456789abcdef" for c in identidad) or len(identidad) != 32:
            raise ValueError("Identificador inválido")
        if identidad not in self.trabajos:
            ruta = self.carpeta / (identidad + ".json")
            if not ruta.exists():
                raise ValueError("No se encontró el lote")
            trabajo = json.loads(ruta.read_text(encoding="utf-8"))
            if trabajo["estado"] == "ejecutando":
                trabajo["estado"] = "interrumpido"
                for fila in trabajo["filas"]:
                    if fila["estado"] in ("pendiente", "en_curso"):
                        fila["estado"] = "sin_confirmar"
                        fila["detalle"] = "La app se cerró; releé el portal antes de preparar otro lote"
                self._guardar(trabajo)
            self.trabajos[identidad] = trabajo
        # Devolver copia evita mutación del plan desde llamadas internas/API.
        return json.loads(json.dumps(self.trabajos[identidad]))

    async def leer(self, tiendas):
        self.validar_tiendas(tiendas)
        errores, filas, contextos = {}, [], {}
        for tienda in tiendas:
            plat = self.worker.plataformas.get(tienda)
            contextos[tienda] = self.contexto(tienda)
            if self.worker.modo_simulado:
                leidas = [{"nombre": "Producto de prueba", "id_remoto": "demo-1",
                           "precio": "1000.00", "error": ""},
                          {"nombre": "Otro producto", "id_remoto": "demo-2",
                           "precio": "1500.00", "error": ""}]
            elif plat is None:
                errores[tienda] = "No hay pestaña disponible"
                continue
            else:
                async with self.worker.bloqueo(tienda):
                    listo, motivo = await self._preparar(tienda)
                    if not listo:
                        errores[tienda] = motivo
                        continue
                    try:
                        leidas = await plat.listar_precios(lambda: (
                            not self.worker.en_verificacion(tienda)
                            and self.contexto(tienda) == contextos[tienda]))
                        if self.contexto(tienda) != contextos[tienda]:
                            raise ValueError("Cambió la tienda durante la lectura; volvé a leer")
                    except Exception as e:
                        errores[tienda] = str(e)
                        continue
            if not leidas:
                errores[tienda] = "No se pudo leer ningún precio"
            for f in leidas:
                clave = hashlib.sha256((tienda + "\0" + f["id_remoto"] + "\0" + f["nombre"]).encode()).hexdigest()
                filas.append({**f, "clave": clave, "tienda": tienda})
        token = secrets.token_hex(16)
        sin_precio = [f for f in filas if f.get("error") or f.get("precio") is None]
        log.info("Lectura de precios: tiendas=%s, %s productos, %s con errores",
                 ", ".join(tiendas), len(filas), len(sin_precio))
        for tienda, detalle in errores.items():
            log.warning("Leyendo precios de %s: %s", tienda, detalle)
        for fila in sin_precio[:10]:
            log.warning("Precio no leído en %s / %s: %s", fila["tienda"],
                        fila["nombre"] or fila["id_remoto"], fila.get("error") or "Sin precio")
        self.lecturas = {k: v for k, v in self.lecturas.items() if time.monotonic() - v["instante"] < 1800}
        if len(self.lecturas) >= 20:
            self.lecturas.pop(next(iter(self.lecturas)))
        self.lecturas[token] = {"instante": time.monotonic(), "filas": filas,
                                "tiendas": tiendas, "contextos": contextos, "errores": errores}
        return {"lectura": token, "filas": filas, "errores": errores,
                "leida_en": ahora(), "simulado": self.worker.modo_simulado}

    def preparar(self, lectura, tiendas, modo, alcance, cantidad, seleccionados,
                 individuales, redondeo):
        self.validar_tiendas(tiendas)
        base = self.lecturas.get(lectura)
        if not base or time.monotonic() - base["instante"] > 1800:
            raise ValueError("La lectura venció; volvé a leer los precios")
        if modo not in ("pesos", "porcentaje", "individual") or alcance not in ("toda", "seleccionados"):
            raise ValueError("Opciones inválidas")
        if any(t not in base["tiendas"] or t in base["errores"] for t in tiendas):
            raise ValueError("Falta leer correctamente las tiendas elegidas")
        candidatas = [f for f in base["filas"] if f["tienda"] in tiendas]
        claves = {f["clave"] for f in candidatas}
        if len(seleccionados) != len(set(seleccionados)) or not set(seleccionados) <= claves:
            raise ValueError("La selección no pertenece a esta lectura y tiendas")
        if not set(individuales) <= claves:
            raise ValueError("Un precio individual no pertenece a esta lectura y tiendas")
        if modo == "individual":
            candidatas = [f for f in candidatas if f["clave"] in individuales]
        elif alcance == "seleccionados":
            candidatas = [f for f in candidatas if f["clave"] in seleccionados]
        if not candidatas:
            raise ValueError("Elegí productos o ingresá precios individuales")
        filas = []
        for f in candidatas:
            if f["error"] or f["precio"] is None:
                raise ValueError("No se pudo leer el precio de " + f["nombre"] + "; volvé a leer o acotá la selección")
            actual = importe(f["precio"])
            nuevo = importe(individuales[f["clave"]]) if modo == "individual" else aumentar(
                actual, modo, cantidad, redondeo)
            if nuevo <= 0:
                raise ValueError("El precio final debe ser mayor que cero")
            if actual == nuevo:
                continue
            filas.append({"clave": f["clave"], "nombre": f["nombre"], "tienda": f["tienda"],
                          "id_remoto": f["id_remoto"], "antes": serializar(actual),
                          "despues": serializar(nuevo), "estado": "pendiente", "detalle": ""})
        if not filas:
            raise ValueError("No hay cambios de precio para ejecutar")
        for tienda in tiendas:
            if self.contexto(tienda) != base["contextos"][tienda]:
                raise ValueError("Cambió la tienda de Ajustes; volvé a leer")
        token = secrets.token_hex(16)
        self.planes = {k: v for k, v in self.planes.items() if time.monotonic() - v["instante"] < 1800}
        if len(self.planes) >= 20:
            self.planes.pop(next(iter(self.planes)))
        self.planes[token] = {"instante": time.monotonic(), "filas": filas,
                               "contextos": {t: base["contextos"][t] for t in tiendas},
                               "simulado": self.worker.modo_simulado, "trabajo": None}
        return {"plan": token, "filas": filas, "simulado": self.worker.modo_simulado}

    def ejecutar(self, token):
        plan = self.planes.get(token)
        if not plan:
            raise ValueError("No se encontró la vista previa; prepará otra")
        if plan["trabajo"]:
            return self.estado(plan["trabajo"])
        if self.activo:
            raise ValueError("Ya hay un lote de precios en ejecución")
        if time.monotonic() - plan["instante"] > 1800:
            raise ValueError("La vista previa venció; volvé a leer")
        self.validar_tiendas(list(plan["contextos"]))
        if any(self.contexto(t) != c for t, c in plan["contextos"].items()):
            raise ValueError("Cambió la tienda; prepará una nueva lectura")
        identidad = secrets.token_hex(16)
        trabajo = {"id": identidad, "estado": "ejecutando", "creado_en": ahora(),
                   "simulado": plan["simulado"], "cancelar": False,
                   "filas": [dict(f) for f in plan["filas"]]}
        self._guardar(trabajo)  # Si no se puede guardar el registro, no toca el portal.
        self.trabajos[identidad] = trabajo
        plan["trabajo"] = identidad
        self.activo = identidad
        self.tarea = asyncio.create_task(self._procesar(trabajo, plan))
        return self.estado(identidad)

    def cancelar(self, identidad):
        trabajo = self.trabajos.get(identidad)
        if not trabajo or trabajo["estado"] != "ejecutando":
            raise ValueError("El lote no está en ejecución")
        trabajo["cancelar"] = True
        self._guardar(trabajo)
        return self.estado(identidad)

    async def _procesar(self, trabajo, plan):
        try:
            for fila in trabajo["filas"]:
                tienda = fila["tienda"]
                if trabajo["cancelar"]:
                    fila["estado"] = "cancelado"
                    continue
                fila["estado"] = "en_curso"
                self._guardar(trabajo)
                try:
                    self.validar_tiendas([tienda])
                    if self.contexto(tienda) != plan["contextos"][tienda]:
                        raise ValueError("Cambió la tienda de Ajustes; no se editó")
                    if plan["simulado"]:
                        fila["estado"] = "simulado"
                        fila["detalle"] = "Simulación; no se editó el portal"
                    else:
                        async with self.worker.bloqueo(tienda):
                            # Revalidar después del lock: pudo cambiar mientras esperaba.
                            self.validar_tiendas([tienda])
                            if self.contexto(tienda) != plan["contextos"][tienda]:
                                raise ValueError("Cambió la tienda de Ajustes; no se editó")
                            if trabajo["cancelar"]:
                                fila["estado"] = "cancelado"
                                continue
                            listo, motivo = await self._preparar(tienda)
                            if not listo:
                                raise ValueError(motivo)
                            plat = self.worker.plataformas[tienda]
                            try:
                                ok = await asyncio.wait_for(plat.cambiar_precio(
                                    fila["nombre"], importe(fila["antes"]), importe(fila["despues"]),
                                    fila["id_remoto"], puede_tocar=lambda: (
                                        not self.worker.en_verificacion(tienda)
                                        and self.contexto(tienda) == plan["contextos"][tienda]
                                        and tienda in self.tiendas())),
                                    timeout=120)
                                fila["estado"] = "confirmado" if ok else "sin_confirmar"
                                fila["detalle"] = "Precio verificado después de recargar" if ok else "El precio guardado no coincide; releé el portal"
                            finally:
                                # No dejar el editor abierto en la pestaña del worker.
                                # La pantalla 2FA, si apareció, es siempre del usuario.
                                if not self.worker.en_verificacion(tienda):
                                    if await plat.en_verificacion():
                                        self.worker.congelar_por_verificacion(tienda, origen="detectada")
                                    else:
                                        await plat.volver_del_editor_precio(
                                            lambda: not self.worker.en_verificacion(tienda))
                    log.info("Precios %s / %s: %s → %s: %s", tienda, fila["nombre"],
                             fila["antes"], fila["despues"], fila["estado"])
                except Exception as e:
                    fila["estado"] = "sin_confirmar"
                    fila["detalle"] = str(e) or "Tiempo agotado; releé el portal"
                    log.warning("No se confirmó precio de %s / %s: %s", tienda, fila["nombre"], e)
                self._guardar(trabajo)
            trabajo["estado"] = "cancelado" if trabajo["cancelar"] else "terminado"
        except asyncio.CancelledError:
            trabajo["estado"] = "interrumpido"
            raise
        except Exception:
            trabajo["estado"] = "interrumpido"
            log.exception("Lote de precios interrumpido")
        finally:
            for fila in trabajo["filas"]:
                if fila["estado"] in ("pendiente", "en_curso"):
                    fila["estado"] = "sin_confirmar"
                    fila["detalle"] = "El lote se interrumpió; releé antes de ejecutar otro"
            trabajo["finalizado_en"] = ahora()
            self.activo = None
            self._guardar(trabajo)
