<#
.SYNOPSIS
    Despliegue completo de SmartWMS en Google Cloud Platform (GCP).
.DESCRIPTION
    Automatiza:
      1. Habilitación de APIs en GCP
      2. Creación de Artifact Registry, Cloud SQL (PostgreSQL) y Secret Manager
      3. Build & Deploy de smartwms-bot y smartwms-backend en Cloud Run
      4. Build & Deploy del Frontend Angular en Firebase Hosting (o Cloud Run)
      5. Compilación de la APK Android apuntando a la URL pública de Cloud Run
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [string]$Region = "southamerica-west1",
    [string]$SqlInstance = "smartwms-db",
    [string]$DbName = "smartwms_ecommerce",
    [string]$DbUser = "smartwms",
    [ValidateSet("firebase", "cloudrun")]
    [string]$FrontendTarget = "firebase"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path

function Assert-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "No se encontró el comando '$Name' en el PATH. Instálalo antes de continuar."
    }
}

Assert-Command "gcloud"
if ($FrontendTarget -eq "firebase") {
    Assert-Command "firebase"
}

Write-Host "=== 1. Configurando proyecto GCP: $ProjectId ($Region) ===" -ForegroundColor Cyan
gcloud config set project $ProjectId

Write-Host "=== 2. Habilitando APIs necesarias ===" -ForegroundColor Cyan
gcloud services enable `
    run.googleapis.com `
    sqladmin.googleapis.com `
    artifactregistry.googleapis.com `
    cloudbuild.googleapis.com `
    secretmanager.googleapis.com

Write-Host "=== 3. Creando Artifact Registry 'smartwms' ===" -ForegroundColor Cyan
$arExists = gcloud artifacts repositories list --location=$Region --filter="name:smartwms" --format="value(name)"
if (-not $arExists) {
    gcloud artifacts repositories create smartwms `
        --repository-format=docker `
        --location=$Region `
        --description="Imagenes Docker de SmartWMS"
}

