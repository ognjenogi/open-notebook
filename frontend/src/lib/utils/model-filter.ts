export interface FilterableModel {
  id?: string
  name: string
  credential?: string | null
  provider?: string
  type?: string
}

export interface FilterableCredential {
  id: string
  name: string
  provider?: string
  base_url?: string | null
}

/**
 * Computes total count and counts per credential ID for a list of models.
 * Correctly attributes legacy models (with null credential and provider 'openrouter')
 * to the OpenRouter credential.
 */
export function computeModelCredentialCounts<T extends FilterableModel>(
  models: T[] | undefined | null,
  credentials: FilterableCredential[] | undefined | null
): { totalCount: number; countsByCredId: Map<string, number> } {
  const countsByCredId = new Map<string, number>()
  const safeModels = models || []
  const safeCredentials = credentials || []

  const openRouterCred = safeCredentials.find(
    (c) => c.provider === 'openrouter' || c.name.toLowerCase().includes('openrouter')
  )

  for (const m of safeModels) {
    let credId = m.credential
    if (!credId && m.provider === 'openrouter' && openRouterCred) {
      credId = openRouterCred.id
    }
    if (credId) {
      countsByCredId.set(credId, (countsByCredId.get(credId) || 0) + 1)
    }
  }

  return {
    totalCount: safeModels.length,
    countsByCredId,
  }
}

/**
 * Filters a list of models by search query (matching name, credential name, or provider)
 * and by selected credential ID ('all' or specific credential ID).
 */
export function filterModelsByCredentialAndSearch<T extends FilterableModel>(
  models: T[] | undefined | null,
  searchQuery: string,
  selectedCredential: string,
  credMap: Map<string, string>,
  openRouterCredId?: string
): T[] {
  const safeModels = models || []
  const query = searchQuery.trim().toLowerCase()

  return safeModels.filter((model) => {
    let credId = model.credential
    if (!credId && model.provider === 'openrouter' && openRouterCredId) {
      credId = openRouterCredId
    }

    const credName = credId ? credMap.get(credId) || '' : model.provider || ''
    const matchesSearch =
      !query ||
      model.name.toLowerCase().includes(query) ||
      credName.toLowerCase().includes(query) ||
      (model.provider ? model.provider.toLowerCase().includes(query) : false)

    const matchesCredential =
      selectedCredential === 'all' || credId === selectedCredential

    return matchesSearch && matchesCredential
  })
}
