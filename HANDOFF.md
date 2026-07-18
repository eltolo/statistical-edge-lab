# Hand-off — Statistical Edge Lab

**Fecha:** 2026-07-18 03:00 ART  
**Máquina origen:** Tato-Ryzen (192.168.1.89)  
**Sesión:** VulcanPi + Tom Hagen

---

## Estado actual

### Repositorios

| Proyecto | URL | Último commit |
|----------|-----|---------------|
| Statistical Edge Lab | `github.com/eltolo/statistical-edge-lab` | `e19af20` |
| Extreme Reversal Paper | `github.com/eltolo/extreme-reversal-paper` | `e0b8758` |

### Experimentos completados

| Exp | Eventos | Decisión | Nota |
|-----|---------|:--------:|------|
| EXP-01 Moderate Pullback | 287 | ❌ REJECTED | No sobrevive USD ni costos |
| EXP-03 Volatility Compression | 1,024 | 🔬 RESEARCH | CI 1d no cruza cero, edge pequeño |
| EXP-04 Breakout From Compression | 285 | 🔬 RESEARCH | 20d +6.14% bruto, concentrado en CEPU |
| EXP-05 Extreme Decline (equity) | 233 | 🔬 RESEARCH | Neto equity -0.20% a 3d |
| EXP-05 Extreme Decline (futuros) | 233 | 🔬 RESEARCH | 5d +1.61% neto futuros, CI sólido |

Paper trader armado en `~/shared/proyectos/strategies/extreme_reversal_paper/`.

### Auditorías

| Archivo | Estado |
|---------|--------|
| `auditoria.md` | ✅ Superado — P0 corregidos en `4a96a01` |
| `auditoria_2.md` | ⚠️ En revisión — nota agregada en `e19af20` |
| `preguntas.md` | ⏳ Esperando respuestas del Auditor |

---

## Lo que falta (post hand-off)

### Pendientes críticos del lab

1. **Esperar respuestas del Auditor** en `preguntas.md` antes de continuar con fixes P1
2. **Rerun EXP-01, EXP-03, EXP-04, EXP-05** con todas las correcciones aplicadas
3. **Parameter neighborhood** para EXP-05 (z-score -1.75, -2.25)
4. **Robustness por horizonte** (leave-one-asset-out, leave-one-year-out, profit concentration)
5. **Cache metadata validation**
6. **Report artifacts** (metrics.csv, charts/)

### Pendientes del paper trader

7. **Tests** para signal_detector y position_manager
8. **Service systemd** para loop continuo
9. **Validación contra datos reales de ROFEX** (no solo sensibilidad de costos)

### Arbol de decisión

```
¿Auditor respondió preguntas.md?
├── NO → Esperar. No implementar sobre supuestos.
└── SÍ → Seguir orden sección 13 de auditoria_2.md:
        1. EXP-03/04 configs ya corregidos → verificar
        2. Horizonte next-open → verificado en 945f8da
        3. Adjusted OHLC → verificado
        4. Unificar execution → P1
        5. Net metrics canónicas → verificado
        6. Holdout mandatory → verificado
        7. Primary horizon → verificado
        8. Dollarizar benchmark → verificado
        9. Baselines matched → P1
        10. Robustness por horizonte → P1
        11. Split purge → P1
        12. CCL alignment → verificado
        13. Metadata + artifacts → P1
        14. Rerun todos los EXP
        15. Actualizar README + AGENTS.md
```

---

## Archivos clave

| Ruta | Propósito |
|------|-----------|
| `~/shared/proyectos/strategies/1-laboratorio/` | Root del lab |
| `statistical_edge_lab_spec.md` | Especificación original (23 secciones) |
| `AGENTS.md` | Entry point del proyecto |
| `auditoria_2.md` | Segunda auditoría con nota de fixes aplicados |
| `preguntas.md` | 8 preguntas al Auditor |
| `config/events/exp_005.yaml` | Experimento candidato |
| `config/costs_futures.yaml` | Costos ROFEX (0.46% RT) |
| `src/forward_returns.py` | Shared forward-return function |
| `src/event_detector.py` | List-based conditions, session cooldown |
| `src/feature_engine.py` | Features configurables por moneda |
| `src/report_generator.py` | Generador de reports + decision engine |
| `run_experiment.py` | CLI principal |
| `tests/test_statistical_edge_lab.py` | 41 tests |
| `~/shared/proyectos/strategies/extreme_reversal_paper/` | Paper trader |
| `resultados/` | Outputs generados (gitignored) |

---

## Dependencias

```bash
pip install pandas numpy pyyaml yfinance pytest
```

Sin venv necesario — todo instalado system-wide en Tato-Ryzen. En otra máquina, crear venv.

---

## Contacto

- **Tom Hagen:** `~/shared/skills/tom-hagen/SKILL.md` — invocar con `@tom`
- **Feature Adoption Policy:** `~/shared/kb/feature_adoption.md`
- **Ecosistema Tolosa:** `~/shared/_start_here.md`
