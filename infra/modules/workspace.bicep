param location string
param tags object
param suffix string
param logAnalyticsWorkspaceId string
param registryId string
param amlPrincipalId string
param apiPrincipalId string
param cicdPrincipalId string
param operatorObjectId string

var dataScientist = 'f6c7c914-8db3-469d-8ca1-694a8f32e121'
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var diagnostics = { workspaceId: logAnalyticsWorkspaceId, logs: [{ categoryGroup: 'allLogs', enabled: true }] }
var workspaceGrants = [{ principalId: amlPrincipalId, type: 'ServicePrincipal' }, { principalId: apiPrincipalId, type: 'ServicePrincipal' }]
// The workspace grants its own system identity Storage Blob Data Contributor, Key Vault Administrator and Azure AI Administrator on the registry at creation; declaring them again fails with RoleAssignmentExists.
var storageGrants = [
  { principalId: amlPrincipalId, type: 'ServicePrincipal' }, { principalId: cicdPrincipalId, type: 'ServicePrincipal' }, { principalId: operatorObjectId, type: 'User' }
]

resource storage 'Microsoft.Storage/storageAccounts@2026-06-01' = {
  name: 'st${replace(suffix, '-', '')}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: { allowSharedKeyAccess: false, allowBlobPublicAccess: false, minimumTlsVersion: 'TLS1_2', supportsHttpsTrafficOnly: true }
}

resource vault 'Microsoft.KeyVault/vaults@2026-02-01' = {
  name: 'kv-${suffix}'
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId, sku: { family: 'A', name: 'standard' }, enableRbacAuthorization: true, enableSoftDelete: true, softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${suffix}'
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logAnalyticsWorkspaceId, IngestionMode: 'LogAnalytics' }
}

resource workspace 'Microsoft.MachineLearningServices/workspaces@2026-05-01' = {
  name: 'mlw-${suffix}'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    friendlyName: 'Patient Risk & Adherence Intelligence', storageAccount: storage.id, keyVault: vault.id, applicationInsights: insights.id, containerRegistry: registryId
    publicNetworkAccess: 'Enabled', systemDatastoresAuthMode: 'identity', hbiWorkspace: false, v1LegacyMode: false
  }
}

resource workspaceAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in workspaceGrants: {
  name: guid(workspace.id, grant.principalId, dataScientist)
  scope: workspace
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', dataScientist), principalId: grant.principalId, principalType: grant.type }
}]

resource storageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in storageGrants: {
  name: guid(storage.id, grant.principalId, storageBlobDataContributor)
  scope: storage
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor), principalId: grant.principalId, principalType: grant.type }
}]

resource workspaceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace'
  scope: workspace
  properties: diagnostics
}

resource vaultDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace'
  scope: vault
  properties: diagnostics
}

@description('Resource id of the workspace.')
output workspaceId string = workspace.id
@description('Name of the workspace.')
output workspaceName string = workspace.name
@description('System identity of the workspace, which builds images in the shared registry.')
output workspacePrincipalId string = workspace.identity.principalId
@description('MLflow tracking URI exposed by the workspace.')
output mlflowTrackingUri string = workspace.properties.mlFlowTrackingUri
@description('Storage account behind the default datastores.')
output storageAccountName string = storage.name
@description('Connection string of the Application Insights component the API and the endpoints report to.')
output insightsConnectionString string = insights.properties.ConnectionString
