// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { RollupChart } from './RollupChart'

afterEach(() => {
  cleanup()
})

describe('RollupChart', () => {
  it('renders an empty state when there is no data', () => {
    render(<RollupChart data={[]} chartType="bar" valueLabel="Viewer Count" />)
    expect(screen.getByRole('img', { name: /no data for this period/i })).toBeTruthy()
  })

  it('renders a custom empty message', () => {
    render(
      <RollupChart
        data={[]}
        chartType="bar"
        valueLabel="Viewer Count"
        emptyMessage="Nothing to show yet"
      />,
    )
    expect(screen.getByRole('img', { name: 'Nothing to show yet' })).toBeTruthy()
  })

  it('renders one bar per datum in bar mode', () => {
    const { container } = render(
      <RollupChart
        data={[
          { label: 'asset-1', value: 10 },
          { label: 'asset-2', value: 5 },
        ]}
        chartType="bar"
        valueLabel="Viewer Count"
      />,
    )
    expect(container.querySelectorAll('rect').length).toBe(2)
  })

  it('renders a single path + one point per datum in line mode', () => {
    const { container } = render(
      <RollupChart
        data={[
          { label: '9:00', value: 3 },
          { label: '9:30', value: 7 },
          { label: '10:00', value: 4 },
        ]}
        chartType="line"
        valueLabel="Viewer Count"
      />,
    )
    expect(container.querySelectorAll('path').length).toBe(1)
    expect(container.querySelectorAll('circle').length).toBe(3)
  })

  it('has an accessible svg title matching the chart', () => {
    render(
      <RollupChart
        data={[{ label: 'a', value: 1 }]}
        chartType="bar"
        valueLabel="Time Viewed"
      />,
    )
    expect(screen.getByRole('img', { name: /time viewed by item/i })).toBeTruthy()
  })
})
