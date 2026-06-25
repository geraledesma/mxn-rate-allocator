# Metodología del Motor de Optimización — Merqurio

**Versión:** 1.0  
**Fecha:** junio de 2026  
**Aplicación:** Calculadora de Tasas MX (merqurio.mx)

---

## 1. Introducción

La Calculadora de Tasas MX resuelve un problema de asignación óptima de capital: dado un monto de ahorro, distribuirlo entre bancos y SOFIPOs mexicanos de manera que se maximice el rendimiento neto, respetando los límites de cobertura institucional (IPAB / Prosofipo) y los costos asociados a cada cuenta.

El motor es un optimizador de programación lineal entera mixta (MILP, *Mixed-Integer Linear Programming*) implementado en Python sobre SciPy. Esta categoría de problemas se utiliza ampliamente en finanzas cuantitativas, logística y asignación de recursos con restricciones discretas.

---

## 2. Datos de entrada

El motor recibe como entradas:

| Parámetro | Descripción |
|---|---|
| `total` | Capital a distribuir (MXN) |
| `institutions` | Lista de instituciones disponibles, cada una con sus tramos y condiciones |
| `horizon_years` | Horizonte de inversión en años (default: 1.0) |
| `periods_per_year` | Períodos de capitalización por año (default: 365, capitalización diaria) |
| `regulatory_rules` | Parámetros regulatorios: límites IPAB/Prosofipo, tasas ISR, inflación proxy |
| `compounding` | Modo de capitalización: `"compound"` (compuesta, default) o `"simple"` |

Cada **institución** define una secuencia de **tramos** (*tiers*), donde cada tramo especifica:
- `limit`: saldo máximo acumulado hasta ese tramo (en MXN)
- `rate`: tasa nominal anual aplicable al capital marginal en ese tramo
- `constraints`: condiciones opcionales (comisión mensual, gasto mínimo mensual) que activan o modifican el tramo

---

## 3. Estructura de tramos

Los tramos son **cumulativos y ordenados de menor a mayor límite**. El capital marginal en cada tramo es la diferencia entre el saldo acumulado en ese tramo y el tramo anterior.

**Ejemplo:** una institución con dos tramos:

| Tramo | Límite acumulado | Tasa | Capital marginal (para $50,000) |
|---|---|---|---|
| 1 | $25,000 | 15% | $25,000 |
| 2 | sin límite | 10% | $25,000 |

Regla fundamental: **el tramo N solo se activa cuando el tramo N−1 está completamente financiado**. El motor impone esta condición como restricción binaria en el MILP.

---

## 4. Formulación matemática

### 4.1 Variables de decisión

Para cada tramo `(i, t)` de institución `i` y tramo `t`, la variable de decisión `x_{i,t}` representa el **saldo acumulado** hasta ese tramo. El capital marginal en el tramo es `x_{i,t} − x_{i,t−1}`.

### 4.2 Función objetivo

El motor maximiza el rendimiento neto total sobre el horizonte `T` (equivalente a minimizar su negativo):

```
maximizar   Σ_{i,t}  r_net(i,t) · Δx_{i,t}
```

donde `Δx_{i,t} = x_{i,t} − x_{i,t−1}` es el capital marginal en el tramo, y `r_net(i,t)` es la tasa neta de retorno del tramo, definida como:

```
r_net(i,t) = r_gross(i,t) − fee_per_unit(i,t) − tax_per_unit(i,t)
```

### 4.3 Rendimiento bruto por unidad

Depende del modo de capitalización seleccionado:

**Capitalización compuesta** (default):

```
r_gross(i,t) = (1 + r_{i,t} / n)^(n·T) − 1
```

donde `r_{i,t}` es la tasa nominal anual del tramo y `n` es el número de períodos de capitalización por año (365 para capitalización diaria).

**Capitalización simple:**

```
r_gross(i,t) = r_{i,t} · T
```

### 4.4 Restricciones

**Restricción presupuestaria:** el total asignado es igual al capital disponible.

```
Σ_i  x_{i, último tramo de i}  =  total
```

**Monotonicidad de tramos:** dentro de cada institución, el saldo acumulado es no decreciente:

```
x_{i,t}  ≥  x_{i,t−1}   ∀ i, t
```

**Límites de cobertura institucional (IPAB / Prosofipo):** para cada institución con cobertura aplicable:

```
x_{i, último tramo de i}  ≤  límite de cobertura de i
```

**Activación de tramos:** si el tramo `t` recibe capital, el tramo anterior debe estar completamente financiado. Esta condición se modela con variables binarias `y_{i,t} ∈ {0, 1}`:

```
x_{i,t} − x_{i,t−1}  ≤  cap · y_{i,t}
x_{i,t−1}  ≥  límite_{i,t−1} · y_{i,t}
```

**No negatividad:**

```
x_{i,t}  ≥  0   ∀ i, t
```

### 4.5 Desempate: minimización de cuentas abiertas

