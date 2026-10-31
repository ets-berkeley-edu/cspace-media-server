import {describe, expect, it} from 'vitest'
import {advisories, check} from './audit.js'

const report = (...vias) => ({
  vulnerabilities: {
    minimatch: {via: vias.filter(v => v.name === 'minimatch')},
    glob: {via: [...vias.filter(v => v.name === 'glob'), 'minimatch']},
    eslint: {via: ['minimatch']}
  }
})
const minimatch = {
  name: 'minimatch', source: 1, severity: 'moderate', title: 'ReDoS',
  url: 'https://github.com/advisories/GHSA-aaaa-bbbb-cccc'
}
const glob = {
  name: 'glob', source: 2, severity: 'high', title: 'Traversal', url: 'https://github.com/advisories/GHSA-dddd-eeee-ffff'
}
const entry = (id, review_by = '2026-11-30') => ({id, reason: 'dev tooling only', review_by})

describe('the npm audit check', () => {
  it('lists each advisory once, with the packages it was found in', () => {
    expect(advisories(report(minimatch, glob))).toEqual([
      {id: 'GHSA-aaaa-bbbb-cccc', severity: 'moderate', title: 'ReDoS', packages: ['minimatch']},
      {id: 'GHSA-dddd-eeee-ffff', severity: 'high', title: 'Traversal', packages: ['glob']}
    ])
  })

  it('passes a clean report and an empty list', () => {
    expect(check({vulnerabilities: {}}, [], '2026-11-01')).toEqual({failures: [], allowed: []})
  })

  it('passes advisories that are on the list', () => {
    const result = check(report(minimatch), [entry('GHSA-aaaa-bbbb-cccc')], '2026-11-01')
    expect(result.failures).toEqual([])
    expect(result.allowed.map(a => a.id)).toEqual(['GHSA-aaaa-bbbb-cccc'])
  })

  it('fails on an advisory that is not on the list', () => {
    const {failures} = check(report(minimatch, glob), [entry('GHSA-aaaa-bbbb-cccc')], '2026-11-01')
    expect(failures).toEqual(['high GHSA-dddd-eeee-ffff in glob: Traversal'])
  })

  it('fails on an entry past its review date', () => {
    const {failures} = check(report(minimatch), [entry('GHSA-aaaa-bbbb-cccc', '2026-10-31')], '2026-11-01')
    expect(failures).toEqual(['audit-allowlist.json: GHSA-aaaa-bbbb-cccc was to be reviewed by 2026-10-31: is a fix out yet?'])
  })

  it('fails on an entry the report no longer needs', () => {
    const {failures} = check({vulnerabilities: {}}, [entry('GHSA-aaaa-bbbb-cccc')], '2026-11-01')
    expect(failures).toEqual(['audit-allowlist.json: GHSA-aaaa-bbbb-cccc is no longer reported: remove it'])
  })

  it('fails on an entry without an ID, a reason or a review date', () => {
    const {failures} = check(report(minimatch), [{id: 'GHSA-aaaa-bbbb-cccc', review_by: '2026-11-30'}], '2026-11-01')
    expect(failures).toEqual([
      'audit-allowlist.json: "GHSA-aaaa-bbbb-cccc" needs a GHSA ID, a reason and review_by (YYYY-MM-DD)'
    ])
  })

  it('fails when npm audit itself fails', () => {
    const {failures} = check({error: {summary: 'registry unreachable'}}, [], '2026-11-01')
    expect(failures).toEqual(['npm audit failed: registry unreachable'])
  })
})
