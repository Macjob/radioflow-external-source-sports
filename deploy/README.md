# Despliegue de producción: publisher deportivo

Este despliegue ejecuta la integración deportiva como un job Docker de corta duración. No expone FastAPI ni publica puertos. Un timer de `systemd` inicia el publisher cada 15 minutos y envía sugerencias a RadioFlow mediante su red Docker interna.

## 1. Validar localmente antes del despliegue

En Windows PowerShell, desde la raíz del repositorio:

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest tests -q
```

`pytest` es necesario solamente para desarrollo y CI. No se instala en la imagen de producción.

## 2. Preparar RadioFlow

En RadioFlow, abre `/settings/external-sources` y crea o instala una fuente activa con la capacidad `suggest_blocks`. Guarda ambos valores cuando aparezcan:

- source key
- token raw de la fuente

El token raw se muestra una sola vez.

## 3. Copiar o clonar el proyecto en el servidor

Los ejemplos asumen Ubuntu o Debian y esta estructura:

```text
/opt/radioflow-sports/
├── source/
├── publisher.env
├── config.json
└── run-publisher.sh
```

Comandos:

```bash
sudo mkdir -p /opt/radioflow-sports
sudo chown "$USER":"$USER" /opt/radioflow-sports
cd /opt/radioflow-sports
git clone https://github.com/Macjob/radioflow-external-source-sports.git source
cd source
```

Para un clon existente:

```bash
cd /opt/radioflow-sports/source
git pull --ff-only
```

## 4. Construir la imagen de producción

```bash
cd /opt/radioflow-sports/source
GIT_SHA="$(git rev-parse --short=12 HEAD)"
docker build --pull \
  --file Dockerfile.publisher \
  --tag "radioflow-sports-publisher:${GIT_SHA}" \
  .
```

Conserva el tag anterior si ya existía un despliegue. El archivo
`/etc/default/radioflow-sports-publisher` debe apuntar siempre al tag exacto que
se validó, no a un `latest` mutable.

La imagen contiene solamente las dependencias del publisher. FastAPI, Uvicorn, pytest, coverage y Ruff quedan fuera.

## 5. Configurar secretos y equipos

```bash
cd /opt/radioflow-sports/source
cp deploy/publisher.env.example /opt/radioflow-sports/publisher.env
cp config.example.json /opt/radioflow-sports/config.json
cp deploy/run-publisher.sh /opt/radioflow-sports/run-publisher.sh
chmod 700 /opt/radioflow-sports/run-publisher.sh
chmod 600 /opt/radioflow-sports/publisher.env
chmod 644 /opt/radioflow-sports/config.json
```

Edita las variables de entorno:

```bash
sudo nano /opt/radioflow-sports/publisher.env
```

Valores requeridos:

```env
FOOTBALL_DATA_API_KEY=tu_clave_real
RADIOFLOW_BASE_URL=http://web:3000
RADIOFLOW_SOURCE_KEY=source_key_exacto_entregado_por_radioflow
RADIOFLOW_SOURCE_TOKEN=tu_token_raw_real
```

Edita los equipos, equivalencias, radios y streams:

```bash
sudo nano /opt/radioflow-sports/config.json
```

No subas ninguno de estos dos archivos al repositorio.

Detente si falta cualquiera de los tres valores secretos o si la fuente Sports
ya está instalada pero no se conserva su token raw. No instales una fuente
duplicada ni rotes un token sin autorización explícita.

## 6. Confirmar conectividad interna con RadioFlow

El despliegue actual usa Docker Compose con:

- proyecto: `radioflow`
- servicio web: `web`
- red: `radioflow_default`
- puerto interno: `3000`

Prueba la resolución DNS y la respuesta HTTP desde la misma red usando la imagen del publisher:

```bash
docker run --rm \
  --network radioflow_default \
  --entrypoint python \
  radioflow-sports-publisher:latest \
  -c 'import requests; response = requests.get("http://web:3000/login", timeout=10, allow_redirects=False); print(response.status_code, response.headers.get("location"))'
```

Cualquier respuesta HTTP —por ejemplo `200`, `302` o `307`— confirma la conectividad. Un error de DNS o conexión debe resolverse antes de activar el publisher.

La configuración correspondiente es:

```env
RADIOFLOW_BASE_URL=http://web:3000
```

Valida además la credencial de football-data.org. Esta comprobación imprime
solo el estado HTTP y nunca la API key:

```bash
docker run --rm \
  --network radioflow_default \
  --env-file /opt/radioflow-sports/publisher.env \
  --entrypoint python \
  "radioflow-sports-publisher:${GIT_SHA}" \
  -c 'import os, requests; response = requests.get("https://api.football-data.org/v4/matches", headers={"X-Auth-Token": os.environ["FOOTBALL_DATA_API_KEY"]}, timeout=10); print("football_data_status=", response.status_code); response.raise_for_status()'
