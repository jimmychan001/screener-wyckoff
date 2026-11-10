# Bitácora de análisis Wyckoff

Un archivo por activo, con la imagen corregida, la lectura y los niveles de decisión.
Los niveles se vigilan solos desde [`seguimiento.csv`](../seguimiento.csv).

| Activo | Gráfico | Lectura | Fase | Ficha |
|---|---|---|---|---|
| **A** | Semanal | Reacumulación | D/E | [A.md](A.md) |
| **MDT** | Mensual | Acumulación | D | [MDT.md](MDT.md) |
| **AEP** | Diario | Distribución (opción A) | D | [AEP.md](AEP.md) |
| **ARE** | Diario | Acumulación | C | [ARE.md](ARE.md) |
| **AMD** | Semanal | Reacumulación (hipótesis base) | B | [AMD.md](AMD.md) |
| **SYK** | Semanal | Acumulación | A | [SYK.md](SYK.md) |
| **DOV** | Semanal | Reacumulación (o distribución) | B extendida | [DOV.md](DOV.md) |
| **IBEX** | 4 horas | Acumulación | E | [IBEX.md](IBEX.md) |

## Cómo agregar un análisis nuevo

1. Sube la imagen a `analisis/img/` (botón *Add file → Upload files* en GitHub).
2. Copia una ficha existente, cámbiale el nombre y edítala.
3. Agrega una fila en `seguimiento.csv` con los niveles.
