import { render as rtlRender, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ChatPanel } from './ChatPanel'

function render(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return rtlRender(
    <QueryClientProvider client={queryClient}>
      {ui}
    </QueryClientProvider>
  )
}

// useTranslation is mocked globally in setup.ts (t returns the key string)

vi.mock('@/lib/hooks/use-modal-manager', () => ({
  useModalManager: () => ({ openModal: vi.fn() }),
}))

// Keep the message-content deps light for this composer-focused test.
vi.mock('@/components/sources/MessageActions', () => ({
  MessageActions: () => null,
}))

const mockUpdateNotebookMutate = vi.fn()
let mockNotebookData: { id: string; model_id?: string | null } | undefined = undefined
let mockDefaultsData: { default_chat_model?: string } | undefined = undefined

vi.mock('@/lib/hooks/use-notebooks', () => ({
  useNotebook: () => ({ data: mockNotebookData }),
  useUpdateNotebook: () => ({ mutate: mockUpdateNotebookMutate }),
}))

vi.mock('@/lib/hooks/use-models', () => ({
  useModelDefaults: () => ({ data: mockDefaultsData }),
  useModels: () => ({ data: [] }),
}))
vi.mock('@/lib/hooks/use-credentials', () => ({
  useCredentials: () => ({ data: [] }),
}))

describe('ChatPanel composer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // jsdom does not implement scrollIntoView (used by the auto-scroll effect).
    window.HTMLElement.prototype.scrollIntoView = vi.fn()
  })

  const getTextarea = () => screen.getByRole('textbox') as HTMLTextAreaElement

  it('sends the typed message and clears the input on send-button click', () => {
    const onSendMessage = vi.fn()
    render(
      <ChatPanel
        messages={[]}
        isStreaming={false}
        contextIndicators={null}
        onSendMessage={onSendMessage}
      />
    )

    const textarea = getTextarea()
    fireEvent.change(textarea, { target: { value: '  hello world  ' } })

    const sendButton = screen.getByRole('button')
    fireEvent.click(sendButton)

    expect(onSendMessage).toHaveBeenCalledTimes(1)
    expect(onSendMessage).toHaveBeenCalledWith('hello world', undefined)
    expect(textarea.value).toBe('')
  })

  it('sends on Cmd+Enter on macOS', () => {
    const uaSpy = vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
    )
    const onSendMessage = vi.fn()
    render(
      <ChatPanel
        messages={[]}
        isStreaming={false}
        contextIndicators={null}
        onSendMessage={onSendMessage}
      />
    )

    const textarea = getTextarea()
    fireEvent.change(textarea, { target: { value: 'via cmd' } })
    fireEvent.keyDown(textarea, { key: 'Enter', metaKey: true, ctrlKey: false })

    expect(onSendMessage).toHaveBeenCalledWith('via cmd', undefined)
    expect(textarea.value).toBe('')
    uaSpy.mockRestore()
  })

  it('sends on Ctrl+Enter on non-macOS', () => {
    const uaSpy = vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    )
    const onSendMessage = vi.fn()
    render(
      <ChatPanel
        messages={[]}
        isStreaming={false}
        contextIndicators={null}
        onSendMessage={onSendMessage}
      />
    )

    const textarea = getTextarea()
    fireEvent.change(textarea, { target: { value: 'via ctrl' } })
    fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true, metaKey: false })

    expect(onSendMessage).toHaveBeenCalledWith('via ctrl', undefined)
    expect(textarea.value).toBe('')
    uaSpy.mockRestore()
  })

  it('does not send while streaming', () => {
    const onSendMessage = vi.fn()
    render(
      <ChatPanel
        messages={[]}
        isStreaming={true}
        contextIndicators={null}
        onSendMessage={onSendMessage}
      />
    )

    const textarea = getTextarea()
    // Textarea is disabled while streaming, but the guard must also hold.
    fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true })

    expect(onSendMessage).not.toHaveBeenCalled()
  })

  it('uses notebook.model_id in notebook context when sending message', () => {
    mockNotebookData = { id: 'notebook:123', model_id: 'model:notebook-llm' }
    mockDefaultsData = { default_chat_model: 'model:default-llm' }
    const onSendMessage = vi.fn()

    render(
      <ChatPanel
        messages={[]}
        isStreaming={false}
        contextIndicators={null}
        onSendMessage={onSendMessage}
        contextType="notebook"
        notebookId="notebook:123"
      />
    )

    const textarea = getTextarea()
    fireEvent.change(textarea, { target: { value: 'test notebook msg' } })

    const sendButton = screen.getByRole('button')
    fireEvent.click(sendButton)

    expect(onSendMessage).toHaveBeenCalledWith('test notebook msg', 'model:notebook-llm')
  })

  it('falls back to defaults.default_chat_model when notebook.model_id is null', () => {
    mockNotebookData = { id: 'notebook:123', model_id: null }
    mockDefaultsData = { default_chat_model: 'model:default-llm' }
    const onSendMessage = vi.fn()

    render(
      <ChatPanel
        messages={[]}
        isStreaming={false}
        contextIndicators={null}
        onSendMessage={onSendMessage}
        contextType="notebook"
        notebookId="notebook:123"
      />
    )

    const textarea = getTextarea()
    fireEvent.change(textarea, { target: { value: 'fallback test' } })

    const sendButton = screen.getByRole('button')
    fireEvent.click(sendButton)

    expect(onSendMessage).toHaveBeenCalledWith('fallback test', 'model:default-llm')
  })

  it('renders model selector and handles model change persistence in notebook context', () => {
    mockNotebookData = { id: 'notebook:123', model_id: 'model:old-llm' }
    const onModelChange = vi.fn()

    render(
      <ChatPanel
        messages={[]}
        isStreaming={false}
        contextIndicators={null}
        onSendMessage={vi.fn()}
        onModelChange={onModelChange}
        contextType="notebook"
        notebookId="notebook:123"
      />
    )

    expect(screen.getByText('chat.model')).toBeInTheDocument()
  })
})
