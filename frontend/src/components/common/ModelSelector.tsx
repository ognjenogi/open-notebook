'use client'

import { Label } from '@/components/ui/label'
import { ModelPickerPopover } from '@/components/common/ModelPickerPopover'

interface ModelSelectorProps {
  id?: string
  name?: string
  label?: string
  modelType: 'language' | 'embedding' | 'speech_to_text' | 'text_to_speech'
  value: string
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
  className?: string
}

export function ModelSelector({
  id,
  label,
  modelType,
  value,
  onChange,
  placeholder,
  disabled = false,
  className,
}: ModelSelectorProps) {
  return (
    <div className="space-y-1.5">
      {label && <Label htmlFor={id}>{label}</Label>}
      <ModelPickerPopover
        value={value}
        onChange={(val) => onChange(val || '')}
        modelType={modelType}
        placeholder={placeholder}
        disabled={disabled}
        className={className}
      />
    </div>
  )
}
