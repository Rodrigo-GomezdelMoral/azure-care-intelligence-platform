param location string
param tags object
param suffix string
param logAnalyticsWorkspaceId string
param actionGroupId string
param registryLoginServer string
param apiImage string
param apiAppClientId string
param budgetStartDate string
param workspaceId string
param insightsConnectionString string
param apiIdentity object
param appSettings object

var issuer = '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
var audience = 'api://${apiAppClientId}'
var env = concat(
  map(items(appSettings), item => { name: item.key, value: item.value }),
  [{ name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insightsConnectionString }, { name: 'AZURE_CLIENT_ID', value: apiIdentity.clientId }]
)

resource containerEnvironment 'Microsoft.App/managedEnvironments@2026-07-01' = {
  name: 'cae-${suffix}'
  location: location
  tags: tags
  properties: { appLogsConfiguration: { destination: 'azure-monitor' } }
}

resource api 'Microsoft.App/containerApps@2026-07-01' = {
  name: 'ca-careapi'
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${apiIdentity.id}': {} } }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single', ingress: { external: true, targetPort: 8000, transport: 'http' }
      registries: [{ server: registryLoginServer, identity: apiIdentity.id }]
    }
    template: {
      containers: [{ name: 'api', image: apiImage, resources: { cpu: json('0.5'), memory: '1Gi' }, env: env }]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

resource auth 'Microsoft.App/containerApps/authConfigs@2026-07-01' = {
  name: 'current'
  parent: api
  properties: {
    platform: { enabled: true }
    globalValidation: { unauthenticatedClientAction: 'Return401', excludedPaths: ['/healthz'] }
    identityProviders: { azureActiveDirectory: { enabled: true, registration: { openIdIssuer: issuer, clientId: apiAppClientId }, validation: { allowedAudiences: [audience, apiAppClientId] } } }
    httpSettings: { requireHttps: true }
  }
}

resource serverErrors 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-careapi-5xx'
  location: 'global'
  tags: tags
  properties: {
    severity: 2, enabled: true, scopes: [api.id], evaluationFrequency: 'PT5M', windowSize: 'PT15M', actions: [{ actionGroupId: actionGroupId }]
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{ criterionType: 'StaticThresholdCriterion', name: 'server-errors', metricNamespace: 'Microsoft.App/containerApps', metricName: 'Requests', operator: 'GreaterThan', threshold: 5, timeAggregation: 'Total', dimensions: [{ name: 'statusCodeCategory', operator: 'Include', values: ['5xx'] }] }]
    }
  }
}

resource pipelineFailures 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: 'alert-careintel-pipeline-failed'
  location: location
  tags: tags
  properties: {
    severity: 2, enabled: true, scopes: [workspaceId], evaluationFrequency: 'PT1H', windowSize: 'PT1H', actions: { actionGroups: [actionGroupId] }
    criteria: { allOf: [{ query: 'AmlRunStatusChangedEvent | where Status == "Failed"', timeAggregation: 'Count', operator: 'GreaterThan', threshold: 0 }] }
  }
}

resource budget 'Microsoft.Consumption/budgets@2026-06-01' = {
  name: 'budget-${suffix}'
  properties: {
    category: 'Cost', amount: 40, timeGrain: 'Monthly', timePeriod: { startDate: budgetStartDate }
    notifications: {
      'actual-80-percent': { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 80, thresholdType: 'Actual', contactEmails: [], contactGroups: [actionGroupId] }
      'forecast-100-percent': { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Forecasted', contactEmails: [], contactGroups: [actionGroupId] }
    }
  }
}

@description('Public URL of the API.')
output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
