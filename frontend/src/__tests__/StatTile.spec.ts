import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import StatTile from '../components/StatTile.vue'
import { managerColor } from '../charts/echarts'

describe('StatTile', () => {
  it('renders label and value', () => {
    const wrapper = mount(StatTile, { props: { label: 'Wins', value: 42 } })
    expect(wrapper.find('.label').text()).toBe('Wins')
    expect(wrapper.find('.value').text()).toBe('42')
  })
})

describe('managerColor', () => {
  it('is deterministic per manager id', () => {
    expect(managerColor(3)).toBe(managerColor(3))
  })

  it('stays within the palette for any id', () => {
    expect(managerColor(999999)).toMatch(/^#[0-9a-f]{6}$/)
  })
})
