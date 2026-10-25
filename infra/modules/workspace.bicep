param location string
param tags object
param suffix string
param logAnalyticsWorkspaceId string
param registryId string
param amlIdentityId string
param amlPrincipalId string
param cicdPrincipalId string
param operatorObjectId string

var dataScientist = 'f6c7c914-8db3-469d-8ca1-694a8f32e121'
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var diagnostics = { workspaceId: logAnalyticsWorkspaceId, logs: [{ categoryGroup: 'allLogs', enabled: true }] }
var workspaceGrants = [{ principalId: amlPrincipalId, type: 'ServicePrincipal' }, { principalId: cicdPrincipalId, type: 'ServicePrincipal' }]
// The workspace grants its own system identity Storage Blob Data Contributor, Key Vault Administrator and Azure AI Administrator on the registry at creation; declaring them again fails with RoleAssignmentExists.
var storageGrants = [
  { principalId: amlPrincipalId, type: 'ServicePrincipal', role: storageBlobDataContributor }, { principalId: cicdPrincipalId, type: 'ServicePrincipal', role: storageBlobDataContributor }
  { principalId: operatorObjectId, type: 'User', role: storageBlobDataContributor }
  // Parallel Run Step, which runs every batch deployment, keeps its state in tables and queues of the same account.
  { principalId: amlPrincipalId, type: 'ServicePrincipal', role: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3' }, { principalId: amlPrincipalId, type: 'ServicePrincipal', role: '974c5e8b-45b9-4653-ba55-5f855dd0fb88' }
]

resource storage 'Microsoft.Storage/storageAccounts@2026-06-01' = {
  #disable-next-line BCP334 // the suffix is always the environment's long name, never under three characters
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
  identity: { type: 'SystemAssigned,UserAssigned', userAssignedIdentities: { '${amlIdentityId}': {} } }
  properties: {
    friendlyName: 'Patient Risk & Adherence Intelligence', storageAccount: storage.id, keyVault: vault.id, applicationInsights: insights.id, containerRegistry: registryId
    publicNetworkAccess: 'Enabled', systemDatastoresAuthMode: 'identity', hbiWorkspace: false, v1LegacyMode: false
  }
}

resource cluster 'Microsoft.MachineLearningServices/workspaces/computes@2026-05-01' = {
  parent: workspace
  name: 'cpu-cluster'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${amlIdentityId}': {} } }
  properties: {
    computeType: 'AmlCompute'
    properties: { vmSize: 'Standard_DS2_v2', vmPriority: 'Dedicated', osType: 'Linux', scaleSettings: { minNodeCount: 0, maxNodeCount: 3, nodeIdleTimeBeforeScaleDown: 'PT5M' } }
  }
}

resource workspaceAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in workspaceGrants: {
  name: guid(workspace.id, grant.principalId, dataScientist)
  scope: workspace
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', dataScientist), principalId: grant.principalId, principalType: grant.type }
}]

resource storageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in storageGrants: {
  name: guid(storage.id, grant.principalId, grant.role)
  scope: storage
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', grant.role), principalId: grant.principalId, principalType: grant.type }
}]

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2026-06-01' existing = { parent: storage, name: 'default' }
resource workspaceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = { name: 'to-shared-workspace', scope: workspace, properties: diagnostics }
resource vaultDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = { name: 'to-shared-workspace', scope: vault, properties: diagnostics }
resource blobDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = { name: 'to-shared-workspace', scope: blobs, properties: diagnostics }

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
