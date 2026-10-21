using './main.bicep'

param landingZone = {
  sharedResourceGroupName: readEnvironmentVariable('SHARED_RESOURCE_GROUP_NAME')
  registryName: readEnvironmentVariable('REGISTRY_NAME')
  registryLoginServer: readEnvironmentVariable('REGISTRY_LOGIN_SERVER')
  logAnalyticsWorkspaceId: readEnvironmentVariable('LOG_ANALYTICS_WORKSPACE_ID')
  actionGroupId: readEnvironmentVariable('ACTION_GROUP_ID')
}
param apiAppClientId = readEnvironmentVariable('API_APP_CLIENT_ID')
param apiImage = readEnvironmentVariable('SERVICE_API_IMAGE_NAME', 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest')
param operatorIp = readEnvironmentVariable('OPERATOR_IP')
param entraAdminObjectId = readEnvironmentVariable('ENTRA_ADMIN_OBJECT_ID')
param entraAdminUpn = readEnvironmentVariable('ENTRA_ADMIN_UPN')
param githubRepository = readEnvironmentVariable('GITHUB_REPOSITORY', '')
param postgresSku = readEnvironmentVariable('POSTGRES_SKU', 'Standard_B1ms')
param postgresLocation = readEnvironmentVariable('POSTGRES_LOCATION', 'swedencentral')
