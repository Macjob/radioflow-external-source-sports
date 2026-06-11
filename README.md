# Radioflow External Source — Sports

Prototipo de fuente externa deportiva para [Radioflow](https://github.com/anomalyco/radioflow).

Este proyecto es independiente del repo principal de Radioflow. Su objetivo es validar un **contrato HTTP** que Radioflow podría consumir en el futuro para generar bloques de reproducción automáticos desde fuentes externas.

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
```

### 2. Crear `config.json`

```bash
cp config.example.json config.json
```

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

Devuelve los partidos en formato compatible con Radioflow:

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
    telegram_notifier.py # Envío de notificaciones Telegram
    storage.py           # Persistencia JSON para dedup
    check_matches.py     # Script de notificaciones (python -m app.check_matches)
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
