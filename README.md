# Screener Wyckoff + Weinstein + Fundamentales

Busca cada día hábil, de forma automática, acciones del **S&P 500 y Nasdaq-100** que estén
**consolidando en una posible acumulación de Wyckoff (Etapa 1 de Weinstein)**, detecta el
**cambio de estructura (CHoCH)** dentro del rango y lo cruza con **análisis fundamental**.
Objetivo: encontrar acciones para comprar y holdear.

No necesitas instalar nada: corre en los servidores de GitHub (GitHub Actions).

## 📄 Dónde ver los resultados

- **[`reports/latest.md`](reports/latest.md)**: el reporte del último día (se abre directo en GitHub, también desde el celular).
- `reports/AAAA-MM-DD.md`: el histórico, un archivo por día.
- `reports/latest.csv`: los mismos datos para abrir en Excel o Google Sheets.
- **Notificaciones:** cuando aparece una señal nueva (CHoCH, LPS o ruptura) en una acción con fundamentales aptos, se crea un *issue* y GitHub te avisa por correo o en la app.

## 🔍 Qué hace (gráfico semanal)

1. **Contexto:** caída previa ≥ 20 %, rango lateral de 26 semanas con ancho ≤ 40 % y media de 30 semanas plana.
2. **Estructura Wyckoff:**
   - Spring/Test (Fase C)
   - CHoCH alcista, con volumen = SOS (Fase D)
   - LPS (mínimo más alto con volumen bajo)
   - Ruptura del techo con volumen (Fase E = inicio de Etapa 2)
3. **Respaldo:**
   - Fuerza relativa Mansfield contra el SPY.
   - Relación de volumen entre semanas alcistas y bajistas dentro del rango.
   - Puntaje fundamental de 0 a 7: crecimiento de ventas, crecimiento del BPA, BPA positivo, flujo de caja libre positivo, ROE, deuda/patrimonio y margen neto.

Cada acción queda en una de estas categorías:

| Veredicto | Significado |
|---|---|
| ✅ CANDIDATO | Fase D o E y fundamentales aptos |
| 👀 Vigilar | Rango de acumulación con fundamentales aptos, pero aún sin CHoCH |
| ⚠️ Fundamental débil | La estructura técnica avanza, pero los números no la respaldan |

Es la misma lógica del indicador de TradingView **Wyckoff+Fund**. Confirma siempre el gráfico a ojo.

## ⚙️ Cómo ajustarlo (desde la web de GitHub, sin programar)

- **`config.json`:** los umbrales. Por ejemplo `max_width` (ancho del rango), `min_decline` (caída previa), `min_roe`, `min_score`. Ábrelo, pulsa el lápiz ✏️, edita y guarda con *Commit changes*.
- **`watchlist.txt`:** tickers extra, uno por línea, en formato Yahoo Finance (las chilenas terminan en `.SN`).
- **Correrlo a mano:** pestaña **Actions** → *Screener diario Wyckoff* → **Run workflow**.
- **Horario:** lunes a viernes cerca de las 19:17 hora de Chile, después del cierre de EE. UU. Se cambia en `.github/workflows/screener.yml`.

## Limitaciones

- Los datos vienen de Yahoo Finance (gratis). A veces Yahoo limita las descargas y alguna acción puede faltar en un día puntual.
- La detección de fases es una aproximación mecánica; cada esquema de Wyckoff es distinto.
- La semana en curso se incluye aunque no haya cerrado: las señales de un lunes pueden cambiar antes del viernes.
- No es una recomendación de inversión.
