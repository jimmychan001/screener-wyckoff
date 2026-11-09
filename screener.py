"""
Screener Wyckoff + Weinstein + Fundamentales  (para comprar y holdear)
======================================================================

Corre solo en GitHub Actions cada día hábil. Trabaja en gráfico SEMANAL:

  1) CONTEXTO   caída previa + rango lateral + media de 30 semanas plana
                → posible Etapa 1 de Weinstein / acumulación Wyckoff
  2) ESTRUCTURA Spring/Test (Fase C) → CHoCH alcista (+SOS si hay volumen)
                → LPS → ruptura del techo con volumen (Fase E = Etapa 2)
  3) RESPALDO   fuerza relativa Mansfield vs SPY + puntaje fundamental 0-7

Resultado: reports/latest.md (+ histórico por fecha y CSV).
Es la misma lógica del indicador de TradingView "Wyckoff+Fund".
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
REPORTS = ROOT / "reports"

PHASE_TXT = {
    0: "Sin rango",
    1: "Rango · Fase B",
    2: "Spring/Test · Fase C",
    3: "CHoCH/SOS · Fase D",
    4: "LPS · Fase D",
    5: "Ruptura · Fase E (Etapa 2)",
}


# ───────────────────────────── UNIVERSO ─────────────────────────────
def load_universe() -> list[str]:
    tickers: set[str] = set()
    for name in CONFIG["universe"]:
        if name == "sp500":
            tickers |= set(_wiki_table("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"))
        elif name == "nasdaq100":
            tickers |= set(_wiki_table("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker"))
    wl = ROOT / "watchlist.txt"
    if wl.exists():
        for line in wl.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip().upper()
            if line:
                tickers.add(line)
    if not tickers:
        sys.exit("Universo vacío: revisa config.json y watchlist.txt")
    return sorted(t.replace(".", "-") for t in tickers)


def _wiki_table(url: str, col: str) -> list[str]:
    import io
    import requests

    try:
        html = requests.get(url, headers={"User-Agent": "screener-wyckoff/1.0"}, timeout=30).text
        for tbl in pd.read_html(io.StringIO(html)):
            if col in tbl.columns:
                return tbl[col].astype(str).str.strip().tolist()
    except Exception as e:  # noqa: BLE001
        print(f"[aviso] no se pudo leer {url}: {e}")
    return []


# ───────────────────────────── DATOS ─────────────────────────────
def download_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    chunk = 100
    for i in range(0, len(tickers), chunk):
        part = tickers[i : i + chunk]
        for attempt in range(3):
            try:
                raw = yf.download(part, period="4y", interval="1d", group_by="ticker",
                                  auto_adjust=True, threads=True, progress=False)
                break
            except Exception as e:  # noqa: BLE001
                print(f"[aviso] descarga fallida ({e}), reintento {attempt + 1}")
                time.sleep(10)
        else:
            continue
        for t in part:
            try:
                d = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                d = d.dropna(subset=["Close"])
                if len(d) > 300:
                    out[t] = d
            except KeyError:
                pass
        time.sleep(2)
    return out


def to_weekly(d: pd.DataFrame) -> pd.DataFrame:
    w = d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return w.dropna(subset=["Close"])


# ───────────────────────────── ANÁLISIS TÉCNICO ─────────────────────────────
@dataclass
class TechResult:
    ticker: str
    close: float
    phase: int
    stage: int
    width_pct: float
    decline_pct: float
    ma_slope: float
    vol_ratio: float
    mrs: float
    rs_up: bool
    range_top: float | None
    range_bot: float | None
    events: list = field(default_factory=list)  # (fecha, evento, precio)

    @property
    def last_event(self):
        return self.events[-1] if self.events else None


def _pivots(high: np.ndarray, low: np.ndarray, L: int, R: int):
    """Devuelve arrays con el valor del pivote en la barra donde se CONFIRMA (i), como ta.pivothigh."""
    n = len(high)
    ph = np.full(n, np.nan)
    pl = np.full(n, np.nan)
    for i in range(L + R, n):
        c = i - R
        win_h = high[c - L : i + 1]
        win_l = low[c - L : i + 1]
        if high[c] == win_h.max() and (high[c] > high[c + 1 : i + 1]).all():
            ph[i] = high[c]
        if low[c] == win_l.min() and (low[c] < low[c + 1 : i + 1]).all():
            pl[i] = low[c]
    return ph, pl


def analyze(ticker: str, w: pd.DataFrame, bench_w: pd.Series, p: dict) -> TechResult | None:
    if len(w) < p["min_weeks"]:
        return None
    o = w.copy()
    c, h, l, v = o["Close"], o["High"], o["Low"], o["Volume"]

    ma = c.rolling(p["ma_len"]).mean()
    slope = (ma - ma.shift(p["slope_lb"])) / ma.shift(p["slope_lb"]) * 100
    hh = h.rolling(p["range_len"]).max()
    ll = l.rolling(p["range_len"]).min()
    width = (hh - ll) / ll * 100
    prior_high = h.rolling(p["prior_len"]).max().shift(p["range_len"])
    decl = (prior_high - ll) / prior_high * 100
    decline_ok = decl >= p["min_decline"]
    flat = slope.abs() <= p["flat_pct"]
    is_consol = (width <= p["max_width"]) & flat & decline_ok

    avg_vol = v.rolling(p["vol_len"]).mean()
    hi_vol = v > avg_vol * p["vol_mult"]
    lo_vol = v < avg_vol
    up = c > c.shift(1)
    dn = c < c.shift(1)
    up_v = v.where(up, 0).rolling(p["range_len"]).sum()
    dn_v = v.where(dn, 0).rolling(p["range_len"]).sum()

    bench = bench_w.reindex(o.index).ffill()
    rs = c / bench
    mrs = (rs / rs.rolling(p["rs_len"]).mean() - 1) * 100

    ph, pl = _pivots(h.values, l.values, p["piv"], p["piv"])

    # máquina de estados (idéntica al indicador de TradingView)
    phase, r_top, r_bot, choch_bar, event_bar = 0, np.nan, np.nan, -1, -1
    last_evt = -1  # última barra con Spring/CHoCH/LPS (para vencer estructuras viejas)
    ph1 = ph0 = pl1 = pl0 = np.nan
    events: list = []
    idx = o.index
    C, H, Lw, V = c.values, h.values, l.values, v.values
    AV, HV, LV, MA = avg_vol.values, hi_vol.values, lo_vol.values, ma.values
    R = p["piv"]
    for i in range(1, len(o)):
        if not np.isnan(ph[i]):
            ph0, ph1 = ph1, ph[i]
        if not np.isnan(pl[i]):
            pl0, pl1 = pl1, pl[i]
        lower_highs = not np.isnan(ph0) and not np.isnan(ph1) and ph1 < ph0
        choch = (not np.isnan(ph1)) and C[i] > ph1 and C[i - 1] <= ph1 and lower_highs
        d = idx[i].date()
        bo_now = False

        if phase == 0 and bool(is_consol.iloc[i]):
            phase, r_top, r_bot, event_bar = 1, hh.iloc[i], ll.iloc[i], i
            events.append((d, "Rango detectado", round(float(C[i]), 2)))

        if 1 <= phase <= 4:
            if phase <= 2 and Lw[i] < r_bot and C[i] > r_bot:
                name = ("Shakeout" if HV[i] else "Spring") if phase == 1 else "Test"
                events.append((d, name + (" (vol bajo)" if LV[i] else ""), round(float(Lw[i]), 2)))
                phase, last_evt = 2, i
            if phase in (1, 2) and choch and C[i] > r_bot:
                choch_bar = i
                events.append((d, "CHoCH + SOS" if HV[i] else "CHoCH (sin volumen)", round(float(C[i]), 2)))
                phase, last_evt = 3, i
            if (phase == 3 and not np.isnan(pl[i]) and (i - R) > choch_bar and pl[i] > r_bot
                    and (np.isnan(pl0) or pl[i] > pl0) and V[i - R] < AV[i - R]):
                events.append((idx[i - R].date(), "LPS", round(float(pl[i]), 2)))
                phase, last_evt = 4, i
            if C[i] > r_top and HV[i] and C[i] > MA[i]:
                events.append((d, "Ruptura Etapa 2" if phase >= 3 else "Ruptura sin CHoCH previo", round(float(C[i]), 2)))
                phase, event_bar, bo_now = 5, i, True
            tol = 1 - p["break_tol"] / 100
            if phase < 5 and C[i] < r_bot * tol and C[i - 1] < r_bot * tol:
                events.append((d, "Rango roto ↓", round(float(C[i]), 2)))
                phase = 0
        if phase in (2, 3, 4) and i - last_evt > p["max_phase_age"]:
            events.append((d, "Estructura vencida (sin avance)", round(float(C[i]), 2)))
            phase = 0
        if phase == 5 and not bo_now and (C[i] < r_bot or i - event_bar > p["post_bars"]):
            phase = 0

    s = float(slope.iloc[-1])
    last = float(c.iloc[-1])
    # Etapa estimada: una ruptura de rango sobre una media que sube suave también es Etapa 2
    # (reacumulación resuelta al alza), no solo la media con pendiente fuerte.
    if last > ma.iloc[-1] and (s > p["flat_pct"] or (s > 0 and phase == 5)):
        stage = 2
    elif last < ma.iloc[-1] and s < -p["flat_pct"]:
        stage = 4
    elif abs(s) <= p["flat_pct"] and bool(decline_ok.iloc[-1]):
        stage = 1
    else:
        stage = 3

    mrs_now = float(mrs.iloc[-1]) if not np.isnan(mrs.iloc[-1]) else np.nan
    mrs_prev = mrs.iloc[-1 - p["rs_lb"]] if len(mrs) > p["rs_lb"] else np.nan
    return TechResult(
        ticker=ticker,
        close=round(last, 2),
        phase=phase,
        stage=stage,
        width_pct=round(float(width.iloc[-1]), 1),
        decline_pct=round(float(decl.iloc[-1]), 1) if not np.isnan(decl.iloc[-1]) else np.nan,
        ma_slope=round(s, 2),
        vol_ratio=round(float(up_v.iloc[-1] / dn_v.iloc[-1]), 2) if dn_v.iloc[-1] else np.nan,
        mrs=round(mrs_now, 2) if not np.isnan(mrs_now) else np.nan,
        rs_up=bool(mrs_now > mrs_prev) if not (np.isnan(mrs_now) or np.isnan(mrs_prev)) else False,
        range_top=round(float(r_top), 2) if phase else None,
        range_bot=round(float(r_bot), 2) if phase else None,
        events=events,
    )


# ───────────────────────────── FUNDAMENTALES ─────────────────────────────
FUND_KEYS = [
    ("Ventas a/a", "revenueGrowth", lambda x, f: x * 100 >= f["min_rev_growth"], lambda x: f"{x*100:.1f}%"),
    ("BPA a/a", "earningsGrowth", lambda x, f: x * 100 >= f["min_eps_growth"], lambda x: f"{x*100:.1f}%"),
    ("BPA TTM > 0", "trailingEps", lambda x, f: x > 0, lambda x: f"{x:.2f}"),
    ("Flujo caja libre > 0", "freeCashflow", lambda x, f: x > 0, lambda x: f"{x/1e6:,.0f} M"),
    ("ROE", "returnOnEquity", lambda x, f: x * 100 >= f["min_roe"], lambda x: f"{x*100:.1f}%"),
    ("Deuda/Patrimonio", "debtToEquity", lambda x, f: 0 <= x / 100 <= f["max_de"], lambda x: f"{x/100:.2f}"),
    ("Margen neto > 0", "profitMargins", lambda x, f: x > 0, lambda x: f"{x*100:.1f}%"),
]


def fundamentals(ticker: str) -> dict:
    import yfinance as yf

    f = CONFIG["fundamentals"]
    info = {}
    for attempt in range(3):
        try:
            info = yf.Ticker(ticker).info or {}
            break
        except Exception as e:  # noqa: BLE001
            print(f"[aviso] info {ticker}: {e}")
            time.sleep(5)
    score, avail, detail = 0, 0, {}
    for label, key, ok_fn, fmt in FUND_KEYS:
        x = info.get(key)
        if x is None or (isinstance(x, float) and np.isnan(x)):
            detail[label] = "s/d"
            continue
        avail += 1
        ok = bool(ok_fn(x, f))
        score += ok
        detail[label] = f"{fmt(x)} {'✓' if ok else '✗'}"
    return {
        "name": info.get("shortName", ticker),
        "sector": info.get("sector", ""),
        "pe": info.get("trailingPE"),
        "fpe": info.get("forwardPE"),
        "score": score,
        "avail": avail,
        "ok": avail > 0 and score >= f["min_score"],
        "detail": detail,
    }


# ───────────────────────────── REPORTE ─────────────────────────────
def verdict(t: TechResult, fu: dict) -> str:
    if t.phase >= 3 and fu["ok"]:
        return "CANDIDATO ✓"
    if t.phase >= 3:
        return "Técnico sí, fundamental débil"
    if t.phase in (1, 2) and fu["ok"]:
        return "Vigilar: falta CHoCH"
    return "No cumple"


def fmt_num(x, suf=""):
    return "s/d" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x}{suf}"


def build_report(rows: list[tuple[TechResult, dict]], n_scanned: int, today: dt.date) -> tuple[str, list]:
    recent_days = CONFIG["report"]["recent_event_days"]
    cutoff = today - dt.timedelta(days=recent_days)
    groups = {"CANDIDATO ✓": [], "Vigilar: falta CHoCH": [], "Técnico sí, fundamental débil": []}
    fresh_signals = []
    for t, fu in rows:
        v = verdict(t, fu)
        if v in groups:
            groups[v].append((t, fu))
        ev = t.last_event
        if ev and ev[0] >= cutoff and fu["ok"] and any(k in ev[1] for k in ("CHoCH", "LPS", "Ruptura")):
            fresh_signals.append((t, fu, ev))

    def sort_key(x):
        t, fu = x
        return (-t.phase, -fu["score"], -(t.mrs if not np.isnan(t.mrs) else -999))

    lines = [
        f"# Screener Wyckoff + Weinstein + Fundamentales — {today.isoformat()}",
        "",
        f"Acciones analizadas: **{n_scanned}** · gráfico **semanal** · referencia RS: {CONFIG['benchmark']}",
        "",
        "> Detecciones mecánicas: cada candidata debe confirmarse a ojo en TradingView con el indicador Wyckoff+Fund.",
        "> No es una recomendación de inversión.",
        "",
    ]
    if fresh_signals:
        lines += [f"## 🔔 Señales nuevas (últimos {recent_days} días) con fundamentales aptos", ""]
        lines += ["| Ticker | Empresa | Evento | Fecha | Precio | Fund. |", "|---|---|---|---|---|---|"]
        for t, fu, ev in fresh_signals:
            lines.append(f"| **{t.ticker}** | {fu['name']} | {ev[1]} | {ev[0]} | {ev[2]} | {fu['score']}/{fu['avail']} |")
        lines.append("")

    titles = {
        "CANDIDATO ✓": "## ✅ Candidatos: estructura Fase D/E + fundamentales aptos",
        "Vigilar: falta CHoCH": "## 👀 En vigilancia: rango de acumulación con fundamentales aptos (falta CHoCH)",
        "Técnico sí, fundamental débil": "## ⚠️ Estructura alcista pero fundamental débil",
    }
    for key, title in titles.items():
        items = sorted(groups[key], key=sort_key)
        lines += [title, ""]
        if not items:
            lines += ["_Ninguna hoy._", ""]
            continue
        lines += [
            "| Ticker | Empresa | Sector | Precio | Fase | Etapa | Rango (piso–techo) | Ancho | Vol ↑/↓ | RS Mansfield | Fund. | Último evento |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for t, fu in items:
            ev = t.last_event
            ev_txt = f"{ev[1]} ({ev[0]})" if ev else ""
            rng = f"{t.range_bot}–{t.range_top}" if t.range_top else ""
            rs = f"{fmt_num(t.mrs)} {'↑' if t.rs_up else '↓'}"
            lines.append(
                f"| **{t.ticker}** | {fu['name']} | {fu['sector']} | {t.close} | {PHASE_TXT[t.phase]} | {t.stage} | "
                f"{rng} | {t.width_pct}% | {fmt_num(t.vol_ratio, 'x')} | {rs} | {fu['score']}/{fu['avail']} | {ev_txt} |"
            )
        lines.append("")

    # detalle fundamental de candidatos y vigilancia
    det = sorted(groups["CANDIDATO ✓"] + groups["Vigilar: falta CHoCH"], key=sort_key)
    if det:
        lines += ["## Detalle fundamental", ""]
        hdr = [k[0] for k in FUND_KEYS]
        lines += ["| Ticker | " + " | ".join(hdr) + " | P/E | P/E fwd |", "|---" * (len(hdr) + 3) + "|"]
        for t, fu in det:
            pe = f"{fu['pe']:.1f}" if fu["pe"] else "s/d"
            fpe = f"{fu['fpe']:.1f}" if fu["fpe"] else "s/d"
            lines.append(f"| {t.ticker} | " + " | ".join(fu["detail"][h] for h in hdr) + f" | {pe} | {fpe} |")
        lines.append("")

    lines += [
        "---",
        "**Cómo leer:** Fase B = rango en formación · C = Spring/Test · D = CHoCH/SOS o LPS (zona de compra) · "
        "E = ruptura con volumen (inicio Etapa 2). Vol ↑/↓ > 1 = más volumen en semanas alcistas (huella de acumulación). "
        "RS Mansfield > 0 y ↑ = supera al índice.",
    ]
    return "\n".join(lines), fresh_signals


# ───────────────────────────── MAIN ─────────────────────────────
def main() -> None:
    today = dt.date.today()
    p = CONFIG["technical"]
    tickers = load_universe()
    bench = CONFIG["benchmark"]
    print(f"Universo: {len(tickers)} acciones")
    prices = download_prices(sorted(set(tickers) | {bench}))
    if bench not in prices:
        sys.exit("No se pudo descargar el índice de referencia")
    bench_w = to_weekly(prices[bench])["Close"]

    techs: list[TechResult] = []
    for t in tickers:
        if t == bench or t not in prices:
            continue
        try:
            r = analyze(t, to_weekly(prices[t]), bench_w, p)
        except Exception as e:  # noqa: BLE001
            print(f"[aviso] {t}: {e}")
            continue
        if r and r.phase >= 1:
            techs.append(r)
    print(f"Con estructura activa (Fase B–E): {len(techs)}")

    rows = []
    for t in techs:
        rows.append((t, fundamentals(t.ticker)))
        time.sleep(0.5)

    report, fresh = build_report(rows, len(prices) - 1, today)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "latest.md").write_text(report, encoding="utf-8")
    (REPORTS / f"{today.isoformat()}.md").write_text(report, encoding="utf-8")
    pd.DataFrame(
        [{
            "ticker": t.ticker, "empresa": fu["name"], "sector": fu["sector"], "precio": t.close,
            "fase": t.phase, "fase_txt": PHASE_TXT[t.phase], "etapa": t.stage, "piso": t.range_bot,
            "techo": t.range_top, "ancho_pct": t.width_pct, "vol_ratio": t.vol_ratio, "rs_mansfield": t.mrs,
            "rs_mejora": t.rs_up, "fund_score": fu["score"], "fund_disp": fu["avail"], "veredicto": verdict(t, fu),
            "ultimo_evento": t.last_event[1] if t.last_event else "", "fecha_evento": t.last_event[0] if t.last_event else "",
        } for t, fu in rows]
    ).to_csv(REPORTS / "latest.csv", index=False)

    # texto para el issue de notificación (lo usa el workflow)
    if fresh:
        body = ["Señales nuevas con fundamentales aptos:", ""]
        body += [f"- **{t.ticker}** ({fu['name']}): {ev[1]} el {ev[0]} a {ev[2]} · fund. {fu['score']}/{fu['avail']}" for t, fu, ev in fresh]
        body += ["", "Reporte completo: reports/latest.md"]
        (REPORTS / "signals.txt").write_text("\n".join(body), encoding="utf-8")
    elif (REPORTS / "signals.txt").exists():
        (REPORTS / "signals.txt").unlink()
    print(report[:3000])


if __name__ == "__main__":
    main()
