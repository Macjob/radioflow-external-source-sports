# Radioflow External Source - Sports

Prototipo de fuente externa deportiva para [Radioflow](https://github.com/anomalyco/radioflow).

Este proyecto es independiente del repo principal de Radioflow. Su objetivo es validar un **contrato HTTP** que Radioflow podría consumir en el futuro para generar bloques de reproducción automáticos desde fuentes externas.

---

## Hosted Add-on v1a

El servicio implementa el primer contrato alojado de RadioFlow sin cambiar los flujos existentes:

```text
GET /manifest.json
GET /health
GET /addon/events
```

La versión web-configurable agrega:

```text
POST /configuration/start
GET  /configure/{sessionId}
POST /configuration/exchange
```

El manifest declara `configuration.type = "web"`. RadioFlow abre el configurador, recibe un código de un solo uso y lo intercambia por un `configId` opaco. RadioFlow cifra ese bearer credential y lo envía únicamente como `X-RadioFlow-Config-Id`; Sports conserva sólo su hash SHA-256 en SQLite.

El backend alojado usa API-Football v3 mediante `API_FOOOTBAL`. La clave nunca se entrega al navegador ni a RadioFlow. La primera vertical permite seleccionar una competición, uno o más equipos y el único evento habilitado en esta versión: `match.scheduled`. El addon produce la acción genérica `suggest_block`, manteniendo toda la semántica deportiva fuera del core.

El servicio oficial se publica bajo `https://addons.radioflow.media/sports`. Consulta [`deploy/HOSTED_SERVICE.md`](deploy/HOSTED_SERVICE.md) para el contenedor persistente, SQLite y proxy HTTPS. El publisher self-hosted existente sigue disponible sin cambios.

`/manifest.json` declara `app.radioflow.sports`, sus capacidades y el evento real que hoy produce: `match.scheduled`. `/addon/events` entrega esos partidos dentro del envelope genérico de RadioFlow. `/health` responde `degraded` cuando el proveedor deportivo no está configurado, sin exponer credenciales.

RadioFlow v1b puede instalar este servicio desde su catálogo y consultarlo mediante polling. `FOOTBALL_DATA_API_KEY`, Python y `config.json` siguen siendo responsabilidad exclusiva del operador del servicio alojado; el usuario normal no recibe tokens ni configura infraestructura local.

---

## Stack

- Python 3.11+
- FastAPI
- Requests
- Pydantic v2
- python-dotenv
- zoneinfo (stdlib)

---

## Requisitos

- Python 3.11 o superior
- API key de [football-data.org](https://www.football-data.org) (gratuita)
- (Opcional) Token de bot de Telegram y Chat ID para notificaciones

---

## Instalación

```bash
# Clonar el repo
git clone https://github.com/Macjob/radioflow-external-source-sports.git
cd radioflow-external-source-sports

# Crear entorno virtual
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate       # Windows

# Instalar dependencias
pip install -r requirements.txt
```

---

## Configuración

### 1. Crear `.env`

```bash
cp .env.example .env
```

Editar `.env` y agregar tus credenciales:

```env
FOOTBALL_DATA_API_KEY=tu-api-key-aqui
TELEGRAM_BOT_TOKEN=opcional
TELEGRAM_CHAT_ID=opcional
RADIOFLOW_BASE_URL=http://127.0.0.1:3000
RADIOFLOW_SOURCE_KEY=sports-test
RADIOFLOW_SOURCE_TOKEN=rf_ext_xxx
```

### 2. Crear `config.json`

```bash
cp config.example.json config.json
```

Cada radio puede declarar `country` con un código ISO 3166-1 alpha-2, por
ejemplo `CL` o `MX`. RadioFlow usa ese dato para resolver correctamente una
estación por `radioLabel` cuando no hay `streamUrl`; las configuraciones
existentes sin `country` siguen siendo válidas.

Editar según necesidad: equipos, radios, zona horaria, etc.

### 3. Obtener API key de football-data.org

1. Ir a https://www.football-data.org/client/register
2. Registrarse (plan gratuito: 10 requests/minuto)
3. Copiar la API key en `FOOTBALL_DATA_API_KEY` del `.env`

### 4. (Opcional) Obtener Token de Telegram

1. Abrir Telegram y buscar `@BotFather`
2. Enviar `/newbot` y seguir instrucciones
3. Copiar el token en `TELEGRAM_BOT_TOKEN`
4. Iniciar conversación con el bot
5. Enviar cualquier mensaje al bot
6. Visitar `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
7. Copiar el `chat.id` en `TELEGRAM_CHAT_ID`

---

## Uso

### Levantar la API

```bash
uvicorn app.main:app --reload
```

La API queda disponible en `http://localhost:8000`.

Documentación interactiva en `http://localhost:8000/docs`.

### Endpoints

#### `GET /health`

```bash
curl http://localhost:8000/health
```

Respuesta: `{"status": "ok"}`

#### `GET /events/today`

```bash
curl http://localhost:8000/events/today
```

Devuelve los partidos relevantes del día:

```json
[
  {
    "id": "match-123",
    "type": "sports_event",
    "title": "Colo-Colo vs Universidad Católica",
    "team": "Colo-Colo",
    "starts_at": "2026-06-10T19:30:00-04:00",
    "timezone": "America/Santiago",
    "source": "football-data.org",
    "radio": {
      "label": "Cooperativa 93.3 FM",
      "url": "https://www.cooperativa.cl"
    }
  }
]
```

#### `GET /radioflow/blocks/today`

```bash
curl http://localhost:8000/radioflow/blocks/today
```

Devuelve los partidos en el formato histórico/intermedio de este prototipo:

```json
[
  {
    "external_id": "sports-match-123",
    "provider": "sports-notifier",
    "kind": "external_audio_recommendation",
    "title": "Hoy juega Colo-Colo",
    "description": "Colo-Colo vs Universidad Católica a las 19:30",
    "start_time": "2026-06-10T19:30:00-04:00",
    "duration_minutes": 120,
    "action": {
      "type": "open_stream",
      "label": "Escuchar en Cooperativa 93.3 FM",
      "url": "https://www.cooperativa.cl"
    },
    "metadata": {
      "sport": "football",
      "team": "Colo-Colo",
      "source": "football-data.org"
    }
  }
]
```

#### `GET /radioflow/suggestions/today`

```bash
curl "http://localhost:8000/radioflow/suggestions/today?source_key=sports-test"
```

Devuelve sugerencias en el contrato v0 real que RadioFlow acepta en `POST /api/external-suggestions`.
El `source_key` debe coincidir con el `sourceKey` configurado en RadioFlow para la fuente externa:

```json
[
  {
    "sourceKey": "sports-test",
    "externalContentId": "sports-match-123",
    "title": "Hoy juega Colo-Colo",
    "description": "Colo-Colo vs Universidad Católica a las 19:30",
    "suggestedDate": "2026-06-10",
    "suggestedStartTime": "19:30",
    "suggestedEndTime": "21:30",
    "contentKind": "metadata_only",
    "contentMode": "reference_only",
    "renderMode": "display_card",
    "fallbackStrategy": "skip",
    "conflictPolicy": "reject",
    "metadata": {
      "sport": "football",
      "team": "Colo-Colo",
      "source": "football-data.org",
      "radioLabel": "Cooperativa 93.3 FM",
      "radioUrl": "https://www.cooperativa.cl",
      "radioCountry": "CL"
    }
  }
]
```

También acepta `country`:

```bash
curl "http://localhost:8000/radioflow/suggestions/today?source_key=sports-test&country=Chile"
```

## Publicar sugerencias hacia RadioFlow

El endpoint `GET /radioflow/suggestions/today` sirve para inspeccionar los payloads. Para enviarlos a una instancia real de RadioFlow usa el publisher CLI:

```bash
python -m app.publish_radioflow_suggestions
```

Antes de publicar:

1. RadioFlow debe estar corriendo localmente o en una URL accesible.
2. Debe existir una External Source activa en RadioFlow.
3. La fuente debe tener capability `suggest_blocks`.
4. Copia el `sourceKey` y el token raw `rf_ext_...` desde el panel de creación.
5. Guarda el token al crearlo: RadioFlow solo lo muestra una vez.

Configura `.env`:

```env
FOOTBALL_DATA_API_KEY=tu-api-key-aqui
RADIOFLOW_BASE_URL=http://127.0.0.1:3000
RADIOFLOW_SOURCE_KEY=sports-test
RADIOFLOW_SOURCE_TOKEN=rf_ext_xxx
```

Primero revisa lo que se enviaría, sin llamar a RadioFlow:

```bash
python -m app.publish_radioflow_suggestions --dry-run
```

Filtra por país configurado:

```bash
python -m app.publish_radioflow_suggestions --country Chile --dry-run
```

Publica realmente:

```bash
python -m app.publish_radioflow_suggestions --country Chile
```

Para completar el recorrido de Autofill:

1. Confirma que el payload tenga una ventana completa y `streamUrl` o
   `radioLabel`; usa `radioCountry` cuando la resolución dependa del nombre.
2. En `/suggestions`, revisa la sugerencia y elige **Save for Autofill**.
3. Confirma que la sugerencia desaparezca de pendientes sin crear todavía un
   bloque de Schedule.
4. En `/schedule`, deja un espacio con la misma duración y ejecuta **Fill gaps**.
5. Verifica que RadioFlow cree un bloque `live_radio` dentro del espacio sin
   mover ni superponer los bloques fijos.

Guardar para Autofill no programa ni inicia reproducción por sí solo.

El comando imprime un resumen con sugerencias `created`, `deduplicated` y `failed`. Luego puedes revisarlas en RadioFlow en `/suggestions`.

### Script de notificaciones

```bash
python -m app.check_matches
```

Envía notificaciones por Telegram para partidos próximos a comenzar (según `notification_window_minutes` en `config.json`).

### Tests

```bash
pytest tests/ -v --cov=app
```

### Cron job (Linux/Mac)

Para ejecutar el checker cada 10 minutos:

```cron
*/10 * * * * cd /ruta/al/proyecto && .venv/bin/python -m app.check_matches
```

### Despliegue de producción

Para ejecutar el publisher como un job Docker aislado, sin exponer FastAPI, consulta [`deploy/README.md`](deploy/README.md). Incluye imagen de producción, script endurecido, servicio `systemd`, timer cada 15 minutos, dry-run, logs y actualización.

---

## Estructura del proyecto

```
radioflow-external-source-sports/
  app/
    __init__.py
    main.py              # FastAPI app, endpoints
    config.py            # Carga config.json como modelo Pydantic
    models.py            # Pydantic models
    football_client.py   # Cliente HTTP para football-data.org
    match_service.py     # Lógica de negocio: filtrado, timezone, radios
    radioflow_blocks.py  # Transformación a formato Radioflow
    radioflow_publisher.py # Cliente HTTP para publicar sugerencias en RadioFlow
    telegram_notifier.py # Envío de notificaciones Telegram
    storage.py           # Persistencia JSON para dedup
    check_matches.py     # Script de notificaciones (python -m app.check_matches)
    publish_radioflow_suggestions.py # Publisher CLI hacia /api/external-suggestions
  config.example.json
  .env.example
  requirements.txt
  README.md
  .gitignore
```

---

## Limitaciones conocidas

- El plan gratuito de football-data.org permite 10 requests/minuto.
- El matching de equipos usa substring case-insensitive contra el `team_mapping` en config.
- La API puede devolver nombres de equipos que no coincidan con el mapping (requiere ajuste manual).
- Las notificaciones por Telegram son opcionales y requieren configuración adicional.
- No hay autenticación en los endpoints (para uso local/prototipo).
- El proyecto no está diseñado para alto volumen.

---

## Próximos pasos recomendados

1. Agregar autenticación vía API key en los endpoints.
2. Soportar más proveedores deportivos (TheSportsDB, API-Sports).
3. Cachear respuestas de la API externa para reducir requests.
4. Agregar soporte para múltiples zonas horarias por equipo.
5. Implementar un sistema de plugins más formal para Radioflow.
6. Agregar health check con métricas de la fuente externa.

---

## Licencia

MIT
