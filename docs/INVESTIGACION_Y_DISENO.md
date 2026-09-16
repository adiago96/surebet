# Sistema de detección de arbitraje deportivo (surebets) — Investigación y diseño técnico

**Fecha de la investigación:** septiembre de 2026. Todos los datos de precios, límites y cobertura de bookmakers de este documento se han comprobado mediante peticiones HTTP reales (no solo lectura de documentación de marketing) el mismo día de la redacción. Donde algo no se pudo verificar directamente se indica explícitamente como "no verificado".

---

## 1. RESUMEN EJECUTIVO

Es posible construir hoy, con **0 € de coste mensual**, un sistema funcional de detección de arbitraje deportivo que:

- Cubre **fútbol, tenis, baloncesto, béisbol, hockey, fútbol americano, MMA, vóley** y decenas de deportes más.
- Detecta arbitrajes **2-way, 3-way, hándicap/Asian Handicap y totals (over/under)**, con una capa de normalización que impide combinar mercados con reglas de liquidación distintas.
- Calcula stakes óptimos, ROI, beneficio garantizado, antigüedad de cada cuota y una puntuación de riesgo de ejecución.
- Envía alertas por Telegram y expone un dashboard web local.

**El límite real no es técnico, es de cobertura de bookmakers.** La única API gratuita seria (The Odds API) **no incluye bet365, Winamax España, Bwin, Codere, Luckia ni Sportium** — lo he comprobado directamente contra su listado de bookmakers, no contra un blog. La única fuente 100% gratuita y sin registro que sí funciona hoy es la **API "guest" pública de Pinnacle** (un solo bookmaker, sharp, sin mercado español). Con esto se puede construir un sistema real y honesto, pero **no** el sistema "compara bet365 vs Winamax en tiempo real" que muchas webs de afiliados prometen falsamente de forma gratuita.

Mi recomendación concreta está al final de este documento (sección 19).

---

## 2. QUÉ ES REALMENTE POSIBLE GRATIS

Con 0 €, hoy (sept. 2026), es posible:

