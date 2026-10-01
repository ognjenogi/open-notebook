'use client'

import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Plus, Check, X } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { Credential } from '@/lib/api/credentials'
import { ProviderInfo } from '@/lib/api/providers'
import { Model, ModelDefaults } from '@/lib/types/models'
import {
  getTypeIcon,
  getTypeColor,
  getTypeLabel,
  TYPE_COLOR_INACTIVE,
} from '@/lib/providers'
import { CredentialFormDialog } from './CredentialFormDialog'
import { CredentialItem } from './CredentialItem'

interface ProviderSectionProps {
  provider: ProviderInfo
  credentials: Credential[]
  models: Model[]
  defaults: ModelDefaults | null
  allCredentials: Credential[]
  encryptionReady: boolean
}

export function ProviderSection({
  provider,
  credentials,
  models,
  defaults,
  allCredentials,
  encryptionReady,
}: ProviderSectionProps) {
  const { t } = useTranslation()
  const [addOpen, setAddOpen] = useState(false)
  const credList = allCredentials || []

  const displayName = provider.display_name || provider.name
  const modalities = provider.modalities.length > 0 ? provider.modalities : ['language']
  const hasCredentials = credentials.length > 0

  // Group models by credential ?? provider
  const providerModels = useMemo(() => {
    return models.filter(m => {
      const groupKey = m.credential ?? m.provider
      if (hasCredentials) {
        return credentials.some(c => c.id === groupKey || c.id === m.credential)
      }
      return groupKey === provider.name
    })
  }, [models, credentials, hasCredentials, provider.name])

  const activeTypes = new Set<string>(providerModels.map(m => m.type))

  // Section title & subtitle
  // When credentials exist, label with credential name; openai_compatible can be a secondary subtitle
  const credentialName = credentials.length === 1
    ? credentials[0].name
    : credentials.length > 1
      ? credentials.map(c => c.name).join(' · ')
      : null

  const headerTitle = credentialName || displayName
  const headerSubtitle = (hasCredentials && provider.name === 'openai_compatible')
    ? 'openai_compatible'
    : (credentials.length === 1 && credentialName !== displayName ? displayName : null)

  return (
    <Card className={hasCredentials ? 'border-l-2 border-l-fern' : undefined}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 flex-wrap">
            <div>
              <CardTitle className={`text-lg capitalize ${hasCredentials ? '' : 'text-muted-foreground'}`}>
                {headerTitle}
              </CardTitle>
              {headerSubtitle && (
                <p className="text-xs text-muted-foreground">{headerSubtitle}</p>
              )}
            </div>
            <div className="flex items-center gap-1">
              {modalities.map((type) => (
                <Badge
                  key={type}
                  variant="secondary"
                  className={`text-xs gap-1 ${activeTypes.has(type) ? getTypeColor(type) : TYPE_COLOR_INACTIVE}`}
                >
                  {getTypeIcon(type)}
                  <span className="hidden sm:inline">{getTypeLabel(type)}</span>
                </Badge>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {hasCredentials ? (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-fern">
                <Check className="h-3 w-3" />
                {t('apiKeys.configured')}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <X className="h-3 w-3" />
                {t('apiKeys.notConfigured')}
              </span>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {credentials.map(cred => {
          const credModels = models.filter(m => (m.credential ?? m.provider) === cred.id || m.credential === cred.id)
          return (
            <CredentialItem
              key={cred.id}
              credential={cred}
              models={credModels}
              defaults={defaults}
              allCredentials={credList}
            />
          )
        })}

        <Button
          variant="outline"
          size="sm"
          onClick={() => setAddOpen(true)}
          className="w-full gap-2"
          disabled={!encryptionReady}
        >
          <Plus className="h-4 w-4" />
          {t('apiKeys.addConfig')}
        </Button>
      </CardContent>

      {addOpen && (
        <CredentialFormDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          provider={provider.name}
        />
      )}
    </Card>
  )
}
