// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { describe, expect, it } from 'vitest'

import type { CustomFieldDef } from '../types/api.generated'
import {
  CUSTOM_FIELD_TYPE_OPTIONS,
  canonicalValueForType,
  customFieldTypeLabel,
  inputKindForType,
  parseOptionsText,
  requiredFieldErrors,
  sortDefs,
  stringifyOptions,
} from './custom-fields-format'

function def(overrides: Partial<CustomFieldDef> = {}): CustomFieldDef {
  return {
    field_id: 'f-meeting-type',
    station_id: 'civiccast-station',
    key: 'meeting_type',
    label: 'Meeting type',
    type: 'list',
    options: ['Regular', 'Special'],
    required: false,
    searchable: true,
    api_exposed: true,
    order: 0,
    ...overrides,
  }
}

describe('customFieldTypeLabel', () => {
  it('maps every type to a human label', () => {
    expect(customFieldTypeLabel('text')).toBe('Text')
    expect(customFieldTypeLabel('longtext')).toBe('Long text')
    expect(customFieldTypeLabel('list')).toBe('List (pick one)')
    expect(customFieldTypeLabel('date')).toBe('Date')
    expect(customFieldTypeLabel('number')).toBe('Number')
    expect(customFieldTypeLabel('boolean')).toBe('Yes / no')
    expect(customFieldTypeLabel('asset_ref')).toBe('Asset reference')
    expect(customFieldTypeLabel('producer_ref')).toBe('Producer reference')
  })

  it('never throws on an unexpected value', () => {
    expect(customFieldTypeLabel('mystery' as CustomFieldDef['type'])).toBe('mystery')
  })
})

describe('CUSTOM_FIELD_TYPE_OPTIONS', () => {
  it('lists all eight types', () => {
    expect(CUSTOM_FIELD_TYPE_OPTIONS).toHaveLength(8)
    expect(CUSTOM_FIELD_TYPE_OPTIONS.map((o) => o.value)).toEqual([
      'text',
      'longtext',
      'list',
      'date',
      'number',
      'boolean',
      'asset_ref',
      'producer_ref',
    ])
  })
})

describe('inputKindForType', () => {
  it('routes each type to its widget kind', () => {
    expect(inputKindForType('text')).toBe('text')
    expect(inputKindForType('longtext')).toBe('textarea')
    expect(inputKindForType('list')).toBe('select')
    expect(inputKindForType('date')).toBe('date')
    expect(inputKindForType('number')).toBe('number')
    expect(inputKindForType('boolean')).toBe('checkbox')
    expect(inputKindForType('asset_ref')).toBe('asset_ref')
    expect(inputKindForType('producer_ref')).toBe('producer_ref')
  })
})

describe('parseOptionsText / stringifyOptions', () => {
  it('splits one option per line, trimming blanks', () => {
    expect(parseOptionsText('Regular\nSpecial\n\n  Workshop  ')).toEqual([
      'Regular',
      'Special',
      'Workshop',
    ])
  })

  it('joins options back to newline text', () => {
    expect(stringifyOptions(['Regular', 'Special'])).toBe('Regular\nSpecial')
    expect(stringifyOptions(undefined)).toBe('')
  })
})

describe('canonicalValueForType', () => {
  it('canonicalizes boolean to true/false', () => {
    expect(canonicalValueForType('boolean', true)).toBe('true')
    expect(canonicalValueForType('boolean', false)).toBe('false')
  })

  it('passes through strings for other types', () => {
    expect(canonicalValueForType('text', 'hello')).toBe('hello')
    expect(canonicalValueForType('number', '42')).toBe('42')
    expect(canonicalValueForType('date', '2026-06-18')).toBe('2026-06-18')
  })
})

describe('requiredFieldErrors', () => {
  it('flags a required field with no value', () => {
    const defs = [def({ field_id: 'f1', required: true, type: 'text' })]
    const errors = requiredFieldErrors(defs, { f1: '' })
    expect(errors).toEqual(['Meeting type'])
  })

  it('treats whitespace-only as empty', () => {
    const defs = [def({ field_id: 'f1', required: true, type: 'text', label: 'Notes' })]
    expect(requiredFieldErrors(defs, { f1: '   ' })).toEqual(['Notes'])
  })

  it('a required boolean is satisfied by false (a value was chosen)', () => {
    const defs = [def({ field_id: 'f1', required: true, type: 'boolean', label: 'Aired' })]
    expect(requiredFieldErrors(defs, { f1: 'false' })).toEqual([])
  })

  it('passes when every required field has a value and ignores optional blanks', () => {
    const defs = [
      def({ field_id: 'f1', required: true, type: 'text', label: 'A' }),
      def({ field_id: 'f2', required: false, type: 'text', label: 'B' }),
    ]
    expect(requiredFieldErrors(defs, { f1: 'x', f2: '' })).toEqual([])
  })
})

describe('sortDefs', () => {
  it('orders by order then label, leaving inputs untouched', () => {
    const a = def({ field_id: 'a', label: 'Zebra', order: 2 })
    const b = def({ field_id: 'b', label: 'Apple', order: 1 })
    const c = def({ field_id: 'c', label: 'Beta', order: 1 })
    const sorted = sortDefs([a, b, c])
    expect(sorted.map((d) => d.field_id)).toEqual(['b', 'c', 'a'])
  })
})
