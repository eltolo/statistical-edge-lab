# Statistical Edge Lab — Resultados Preliminares

## Resumen ejecutivo

Se ejecutaron 4 de 5 experimentos sobre 8 acciones argentinas (2015-2026).
Pipeline corregido: features en USD, entry next_open, costos por evento, split temporal.

| Experimento | Eventos | Decisión Equity | Decisión Futuros (0.46% RT) |
|-------------|---------|:---:|:---:|
| EXP-01: Moderate Pullback | 287 | ❌ REJECTED | ❌ REJECTED |
| EXP-03: Volatility Compression | 1,024 | 🔬 RESEARCH | 🔬 RESEARCH |
| EXP-04: Breakout From Compression | 285 | 🔬 RESEARCH | 🟡 CANDIDATE (concentrado) |
| **EXP-05: Extreme Decline** | 233 | 🔬 RESEARCH | 🟢 **CANDIDATE** |

## Candidato principal: EXP-05

| Métrica | 3 días | 5 días | 10 días |
|---------|:---:|:---:|:---:|
| Retorno bruto | +1.76% | +2.07% | +0.99% |
| Neto futuros (0.46% RT) | **+1.30%** | **+1.61%** | +0.53% |
| Win Rate | 59.7% | 57.1% | 56.2% |
| Profit Factor | 1.89 | 1.82 | 1.23 |
| CI Bootstrap 95% | [0.86, 2.69] | [0.87, 3.27] | [-0.66, 2.62] |
| Mejor trade % | 3.3% | 3.3% | 3.3% |

**Condición del evento:** Caída de 3 días con z-score < -2.0, mercado no en BEAR.

## Hallazgos clave

1. **Ningún edge sobrevive costos de acciones (1.96% RT).** Los costos de BYMA son prohibitivos para estrategias de entrada frecuente.
2. **Tres familias de eventos tienen señal en USD** pero el edge es pequeño (1-2%).
3. **EXP-05 es el más robusto:** mejor diversificación, CI sólido, incremental edge positivo.
4. **EXP-04 tiene el mejor retorno absoluto** pero concentración excesiva en CEPU.BA.
5. **Futuros ROFEX cambian completamente el panorama:** 6.4x más baratos que acciones.

## Pendientes

- Parameter neighborhood para EXP-05 (z-score -1.5, -2.5)
- Validación walk-forward del split temporal en el decision engine
- Soporte para SHORT (futuros permiten ambas direcciones)
- EXP-02 (Pullback With Volume) no se ejecutó por recomendación de Tom Hagen
