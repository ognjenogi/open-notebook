'use client'

import { useMemo } from 'react'
import { Settings2 } from 'lucide-react'
import { useModelDefaults, useModels } from '@/lib/hooks/use-models'
import { useCredentials } from '@/lib/hooks/use-credentials'
import { useTranslation } from '@/lib/hooks/use-translation'
import { ModelPickerPopover } from '@/components/common/ModelPickerPopover'

interface ModelSelectorProps {
  currentModel?: string
  onModelChange: (model?: string) => void
  disabled?: boolean
}

export function ModelSelector({
  currentModel,
  onModelChange,
  disabled = false,
}: ModelSelectorProps) {
  const { t } = useTranslation()
  const { data: models } = useModels()
  const { data: credentials } = useCredentials()
  const { data: defaults } = useModelDefaults()

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

  const defaultModel = useMemo(() => {
    if (!defaults?.default_chat_model || !models) return undefined
    return models.find((m) => m.id === defaults.default_chat_model)
  }, [defaults?.default_chat_model, models])

  const defaultOptionLabel = useMemo(() => {
    if (defaultModel) {
      let credId = defaultModel.credential
      if (!credId && defaultModel.provider === 'openrouter' && openRouterCred) {
        credId = openRouterCred.id
      }
      const credName = credId ? credMap.get(credId) : defaultModel.provider
      const label = credName ? `${credName} · ${defaultModel.name}` : defaultModel.name
      return `${t('common.default')} (${label})`
    }
    return t('transformations.systemDefault') || 'System Default'
  }, [defaultModel, openRouterCred, credMap, t])

  return (
    <div title={t('transformations.overrideModelDesc')} className="inline-flex">
      <ModelPickerPopover
        value={currentModel}
        onChange={(newModel) => onModelChange(newModel)}
        modelType="language"
        placeholder={t('common.model')}
        defaultOption={{
          label: defaultOptionLabel,
          modelId: defaults?.default_chat_model || undefined,
        }}
        triggerIcon={<Settings2 className="h-3.5 w-3.5 text-muted-foreground" />}
        disabled={disabled}
        size="sm"
        align="end"
        className="max-w-[280px]"
      />
      {currentModel && (
        <span className="sr-only">
          {t('transformations.sessionUseReplacement', {
            name: models?.find((m) => m.id === currentModel)?.name || currentModel,
          })}
        </span>
      )}
    </div>
  )
}
