param location string
param tags object
param suffix string
param logAnalyticsWorkspaceId string
param operatorIp string
param entraAdminObjectId string
param entraAdminUpn string
param postgresSku string

var databaseName = 'care'

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' = {
  name: 'psql-${suffix}'
  location: location
  tags: tags
  sku: { name: postgresSku, tier: 'Burstable' }
  properties: {
    version: '17', storage: { storageSizeGB: 32, autoGrow: 'Disabled' }, backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }, network: { publicNetworkAccess: 'Enabled' }
    authConfig: { activeDirectoryAuth: 'Enabled', passwordAuth: 'Disabled', tenantId: tenant().tenantId }
  }
}

resource administrator 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2025-08-01' = {
  parent: postgres
  name: entraAdminObjectId
  properties: { principalType: 'User', principalName: entraAdminUpn, tenantId: tenant().tenantId }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-08-01' = {
  parent: postgres
  name: databaseName
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [administrator]
}

resource extensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: { value: 'VECTOR', source: 'user-override' }
  dependsOn: [database]
}

resource azureServices 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2025-08-01' = {
  parent: postgres
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
  dependsOn: [extensions]
}

resource operator 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2025-08-01' = {
  parent: postgres
  name: 'operator'
  properties: { startIpAddress: operatorIp, endIpAddress: operatorIp }
  dependsOn: [azureServices]
}

resource postgresDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-shared-workspace'
  scope: postgres
  properties: { workspaceId: logAnalyticsWorkspaceId, logs: [{ categoryGroup: 'allLogs', enabled: true }], metrics: [{ category: 'AllMetrics', enabled: true }] }
}

@description('Fully qualified host name of the server.')
output postgresHost string = postgres.properties.fullyQualifiedDomainName
@description('Name of the application database.')
output databaseName string = databaseName
