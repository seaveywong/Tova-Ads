import test from 'node:test'
import assert from 'node:assert/strict'
import { compareRows, entityContext, entityKey, searchMatches, normalizeViewPreferences, fbResult } from './adManagerView.js'

test('hierarchy lookup and search never borrow names from another account or platform', () => {
  const row = { id: 'ad', act_id: 'a', platform: 'fb', adset_id: { id: 'set' }, name: 'Creative', account_name: 'Shop' }
  const context = entityContext({ campaigns: [{ id: 'campaign', act_id: 'a', name: 'Summer' }], adsets: [
    { id: 'set', act_id: 'a', campaign_id: 'campaign', name: 'Retargeting' },
    { id: 'set', act_id: 'b', name: 'Wrong account' },
    { id: 'set', act_id: 'a', platform: 'tt', name: 'Wrong platform' },
  ] })
  assert.equal(searchMatches(row, 'summer shop retargeting', context), true)
  assert.equal(searchMatches(row, 'wrong', context), false)
  assert.notEqual(entityKey(row), entityKey({ ...row, platform: 'tt' }))
})

test('blocked accounts remain last in either sort direction; native currencies are not mixed', () => {
  const rows = [{ id: 'blocked', spend: 999, blocked: true }, { id: 'small', spend: 1, spend_usd: 100 }, { id: 'large', spend: 10, spend_usd: 2 }]
  const options = { key: 'spend', direction: 'desc', blocked: row => !!row.blocked, statusRank: () => 0 }
  assert.deepEqual([...rows].sort((a,b) => compareRows(a,b,options)).map(x => x.id), ['large','small','blocked'])
  assert.deepEqual([...rows].sort((a,b) => compareRows(a,b,{...options, mixedCurrency:true})).map(x => x.id), ['small','large','blocked'])
  assert.equal([...rows].sort((a,b) => compareRows(a,b,{...options,direction:'asc'})).at(-1).id, 'blocked')
})

test('missing FB results never fall back to combined conversions', () => {
  assert.equal(fbResult({ conversions: 19 }), null)
  assert.equal(fbResult({ results_fb: 0, conversions: 19 }), 0)
  assert.equal(fbResult({ results_fb: 5, results_fb_complete: false }), null)
})

test('pre-collection zeros are not presented as measured FB results', () => {
  assert.equal(fbResult({ results_fb: 0, results_fb_available: false }), null)
  assert.equal(fbResult({ results_fb: 0, results_fb_available: true }), 0)
  assert.equal(fbResult({ results_fb: 4, results_fb_available: false }), null)
})

test('persisted settings reject removed columns and invalid sort keys per level', () => {
  const prefs = normalizeViewPreferences({ ad: { columns: ['budget','spend','spend','bad'], sortKey:'budget', sortDir:'bad' } })
  assert.deepEqual(prefs.ad.columns, ['spend'])
  assert.equal(prefs.ad.sortKey, 'spend')
  assert.equal(prefs.ad.sortDir, 'desc')
  assert.ok(prefs.campaign.columns.includes('results_fb'))
  assert.ok(prefs.campaign.columns.includes('conversions'))
})
