'use client'

import { AppSidebar } from './AppSidebar'
import { SetupBanner } from './SetupBanner'

interface AppShellProps {
  children: React.ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex h-[100dvh] min-h-[100dvh] w-full overflow-hidden flex-col md:flex-row">
      <AppSidebar />
      <main className="flex-1 flex flex-col min-h-0 overflow-hidden w-full pb-16 md:pb-0">
        <SetupBanner />
        {children}
      </main>
    </div>
  )
}
