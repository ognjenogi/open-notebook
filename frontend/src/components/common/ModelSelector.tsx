import { useId, useMemo } from 'react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Label } from '@/components/ui/label'
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
  const filteredModels = models?.filter(model => model.type === modelType) || []
  return (
    <div className="space-y-2">
      {label && <Label htmlFor={selectId}>{label}</Label>}
      <Select name={name} value={value} onValueChange={onChange} disabled={disabled || isLoading}>
        <SelectTrigger id={selectId}>
          <SelectValue placeholder={placeholder || t('settings.embeddingOptionPlaceholder')} />
        </SelectTrigger>
        <SelectContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-2">
              <LoadingSpinner size="sm" />
            </div>
          ) : filteredModels.length === 0 ? (
            <div className="text-sm text-muted-foreground py-2 px-2">
              {t('common.noResults')}
            </div>
          ) : (
            filteredModels.map((model) => {
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
  )
}
