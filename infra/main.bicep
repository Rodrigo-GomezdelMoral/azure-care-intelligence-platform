targetScope = 'resourceGroup'

@export()
@description('The landing zone outputs this workload consumes, copied verbatim from azd env get-values of azure-ai-landing-zone.')
type landingZoneOutputs = {
  sharedResourceGroupName: string, registryName: string, registryLoginServer: string, logAnalyticsWorkspaceId: string, actionGroupId: string
}

@description('Region of every resource; defaults to the location of the existing resource group.')
param location string = resourceGroup().location
@description('Landing zone outputs; the shared registry, workspace and action group are referenced as existing, never created here.')
param landingZone landingZoneOutputs
@description('Client id of the app registration that defines the Care.Read app role; created by the bootstrap in the README.')
param apiAppClientId string
@description('Image of the serving API; azd replaces it after the first build.')
param apiImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
@description('Public address allowed through the PostgreSQL firewall besides Azure services: the operator who runs the role script.')
param operatorIp string
@description('Object id of the Entra administrator of PostgreSQL, who creates the database roles for the identities (ops/pg_roles.sh).')
param entraAdminObjectId string
@description('User principal name of that administrator.')
param entraAdminUpn string
@description('owner/name of the GitHub repository whose workflows sign in as id-carecicd; empty skips the federation.')
param githubRepository string = ''
@description('Compute size of the PostgreSQL server; Burstable B1ms unless the region has no capacity for it.')
param postgresSku string = 'Standard_B1ms'
@description('Region of the PostgreSQL server, which may differ from the group when the group region has no Burstable capacity.')
param postgresLocation string = location
@description('First day of the month the budget starts.')
param budgetStartDate string = utcNow('yyyy-MM-01')

var suffix = 'careintel-prod-swc'
var tags = { workload: 'careintel', env: 'prod', owner: 'portfolio', managedBy: 'bicep', repo: 'azure-care-intelligence-platform' }
var identityNames = ['id-careaml', 'id-careapi', 'id-carecicd']
var federation = { 'github-main': 'ref:refs/heads/main', 'github-pull-request': 'pull_request', 'github-production': 'environment:production' }

resource identities 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = [for name in identityNames: {
  name: name
  location: location
  tags: tags
}]

@batchSize(1)
resource federated 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2024-11-30' = [for item in items(empty(githubRepository) ? {} : federation): {
  parent: identities[2]
  name: item.key
  properties: { issuer: 'https://token.actions.githubusercontent.com', subject: 'repo:${githubRepository}:${item.value}', audiences: ['api://AzureADTokenExchange'] }
}]

resource assignPipelineIdentity 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(identities[0].id, identities[2].id, 'f1a07417-d97a-45cb-824c-7a7467783830')
  scope: identities[0]
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'f1a07417-d97a-45cb-824c-7a7467783830'), principalId: identities[2].properties.principalId, principalType: 'ServicePrincipal' }
}

module workspace 'modules/workspace.bicep' = {
  name: 'workspace'
  params: {
    location: location, tags: tags, suffix: suffix, logAnalyticsWorkspaceId: landingZone.logAnalyticsWorkspaceId
    registryId: resourceId(landingZone.sharedResourceGroupName, 'Microsoft.ContainerRegistry/registries', landingZone.registryName)
    amlIdentityId: identities[0].id, amlPrincipalId: identities[0].properties.principalId
    cicdPrincipalId: identities[2].properties.principalId, operatorObjectId: entraAdminObjectId
  }
}

module data 'modules/data.bicep' = {
  name: 'data'
  params: {
    location: postgresLocation, tags: tags, suffix: suffix, logAnalyticsWorkspaceId: landingZone.logAnalyticsWorkspaceId
    operatorIp: operatorIp, entraAdminObjectId: entraAdminObjectId, entraAdminUpn: entraAdminUpn, postgresSku: postgresSku
  }
}

module sharedAccess 'modules/shared-access.bicep' = {
  name: 'shared-access'
  scope: resourceGroup(landingZone.sharedResourceGroupName)
  params: {
    registryName: landingZone.registryName
    pullPrincipalIds: [identities[0].properties.principalId, identities[1].properties.principalId, workspace.outputs.workspacePrincipalId]
  }
}

module apps 'modules/apps.bicep' = {
  name: 'apps'
  params: {
    location: location, tags: tags, suffix: suffix, logAnalyticsWorkspaceId: landingZone.logAnalyticsWorkspaceId
    actionGroupId: landingZone.actionGroupId, registryLoginServer: landingZone.registryLoginServer, apiImage: apiImage
    apiAppClientId: apiAppClientId, budgetStartDate: budgetStartDate, workspaceId: workspace.outputs.workspaceId
    apiIdentity: { id: identities[1].id, clientId: identities[1].properties.clientId, principalId: identities[1].properties.principalId }
    appSettings: {
      AZURE_SUBSCRIPTION_ID: subscription().subscriptionId, AZURE_RESOURCE_GROUP: resourceGroup().name, AML_WORKSPACE: workspace.outputs.workspaceName
      POSTGRES_HOST: data.outputs.postgresHost, POSTGRES_DATABASE: data.outputs.databaseName, ENTRA_TENANT_ID: tenant().tenantId
      API_AUDIENCE: 'api://${apiAppClientId}', MODEL_NAME: 'readmission-risk', ONLINE_ENDPOINT: 'ep-readmission-risk', BATCH_ENDPOINT: 'bep-cohort-scoring'
      POSTGRES_USER: 'id-careapi', REQUIRE_AUTH: 'true'
    }
  }
}

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = landingZone.registryLoginServer
output workspaceName string = workspace.outputs.workspaceName
output mlflowTrackingUri string = workspace.outputs.mlflowTrackingUri
output storageAccountName string = workspace.outputs.storageAccountName
output postgresHost string = data.outputs.postgresHost
output apiUrl string = apps.outputs.apiUrl
output amlIdentityClientId string = identities[0].properties.clientId
output cicdClientId string = identities[2].properties.clientId
