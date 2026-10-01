'use client'

import { useState, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Search, RefreshCw, Sparkles, Check, ChevronsUpDown, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useModels, useModelDefaults, MODEL_QUERY_KEYS } from '@/lib/hooks/use-models'
import { useCredentials, CREDENTIAL_QUERY_KEYS } from '@/lib/hooks/use-credentials'
import { useTranslation } from '@/lib/hooks/use-translation'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Model } from '@/lib/types/models'
import {
  computeModelCredentialCounts,
  filterModelsByCredentialAndSearch,
} from '@/lib/utils/model-filter'

export interface ModelPickerPopoverProps {
  value?: string
  onChange: (value?: string) => void
  modelType?: 'language' | 'embedding' | 'speech_to_text' | 'text_to_speech'
  models?: Model[]
  placeholder?: string
  disabled?: boolean
  allowNone?: boolean
  noneLabel?: string
  defaultOption?: {
    label: string
    modelId?: string
  }
  triggerIcon?: React.ReactNode
  triggerLabel?: string
  className?: string
  align?: 'start' | 'center' | 'end'
  size?: 'sm' | 'default'
}

export function ModelPickerPopover({
  value,
  onChange,
  modelType,
  models: propModels,
  placeholder,
  disabled = false,
  allowNone = false,
  noneLabel,
  defaultOption,
  triggerIcon,
  triggerLabel,
  className,
  align = 'start',
  size = 'default',
}: ModelPickerPopoverProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [selectedCredential, setSelectedCredential] = useState('all')
  const [isRefreshing, setIsRefreshing] = useState(false)

  const queryClient = useQueryClient()
  const { data: queriedModels, isLoading: modelsLoading } = useModels()
  const { data: credentials, isLoading: credentialsLoading } = useCredentials()
  const { data: defaults } = useModelDefaults()

  const allModels = propModels || queriedModels || []
  const isLoading = (modelsLoading && !propModels) || credentialsLoading

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

  // Filter models by type if modelType is provided
  const typeModels = useMemo(() => {
    if (!modelType) return allModels
    return allModels.filter((m) => m.type === modelType)
  }, [allModels, modelType])

  // Compute counts for the pill buttons
  const { totalCount, countsByCredId } = useMemo(() => {
    return computeModelCredentialCounts(typeModels, credentials)
  }, [typeModels, credentials])

  // Sort credentials list: Open Code Go first, then Z.AI, then OpenRouter, then others
  const sortedCredentials = useMemo(() => {
    const list = credentials || []
    return [...list].sort((a, b) => {
      const aName = a.name.toLowerCase()
      const bName = b.name.toLowerCase()
      const aIsOpenCode = aName.includes('open code') || a.provider === 'opencode'
      const bIsOpenCode = bName.includes('open code') || b.provider === 'opencode'
      if (aIsOpenCode && !bIsOpenCode) return -1
      if (!aIsOpenCode && bIsOpenCode) return 1

      const aIsZai = aName.includes('z.ai') || aName.includes('zai')
      const bIsZai = bName.includes('z.ai') || bName.includes('zai')
      if (aIsZai && !bIsZai) return -1
      if (!aIsZai && bIsZai) return 1

      const aIsOpenRouter = aName.includes('openrouter') || a.provider === 'openrouter'
      const bIsOpenRouter = bName.includes('openrouter') || b.provider === 'openrouter'
      if (aIsOpenRouter && !bIsOpenRouter) return -1
      if (!aIsOpenRouter && bIsOpenRouter) return 1

      return a.name.localeCompare(b.name)
    })
  }, [credentials])

  // Filter models by search and selected credential
  const filteredModels = useMemo(() => {
    return filterModelsByCredentialAndSearch(
      typeModels,
      search,
      selectedCredential,
      credMap,
      openRouterCred?.id
    ).sort((a, b) => {
      const credA = a.credential ? credMap.get(a.credential) || a.provider : a.provider
      const credB = b.credential ? credMap.get(b.credential) || b.provider : b.provider
      const labelA = `${credA} · ${a.name}`
      const labelB = `${credB} · ${b.name}`
      return labelA.localeCompare(labelB)
    })
  }, [typeModels, search, selectedCredential, credMap, openRouterCred?.id])

  // Handle refresh action
  const handleRefresh = async () => {
    setIsRefreshing(true)
    try {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: MODEL_QUERY_KEYS.models }),
        queryClient.invalidateQueries({ queryKey: CREDENTIAL_QUERY_KEYS.all }),
        queryClient.invalidateQueries({ queryKey: ['providers'] }),
        queryClient.invalidateQueries({ queryKey: MODEL_QUERY_KEYS.defaults }),
      ])
    } finally {
      setTimeout(() => setIsRefreshing(false), 500)
    }
  }

  // Determine current display label for trigger
  const displayLabel = useMemo(() => {
    if (triggerLabel) return triggerLabel
    if (value) {
      const m = allModels.find((model) => model.id === value)
      if (m) {
        let credId = m.credential
        if (!credId && m.provider === 'openrouter' && openRouterCred) {
          credId = openRouterCred.id
        }
        const credName = credId ? credMap.get(credId) : m.provider
        return credName ? `${credName} · ${m.name}` : m.name
      }
      return value
    }
    if (defaultOption) {
      return defaultOption.label
    }
    return placeholder || t('models.selectModelPlaceholder') || 'Select model...'
  }, [triggerLabel, value, allModels, openRouterCred, credMap, defaultOption, placeholder, t])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size={size === 'sm' ? 'sm' : 'default'}
          disabled={disabled}
          className={cn(
            'flex items-center justify-between gap-2 font-normal text-left cursor-pointer truncate',
            size === 'sm' ? 'h-8 text-xs px-2.5' : 'h-9 text-xs sm:text-sm px-3',
            !value && !defaultOption && 'text-muted-foreground',
            className
          )}
          type="button"
        >
          <div className="flex items-center gap-2 truncate flex-1 min-w-0">
            {triggerIcon}
            <span className="truncate">{displayLabel}</span>
          </div>
          <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>

      <PopoverContent
        align={align}
        sideOffset={6}
        className="w-[340px] sm:w-[450px] p-3 space-y-3 bg-popover text-popover-foreground border border-border rounded-xl shadow-2xl z-50"
      >
        {/* Top row: Search input + Refresh button */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search models..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8.5 pr-3 h-8.5 text-xs bg-muted/20 border-muted-foreground/20 rounded-lg focus-visible:ring-1"
              autoFocus
            />
          </div>
          <Button
            variant="outline"
            size="icon"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="h-8.5 w-8.5 rounded-lg border-muted-foreground/20 bg-muted/20 hover:bg-muted/40 shrink-0 cursor-pointer"
            title="Refresh models"
            type="button"
          >
            <RefreshCw
              className={cn(
                'h-3.5 w-3.5 text-muted-foreground',
                isRefreshing && 'animate-spin'
              )}
            />
          </Button>
        </div>

        {/* Second row: Horizontal Pill Tabs matching photo */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
          <button
            type="button"
            onClick={() => setSelectedCredential('all')}
            className={cn(
              'px-2.5 py-1 rounded-md text-xs transition-all whitespace-nowrap cursor-pointer',
              selectedCredential === 'all'
                ? 'bg-white text-zinc-950 dark:bg-white dark:text-zinc-950 font-semibold shadow-sm'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/30 font-medium'
            )}
          >
            All ({totalCount})
          </button>

          {sortedCredentials.map((cred) => {
            const count = countsByCredId.get(cred.id) || 0
            const isOpenCode =
              cred.name.toLowerCase().includes('open code') ||
              cred.provider === 'opencode' ||
              (cred.base_url && cred.base_url.includes('opencode.ai'))
            const isSelected = selectedCredential === cred.id

            if (isOpenCode) {
              return (
                <button
                  key={cred.id}
                  type="button"
                  onClick={() => setSelectedCredential(cred.id)}
                  className={cn(
                    'px-2.5 py-1 rounded-md text-xs font-medium flex items-center gap-1 transition-all whitespace-nowrap cursor-pointer',
                    isSelected
                      ? 'bg-sky-500 text-white font-semibold shadow-sm'
                      : 'bg-sky-950/60 border border-sky-800/80 text-sky-400 hover:bg-sky-900/60'
                  )}
                >
                  <Sparkles className="h-3 w-3 shrink-0" />
                  <span>
                    {cred.name} ({count})
                  </span>
                </button>
              )
            }

            return (
              <button
                key={cred.id}
                type="button"
                onClick={() => setSelectedCredential(cred.id)}
                className={cn(
                  'px-2.5 py-1 rounded-md text-xs transition-all whitespace-nowrap cursor-pointer',
                  isSelected
                    ? 'bg-white text-zinc-950 dark:bg-white dark:text-zinc-950 font-semibold shadow-sm'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted/30 font-medium'
                )}
              >
                {cred.name} ({count})
              </button>
            )
          })}
        </div>

        {/* Third section: Scrollable list of models */}
        <div className="max-h-[260px] overflow-y-auto space-y-0.5 pr-1 divide-y divide-border/20">
          {/* Default Option (e.g. for chat override) */}
          {defaultOption && (
            <button
              type="button"
              onClick={() => {
                onChange(undefined)
                setOpen(false)
              }}
              className={cn(
                'w-full flex items-center justify-between px-2.5 py-1.5 rounded-md text-xs transition-colors cursor-pointer text-left',
                !value
                  ? 'bg-accent text-accent-foreground font-medium'
                  : 'hover:bg-muted/60 text-foreground'
              )}
            >
              <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
                <Check
                  className={cn(
                    'h-3.5 w-3.5 shrink-0',
                    !value ? 'opacity-100 text-primary' : 'opacity-0'
                  )}
                />
                <span className="truncate">{defaultOption.label}</span>
              </div>
              <span className="text-[10px] text-muted-foreground shrink-0 uppercase tracking-wider font-semibold">
                Default
              </span>
            </button>
          )}

          {/* None Option (e.g. for optional default slots) */}
          {allowNone && (
            <button
              type="button"
              onClick={() => {
                onChange('')
                setOpen(false)
              }}
              className={cn(
                'w-full flex items-center justify-between px-2.5 py-1.5 rounded-md text-xs transition-colors cursor-pointer text-left',
                !value
                  ? 'bg-accent text-accent-foreground font-medium'
                  : 'hover:bg-muted/60 text-muted-foreground'
              )}
            >
              <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
                <Check
                  className={cn(
                    'h-3.5 w-3.5 shrink-0',
                    !value ? 'opacity-100 text-primary' : 'opacity-0'
                  )}
                />
                <span className="truncate">{noneLabel || 'None (disabled)'}</span>
              </div>
            </button>
          )}

          {/* Loading state */}
          {isLoading ? (
            <div className="py-8 flex items-center justify-center">
              <LoadingSpinner size="sm" />
            </div>
          ) : filteredModels.length === 0 ? (
            <div className="py-8 text-center text-xs text-muted-foreground">
              {t('common.noResults') || 'No models found'}
            </div>
          ) : (
            filteredModels.map((model) => {
              const isSelected = value === model.id
              let credId = model.credential
              if (!credId && model.provider === 'openrouter' && openRouterCred) {
                credId = openRouterCred.id
              }
              const credName = credId ? credMap.get(credId) : model.provider
              const isOpenCode =
                credName?.toLowerCase().includes('open code') || model.provider === 'opencode'
              const isZai = credName?.toLowerCase().includes('z.ai') || credName?.toLowerCase().includes('zai')

              return (
                <button
                  key={model.id}
                  type="button"
                  onClick={() => {
                    onChange(model.id)
                    setOpen(false)
                  }}
                  className={cn(
                    'w-full flex items-center justify-between px-2.5 py-1.5 rounded-md text-xs transition-colors cursor-pointer text-left',
                    isSelected
                      ? 'bg-accent text-accent-foreground font-medium'
                      : 'hover:bg-muted/60 text-foreground'
                  )}
                >
                  <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
                    <Check
                      className={cn(
                        'h-3.5 w-3.5 shrink-0',
                        isSelected ? 'opacity-100 text-primary' : 'opacity-0'
                      )}
                    />
                    <span className="truncate">{model.name}</span>
                  </div>
                  {credName && (
                    <span
                      className={cn(
                        'text-[10px] px-1.5 py-0.5 rounded border shrink-0 font-normal',
                        isOpenCode
                          ? 'border-sky-800/80 bg-sky-950/40 text-sky-400'
                          : isZai
                          ? 'border-amber-800/80 bg-amber-950/40 text-amber-400'
                          : 'border-border/60 bg-muted/40 text-muted-foreground'
                      )}
                    >
                      {credName}
                    </span>
                  )}
                </button>
              )
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}