```

El estado debe ser `200`. Sin esta comprobación, un error de red o credencial
podría parecer un resultado válido de cero partidos.

## 7. Configurar systemd

Copia el servicio, timer y archivo de configuración:

```bash
sudo cp /opt/radioflow-sports/source/deploy/systemd/radioflow-sports-publisher.service \
  /etc/systemd/system/radioflow-sports-publisher.service

sudo cp /opt/radioflow-sports/source/deploy/systemd/radioflow-sports-publisher.timer \
  /etc/systemd/system/radioflow-sports-publisher.timer

sudo cp /opt/radioflow-sports/source/deploy/systemd/radioflow-sports-publisher.default.example \
  /etc/default/radioflow-sports-publisher
```

Confirma la configuración de red del publisher:

```bash
sudo nano /etc/default/radioflow-sports-publisher
```

Ejemplo:

```env
RADIOFLOW_SPORTS_DIR=/opt/radioflow-sports
RADIOFLOW_SPORTS_IMAGE=radioflow-sports-publisher:REEMPLAZAR_CON_GIT_SHA
RADIOFLOW_DOCKER_NETWORK=radioflow_default
RADIOFLOW_SPORTS_COUNTRY=Chile
```

Recarga `systemd`:

```bash
sudo systemctl daemon-reload
```

## 8. Ejecutar primero un dry-run

Este comando consulta partidos e imprime los payloads sin llamar a RadioFlow:

```bash
docker run --rm \
  --network radioflow_default \
  --env-file /opt/radioflow-sports/publisher.env \
  --mount type=bind,src=/opt/radioflow-sports/config.json,dst=/app/config.json,readonly \
  radioflow-sports-publisher:latest \
  --country Chile \
  --dry-run
```

Resultado esperado: código de salida `0`, un resumen y cero o más sugerencias preparadas.

Si el resumen muestra `prepared: 0`, el dry-run valida la consulta y la
configuración, pero una publicación posterior no podrá validar el token de
RadioFlow de extremo a extremo. No declares completa esa validación hasta
observar al menos un resultado `created` o `deduplicated`.

## 9. Realizar una publicación real

```bash
sudo systemctl start radioflow-sports-publisher.service
sudo systemctl status radioflow-sports-publisher.service --no-pager
sudo journalctl -u radioflow-sports-publisher.service -n 100 --no-pager
```

Después confirma las sugerencias en RadioFlow, en `/suggestions`.

Para validar el onboarding de Autofill, revisa en `/suggestions` una sugerencia
con radio reproducible, elige **Save for Autofill**, confirma que aún no exista
un bloque programado y luego usa **Fill gaps** sobre un espacio de duración
compatible en `/schedule`.

## 10. Activar el timer

```bash
sudo systemctl enable --now radioflow-sports-publisher.timer
sudo systemctl list-timers radioflow-sports-publisher.timer
```

Para seguir los logs:

```bash
sudo journalctl -u radioflow-sports-publisher.service -f
```

## Actualizar la integración

```bash
cd /opt/radioflow-sports/source
git pull --ff-only
GIT_SHA="$(git rev-parse --short=12 HEAD)"
docker build --pull --file Dockerfile.publisher --tag "radioflow-sports-publisher:${GIT_SHA}" .
sudo sed -i "s|^RADIOFLOW_SPORTS_IMAGE=.*|RADIOFLOW_SPORTS_IMAGE=radioflow-sports-publisher:${GIT_SHA}|" /etc/default/radioflow-sports-publisher
sudo systemctl start radioflow-sports-publisher.service
sudo journalctl -u radioflow-sports-publisher.service -n 100 --no-pager
```

La siguiente ejecución del timer utilizará automáticamente la imagen nueva.

## Desactivar o eliminar

Pausar las ejecuciones:

```bash
sudo systemctl disable --now radioflow-sports-publisher.timer
```

Para volver a una imagen anterior, restaura su tag exacto en
`/etc/default/radioflow-sports-publisher` y ejecuta manualmente el servicio antes
de reactivar el timer. Esto detiene publicaciones futuras, pero no elimina las
sugerencias ya creadas o deduplicadas en RadioFlow.

Eliminar las unidades:

```bash
sudo rm /etc/systemd/system/radioflow-sports-publisher.service
sudo rm /etc/systemd/system/radioflow-sports-publisher.timer
sudo rm /etc/default/radioflow-sports-publisher
sudo systemctl daemon-reload
```

## Notas operacionales

- El contenedor no publica puertos.
- Se ejecuta como usuario no root y con filesystem de solo lectura.
- Está limitado a 0,5 CPU y 192 MB de memoria.
- Un lock en el host evita ejecuciones superpuestas.
- Una publicación fallida devuelve un código distinto de cero y queda registrada en los logs de `systemd`.
- RadioFlow mantiene la responsabilidad sobre autenticación por token, estado de la fuente, capabilities, deduplicación, conflictos y auditoría.