Cuando múltiples asignaciones producen el mismo rendimiento neto óptimo, el motor prefiere la que abre el menor número de cuentas. Esto se implementa agregando una penalización infinitesimal `δ` sobre indicadores binarios de institución abierta `z_i ∈ {0, 1}`:

```
minimizar   −Σ r_net · Δx  +  δ · Σ z_i
```

El parámetro `δ` se calibra automáticamente como una fracción del coeficiente mínimo de la función objetivo principal, garantizando que el desempate nunca distorsione la solución óptima.

---

## 5. Modelado de costos de activación

Algunas instituciones requieren condiciones para acceder a su tasa (ej. membresía mensual, gasto mínimo mensual). Estos costos se deducen del rendimiento bruto al evaluar la conveniencia del tramo:

**Comisión mensual (`monthly_expense`):** costo total = `costo_mensual × 12 × T`

**Gasto mínimo mensual:** el costo se modela como el cumplimiento del gasto mínimo requerido. El motor ajusta la tasa neta considerando este costo.

Solo se cobran costos de activación cuando el tramo recibe capital (el motor no penaliza tramos no financiados).

---

## 6. Modelado fiscal

El motor aplica las reglas del ISR mexicano sobre intereses de ahorro a las instituciones reguladas.

### 6.1 Bancos (CNBV)

**Retención en fuente:** 0.9% anual sobre el saldo principal (retenida directamente por el banco, independiente de la tasa de interés).

**ISR sobre interés real:** la base gravable es el interés real, definido como el excedente del interés nominal sobre la inflación estimada:

```
ISR = max(0,  interés_nominal − saldo × inflación_proxy × T)  ×  tasa_ISR
```

donde `inflación_proxy = 4.21%` anual (proxy conservador).

### 6.2 SOFIPOs

**Exención de saldo:** los primeros $213,973 MXN de saldo en una SOFIPO están exentos de ISR.

**ISR sobre el excedente:** sobre el saldo que excede la exención se aplica la misma lógica de interés real, pero sobre la proporción taxable del rendimiento.

### 6.3 Fintechs / otros

Sin modelado fiscal específico (el motor asume tratamiento neutro para instituciones no clasificadas como banco o SOFIPO).

---

## 7. Cobertura institucional

Los límites de protección funcionan como restricciones duras en la asignación. El motor no asignará más capital a una institución del que cubre su seguro:

| Tipo | Esquema | Límite por depositante |
|---|---|---|
| Banco (CNBV) | IPAB | $3,300,000 MXN |
| SOFIPO (CNBV) | Prosofipo | $208,000 MXN |
| Fintech / Otro | Sin cobertura | Sin límite impuesto |

Los límites son configurables y se actualizan sin cambios de código.

---

## 8. Benchmark de referencia

El rendimiento del plan se compara contra **CETES a 28 días**, la tasa libre de riesgo del ahorro en pesos mexicanos. Esta es la comparación más conservadora y verificable disponible: superar la tasa del gobierno es la evidencia más directa de que la optimización entrega valor.

**CETES no es un producto ofrecido por la herramienta** (no cumple el criterio de liquidez diaria), pero sirve como referencia de rendimiento.

La tasa CETES se actualiza manualmente junto con las tasas de las instituciones. Fuente: Banco de México (banxico.org.mx).

---

## 9. Supuestos y limitaciones

| Supuesto | Detalle |
|---|---|
| Liquidez diaria | Solo se incluyen productos a la vista (cuentas de ahorro y cuentas nómina). No se modelan CETES, pagarés, ni fondos de deuda. |
| Tasas estáticas | Las tasas se tratan como constantes durante el horizonte de inversión. La herramienta recomienda revisión periódica. |
| Asignación completa | El capital total se despliega íntegramente. No se modelan reservas de liquidez. |
| Sin posiciones cortas | Todas las asignaciones son no negativas. |
| Sin costos de transacción | No se modelan comisiones de apertura, transferencias o cierre de cuentas. |
| Un período | Optimización estática para un horizonte fijo. No incluye rebalanceo dinámico. |
| Independencia de instituciones | El motor no modela correlación entre tasas de diferentes instituciones. |

---

## 10. Información del modelo

| Campo | Valor |
|---|---|
| Lenguaje | Python 3.10+ |
| Solver | SciPy `milp` (HiGHS backend) |
| Tipo de problema | MILP (programación lineal entera mixta) |
| Complejidad | O(n · t) variables continuas + O(n · t) variables binarias, donde n = instituciones, t = tramos promedio |
| Licencia | BUSL-1.1 (Business Source License) — uso comercial restringido hasta 2030-06-11 |

---

*Esta herramienta es de carácter informativo. No constituye asesoría financiera, fiscal ni de inversión. Las tasas mostradas provienen de fuentes públicas y pueden variar. Consulta directamente con cada institución antes de tomar decisiones de inversión.*
