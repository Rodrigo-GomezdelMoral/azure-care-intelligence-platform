param registryName string
param pullPrincipalIds string[]

var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var grants = map(pullPrincipalIds, id => { principalId: id, role: acrPull })

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = { name: registryName }

resource registryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for grant in grants: {
  name: guid(registry.id, grant.principalId, grant.role)
  scope: registry
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', grant.role), principalId: grant.principalId, principalType: 'ServicePrincipal' }
}]
