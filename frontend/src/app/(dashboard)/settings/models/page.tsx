'use client'

import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AppShell } from '@/components/layout/AppShell'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { Key, ShieldAlert, AlertCircle } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useModels, useModelDefaults, MODEL_QUERY_KEYS } from '@/lib/hooks/use-models'
import {
  useCredentials,
  useCredentialStatus,
  useEnvStatus,
  CREDENTIAL_QUERY_KEYS,
} from '@/lib/hooks/use-credentials'
import { useProviders } from '@/lib/hooks/use-providers'
import { Credential } from '@/lib/api/credentials'
import {
  DefaultModelSelectors,
  MigrationBanner,
  ProviderSection,
} from '@/components/settings'
import { ModelFilterBar } from '@/components/common/ModelFilterBar'
import {
  computeModelCredentialCounts,
  filterModelsByCredentialAndSearch,
} from '@/lib/utils/model-filter'

export default function ApiKeysPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [searchQuery, setSearchQuery] = useState('')
  const [credentialFilter, setCredentialFilter] = useState('all')

  // Data
  const { data: credentials, isLoading: credentialsLoading } = useCredentials()
  const { data: models, isLoading: modelsLoading } = useModels()
  const { data: defaults, isLoading: defaultsLoading } = useModelDefaults()
  const { data: credentialStatus } = useCredentialStatus()
  const { data: envStatus } = useEnvStatus()
  const {
    data: providers,
    isLoading: providersLoading,
    isError: providersError,
  } = useProviders()

  const encryptionReady = credentialStatus?.encryption_configured ?? true

  const openRouterCred = useMemo(() => {
    return credentials?.find(
      (c) => c.provider === 'openrouter' || c.name.toLowerCase().includes('openrouter')
    )
  }, [credentials])

  const credMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const c of credentials || []) {
      map.set(c.id, c.name)
    }
    return map
  }, [credentials])

  const { totalCount, countsByCredId } = useMemo(() => {
    return computeModelCredentialCounts(models, credentials)
  }, [models, credentials])

  // Filter models by search query and credential
  const filteredModels = useMemo(() => {
    return filterModelsByCredentialAndSearch(
      models,
      searchQuery,
      credentialFilter,
      credMap,
      openRouterCred?.id
    )
  }, [models, searchQuery, credentialFilter, credMap, openRouterCred?.id])

  // Group credentials by provider
  const credentialsByProvider = useMemo(() => {
    const grouped: Record<string, Credential[]> = {}
    for (const provider of providers ?? []) {
      grouped[provider.name] = []
    }
    if (credentials) {
      for (const cred of credentials) {
        if (credentialFilter !== 'all' && cred.id !== credentialFilter) {
          continue
        }
        if (!grouped[cred.provider]) grouped[cred.provider] = []
        grouped[cred.provider].push(cred)
      }
    }
    return grouped
  }, [credentials, providers, credentialFilter])

  // Providers needing migration
  const providersToMigrate = useMemo(() => {
    if (!envStatus || !credentialStatus) return []
    const result: string[] = []
    for (const provider in envStatus) {
      if (envStatus[provider] && credentialStatus.source[provider] === 'environment') {
        result.push(provider)
      }
    }
    return result
  }, [envStatus, credentialStatus])

  // Sort: configured providers first (the backend registry owns the base order)
  const sortedProviders = useMemo(() => {
    return [...(providers ?? [])].sort((a, b) => {
      const aHas = (credentialsByProvider[a.name]?.length || 0) > 0 ? 1 : 0
      const bHas = (credentialsByProvider[b.name]?.length || 0) > 0 ? 1 : 0
      return bHas - aHas
    })
  }, [providers, credentialsByProvider])

  const visibleProviders = useMemo(() => {
    if (credentialFilter === 'all' && !searchQuery.trim()) {
      return sortedProviders
    }
    return sortedProviders.filter((provider) => {
      const creds = credentialsByProvider[provider.name] || []
      const hasCreds = creds.length > 0
      const hasMatchingModels = filteredModels.some((m) => {
        let mCredId = m.credential
        if (!mCredId && m.provider === 'openrouter' && openRouterCred) {
          mCredId = openRouterCred.id
        }
        return creds.some((c) => c.id === mCredId) || (m.provider === provider.name && !mCredId)
      })
      if (credentialFilter !== 'all') {
        return hasCreds && (hasMatchingModels || filteredModels.length === 0)
      }
      return hasMatchingModels || hasCreds
    })
  }, [sortedProviders, credentialsByProvider, filteredModels, credentialFilter, searchQuery, openRouterCred])

  const handleRefresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: MODEL_QUERY_KEYS.models }),
      queryClient.invalidateQueries({ queryKey: CREDENTIAL_QUERY_KEYS.all }),
      queryClient.invalidateQueries({ queryKey: ['providers'] }),
      queryClient.invalidateQueries({ queryKey: MODEL_QUERY_KEYS.defaults }),
    ])
  }

  const isLoading = credentialsLoading || modelsLoading || defaultsLoading || providersLoading

  if (isLoading) {
    return (
      <AppShell>
        <div className="flex items-center justify-center min-h-[60vh]">
          <LoadingSpinner size="lg" />
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-6">
          {/* Header */}
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight flex items-center gap-2">
              <Key className="h-5 w-5 text-muted-foreground" />
              {t('apiKeys.title')}
            </h1>
            <p className="text-muted-foreground mt-1">{t('apiKeys.description')}</p>
          </div>

          {/* Encryption warning */}
          {!encryptionReady && (
            <Alert className="border-destructive/30 bg-destructive-tint">
              <ShieldAlert className="h-4 w-4 text-destructive" />
              <AlertTitle className="text-destructive">{t('apiKeys.encryptionRequired')}</AlertTitle>
              <AlertDescription className="text-destructive">
                <code className="text-xs bg-destructive-tint px-1 py-0.5 rounded">
                  {t('apiKeys.encryptionRequiredDescription')}
                </code>
              </AlertDescription>
            </Alert>
          )}

          {/* Migration banner */}
          {encryptionReady && <MigrationBanner providersToMigrate={providersToMigrate} />}

          {/* Default Model Selectors */}
          {models && defaults && (
            <DefaultModelSelectors models={models} defaults={defaults} />
          )}

          {/* Filter Controls matching photo */}
          <ModelFilterBar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            selectedCredential={credentialFilter}
            onCredentialChange={setCredentialFilter}
            totalCount={totalCount}
            credentialCounts={countsByCredId}
            credentials={credentials || []}
            onRefresh={handleRefresh}
          />

          {/* Provider Cards */}
          {providersError ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>{t('apiKeys.providersLoadFailed')}</AlertTitle>
              <AlertDescription>{t('apiKeys.providersLoadFailedDescription')}</AlertDescription>
            </Alert>
          ) : (
            <div className="grid gap-4">
              {visibleProviders.map((provider) => (
                <ProviderSection
                  key={provider.name}
                  provider={provider}
                  credentials={credentialsByProvider[provider.name] || []}
                  models={filteredModels}
                  defaults={defaults || null}
                  allCredentials={credentials || []}
                  encryptionReady={encryptionReady}
                />
              ))}
            </div>
          )}

          {/* Help link */}
          <div className="border-t pt-4">
            <a
              href="https://github.com/lfnovo/open-notebook/blob/main/docs/5-CONFIGURATION/ai-providers.md"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-primary hover:underline"
            >
              {t('apiKeys.learnMore')}
            </a>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
