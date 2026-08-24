## Paso 0: Entra al Container con "DevContainer: Reopen in Container"

## Paso 1: Vinculación
gcloud init

## Paso 2: Creación del repositorio en Artifact Registry (GCP)
gcloud artifacts repositories create repositorio-agente-inmobiliario --repository-format docker --project datapath-ai-david-sanchez --location us-central1

## Paso 3: Crear el repositorio de github

## Paso 4: Crear la Key de la Cuenta de Servicio en "IAM y Administración"

## Paso 5: Colocar el Service Account Key en GitHub Settings
- Debes ir a "Secrets and variables"
- Luego a "Actions"
- Clic en "New repository secret"
- El nombre del Secreto es "AR_SERVICE_ACCOUNT_KEY"
- En la caja de abajo copia y pega todo lo que está dentro de la Clave JSON que descargaste de la cuenta de servicio.

## Paso 6 - 1 Primer commit en tu Repo, Automatizacion:
- git init
- git add .
- git commit -m "Proyecto de automatización de despliegue en AR"
- git branch -M main
- git remote add origin https://github.com/DavidSanchezR/Deploy-Agente-Inmobiliario-Github-Action-AR.git
- git push -u origin main
## Paso 6 - 2 Automatizando nuevamente:
rm -rf /ws/code/.git


## Cuando deseas volver a subir por algun error corres lo siguiente:
- git status
- git add .
- git commit -m "Ajustes en workflow de CI/CD 2"
- git push
