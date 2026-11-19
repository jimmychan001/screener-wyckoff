"""
Módulo "Estrellas en soporte/resistencia"  (gráfico DIARIO)
===========================================================

Busca dos patrones de giro de tres velas, pero SOLO cuando aparecen sobre un nivel
relevante del gráfico:

  ⭐ ESTRELLA DEL AMANECER (alcista) sobre un SOPORTE
     1) vela bajista grande (después de una bajada)
     2) vela de cuerpo pequeño (la "estrella") que queda abajo
     3) vela alcista que cierra sobre la mitad del cuerpo de la vela 1

  🌆 ESTRELLA DEL ATARDECER (bajista) bajo una RESISTENCIA
     el espejo: vela alcista grande → estrella arriba → vela bajista que cierra
     bajo la mitad del cuerpo de la vela 1

SOPORTES Y RESISTENCIAS: se calculan solos con los máximos y mínimos pivote del
último año. Los pivotes cercanos (a menos de `cluster_atr` ATR) se agrupan en una
zona; cuantos más toques, más fuerte el nivel. Un mínimo anterior que se rompió
puede actuar como resistencia y al revés (cambio de polaridad), por eso se usan
todos los pivotes.

COINCIDENCIA: el patrón cuenta solo si el extremo de las tres velas (el mínimo en
la estrella del amanecer, el máximo en la del atardecer) toca la zona, con una
tolerancia de `tol_atr` ATR, y la vela 3 cierra del lado correcto del nivel.

CONTEXTO (no filtra, pero se reporta): RVOL de la vela 3 (volumen / promedio de 50
sesiones) y la tendencia de fondo (precio vs. media de 150 días ≈ 30 semanas de
Weinstein, y si esa media sube o baja).

Usa los mismos precios diarios que ya descarga screener.py (no descarga nada extra).
Los parámetros están en config.json → "estrellas".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class StarResult:
    ticker: str
    tipo: str               # "Amanecer ⭐" o "Atardecer 🌆"
    fecha: object           # fecha de la vela 3 (la que completa el patrón)
    dias: int               # sesiones desde que se completó (0 = hoy)
    close: float            # cierre actual
    nivel: float            # precio del soporte / resistencia
    nivel_tipo: str         # "Soporte" / "Resistencia" / "Soporte (ex-resistencia)" ...
    toques: int             # cuántos pivotes forman la zona
    dist_atr: float         # distancia del extremo del patrón al nivel, en ATR
    rvol3: float            # volumen de la vela 3 / promedio 50 sesiones
    tendencia: str          # contexto de la media de 150 días
    stop: float             # extremo del patrón (referencia de invalidación)


# ───────────────────────── utilidades ─────────────────────────
def _atr(h: np.ndarray, lo: np.ndarray, c: np.ndarray, n: int) -> np.ndarray:
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - prev_c), np.abs(lo - prev_c)))
    return pd.Series(tr).rolling(n).mean().values


def _pivots(h: np.ndarray, lo: np.ndarray, L: int, R: int, start: int, end: int):
    """Pivotes confirmados entre start y end (end excluido). Devuelve listas de (índice, precio)."""
    highs, lows = [], []
    for i in range(max(start, L), min(end, len(h) - R)):
        if i + R >= end:
            break
        if h[i] == h[i - L: i + R + 1].max():
            highs.append((i, h[i]))
        if lo[i] == lo[i - L: i + R + 1].min():
            lows.append((i, lo[i]))
    return highs, lows


def _levels(highs, lows, atr: float, cluster_atr: float):
    """Agrupa pivotes cercanos en zonas. Cada zona: precio medio, toques, de dónde vienen."""
    pts = [(p, "H") for _, p in highs] + [(p, "L") for _, p in lows]
    if not pts:
        return []
    pts.sort()
    zones, cur = [], [pts[0]]
    for p in pts[1:]:
        if p[0] - cur[-1][0] <= cluster_atr * atr:
            cur.append(p)
        else:
            zones.append(cur)
            cur = [p]
    zones.append(cur)
    out = []
    for z in zones:
        prices = [p for p, _ in z]
        kinds = {k for _, k in z}
        out.append({"price": float(np.mean(prices)), "touches": len(z), "kinds": kinds})
    return out


def _level_name(kinds: set, bullish: bool) -> str:
    if bullish:  # el nivel actúa como soporte
        if kinds == {"H"}:
            return "Soporte (ex-resistencia)"
        return "Soporte"
    if kinds == {"L"}:
        return "Resistencia (ex-soporte)"
    return "Resistencia"


# ───────────────────────── detección ─────────────────────────
def _is_morning(o, h, lo, c, i1, atr, p) -> bool:
    i2, i3 = i1 + 1, i1 + 2
    body1 = o[i1] - c[i1]
    if body1 <= 0 or body1 < p["min_body_atr"] * atr:
        return False
    if body1 < p["min_body_range"] * (h[i1] - lo[i1]):
        return False
    body2 = abs(c[i2] - o[i2])
    if body2 > p["max_star_body"] * body1:
        return False
    # la estrella queda abajo: su cuerpo no sube más allá del cierre de la vela 1 (con un margen)
    if max(o[i2], c[i2]) > c[i1] + p["star_overlap"] * body1:
        return False
    body3 = c[i3] - o[i3]
    if body3 <= 0 or body3 < p["min_body3_atr"] * atr:
        return False
    # la vela 3 cierra sobre la mitad (o el % configurado) del cuerpo de la vela 1
    return c[i3] >= c[i1] + p["penetration"] * body1


def _is_evening(o, h, lo, c, i1, atr, p) -> bool:
    i2, i3 = i1 + 1, i1 + 2
    body1 = c[i1] - o[i1]
    if body1 <= 0 or body1 < p["min_body_atr"] * atr:
        return False
    if body1 < p["min_body_range"] * (h[i1] - lo[i1]):
        return False
    body2 = abs(c[i2] - o[i2])
    if body2 > p["max_star_body"] * body1:
        return False
    if min(o[i2], c[i2]) < c[i1] - p["star_overlap"] * body1:
        return False
    body3 = o[i3] - c[i3]
    if body3 <= 0 or body3 < p["min_body3_atr"] * atr:
        return False
    return c[i3] <= c[i1] - p["penetration"] * body1


def scan_stars(ticker: str, d: pd.DataFrame, p: dict) -> list[StarResult]:
    """Analiza un DataFrame diario (Open/High/Low/Close/Volume). Devuelve los patrones recientes en S/R."""
    d = d.dropna(subset=["Open", "High", "Low", "Close"])
    if len(d) < max(p["lookback"], 160) + 20:
        return []

    o = d["Open"].values.astype(float)
    h = d["High"].values.astype(float)
    lo = d["Low"].values.astype(float)
    c = d["Close"].values.astype(float)
    v = d["Volume"].fillna(0).values.astype(float)
    idx = d.index
    n = len(d)

    if np.mean(c[-50:] * v[-50:]) < p["min_dollar_vol"]:
        return []

    atr = _atr(h, lo, c, p["atr_len"])
    vavg = pd.Series(v).rolling(50).mean().shift(1).values
    ma = pd.Series(c).rolling(150).mean().values

    out: list[StarResult] = []
    for k in range(p["recent_days"]):
        i3 = n - 1 - k
        i1 = i3 - 2
        a = atr[i1 - 1]  # ATR previo al patrón
        if np.isnan(a) or a <= 0:
            continue
        tb = p["trend_days"]
        bull = _is_morning(o, h, lo, c, i1, a, p) and c[i1 - 1] < c[i1 - 1 - tb]   # venía bajando
        bear = _is_evening(o, h, lo, c, i1, a, p) and c[i1 - 1] > c[i1 - 1 - tb]   # venía subiendo
        if not (bull or bear):
            continue

        # niveles con pivotes confirmados ANTES de la vela 1
        highs, lows = _pivots(h, lo, p["piv"], p["piv"], i1 - p["lookback"], i1)
        zones = [z for z in _levels(highs, lows, a, p["cluster_atr"]) if z["touches"] >= p["min_touches"]]
        tol = p["tol_atr"] * a

        if bull:
            ext = lo[i1: i3 + 1].min()
            star_low_body = min(o[i1 + 1], c[i1 + 1])
            cands = [z for z in zones if ext - tol <= z["price"] <= star_low_body + tol and c[i3] > z["price"]]
        else:
            ext = h[i1: i3 + 1].max()
            star_high_body = max(o[i1 + 1], c[i1 + 1])
            cands = [z for z in zones if star_high_body - tol <= z["price"] <= ext + tol and c[i3] < z["price"]]
        if not cands:
            continue
        z = max(cands, key=lambda z: (z["touches"], -abs(z["price"] - ext)))

        # contexto de tendencia (media de 150 días ≈ 30 semanas)
        if np.isnan(ma[i3]) or np.isnan(ma[i3 - 20]):
            trend = "s/d"
        else:
            above = c[i3] > ma[i3]
            rising = ma[i3] > ma[i3 - 20]
            trend = ("sobre" if above else "bajo") + " MA150 " + ("↑" if rising else "↓")

        rv = v[i3] / vavg[i3] if vavg[i3] and not np.isnan(vavg[i3]) else float("nan")
        out.append(StarResult(
            ticker=ticker,
            tipo="Amanecer ⭐" if bull else "Atardecer 🌆",
            fecha=idx[i3].date(),
            dias=k,
            close=round(float(c[-1]), 2),
            nivel=round(z["price"], 2),
            nivel_tipo=_level_name(z["kinds"], bull),
            toques=int(z["touches"]),
            dist_atr=round(float(abs(ext - z["price"]) / a), 2),
            rvol3=round(float(rv), 2),
            tendencia=trend,
            stop=round(float(ext), 2),
        ))
    return out


# ───────────────────────── reporte ─────────────────────────
def report_section(results: list[StarResult], funds: dict[str, dict], rvol_ok: float) -> list[str]:
    lines = [
        "## ⭐ Estrellas del amanecer / atardecer en soporte o resistencia (diario)",
        "",
        "Patrón de giro de tres velas que coincide con un nivel de soporte/resistencia calculado con pivotes. "
        f"✅ = la vela 3 tuvo volumen alto (RVOL ≥ {rvol_ok}).",
        "",
    ]
    if not results:
        return lines + ["_Ninguna en los últimos días._", ""]
    results = sorted(results, key=lambda r: (r.dias, r.tipo, -r.toques))
    lines += [
        "| Ticker | Empresa | Patrón | Fecha | Precio | Nivel | Toques | Extremo (stop) | RVOL vela 3 | Tendencia | Fund. |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        fu = funds.get(r.ticker, {})
        fund = f"{fu['score']}/{fu['avail']}" if fu else "—"
        vol = f"{r.rvol3}{' ✅' if r.rvol3 >= rvol_ok else ''}"
        lines.append(
            f"| **{r.ticker}** | {fu.get('name', '')} | {r.tipo} | {r.fecha} | {r.close} | {r.nivel_tipo} {r.nivel} | "
            f"{r.toques} | {r.stop} | {vol} | {r.tendencia} | {fund} |"
        )
    lines += [
        "",
        "**Cómo leer:** *Nivel* = zona de pivotes donde apareció el patrón (*ex-resistencia* = un techo roto que ahora "
        "hace de soporte). *Toques* = cuántos pivotes forman la zona (más = más fuerte). *Extremo* = mínimo (amanecer) "
        "o máximo (atardecer) de las tres velas, referencia para el stop. *Tendencia*: un amanecer **sobre MA150 ↑** "
        "es un retroceso en Etapa 2; **bajo MA150 ↓** es contra tendencia (más riesgoso). Confírmalo siempre en el gráfico.",
        "",
    ]
    return lines


def to_rows(results: list[StarResult], funds: dict[str, dict]) -> list[dict]:
    return [{
        "ticker": r.ticker, "empresa": funds.get(r.ticker, {}).get("name", ""), "patron": r.tipo,
        "fecha": r.fecha, "dias": r.dias, "precio": r.close, "nivel": r.nivel, "tipo_nivel": r.nivel_tipo,
        "toques": r.toques, "dist_atr": r.dist_atr, "extremo_stop": r.stop, "rvol_vela3": r.rvol3,
        "tendencia": r.tendencia,
    } for r in results]
