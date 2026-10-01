'use client'

import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Search, RefreshCw, Sparkles } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { MODEL_QUERY_KEYS } from '@/lib/hooks/use-models'
import { CREDENTIAL_QUERY_KEYS, useCredentials } from '@/lib/hooks/use-credentials'

export interface ModelFilterBarProps {
  searchQuery: string
  onSearchChange: (value: string) => void
  selectedCredential: string
  onCredentialChange: (credId: string) => void
  totalCount?: number
  credentialCounts?: Map<string, number>
  credentials?: Array<{
    id: string
    name: string
    provider?: string
    base_url?: string | null
  }>
  onRefresh?: () => void | Promise<void>
  compact?: boolean
  className?: string
  placeholder?: string
}

export function ModelFilterBar({
  searchQuery,
  onSearchChange,
  selectedCredential,
  onCredentialChange,
  totalCount,
  credentialCounts,
  credentials: propCredentials,
  onRefresh,
  compact = false,
  className,
  placeholder = 'Search models...',
}: ModelFilterBarProps) {
  const queryClient = useQueryClient()
  const [isRefreshing, setIsRefreshing] = useState(false)
  const { data: queriedCredentials } = useCredentials()

  const credentialsList = propCredentials || queriedCredentials || []

  // Sort credentials to place Open Code Go first, then Z.AI, then OpenRouter, then others
  const sortedCredentials = useMemo(() => {
    return [...credentialsList].sort((a, b) => {
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
  }, [credentialsList])

  const handleRefresh = async () => {
    setIsRefreshing(true)
    try {
      if (onRefresh) {
        await onRefresh()
      } else {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: MODEL_QUERY_KEYS.models }),
          queryClient.invalidateQueries({ queryKey: CREDENTIAL_QUERY_KEYS.all }),
          queryClient.invalidateQueries({ queryKey: ['providers'] }),
          queryClient.invalidateQueries({ queryKey: MODEL_QUERY_KEYS.defaults }),
        ])
      }
    } finally {
      setTimeout(() => setIsRefreshing(false), 500)
    }
  }

  return (
    <div className={cn('space-y-2.5', className)}>
      {/* Top row: Search input + Refresh button */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search
            className={cn(
              'absolute left-3.5 top-1/2 -translate-y-1/2 text-muted-foreground',
              compact ? 'h-3.5 w-3.5' : 'h-4 w-4'
            )}
          />
          <Input
            placeholder={placeholder}
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className={cn(
              'pl-10 pr-4 bg-muted/20 border-muted-foreground/20 text-foreground focus-visible:ring-1 w-full',
              compact ? 'h-9 rounded-lg text-xs' : 'h-11 rounded-xl text-sm'
            )}
          />
        </div>
        <Button
          variant="outline"
          size="icon"
          onClick={handleRefresh}
          disabled={isRefreshing}
          className={cn(
            'border-muted-foreground/20 bg-muted/20 hover:bg-muted/40 shrink-0 cursor-pointer',
            compact ? 'h-9 w-9 rounded-lg' : 'h-11 w-11 rounded-xl'
          )}
          title="Refresh models"
          type="button"
        >
          <RefreshCw
            className={cn(
              'text-muted-foreground',
              compact ? 'h-3.5 w-3.5' : 'h-4 w-4',
              isRefreshing && 'animate-spin'
            )}
          />
        </Button>
      </div>

      {/* Second row: Horizontal Pill Tabs matching photo */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none">
        <button
          type="button"
          onClick={() => onCredentialChange('all')}
          className={cn(
            'transition-all whitespace-nowrap cursor-pointer',
            compact
              ? 'px-2.5 py-1 rounded-md text-xs'
              : 'px-3.5 py-1.5 rounded-lg text-xs md:text-sm',
            selectedCredential === 'all'
              ? 'bg-white text-zinc-950 dark:bg-white dark:text-zinc-950 font-semibold shadow-sm'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted/30 font-medium'
          )}
        >
          All{totalCount !== undefined ? ` (${totalCount})` : ''}
        </button>

        {sortedCredentials.map((cred) => {
          const count = credentialCounts?.get(cred.id)
          const isOpenCode =
            cred.name.toLowerCase().includes('open code') ||
            cred.provider === 'opencode' ||
            (cred.base_url && cred.base_url.includes('opencode.ai'))
          const isSelected = selectedCredential === cred.id
          const countLabel = count !== undefined ? ` (${count})` : ''

          if (isOpenCode) {
            return (
              <button
                key={cred.id}
                type="button"
                onClick={() => onCredentialChange(cred.id)}
                className={cn(
                  'font-medium flex items-center gap-1.5 transition-all whitespace-nowrap cursor-pointer',
                  compact
                    ? 'px-2.5 py-1 rounded-md text-xs'
                    : 'px-3.5 py-1.5 rounded-lg text-xs md:text-sm',
                  isSelected
                    ? 'bg-sky-500 text-white font-semibold shadow-sm border border-sky-400'
                    : 'bg-sky-950/60 border border-sky-800/80 text-sky-400 hover:bg-sky-900/60'
                )}
              >
                <Sparkles className={compact ? 'h-3 w-3 shrink-0' : 'h-3.5 w-3.5 shrink-0'} />
                <span>
                  {cred.name}
                  {countLabel}
                </span>
              </button>
            )
          }

          return (
            <button
              key={cred.id}
              type="button"
              onClick={() => onCredentialChange(cred.id)}
              className={cn(
                'transition-all whitespace-nowrap cursor-pointer',
                compact
                  ? 'px-2.5 py-1 rounded-md text-xs'
                  : 'px-3.5 py-1.5 rounded-lg text-xs md:text-sm',
                isSelected
                  ? 'bg-white text-zinc-950 dark:bg-white dark:text-zinc-950 font-semibold shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/30 font-medium'
              )}
            >
              {cred.name}
              {countLabel}
            </button>
          )
        })}
      </div>
    </div>
  )
}
