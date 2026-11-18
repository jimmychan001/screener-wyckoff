"""
Módulo "Clavicular y volumen": acumulación con secado de volumen  (gráfico DIARIO)
==================================================================================

Busca el patrón del video de Rankia (Clavicular y volumen):

  1) TENDENCIA PREVIA  caída fuerte antes del rango (el "último desarrollo tendencial")
  2) CLIMAX DE VENTA   barra de volumen gigante cerca del piso → "parada del precio"
  3) RANGO LATERAL     el precio lateraliza sobre el piso del climax sin romperlo
  4) VOLUMEN DECRECIENTE  la "línea amarilla": el volumen baja a lo largo del rango
  5) SECADO EN SOPORTE el "recuadro verde": volumen muy bajo con el precio en la
                       parte baja del rango o haciendo un mínimo más alto
  6) INTENCIÓN         ruptura del techo con volumen alto → alerta

Usa los mismos precios diarios que ya descarga screener.py (no descarga nada extra).
Los parámetros están en config.json → "secado".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DryUpResult:
    ticker: str
    close: float
    score: int              # 0-7 (cuántas condiciones cumple)
    estado: str             # "Acumulando · secado" / "Acumulando" / "INTENCIÓN ↑"
    climax_date: object
    climax_vol_x: float     # volumen del climax / promedio previo
    decline_pct: float      # caída previa hasta el climax
    floor: float            # piso del rango (clavicular inferior)
    top: float              # techo del rango (clavicular superior)
    width_pct: float
    range_days: int
    vol_slope_pct: float    # cambio % del volumen cada 20 sesiones dentro del rango (negativo = decrece)
    vol_late_early: float   # volumen promedio últimas 20 / primeras 20 sesiones del rango
    dryup_x: float          # volumen promedio últimas N sesiones / promedio del rango
    pos_pct: float          # posición del precio dentro del rango (0 = piso, 100 = techo)
    higher_low: bool
    breakout_date: object = None
    checks: str = ""


def scan_dryup(ticker: str, d: pd.DataFrame, p: dict) -> DryUpResult | None:
    """Analiza un DataFrame diario (Open/High/Low/Close/Volume). Devuelve None si no hay patrón."""
    d = d.dropna(subset=["Close", "Volume"])
    d = d[d["Volume"] > 0]
    if len(d) < p["avg_len"] + p["max_range_days"] + 20:
        return None

    c = d["Close"].values.astype(float)
    h = d["High"].values.astype(float)
    lo = d["Low"].values.astype(float)
    v = d["Volume"].values.astype(float)
    idx = d.index
    n = len(d)

    # liquidez mínima (precio × volumen promedio 50 sesiones)
    if np.mean(c[-50:] * v[-50:]) < p["min_dollar_vol"]:
        return None

    # ── 2) CLIMAX DE VENTA: la barra de mayor volumen relativo dentro de la ventana de búsqueda
    avg_prev = pd.Series(v).rolling(p["avg_len"]).mean().shift(1).values  # promedio ANTERIOR a cada barra
    start = n - p["max_range_days"]
    end = n - p["min_range_days"]
    best, best_x = -1, 0.0
    for i in range(max(start, p["avg_len"] + 1), end + 1):
        if np.isnan(avg_prev[i]) or avg_prev[i] <= 0:
            continue
        x = v[i] / avg_prev[i]
        # el climax tiene que ocurrir cerca de los mínimos de ese momento (no un pico de volumen en un rally)
        recent_low = lo[max(0, i - 10): i + 1].min()
        if x > best_x and lo[i] <= recent_low * 1.03:
            best, best_x = i, x
    if best < 0 or best_x < p["climax_mult"]:
        return None
    sc = best

    # ── 1) CAÍDA PREVIA: del máximo de los N días anteriores al climax hasta el mínimo del climax
    prior_hi = h[max(0, sc - p["prior_days"]): sc].max()
    climax_low = lo[max(0, sc - 3): sc + 4].min()
    decline = (prior_hi - climax_low) / prior_hi * 100

    # ── 3) RANGO: desde el climax hasta hoy (sin contar los días de ruptura recientes)
    bo_win = p["breakout_days"]
    rng_end = n - bo_win  # el rango se mide excluyendo las últimas sesiones (por si ya rompió)
    floor = lo[sc: rng_end].min()
    top = h[sc: rng_end].max()
    width = (top - floor) / floor * 100
    range_days = n - sc
    last = c[-1]

    # el precio no puede haber perforado el piso del climax con fuerza (eso sería continuación bajista)
    broke_down = floor < climax_low * (1 - p["max_undercut"] / 100) or last < floor * (1 - p["max_undercut"] / 100)

    # ── 4) VOLUMEN DECRECIENTE dentro del rango (excluye las barras del climax)
    skip = p["skip_after_climax"]
    rv = v[sc + skip: rng_end]
    if len(rv) < 30:
        return None
    t = np.arange(len(rv))
    slope = np.polyfit(t, np.log(rv), 1)[0]  # pendiente del log-volumen por sesión
    vol_slope_pct = (np.exp(slope * 20) - 1) * 100  # % de cambio cada 20 sesiones
    early = rv[:20].mean()
    late = v[rng_end - 20: rng_end].mean()
    late_early = late / early

    # ── 5) SECADO EN SOPORTE
    k = p["dryup_days"]
    range_avg = rv.mean()
    dry_x = v[-k:].mean() / range_avg
    pos = (last - floor) / (top - floor) * 100 if top > floor else 50.0
    recent_low = lo[-p["higher_low_days"]:].min()
    higher_low = recent_low > floor * (1 + p["higher_low_pct"] / 100)

    # ── 6) INTENCIÓN: cierre sobre el techo con volumen alto en las últimas sesiones
    avg20 = pd.Series(v).rolling(20).mean().shift(1).values
    breakout_i = None
    for i in range(n - bo_win, n):
        if c[i] > top and v[i] >= avg20[i] * p["breakout_mult"]:
            breakout_i = i
            break

    checks = {
        "caída previa": decline >= p["min_decline"],
        "climax": best_x >= p["climax_mult"],
        "rango": width <= p["max_width"] and not broke_down,
        "vol. pendiente ↓": vol_slope_pct <= p["max_vol_slope"],
        "vol. final/inicial": late_early <= p["max_late_early"],
        "secado": dry_x <= p["max_dryup"],
        "soporte / mínimo más alto": pos <= p["max_pos"] or higher_low,
    }
    # condiciones obligatorias: sin estas no es el patrón
    if not (checks["caída previa"] and checks["rango"]):
        return None
    score = int(sum(checks.values()))
    if breakout_i is None and score < p["min_score"]:
        return None
    if breakout_i is None and last > top:  # ya salió del rango sin volumen: ya no es acumulación
        return None

    if breakout_i is not None:
        estado = "INTENCIÓN ↑"
    elif checks["secado"] and checks["soporte / mínimo más alto"]:
        estado = "Acumulando · secado"
    else:
        estado = "Acumulando"

    return DryUpResult(
        ticker=ticker,
        close=round(float(last), 2),
        score=score,
        estado=estado,
        climax_date=idx[sc].date(),
        climax_vol_x=round(float(best_x), 1),
        decline_pct=round(float(decline), 1),
        floor=round(float(floor), 2),
        top=round(float(top), 2),
        width_pct=round(float(width), 1),
        range_days=int(range_days),
        vol_slope_pct=round(float(vol_slope_pct), 1),
        vol_late_early=round(float(late_early), 2),
        dryup_x=round(float(dry_x), 2),
        pos_pct=round(float(pos), 0),
        higher_low=bool(higher_low),
        breakout_date=idx[breakout_i].date() if breakout_i is not None else None,
        checks=" · ".join(k for k, ok in checks.items() if not ok) or "todas",
    )


def report_section(results: list[DryUpResult], funds: dict[str, dict]) -> list[str]:
    """Sección markdown para el reporte diario."""
    lines = [
        "## 🔍 Clavicular y volumen: acumulación con secado de volumen (diario)",
        "",
        "Caída previa → climax de venta → rango lateral con **volumen decreciente** y **secado cerca del soporte**. "
        "La *intención* es la ruptura del techo con volumen alto.",
        "",
    ]
    if not results:
        return lines + ["_Ninguna hoy._", ""]

    order = {"INTENCIÓN ↑": 0, "Acumulando · secado": 1, "Acumulando": 2}
    results = sorted(results, key=lambda r: (order[r.estado], -r.score, r.dryup_x))
    lines += [
        "| Ticker | Empresa | Estado | Puntaje | Precio | Piso–Techo | Posición | Climax | Caída previa | "
        "Vol. c/20 ses. | Vol. final/inicial | Secado | Mín. más alto | Fund. | Falta |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        fu = funds.get(r.ticker, {})
        name = fu.get("name", "")
        fund = f"{fu['score']}/{fu['avail']}" if fu else "s/d"
        estado = f"**{r.estado}** ({r.breakout_date})" if r.breakout_date else r.estado
        lines.append(
            f"| **{r.ticker}** | {name} | {estado} | {r.score}/7 | {r.close} | {r.floor}–{r.top} | {r.pos_pct:.0f}% | "
            f"{r.climax_date} ({r.climax_vol_x}x) | {r.decline_pct}% | {r.vol_slope_pct:+.0f}% | {r.vol_late_early}x | "
            f"{r.dryup_x}x | {'sí' if r.higher_low else 'no'} | {fund} | {r.checks} |"
        )
    lines += [
        "",
        "**Cómo leer:** *Posición* 0% = en el piso, 100% = en el techo. *Vol. c/20 ses.* = cuánto cambia el volumen "
        "cada 20 sesiones dentro del rango (negativo = la línea amarilla baja). *Vol. final/inicial* < 1 = el volumen "
        "del final del rango es menor que el del inicio. *Secado* = volumen de los últimos días / promedio del rango "
        "(< 0.6 = recuadro verde). *Falta* = condiciones que no cumple.",
        "",
    ]
    return lines


def to_rows(results: list[DryUpResult], funds: dict[str, dict]) -> list[dict]:
    rows = []
    for r in results:
        fu = funds.get(r.ticker, {})
        rows.append({
            "ticker": r.ticker, "empresa": fu.get("name", ""), "sector": fu.get("sector", ""),
            "estado": r.estado, "puntaje": r.score, "precio": r.close, "piso": r.floor, "techo": r.top,
            "ancho_pct": r.width_pct, "posicion_pct": r.pos_pct, "dias_rango": r.range_days,
            "fecha_climax": r.climax_date, "climax_vol_x": r.climax_vol_x, "caida_previa_pct": r.decline_pct,
            "vol_pendiente_20s_pct": r.vol_slope_pct, "vol_final_inicial": r.vol_late_early,
            "secado_x": r.dryup_x, "minimo_mas_alto": r.higher_low, "fecha_ruptura": r.breakout_date or "",
            "fund_score": fu.get("score", ""), "fund_disp": fu.get("avail", ""), "falta": r.checks,
        })
    return rows
