'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Settings2, Sparkles } from 'lucide-react'
import { useModelDefaults, useModels } from '@/lib/hooks/use-models'
import { useCredentials } from '@/lib/hooks/use-credentials'
import { useTranslation } from '@/lib/hooks/use-translation'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ModelFilterBar } from '@/components/common/ModelFilterBar'
import {
  computeModelCredentialCounts,
  filterModelsByCredentialAndSearch,
} from '@/lib/utils/model-filter'

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
  const [open, setOpen] = useState(false)
  const [selectedModel, setSelectedModel] = useState(currentModel || 'default')
  const [search, setSearch] = useState('')
  const [selectedCredential, setSelectedCredential] = useState('all')
  const { data: models, isLoading: modelsLoading } = useModels()
  const { data: credentials, isLoading: credentialsLoading } = useCredentials()
  const isLoading = modelsLoading || credentialsLoading
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

  useEffect(() => {
    setSelectedModel(currentModel || 'default')
  }, [currentModel])

  // Filter for language models only and sort by name
  const languageModels = useMemo(() => {
    if (!models) {
      return []
    }
    return [...models]
      .filter((model) => model.type === 'language')
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [models])

  const { totalCount, countsByCredId } = useMemo(() => {
    return computeModelCredentialCounts(languageModels, credentials)
  }, [languageModels, credentials])

  const filteredLanguageModels = useMemo(() => {
    return filterModelsByCredentialAndSearch(
      languageModels,
      search,
      selectedCredential,
      credMap,
      openRouterCred?.id
    )
  }, [languageModels, search, selectedCredential, credMap, openRouterCred?.id])

  const defaultModel = useMemo(() => {
    if (!defaults?.default_chat_model) return undefined
    return languageModels.find((model) => model.id === defaults.default_chat_model)
  }, [defaults?.default_chat_model, languageModels])

  const currentModelName = useMemo(() => {
    if (currentModel) {
      const m = languageModels.find((model) => model.id === currentModel)
      if (m) {
        let credId = m.credential
        if (!credId && m.provider === 'openrouter' && openRouterCred) {
          credId = openRouterCred.id
        }
        const credName = credId ? credMap.get(credId) : m.provider
        return credName ? `${credName} · ${m.name}` : m.name
      }
      return currentModel
    }
    if (defaultModel) {
      let credId = defaultModel.credential
      if (!credId && defaultModel.provider === 'openrouter' && openRouterCred) {
        credId = openRouterCred.id
      }
      const credName = credId ? credMap.get(credId) : defaultModel.provider
      return credName ? `${credName} · ${defaultModel.name}` : defaultModel.name
    }
    return t('common.default')
  }, [currentModel, languageModels, defaultModel, credMap, openRouterCred, t])

  const handleSave = () => {
    onModelChange(selectedModel === 'default' ? undefined : selectedModel)
    setOpen(false)
  }

  const handleReset = () => {
    setSelectedModel('default')
    setSearch('')
    setSelectedCredential('all')
    onModelChange(undefined)
    setOpen(false)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          className="gap-2 cursor-pointer"
        >
          <Settings2 className="h-4 w-4" />
          <span className="text-xs">{currentModelName}</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-sky-400" />
            {t('common.modelConfiguration')}
          </DialogTitle>
          <DialogDescription>
            {t('transformations.overrideModelDesc')}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-3">
          {/* Universal Model Filter Bar */}
          <ModelFilterBar
            searchQuery={search}
            onSearchChange={setSearch}
            selectedCredential={selectedCredential}
            onCredentialChange={setSelectedCredential}
            totalCount={totalCount}
            credentialCounts={countsByCredId}
            credentials={credentials || []}
            compact
          />

          <div className="grid gap-1.5">
            <Label htmlFor="model" className="text-xs">
              {t('common.model')}
            </Label>
            <Select value={selectedModel} onValueChange={setSelectedModel}>
              <SelectTrigger id="model">
                <SelectValue placeholder={t('models.selectModelPlaceholder')} />
              </SelectTrigger>
              <SelectContent className="max-h-[300px]">
                <SelectItem value="default">
                  <div className="flex items-center justify-between w-full">
                    <span>
                      {defaultModel
                        ? (() => {
                            let credId = defaultModel.credential
                            if (!credId && defaultModel.provider === 'openrouter' && openRouterCred) {
                              credId = openRouterCred.id
                            }
                            const credName = credId ? credMap.get(credId) : defaultModel.provider
                            const label = credName
                              ? `${credName} · ${defaultModel.name}`
                              : defaultModel.name
                            return `${t('common.default')} (${label})`
                          })()
                        : t('transformations.systemDefault')}
                    </span>
                  </div>
                </SelectItem>
                {isLoading ? (
                  <div className="flex items-center justify-center py-2">
                    <LoadingSpinner size="sm" />
                  </div>
                ) : filteredLanguageModels.length === 0 ? (
                  <div className="text-sm text-muted-foreground py-2 px-2 text-center">
                    {t('common.noResults') || 'No models found'}
                  </div>
                ) : (
                  filteredLanguageModels.map((model) => {
                    let credId = model.credential
                    if (!credId && model.provider === 'openrouter' && openRouterCred) {
                      credId = openRouterCred.id
                    }
                    const credName = credId ? credMap.get(credId) : model.provider
                    const optionLabel = credName ? `${credName} · ${model.name}` : model.name
                    return (
                      <SelectItem key={model.id} value={model.id}>
                        <div className="flex items-center justify-between w-full gap-2">
                          <span className="truncate">{optionLabel}</span>
                        </div>
                      </SelectItem>
                    )
                  })
                )}
              </SelectContent>
            </Select>
          </div>

          {selectedModel && selectedModel !== 'default' && (
            <div className="rounded-lg bg-muted p-2.5">
              <p className="text-xs text-muted-foreground">
                {t('transformations.sessionUseReplacement', {
                  name: languageModels.find((m) => m.id === selectedModel)?.name || selectedModel,
                })}
              </p>
            </div>
          )}
        </div>

        <DialogFooter className="flex justify-between">
          <Button variant="outline" onClick={handleReset}>
            {t('common.resetToDefault')}
          </Button>
          <Button onClick={handleSave}>{t('common.saveChanges')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