- Consultar **The Odds API** con su free tier real: **500 créditos/mes**, no 500 al día (una afirmación que circula en varios blogs de terceros y que la web oficial contradice). El coste de cada llamada es `nº mercados × nº regiones`, y una sola llamada devuelve **todos** los bookmakers de esa región de golpe. Fuente: [the-odds-api.com](https://the-odds-api.com/) y [documentación v4](https://the-odds-api.com/liveapi/guides/v4/) (comprobado con `curl` contra `api.the-odds-api.com`).
- Consultar la **API pública "guest" de Pinnacle** (`guest.api.arcadia.pinnacle.com`) sin API key, sin registro y sin límite de peticiones documentado. Comprobado en vivo: a fecha de esta investigación devolvió **1826 eventos y 46.927 cuotas** en una sola pasada sobre 8 deportes.
- Usar el **Betfair Exchange API** con una "Delayed App Key" gratuita para siempre (datos con ~1 minuto de retraso), válida para pre-match pero no para live. Fuente: [Betfair Developer Program FAQ](https://support.developer.betfair.com/hc/en-us/articles/115003864531-Are-there-any-costs-associated-with-API-access).

Lo que **no** es realmente posible gratis, pese a lo que anuncian varias webs:

- Cuotas de **bet365** para España/UE/fútbol/tenis. Bet365 prohíbe expresamente el scraping en sus Términos y Condiciones ("Bet365's terms of service prohibit screen scraping... including results, statistics, sporting data and fixture lists, odds and betting figures"), y The Odds API solo ofrece `bet365_au` (Australia), **de pago**, y limitado a AFL/NRL.
- Un agregador gratuito y legítimo que incluya **Winamax España, Bwin, Codere, Luckia o Sportium**. No existen en ninguna región de The Odds API (comprobado: no hay ninguna clave `*_es` en todo su listado de bookmakers).
- **WebSocket gratuito en tiempo real** de múltiples bookmakers. Odds-api.io solo da "3 días de prueba de WebSocket"; el resto de estos servicios cobra el streaming.

---

## 3. COMPARATIVA DE APIs

| Servicio | URL | Precio | Free tier | Req/mes free | Bookmakers | Deportes | Mercados | Live odds | WebSocket | Bet365 | Winamax | Betfair | Bookmakers ES | API REST | Open source | Restricciones | ¿Recomendado? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **The Odds API** | the-odds-api.com | Free / £98+/mes | 500 créditos/mes | ~500 (coste=mercados×regiones) | ~40-70 según región (verificado: región `eu` trae pinnacle, marathonbet, betfair_ex_eu, unibet_fr/it/nl/se, winamax_de/fr, williamhill, sport888, tipico_de, betclic_fr...) | 30+ (fútbol, tenis, baloncesto, béisbol, hockey, NFL, MMA, cricket...) | h2h, spreads, totals, outrights (props solo de pago, solo EEUU) | Sí (mismo endpoint, sin distinguir claramente frescura) | No en free (solo REST) | Solo `bet365_au`, de pago, solo AFL/NRL | Solo DE/FR (`winamax_de`, `winamax_fr`), no España | Sí, `betfair_ex_eu`/`betfair_ex_uk` | **No hay ninguna** | Sí | No | No redistribuir como feed de datos crudo | **Sí, como base principal** |
| **Pinnacle guest API** | guest.api.arcadia.pinnacle.com | Gratis | Sin límite documentado | N/D | Solo Pinnacle (1 bookmaker) | Prácticamente todos (soccer, tennis, basketball, hockey, baseball, football, MMA, volleyball, esports...) | Moneyline, spread, total (verificado con curl) | Sí, delay bajo | No | No | No | No (es otro bookmaker) | No | Sí (JSON, no HTML) | No (endpoint interno no documentado oficialmente) | Zona gris de ToS: no hay política pública que autorice uso por terceros | **Sí, como fuente complementaria/sharp** |
| **Betfair Exchange API** | developer.betfair.com | Gratis (dev) / 499£ una vez (live) | Delayed key gratis siempre | Sin límite de créditos, sí de rate (1000 req/min) | Betfair Exchange (y Sportsbook UK) | Amplia | Back/lay de exchange, no mercados de casa tradicional | Con Delayed Key: ~1 min de retraso | Sí (Stream API), conflated con delayed key | No | No | Sí, es la propia Betfair | No | Sí | No | Uso comercial requiere aprobación; live real-time cuesta 499£ una vez | Complementario (matched betting back/lay) |
| **Odds-API.io** | odds-api.io | Free / pago | 100 req/hora, hasta 500/día | ~500/día en teoría | Solo 2 "recreativos" en free (no confirmado cuáles exactamente) | 34 deportes anunciados | Pre-match solo en free | No en free | No en free (solo prueba 3 días) | No confirmado en free | No confirmado | No confirmado | No | Sí | No | "Development/testing only", producción requiere pago | Secundario, verificar antes de depender de él |
| **OddsPapi / SharpAPI / SportsGameOdds / UK Odds API** (webs de afiliación) | oddspapi.io, sharpapi.io, sportsgameodds.com | "Gratis" | Afirman 250-∞ req/mes | Cifras inconsistentes entre sí | Afirman "bet365, Winamax, 350+ bookmakers gratis" | — | — | — | — | **Afirmación no verificable y contradictoria** con el ToS público de bet365 y con la propia documentación de The Odds API | — | — | — | — | — | Contenido tipo granja SEO, marketing calcado entre sitios ("gratis para siempre, sin tarjeta, sin llamada de ventas" repetido literalmente en varias webs) | **No confiar sin verificación independiente** |
| **OddsPortal / Flashscore (scraping)** | oddsportal.com, flashscore.com | Gratis si se hace scraping | — | — | Decenas | Amplia | Amplia (histórico incluido) | Sí | No | Vía scraping, viola ToS | Vía scraping, viola ToS | Vía scraping, viola ToS | Sí, potencialmente | No (HTML/JS) | Varios repos GitHub no oficiales | **ToS prohíbe explícitamente el scraping y uso comercial**; `robots.txt` lo desaconseja | **No recomendado para uso continuo** (ver Fase 2) |

Fuentes citadas en la tabla: [the-odds-api.com](https://the-odds-api.com/), [the-odds-api.com/sports-odds-data/bookmaker-apis.html](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html) (comprobado por descarga directa de la página y grep del HTML), [the-odds-api.com/liveapi/guides/v4/](https://the-odds-api.com/liveapi/guides/v4/), [odds-api.io/pricing/free](https://odds-api.io/pricing/free), [developer.betfair.com](https://developer.betfair.com/en/exchange-api/faq/), [help.bet365.com Términos y Condiciones](https://help.bet365.com/s/en-ch/terms-and-conditions).

---

## 4. COMPARATIVA DE SCRAPERS

Investigación técnica de cómo cargan cuotas las webs modernas (no HTML estático):

- **Pinnacle**: usa un endpoint JSON interno propio (`guest.api.arcadia.pinnacle.com`) que su propia web consume vía XHR. No es "scraping de HTML", es el mismo backend JSON que usa el navegador. Verificado directamente.
- **OddsPortal / Flashscore**: cargan datos vía llamadas internas (XHR/JSON) también, pero sus Términos de Servicio prohíben expresamente el scraping y el uso comercial, y `robots.txt` desaconseja el rastreo de esas rutas. Existen varios proyectos GitHub (`gingeleski/oddsporter`, scrapers vía Apify/Selenium) pero todos operan en una zona de incumplimiento de ToS, no de "endpoint público tolerado" como Pinnacle.
- **Bet365**: usa WebSockets internos fuertemente ofuscados y con protecciones anti-bot activas, y su ToS prohíbe explícitamente el scraping de cuotas. **No se ha investigado ni se recomienda ningún método para extraer datos de bet365** — más allá de ser técnicamente complejo (WebSocket cifrado/ofuscado, fingerprinting), es un incumplimiento directo y explícito de sus condiciones de uso.
- **Proyectos GitHub existentes**: se han revisado varios (`TessaRichardson/SureBetsBot`, `odds-api/arbitrage-betting-scanner-bot`, `eric-barch/betbot`). Ninguno es un producto maduro y en producción: `SureBetsBot` es un proyecto de portfolio con 3 commits y datos mock por defecto; `betbot` usa control remoto de Chrome (browser automation), lo que confirma que scrapear sportsbooks modernos sin API interna normalmente exige automatizar un navegador real, con el coste de mantenimiento y fragilidad que eso implica.

**Conclusión de esta fase:** scraping directo de HTML no tiene sentido en 2026 porque los datos ya viajan como JSON/WebSocket interno, pero **solo Pinnacle ofrece ese JSON sin controles de acceso ni prohibición explícita**. El resto de casas relevantes (bet365, Winamax, Bwin...) o bien tienen protecciones anti-bot activas, o bien prohíben expresamente esta práctica en sus términos — y el usuario pidió explícitamente no evadir esos controles.

---

## 5. BOOKMAKERS DISPONIBLES

Tabla de verificación específica (comprobada por request HTTP real, no por lista de marketing):

| Bookmaker | ¿Incluido gratis en alguna fuente? | Detalle verificado |
|---|---|---|
| Bet365 | ❌ | Solo `bet365_au` en The Odds API, de pago, limitado a AFL/NRL. ToS de bet365 prohíbe scraping explícitamente. |
| Winamax | ⚠️ Parcial | `winamax_de` y `winamax_fr` en The Odds API (región `eu`). **No** hay `winamax_es`, pese a que Winamax opera en España. |
| Betfair (Exchange) | ✅ | `betfair_ex_eu` / `betfair_ex_uk` en The Odds API (delay corto, incluido en free si el crédito alcanza), y directamente vía Betfair Exchange API (delayed key gratis). |
| Bwin | ❌ | No aparece en ninguna región de The Odds API. |
| Unibet | ⚠️ Parcial | `unibet_fr`, `unibet_it`, `unibet_nl`, `unibet_se`, `unibet` (UK/AU). No hay versión España. |
| William Hill | ✅ (UK) | `williamhill` (UK). |
| 888sport | ⚠️ | Aparece como `sport888` en regiones EU/UK, no confirmado si corresponde a la marca española. |
| Codere | ⚠️ Parcial | Solo `codere_it` (Italia). No hay `codere_es`. |
| Luckia | ❌ | No aparece en ninguna fuente investigada. |
| Sportium | ❌ | No aparece en ninguna fuente investigada. |
| Marathonbet | ✅ | Presente en región `eu` de The Odds API. |
| Pinnacle | ✅ | Vía The Odds API (región `eu`) **y** vía su propia API guest gratuita directa. |

**Conclusión honesta:** con fuentes 100% gratuitas y legítimas, hoy **no existe cobertura real del mercado de apuestas español** (Codere, Luckia, Sportium, Bwin, Winamax ES, bet365 ES quedan todos fuera). El sistema es viable y útil para arbitrajes entre **Pinnacle + los bookmakers europeos que sí trae The Odds API** (Marathonbet, Unibet FR/IT/NL/SE, Winamax DE/FR, William Hill, Betfair Exchange, Betclic FR, 888sport, Tipico DE), no para "bet365 vs Winamax España" tal como se plantea en el enunciado original.

---

## 6. ARQUITECTURA RECOMENDADA

```
The Odds API (REST, créditos limitados)      Pinnacle guest API (REST, gratis, ilimitado de facto)
              \                                          /
               \                                        /
                v                                      v
                     COLLECTORS (async, httpx)
                              |
                     NORMALIZACIÓN
        - unify() cruza eventos entre fuentes (Fase 5/12)
        - MarketKey exige: deporte + evento + familia + periodo + reglas + línea
        - handicap_home_perspective_line() unifica "Madrid -1.5" = "Elche +1.5"
                              |
                     SQLite (snapshots + histórico)
                              |
                     MOTOR DE ARBITRAJE (Fase 4)
        sum(1/odd_i) < 1  sobre selecciones EXHAUSTIVAS y verificadas
                              |
                     VALIDACIÓN DE RIESGO (Fase 6/8)
        freshness (FRESH/AGING/STALE) + execution_risk_score (0-100)
        MATHEMATICAL ARBITRAGE  vs  EXECUTABLE ARBITRAGE (candidato)
                              |
                     STAKE CALCULATOR (Fase 7)
        reparto proporcional a 1/odd, redondeo real, detecta si el
        redondeo destruye el margen
                              |
                    /                    \
          ALERT ENGINE (Telegram)      DASHBOARD WEB (FastAPI + HTML/JS)
```

Todo el código vive en `surebet/` (ver árbol completo en la sección 14). Sin Redis, sin Kubernetes, sin microservicios: un único proceso Python con `asyncio`, SQLite como base de datos, y un proceso FastAPI separado y opcional para el dashboard.

---

## 7. MODELO DE DATOS

Implementado en [`surebet/models.py`](../surebet/models.py):

- **`Event`**: evento normalizado (`event_id`, deporte, liga, equipos, hora de inicio, si es live).
- **`MarketKey`**: la pieza central. Agrupa `sport_key + event_id + family + period + rules + line`. Dos cuotas solo se consideran del mismo mercado si **todo** coincide, incluyendo `Period` (tiempo reglamentario vs. prórroga vs. primera parte) y `SettlementRules` (p.ej. `TENNIS_RETIREMENT_VOID` vs. `TENNIS_RETIREMENT_ACTION`, o `SOCCER_ABANDONED_VOID` vs. `SOCCER_ABANDONED_SETTLED_IF_PLAYED`).
- **`OddQuote`**: una cuota concreta de un bookmaker, con `received_at`, `bookmaker_last_update` (si la fuente lo reporta) y `age_seconds` calculado.

La convención clave (documentada en el propio código, [`surebet/normalize/markets.py`](../surebet/normalize/markets.py)): en mercados de hándicap, `line` se expresa siempre en perspectiva del equipo "home". Así "Real Madrid -1.5" y "Elche +1.5" terminan con el **mismo** `MarketKey.line = -1.5` y se agrupan automáticamente como complementarios — sin necesidad de una tabla de equivalencias manual ni de asumir nada por el nombre del mercado.

---

## 8. MOTOR DE ARBITRAJE

Implementado en [`surebet/engine/arbitrage.py`](../surebet/engine/arbitrage.py). Es intencionadamente genérico:

```
total_implied_prob = sum(1 / odd_i  para cada selección i)
es_arbitraje = total_implied_prob < 1
profit_pct  = (1 / total_implied_prob - 1) * 100
```

Funciona igual para 2-way, 3-way, hándicap y totals porque **no conoce el deporte**: solo opera sobre un diccionario `selección -> mejor cuota` que la capa de normalización le garantiza que es exhaustivo y coherente. Verificado con el ejemplo exacto del enunciado (`1/2.00 + 1/2.37`): el sistema calcula **8.4668%** de beneficio, tal y como debe ser matemáticamente.

Líneas de cuarto (.25/.75) **no requieren lógica especial de "split"** en el motor: como el emparejamiento exige coincidencia **exacta** de `line`, nunca se compara una cuota de línea 1.25 contra una de línea 1.5 (eso sería un falso arbitraje). Lo único que añade el motor de riesgo es una pequeña penalización de riesgo en líneas de cuarto, porque en la práctica suelen tener menor liquidez.

---

## 9. NORMALIZACIÓN DE MERCADOS

Este es el punto que el enunciado marca como "probablemente el más importante", y es donde se concentra la mayor parte de la lógica no trivial ([`surebet/normalize/`](../surebet/normalize/)):

1. **`markets.py`** define qué conjunto de selecciones es obligatorio y exhaustivo para cada familia de mercado (`_REQUIRED_SELECTIONS`). Si falta una selección (p.ej. no hay cuota de "draw" en un 1X2), el grupo se descarta sin evaluar — nunca se fuerza un arbitraje con datos incompletos.
2. **`is_exhaustive()`** es la función que decide si un grupo de cuotas realmente cubre el 100% de los resultados posibles. Un ejemplo del enunciado ("Real Madrid gana por al menos 2 goles") **nunca** llega a convertirse en un `MarketKey` de tipo `HANDICAP`, porque no es un hándicap de casa de apuestas con `point` estandarizado — es un mercado de "margen de victoria" con reglas de liquidación propias que este MVP no modela (documentado como fuera de alcance en el roadmap, sección 13, para evitar precisamente el falso arbitraje que el enunciado pone como ejemplo).
3. **`events.py`** resuelve el problema de "el mismo partido con dos IDs distintos entre fuentes" con una heurística conservadora: mismo deporte, nombres de equipo con similitud ≥ 0.82 (usando `difflib`), y hora de inicio dentro de una tolerancia de 10 minutos. Documentado como heurística, no como garantía absoluta — es la misma filosofía que "no asumir, comprobar" aplicada a nivel de evento, no solo de mercado.
4. **`cross_source.py`** aplica esa heurística para fusionar los eventos de The Odds API y de Pinnacle bajo un identificador canónico común, permitiendo que sus cuotas se agrupen en `group_by_market()` como si vinieran de una sola fuente.

---

## 10. CÁLCULO DE STAKES

Implementado en [`surebet/engine/stakes.py`](../surebet/engine/stakes.py). Reparte el bankroll proporcionalmente a `1/odd_i` (para igualar el retorno en cualquier resultado), y luego:

- Redondea **hacia abajo** al incremento mínimo de cada bookmaker (nunca hacia arriba, para no arriesgar más bankroll del especificado).
- Respeta el stake mínimo y máximo conocido de cada bookmaker.
- **Recalcula el beneficio después de redondear**, nunca antes. Un test (`tests/test_stakes.py::test_rounding_can_destroy_marginal_arbitrage`) demuestra un caso real donde un margen pequeño con un incremento de apuesta grande destruye completamente el arbitraje tras el redondeo — el sistema lo detecta (`arbitrage_survives_rounding = False`) en vez de recomendar una apuesta que en la práctica ya no es rentable.
- Si el stake óptimo supera el máximo de una casa, lo marca (`limited_by_max_stake = True`) para que el motor de riesgo lo penalice.

---

## 11. LIVE BETTING

**Por qué el live es mucho más difícil** (investigado, no asumido):

- The Odds API no separa claramente "cuánto ha tardado la cuota en llegarme" de "cuándo la actualizó el bookmaker" en su endpoint estándar de forma fiable segundo a segundo; su modelo de créditos (`markets × regiones` por llamada) hace que sondear cada 2-3 segundos agote el free tier de 500 créditos/mes en minutos.
- Pinnacle guest API sí permite polling más frecuente sin coste, pero no ofrece WebSocket público, así que "tiempo real" real solo se consigue con polling agresivo, que tiene su propio riesgo de bloqueo.
- El mercado en vivo se suspende constantemente (gol, tarjeta, punto de set) y el veredicto de "cuota vigente" puede cambiar en menos de un segundo — de ahí que el sistema use umbrales de frescura mucho más estrictos en vivo (`LIVE_FRESH_SECONDS=5`, `LIVE_STALE_SECONDS=20`) que en pre-match (`180`/`900`).
- Betfair Exchange sí tiene Stream API real gratuito, pero con la Delayed Key los datos llegan "conflated" (agregados, con retraso), lo que la hace inútil para arbitraje en vivo real y sí útil para pre-match.

**Recomendación de esta fase:** empezar solo con pre-match (como está planteado el MVP1-3 de este proyecto) y añadir live como fase posterior (MVP4), aceptando que con recursos 100% gratuitos el live será de calidad notablemente inferior a un servicio de pago especializado.

---

## 12. RIESGOS

- **Riesgo de cobertura**: sin bet365/Winamax ES/Bwin, el volumen de arbitrajes reales detectables es menor que en un sistema comercial de pago.
- **Riesgo de cuota de la API**: 500 créditos/mes obliga a espaciar el polling (por defecto cada 30 minutos en este proyecto), lo que reduce las probabilidades de capturar arbitrajes de corta duración.
- **Riesgo de ToS**: usar la API guest de Pinnacle es una zona gris (sin prohibición explícita encontrada, pero tampoco autorización explícita). Se recomienda uso personal, frecuencia moderada, y dejar de usarla si empieza a bloquear.
- **Riesgo de falso positivo**: mitigado por la capa de normalización y el motor de riesgo, pero nunca es cero — de ahí la distinción explícita `MATHEMATICAL ARBITRAGE` vs `EXECUTABLE ARBITRAGE` en todo el sistema (`surebet/engine/risk.py`).
- **Riesgo de ejecución**: cuentas de apuestas limitadas/cerradas por los propios bookmakers si detectan arbitraje sistemático (riesgo del mundo real del arbitraje deportivo, no del software).

---

## 13. PLAN MVP

- **MVP1** (implementado en este entrega): The Odds API sola, mercados `h2h` 2-way/3-way, pre-match, detección de arbitraje matemático. Ejecutable hoy con solo una API key gratuita.
- **MVP2** (implementado): + Pinnacle guest API como segunda fuente, + hándicap/Asian Handicap y totals, + fusión de eventos entre fuentes (`cross_source.py`).
- **MVP3** (implementado): + alertas Telegram, + dashboard web, + histórico en SQLite con estadísticas básicas de backtest (`/api/backtest`).
- **MVP4** (roadmap, no implementado): live betting — requiere polling más agresivo de Pinnacle, gestión de suspensión de mercado, y umbrales de frescura mucho más estrictos (la infraestructura de `risk.py` ya está preparada para `is_live=True`, falta el collector específico de live).
- **MVP5** (roadmap, no implementado): fuentes adicionales — evaluar Betfair Exchange API directamente (más allá de lo que ya trae The Odds API) para back/lay matched betting, y reevaluar periódicamente si aparecen nuevas fuentes gratuitas con cobertura española.

---

## 14. CÓDIGO

Estructura real del proyecto (todo funcional, testeado):

```
Surebet/
  requirements.txt
  .env.example
  docs/INVESTIGACION_Y_DISENO.md   (este documento)
  surebet/
    config.py            Configuración vía variables de entorno
    models.py             Event, MarketKey, OddQuote
    oddsconv.py            Conversión de cuotas americanas a decimales
    collectors/
      the_odds_api.py       Collector real de The Odds API
      pinnacle_guest.py      Collector real de la API pública de Pinnacle
    normalize/
      events.py              Fusión de eventos entre fuentes
      markets.py              Agrupación y verificación de exhaustividad de mercados
      cross_source.py          Unificación de IDs entre fuentes
    engine/
      arbitrage.py             Motor matemático de arbitraje
      stakes.py                 Calculadora de stakes con redondeo real
      risk.py                    Frescura de datos + execution risk score
    storage/db.py               SQLite: snapshots + oportunidades + backtest
    alerts/telegram.py           Formato y envío de alertas Telegram
    api/main.py + static/dashboard.html    Dashboard FastAPI
    scanner.py                   Orquestador end-to-end
  scripts/
    run_scanner.py                CLI del scanner (bucle o --once)
    run_dashboard.py               Lanza el dashboard
  tests/
    test_arbitrage.py, test_stakes.py, test_normalize.py, test_risk.py
```

**Verificación real realizada durante esta entrega** (no solo "debería funcionar"):

- Suite de tests: **18/18 tests pasan** (`pytest`).
- Ejecución real contra Pinnacle en vivo: **1826 eventos, 46.927 cuotas** procesadas sin errores.
- Prueba sintética de arbitraje con los números exactos del enunciado (`2.00` / `2.37`): el sistema calculó **8.4668%** de beneficio y generó correctamente el registro `VALID_ARB`, coincidiendo con el cálculo manual esperado.
- Dashboard probado localmente: `GET /`, `GET /api/opportunities`, `GET /api/backtest` responden `200 OK`.

---

## 15. PASOS EXACTOS PARA INSTALARLO

1. Instala Python 3.11+ (en este equipo ya está disponible vía `py`).
2. Desde `C:\ALEX\Surebet`:
   ```
   py -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   copy .env.example .env
   ```
3. Consigue tu API key gratuita de The Odds API en <https://the-odds-api.com/> (formulario, sin tarjeta) y pégala en `.env` como `THE_ODDS_API_KEY`.
4. (Opcional) Crea un bot de Telegram con `@BotFather`, copia el token en `TELEGRAM_BOT_TOKEN`, escríbele un mensaje y visita `https://api.telegram.org/bot<TOKEN>/getUpdates` para obtener tu `TELEGRAM_CHAT_ID`.
5. Prueba una pasada única:
   ```
   .venv\Scripts\python scripts\run_scanner.py --once
   ```
6. Lanza el bucle continuo (respeta `POLL_INTERVAL_SECONDS` del `.env`):
   ```
   .venv\Scripts\python scripts\run_scanner.py
   ```
7. En otra terminal, lanza el dashboard:
   ```
   .venv\Scripts\python scripts\run_dashboard.py
   ```
   y abre <http://127.0.0.1:8000>.
8. Ejecuta los tests en cualquier momento con `.venv\Scripts\python -m pytest`.

---

## 16. COSTE REAL = 0 €

- The Odds API: gratis (500 créditos/mes).
- Pinnacle guest API: gratis, sin registro.
- SQLite: gratis, embebido.
- FastAPI + Telegram Bot API: gratis.
- Ejecutándose en tu propio ordenador: sin coste de hosting.

**Coste real: 0 €/mes**, siempre que no se supere el free tier de The Odds API (controlado por `POLL_INTERVAL_SECONDS` y el número de deportes/mercados configurados en `.env`).

---

## 17. QUÉ LIMITACIONES TENDRÁS

- Sin bet365, Winamax España, Bwin, Codere, Luckia, Sportium: el sistema no puede generar arbitrajes con esas casas, punto.
- Frecuencia de escaneo baja (por defecto cada 30 min) por el presupuesto de créditos gratuito de The Odds API — muchos arbitrajes de vida corta se perderán.
- Sin WebSocket real: todo es polling.
- Sin live betting real en este MVP (queda como roadmap).
- El emparejamiento de eventos entre fuentes es heurístico (nombres + hora), puede fallar en casos raros (aplazamientos, cambios de sede).
- Player props, outrights y mercados de "margen de victoria"/"handicap de puntos en vivo con reglas propias" quedan fuera del MVP por ser fuente de falsos arbitrajes si no se modelan con cuidado.

---

## 18. QUÉ MEJORARÍA SI EN EL FUTURO PAGAS

El primer coste inevitable y cuantificable si quieres mejorar esto de verdad:

- **The Odds API plan Starter** (20.000 créditos/mes) — a partir de **~30 $/mes** según su página de precios actual — permite polling mucho más frecuente y más deportes/mercados simultáneos.
- **Betfair Live App Key**: pago único de **£499** (no mensual) si quieres datos de Betfair Exchange sin el retraso de ~1 minuto de la Delayed Key — relevante solo si te interesa el live o el matched betting con exchange.
- Un servicio de pago especializado en cobertura de bookmakers españoles (Codere, Luckia, Sportium, bet365 ES) probablemente requeriría contratar una API comercial de "odds feed" (no evaluada en profundidad aquí porque el objetivo explícito de esta investigación era 0 €), o negociar acceso directo con los propios operadores.

---

## 19. RECOMENDACIÓN CONCRETA

> Si yo quisiera construir esto hoy con 0 €, haría exactamente:
>
> **A)** The Odds API (free tier, región `eu`) como fuente principal — es la única API gratuita con cobertura multi-bookmaker real y verificable, aceptando que su cuota de 500 créditos/mes obliga a un polling espaciado (30-60 min) y que no cubre el mercado español.
>
> **B)** La API pública "guest" de Pinnacle como segunda fuente gratuita e ilimitada de facto, para tener una pata "sharp" adicional y no depender solo del presupuesto de créditos de (A) — sabiendo que es una zona gris de ToS y usándola con moderación.
>
> **C)** El pipeline de normalización estricta (`MarketKey` con periodo + reglas de liquidación + línea exacta) implementado en este proyecto, en vez de un simple "comparador de cuotas por nombre de mercado" — porque sin esa capa, cualquier sistema de arbitraje gratuito acaba generando falsos positivos por comparar mercados que no son realmente complementarios.
>
> Todo lo demás (Telegram, dashboard, SQLite, stakes) es exactamente lo que ya está construido y probado en este repositorio.
