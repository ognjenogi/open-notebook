import { useId, useMemo, useState } from 'react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useModels } from '@/lib/hooks/use-models'
import { useCredentials } from '@/lib/hooks/use-credentials'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useTranslation } from '@/lib/hooks/use-translation'

interface ModelSelectorProps {
  id?: string
  name?: string
  label?: string
  modelType: 'language' | 'embedding' | 'speech_to_text' | 'text_to_speech'
  value: string
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
}

export function ModelSelector({
  id,
  name,
  label,
  modelType,
  value,
  onChange,
  placeholder,
  disabled = false
}: ModelSelectorProps) {
  const { t } = useTranslation()
  const [search, setSearch] = useState('')
  const [selectedCredential, setSelectedCredential] = useState('all')
  const { data: models, isLoading: modelsLoading } = useModels()
  const { data: credentials, isLoading: credentialsLoading } = useCredentials()
  const isLoading = modelsLoading || credentialsLoading
  const derivedId = useId()
  const selectId = id || derivedId

  const credMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const c of credentials || []) {
      map.set(c.id, c.name)
    }
    return map
  }, [credentials])

  // Filter models by type
  const typeModels = useMemo(() => {
    return models?.filter(model => model.type === modelType) || []
  }, [models, modelType])

  // Filter by search and credential
  const filteredModels = useMemo(() => {
    return typeModels.filter((model) => {
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
  }, [typeModels, search, selectedCredential, credMap])

  // Ensure currently selected model is visible in the select even if filtered out
  const displayModels = useMemo(() => {
    if (value && !filteredModels.some(m => m.id === value)) {
      const current = typeModels.find(m => m.id === value)
      if (current) {
        return [current, ...filteredModels]
      }
    }
    return filteredModels
  }, [filteredModels, value, typeModels])

  return (
    <div className="space-y-2">
      {label && <Label htmlFor={selectId}>{label}</Label>}
      <div className="flex gap-2">
        <Input
          placeholder={t('models.searchModels') || 'Search models...'}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 text-xs flex-1"
          disabled={disabled || isLoading}
        />
        <Select
          value={selectedCredential}
          onValueChange={setSelectedCredential}
          disabled={disabled || isLoading}
        >
          <SelectTrigger className="h-8 text-xs w-[130px] shrink-0">
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
      <Select name={name} value={value} onValueChange={onChange} disabled={disabled || isLoading}>
        <SelectTrigger id={selectId}>
          <SelectValue placeholder={placeholder || t('settings.embeddingOptionPlaceholder')} />
        </SelectTrigger>
        <SelectContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-2">
              <LoadingSpinner size="sm" />
            </div>
          ) : displayModels.length === 0 ? (
            <div className="text-sm text-muted-foreground py-2 px-2 text-center">
              {t('common.noResults') || 'No models found'}
            </div>
          ) : (
            displayModels.map((model) => {
              const credName = model.credential ? credMap.get(model.credential) : model.provider
              const optionLabel = credName ? `${credName} · ${model.name}` : model.name
              return (
                <SelectItem key={model.id} value={model.id}>
                  <div className="flex items-center justify-between w-full gap-2">
                    <span className="truncate">{optionLabel}</span>
                    {credName && (
                      <Badge variant="outline" className="text-[10px] font-normal px-1.5 py-0 shrink-0">
                        {credName}
                      </Badge>
                    )}
                  </div>
                </SelectItem>
              )
            })
          )}
        </SelectContent>
      </Select>
    </div>
  )
}
