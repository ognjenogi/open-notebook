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
import { Input } from '@/components/ui/input'
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

interface ModelSelectorProps {
  currentModel?: string
  onModelChange: (model?: string) => void
  disabled?: boolean
}

export function ModelSelector({ 
  currentModel, 
  onModelChange,
  disabled = false 
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

  const filteredLanguageModels = useMemo(() => {
    return languageModels.filter((model) => {
      const credName = model.credential ? credMap.get(model.credential) || '' : model.provider || ''
      const query = search.trim().toLowerCase()
      const matchesSearch =
        !query ||
        model.name.toLowerCase().includes(query) ||
        credName.toLowerCase().includes(query) ||
        model.provider.toLowerCase().includes(query)

      const matchesCredential =
        selectedCredential === 'all' || model.credential === selectedCredential

      return matchesSearch && matchesCredential
    })
  }, [languageModels, search, selectedCredential, credMap])

  const defaultModel = useMemo(() => {
    if (!defaults?.default_chat_model) return undefined
    return languageModels.find(model => model.id === defaults.default_chat_model)
  }, [defaults?.default_chat_model, languageModels])

  const currentModelName = useMemo(() => {
    if (currentModel) {
      const m = languageModels.find(model => model.id === currentModel)
      if (m) {
        const credName = m.credential ? credMap.get(m.credential) : m.provider
        return credName ? `${credName} · ${m.name}` : m.name
      }
      return currentModel
    }
    if (defaultModel) {
      const credName = defaultModel.credential ? credMap.get(defaultModel.credential) : defaultModel.provider
      return credName ? `${credName} · ${defaultModel.name}` : defaultModel.name
    }
    return t('common.default')
  }, [currentModel, languageModels, defaultModel, credMap, t])

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
          className="gap-2"
        >
          <Settings2 className="h-4 w-4" />
          <span className="text-xs">
            {currentModelName}
          </span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5" />
            {t('common.modelConfiguration')}
          </DialogTitle>
          <DialogDescription>
            {t('transformations.overrideModelDesc')}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div className="grid gap-1.5">
              <Label htmlFor="model-search" className="text-xs">
                {t('common.search') || 'Search'}
              </Label>
              <Input
                id="model-search"
                placeholder="Search models..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-9 text-xs"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="credential-filter" className="text-xs">
                {t('common.credential') || 'Credential'}
              </Label>
              <Select value={selectedCredential} onValueChange={setSelectedCredential}>
                <SelectTrigger id="credential-filter" className="h-9 text-xs">
                  <SelectValue placeholder="All Credentials" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Credentials</SelectItem>
                  {credentials?.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="model">{t('common.model')}</Label>
            <Select value={selectedModel} onValueChange={setSelectedModel}>
              <SelectTrigger id="model">
                <SelectValue placeholder={t('models.selectModelPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">
                  <div className="flex items-center justify-between w-full">
                    <span>
                      {defaultModel 
                        ? (() => {
                            const credName = defaultModel.credential ? credMap.get(defaultModel.credential) : defaultModel.provider
                            const label = credName ? `${credName} · ${defaultModel.name}` : defaultModel.name
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
                    const credName = model.credential ? credMap.get(model.credential) : model.provider
                    const optionLabel = credName ? `${credName} · ${model.name}` : model.name
                    return (
                      <SelectItem key={model.id} value={model.id}>
                        <div className="flex items-center justify-between w-full">
                          <span>{optionLabel}</span>
                        </div>
                      </SelectItem>
                    )
                  })
                )}
              </SelectContent>
            </Select>
          </div>
          {selectedModel && selectedModel !== 'default' && (
            <div className="rounded-lg bg-muted p-3">
              <p className="text-sm text-muted-foreground">
                {t('transformations.sessionUseReplacement', { name: languageModels.find(m => m.id === selectedModel)?.name || selectedModel })}
              </p>
            </div>
          )}
        </div>
        <DialogFooter className="flex justify-between">
          <Button variant="outline" onClick={handleReset}>
            {t('common.resetToDefault')}
          </Button>
          <Button onClick={handleSave}>
            {t('common.saveChanges')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
