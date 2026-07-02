# Metodología de Scraping y Actualización de Tasas — Merqurio

**Versión:** 1.0  
**Fecha:** julio de 2026  
**Responsable de ejecución:** Hermes CTO Agent (cron diario)

---

## 1. Principio rector

Las tasas mostradas en Merqurio provienen **siempre de fuentes primarias oficiales** — los documentos de Términos y Condiciones de cada institución. Los homepages, banners y agregadores externos (tasas.mx, investrack.mx) se usan únicamente como referencia de validación cruzada, nunca como fuente autoritativa.

> Una tasa incorrecta daña directamente al usuario. La fuente primaria es la única que puede garantizar precisión.

### Reglas de oro del scraper

1. **La tasa que entra al DB es siempre la tasa nominal del T&C, nunca el GAT ni el valor del homepage.**
   - El GAT (Ganancia Anual Total) es una tasa efectiva compuesta — puede diferir del nominal en 50–200bp.
   - Ejemplo: Ualá anuncia "16%" en homepage = GAT del 15% nominal confirmado en T&C.
2. **Toda institución manual debe tener `source_url`** apuntando al T&C oficial vigente en `manual_additions.yaml`.
3. **Si hay discrepancia homepage vs T&C > 50bp**, documentarla en el YAML con comentario antes de ingresar.
4. **Capturar todos los tramos** del T&C, no solo el mejor. El optimizer necesita la estructura completa para asignar correctamente.

---

## 2. Elegibilidad de productos

**Regla de oro:** Solo entran al DB **cuentas a la vista** (liquidez diaria, sin plazo forzoso). Los productos a plazo (>1 mes) quedan excluidos aunque la misma institución los ofrezca.

| Tipo de producto | Elegible | Ejemplo |
|---|---|---|
| Cuenta de ahorro a la vista / débito con rendimiento | ✓ SÍ | Cuenta Nu, Klar Fondo Flexible |
| CETES 28 días (≤1 mes) | ✓ SÍ | via tasas.mx, columna "1mes" |
| Plazo fijo 60 días+ | ✗ NO | Stori Inversión+ 60 días |
| Pagarés / plazo fijo cualquier duración | ✗ NO | Finsus plazo fijo, Crediclub plazos |

> Stori y Finsus tienen tasas de plazo fijo en tasas.mx. Su columna "vista" está vacía. Sus productos a la vista se curan manualmente.

---

## 3. Jerarquía de fuentes

| Prioridad | Fuente | Uso | Ejemplos |
|---|---|---|---|
| 1 | Página oficial de la institución | Tasa vigente authoritative | `uala.mx`, `nu.com.mx`, `openbank.mx` |
| 2 | App móvil oficial | Tasas que no aparecen en web pública | Mercado Pago, DiDi |
| 3 | Documentos T&C / PDF oficial | Estructura de tramos, límites, condiciones | PlataCard booklet, Stori folleto |
| 4 | tasas.mx | Validación cruzada, detección de cambios | Comparación post-scrape |
| 5 | Curación manual de CTO | Cuando fuentes 1-4 no están disponibles o son ambiguas | Mifel (403) |

**Regla de conflicto:** si la fuente primaria y tasas.mx difieren, la fuente primaria gana. El conflicto se documenta en `manual_additions.yaml` con comentario.

---

## 4. Clasificación de instituciones por fuente

### 4.1 Scrapeables automáticamente (tasas.mx, columna "vista")

Estas instituciones tienen **tasa a la vista** publicada en tasas.mx y se actualizan con `rate-scrape --ingest` diario.

