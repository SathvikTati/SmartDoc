import { Label, SegmentedControl, Select } from '@/components/ui/Field'

export const MODE_OPTIONS = [
  {
    value: 'naive',
    label: 'Naive',
    hint: 'Vector search only. The baseline the other modes are measured against.',
  },
  {
    value: 'hybrid',
    label: 'Hybrid',
    hint: 'Semantic + BM25 fused with RRF, over document → section → chunk narrowing.',
  },
  {
    value: 'agentic',
    label: 'Agentic',
    hint: 'LangGraph agent: plans tools, validates evidence, retries once if thin.',
  },
]

const TOP_K_OPTIONS = [3, 4, 5, 6, 8, 10, 12, 15, 20].map((value) => ({
  value: String(value),
  label: String(value),
}))

export function QueryControls({
  mode,
  topK,
  onModeChange,
  onTopKChange,
  disabled,
}) {
  const active = MODE_OPTIONS.find((option) => option.value === mode)

  return (
    <div className="flex flex-wrap items-end gap-5">
      <div>
        <Label className="mb-1">Retrieval mode</Label>
        <SegmentedControl
          name="rag-mode"
          value={mode}
          options={MODE_OPTIONS}
          onChange={onModeChange}
        />
      </div>

      <div>
        <Label htmlFor="top-k" className="mb-1">
          Top K
        </Label>
        <Select
          id="top-k"
          value={String(topK)}
          disabled={disabled}
          onChange={(event) => onTopKChange(Number(event.target.value))}
          options={TOP_K_OPTIONS}
          className="w-20"
        />
      </div>

      {active && (
        <p className="min-w-0 flex-1 pb-1.5 text-xs text-ink-subtle">
          {active.hint}
        </p>
      )}
    </div>
  )
}