Write-Host "=== 4. Verificando/Creando Cloud SQL PostgreSQL ($SqlInstance) ===" -ForegroundColor Cyan
$sqlExists = gcloud sql instances list --filter="name=$SqlInstance" --format="value(name)"
if (-not $sqlExists) {
    $DbPass = Read-Host "Ingresa una contraseña segura para el usuario '$DbUser' de Cloud SQL" -AsSecureString
    $DbPassPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($DbPass))

    gcloud sql instances create $SqlInstance `
        --database-version=POSTGRES_15 `
        --tier=db-f1-micro `
        --region=$Region

    gcloud sql databases create $DbName --instance=$SqlInstance
    gcloud sql users create $DbUser --instance=$SqlInstance --password=$DbPassPlain
} else {
    $DbPass = Read-Host "Ingresa la contraseña existente de '$DbUser' en Cloud SQL" -AsSecureString
    $DbPassPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($DbPass))
}

$ConnectionName = gcloud sql instances describe $SqlInstance --format="value(connectionName)"
$DatabaseUrl = "postgresql+pg8000://${DbUser}:${DbPassPlain}@/${DbName}?unix_sock=/cloudsql/${ConnectionName}/.s.PGSQL.5432"

Write-Host "=== 5. Configurando Secret Manager ===" -ForegroundColor Cyan
function Ensure-Secret($SecretName, $PromptMsg, $DefaultRandom = $false) {
    $exists = gcloud secrets list --filter="name:$SecretName" --format="value(name)"
    if (-not $exists) {
        if ($DefaultRandom) {
            $val = [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
        } else {
            $val = Read-Host $PromptMsg
        }
        $val | gcloud secrets create $SecretName --data-file=-
    }
}

Ensure-Secret "smartwms-jwt-secret" "" $true
Ensure-Secret "smartwms-webhook-secret" "" $true
$fernetKey = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
$existsMfa = gcloud secrets list --filter="name:smartwms-mfa-key" --format="value(name)"
if (-not $existsMfa) { $fernetKey | gcloud secrets create smartwms-mfa-key --data-file=- }
Ensure-Secret "smartwms-gemini-key" "Ingresa tu GEMINI_API_KEY (o presiona Enter si usaras fallback local)"

$existsDbUrl = gcloud secrets list --filter="name:smartwms-database-url" --format="value(name)"
if (-not $existsDbUrl) {
    $DatabaseUrl | gcloud secrets create smartwms-database-url --data-file=-
}

$ImageRepo = "${Region}-docker.pkg.dev/${ProjectId}/smartwms"

Write-Host "=== 6. Compilando y desplegando smartwms-bot en Cloud Run ===" -ForegroundColor Cyan
gcloud builds submit "$RepoRoot\bot" --tag "${ImageRepo}/smartwms-bot:latest"
gcloud run deploy smartwms-bot `
    --image "${ImageRepo}/smartwms-bot:latest" `
    --region $Region `
    --platform managed `
    --allow-unauthenticated `
    --add-cloudsql-instances $ConnectionName `
    --set-secrets "DATABASE_URL=smartwms-database-url:latest,JWT_SECRET=smartwms-jwt-secret:latest,GEMINI_API_KEY=smartwms-gemini-key:latest"

$BotUrl = gcloud run services describe smartwms-bot --region $Region --format="value(status.url)"

Write-Host "=== 7. Compilando y desplegando smartwms-backend en Cloud Run ===" -ForegroundColor Cyan
gcloud builds submit "$RepoRoot\ecommerce\backend" --tag "${ImageRepo}/smartwms-backend:latest"
gcloud run deploy smartwms-backend `
    --image "${ImageRepo}/smartwms-backend:latest" `
    --region $Region `
    --platform managed `
    --allow-unauthenticated `
    --add-cloudsql-instances $ConnectionName `
    --set-env-vars "BOT_URL=${BotUrl}/api/chat,MFA_ISSUER=SmartWMS,MFA_REQUIRED_ROLES=*" `
    --set-secrets "DATABASE_URL=smartwms-database-url:latest,JWT_SECRET=smartwms-jwt-secret:latest,WEBHOOK_SECRET=smartwms-webhook-secret:latest,MFA_ENCRYPTION_KEY=smartwms-mfa-key:latest"

$BackendUrl = gcloud run services describe smartwms-backend --region $Region --format="value(status.url)"

Write-Host "=== 8. Compilando y desplegando Frontend Angular ($FrontendTarget) ===" -ForegroundColor Cyan
$EnvProdPath = "$RepoRoot\ecommerce\frontend\smartwms-angular\src\environments\environment.prod.ts"
@"
export const environment = {
  production: true,
  apiUrl: '$BackendUrl',
  botApiUrl: '$BackendUrl',
};
"@ | Set-Content -Path $EnvProdPath -Encoding UTF8

Push-Location "$RepoRoot\ecommerce\frontend\smartwms-angular"
npm ci
npm run build
if ($FrontendTarget -eq "firebase") {
    firebase deploy --only hosting --project $ProjectId
} else {
    gcloud builds submit . --tag "${ImageRepo}/smartwms-frontend:latest"
    gcloud run deploy smartwms-frontend `
        --image "${ImageRepo}/smartwms-frontend:latest" `
        --region $Region `
        --platform managed `
        --allow-unauthenticated
}
Pop-Location

Write-Host "=== 9. Generando APK Android apuntando a $BackendUrl ===" -ForegroundColor Cyan
Push-Location "$RepoRoot\android-operario"
.\gradlew.bat assembleProductionDebug "-PCLOUD_RUN_URL=$BackendUrl"
Pop-Location

Write-Host "=== DESPLIEGUE COMPLETADO ===" -ForegroundColor Green
Write-Host "Backend URL: $BackendUrl"
Write-Host "Bot URL:     $BotUrl"
Write-Host "APK generada en: $RepoRoot\android-operario\app\build\outputs\apk\production\debug\"
