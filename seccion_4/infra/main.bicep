// =============================================================================
// Infraestructura mínima en Azure para la aplicación (NO se ha desplegado: es una plantilla).
//   * Plan de App Service Linux (F1 gratis para piloto; B1 recomendado para uso real)
//   * Web App Python 3.11 con HTTPS obligatorio, TLS 1.2, FTP deshabilitado y sondeo de salud
// Despliegue (cuando se decida):
//   az group create -n rg-monitoreo -l eastus2
//   az deployment group create -g rg-monitoreo -f infra/main.bicep \
//      -p nombreApp=<nombre-unico> djangoSecretKey=<clave> [databaseUrl=<url>] [sku=B1]
// =============================================================================

@description('Nombre único global de la Web App (queda <nombreApp>.azurewebsites.net).')
param nombreApp string

@description('Región de Azure.')
param ubicacion string = resourceGroup().location

@description('Plan: F1 (gratis, 60 min CPU/día, sin Always On) para piloto; B1 para producción básica.')
@allowed([ 'F1', 'B1', 'B2', 'P0v3' ])
param sku string = 'F1'

@secure()
@description('DJANGO_SECRET_KEY (mínimo 50 caracteres).')
param djangoSecretKey string

@secure()
@description('Cadena de conexión. Por defecto SQLite persistente en /home (válido para piloto de una instancia).')
param databaseUrl string = 'sqlite:////home/data/db.sqlite3'

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'plan-${nombreApp}'
  location: ubicacion
  kind: 'linux'
  sku: { name: sku }
  properties: { reserved: true }
}

resource app 'Microsoft.Web/sites@2023-12-01' = {
  name: nombreApp
  location: ubicacion
  kind: 'app,linux'
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: 'bash startup.sh'
      alwaysOn: sku != 'F1'
      healthCheckPath: '/salud/'
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      http20Enabled: true
      appSettings: [
        { name: 'DJANGO_SETTINGS_MODULE', value: 'config.settings.prod' }
        { name: 'DJANGO_SECRET_KEY', value: djangoSecretKey }
        { name: 'DJANGO_ALLOWED_HOSTS', value: '${nombreApp}.azurewebsites.net' }
        { name: 'DATABASE_URL', value: databaseUrl }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'DISABLE_COLLECTSTATIC', value: 'true' }
      ]
    }
  }
}

output url string = 'https://${app.properties.defaultHostName}'