| Institución | Tipo | T&C oficial | Notas |
|---|---|---|---|
| DiDi | SOFIPO | [DiDi Cuenta](https://web.didiglobal.com/mx/jpsofiexpress/didi-cuenta/) · [Contrato PDF](https://web.didiglobal.com/mx/didi-cuenta/contrato.pdf) | 15% en primeros $10k; 7.5% el resto |
| Revolut | Banco | [Rendimientos Diarios](https://www.revolut.com/es-MX/instant-access-savings/) | 15% primeros $25k; tiered hasta $1M |
| Nu | SOFIPO | [Folleto PDF](https://cdn.nubank.com.br/MX/folleto-informativo-cuenta.pdf) | Cajita Turbo 13% ($25k); requiere ≥1 compra/30 días |
| Mercado Pago | IFPE | [T&C Beneficio MP](https://www.mercadopago.com.mx/ayuda/terminos-condiciones-beneficio_32110) | 12-15% condicional a gasto mensual |
| Openbank | Banco | [Cuenta Open+](https://www.openbank.mx/cuenta-debito-open-plus) · [Open Light](https://www.openbank.mx/cuenta-debito-open-light) | Santander México / IPAB; 13% primeros $40k |
| Klar | SOFIPO | [Fondo de Rendimiento](https://www.klar.mx/inversion) | 8.5% flexible/on-demand (Klar Plus/Platino) |
| Supertasas | SOFIPO | [Crediclub](https://crediclub.com.mx) (supertasas.com redirige aquí) | Solo tasa a la vista; plazos excluidos |
| BONDDIA | Fondo | [BMV](https://www.bmv.com.mx/es/fondos/BONDDIA-7407) · [GBM](https://gbm.com/) | Fondo gob. diario; liquidez inmediata |
| Cetes | Gobierno | [Cetesdirecto](https://www.cetesdirecto.com) · [Banxico](https://banxico.org.mx) | CETES 28 días ≤ 1 mes — columna "1mes" en tasas.mx |

### 4.2 Curación manual

Estas instituciones requieren actualización manual en `data/manual_additions.yaml`. Motivos: (a) no aparecen en tasas.mx, (b) tasas.mx solo muestra productos de plazo fijo para ellas.

El CTO Agent alerta cuando la tasa tiene más de 30 días sin actualizarse.

| Institución | Tipo | T&C oficial | Última verificación | Notas |
|---|---|---|---|---|
| Uala | Banco | [T&C V9](https://www.uala.mx/tyc-uala-cuenta-con-rendimiento-plus) | Jul 2026 | 15% nominal ($30k) con gasto ≥$6k/mes; 12% con $3k/mes. Tasa Base desconocida. |
| PlataCard | Banco | [Ahorro Flexible booklet](https://prime.platacard.mx/file-service/static/eula/ahorro_flexible_booklet.pdf) | Jul 2026 | 7% nominal base (promo 11% expiró jul 3). IPAB. Sin membresía requerida. |
| Stori | SOFIPO | [Folleto PDF](https://www.storicard.com/files/stori-cuentamas/folleto-informativo-depositos.pdf?v=20260113) | Jul 2026 | Stori Cuenta+ 6.77% nominal a la vista. tasas.mx solo muestra plazos fijos. |
| Finsus | SOFIPO | [FAQ tasas](https://finsus.mx/faqs-items/cuales-son-las-tasas-que-manejan-en-cuenta-de-ahorro-y-en-inversion/) | Jul 2026 | 4% nominal a la vista (bajo vs benchmark). Plazos fijos (7d-1año) excluidos. |
| Mifel | Banco | mifel.com.mx (403 — pendiente) | Jun 2026 | 10% nominal hasta $500k (T&C PDF Jun 2026, URL pendiente). |

---

## 5. Proceso de actualización automática

```
Hermes CTO Agent (cron diario, 07:00 CST)
  └── rate-scrape --ingest
        ├── GET tasas.mx → tabla HTML
        ├── Parsear tasas por institución y tenor
        ├── Generar data/scraped_live.yaml
        └── rate-ingest → SCD2 SQLite
              ├── Comparar vs versión activa
              ├── Si hay cambio: cerrar versión anterior, insertar nueva
              └── Si no hay cambio: no-op (idempotente)
  └── En fallo: alert CTO Telegram bot
```

**Frecuencia:** diaria.  
**Idempotencia:** si las tasas no cambiaron, no se escribe nada al DB.  
**Auditoría:** cada cambio queda registrado en `change_batches` con timestamp exacto.

---

## 6. Proceso de actualización manual

Cuando una institución cambia su tasa y no está en tasas.mx:

1. Verificar la nueva tasa en la fuente primaria oficial
2. Editar `data/manual_additions.yaml`
3. Agregar comentario con fuente y fecha: `# source: uala.mx — Jul 2026`
4. Correr `rate-ingest data/manual_additions.yaml --note "manual: <institución> <tasa> desde <fuente>"`
5. Verificar en DB que el cambio quedó registrado

---

## 7. Campos que se scrapeán vs. se curan manualmente

| Campo | Actualización | Quién |
|---|---|---|
| Tasa nominal (rate) | Automática (diaria vía tasas.mx) | Hermes CTO Agent |
| Límite de tramo (limit_mxn) | Manual (raramente cambia) | CTO / Gera |
| Condiciones (constraints) | Manual (T&C oficial) | CTO / Gera |
| Tipo de institución | Manual (dato estático) | CTO / Gera |
| Límite de cobertura IPAB/Prosofipo | Manual (anual, por CNBV) | CTO / Gera |

---

## 8. Validación post-scrape

Después de cada ingest automático, el CTO Agent verifica:

- Ninguna tasa activa es `0%` para una institución cuya fuente primaria reporta tasa positiva
- Ningún cambio supera `±500bp` en un día (flag de anomalía)
- Todas las instituciones de la sección 4.1 tienen versión activa en el DB

Si alguna validación falla, se envía alerta al CTO Telegram bot con detalle.

---

## 9. Incorporación de nuevas instituciones

Para agregar una institución nueva:

1. **Verificar elegibilidad:** producto a la vista (liquidez diaria, sin plazo forzoso), institución regulada CNBV o equivalente
2. **Identificar fuente primaria:** URL del T&C oficial con la tasa publicada
3. **Verificar metodología:** confirmar que el producto es a la vista (no plazo fijo). Ver sección 2.
4. **Determinar estructura de tramos:** revisar T&C oficial para límites de saldo y condiciones
5. **Clasificar fuente:** ¿tiene columna "vista" en tasas.mx? → sección 4.1. ¿No? → sección 4.2
6. **Si sección 4.1:** agregar a `TIER_STRUCTURES` en `cli/scrape.py` con `rate_key: "vista"` y comentario de fuente
7. **Si sección 4.2:** agregar a `data/manual_additions.yaml` con `source_url` y comentario de fecha
8. Documentar en la tabla correspondiente de este archivo (sección 4.1 o 4.2)

---

*Este documento describe la metodología de obtención de datos, no el motor de optimización. Para la formulación matemática ver `docs/metodologia.md`.*
