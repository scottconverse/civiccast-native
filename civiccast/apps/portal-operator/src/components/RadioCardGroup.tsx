import type { KeyboardEvent, ReactNode } from 'react'

export interface RadioCardOption<T extends string> {
  id: T
  label: ReactNode
  description?: ReactNode
  trailing?: ReactNode
}

interface Props<T extends string> {
  label: string
  options: ReadonlyArray<RadioCardOption<T>>
  value: T
  onChange: (value: T) => void
  className?: string
  buttonClassName?: string
  getDescriptionColor?: (active: boolean) => string
}

export function RadioCardGroup<T extends string>({
  label,
  options,
  value,
  onChange,
  className = 'grid gap-2',
  buttonClassName = 'flex flex-col gap-1 rounded-md p-3 text-left',
  getDescriptionColor = (active) =>
    active ? 'var(--cc-brand-2)' : 'var(--cc-ink-3)',
}: Props<T>) {
  const selectedIndex = Math.max(
    0,
    options.findIndex((option) => option.id === value),
  )

  const move = (
    event: KeyboardEvent<HTMLButtonElement>,
    nextIndex: number,
  ) => {
    event.preventDefault()
    const next = options[nextIndex]
    if (!next) return
    onChange(next.id)
    const buttons = Array.from(
      event.currentTarget
        .closest('[role="radiogroup"]')
        ?.querySelectorAll<HTMLButtonElement>('[role="radio"]') ?? [],
    )
    buttons[nextIndex]?.focus()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (options.length === 0) return
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      move(event, (selectedIndex + 1) % options.length)
    }
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      move(event, (selectedIndex - 1 + options.length) % options.length)
    }
    if (event.key === 'Home') {
      move(event, 0)
    }
    if (event.key === 'End') {
      move(event, options.length - 1)
    }
  }

  return (
    <div role="radiogroup" aria-label={label} className={className}>
      {options.map((option) => {
        const active = option.id === value
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.id)}
            onKeyDown={onKeyDown}
            className={buttonClassName}
            style={{
              border: `1px solid ${active ? 'var(--cc-brand)' : 'var(--cc-line)'}`,
              background: active ? 'var(--cc-brand-soft)' : 'var(--cc-surface)',
              color: active ? 'var(--cc-brand-2)' : 'var(--cc-ink)',
            }}
          >
            <span className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold">{option.label}</span>
              {option.trailing}
            </span>
            {option.description && (
              <span
                className="text-[11px]"
                style={{ color: getDescriptionColor(active) }}
              >
                {option.description}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
