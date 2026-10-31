// npm audit, with a short list of known advisories allowed for a while (audit-allowlist.json).
//
// CI runs this in place of `npm audit` (security.yml on every pull request and push, audit.yml every Monday). It fails
// on any advisory not on the list, on an entry past its review date, and on an entry no advisory needs any more, so
// the list only ever holds advisories someone has looked at, and empties itself out as the fixes arrive.
//   node scripts/audit.js      (or npm run audit-check), in admin/

import {readFileSync} from 'node:fs'
import {spawnSync} from 'node:child_process'
import {pathToFileURL} from 'node:url'

// The advisories in `npm audit --json`'s report, one per advisory ID (GHSA-…), with the packages it was found in.
export function advisories(report) {
  const found = new Map()
  for (const [name, vulnerability] of Object.entries(report.vulnerabilities ?? {})) {
    for (const via of vulnerability.via ?? []) {
      if (typeof via !== 'object') continue // a package that is vulnerable only through another one
      const id = String(via.url ?? via.source).split('/').pop()
      const advisory = found.get(id) ?? {id, severity: via.severity, title: via.title, packages: new Set()}
      advisory.packages.add(via.name ?? name)
      found.set(id, advisory)
    }
  }
  return [...found.values()].map(a => ({...a, packages: [...a.packages].sort()}))
}

// What fails the check: an error from npm audit, an advisory not on the list, an entry past its review date (YYYY-MM-DD,
// compared with today's), or an entry for an advisory the report no longer has.
export function check(report, allowlist, today) {
  if (report.error) {
    return {failures: [`npm audit failed: ${report.error.summary ?? JSON.stringify(report.error)}`], allowed: []}
  }
  const found = advisories(report)
  const listed = new Map(allowlist.map(entry => [entry.id, entry]))
  const failures = []
  for (const advisory of found) {
    if (!listed.has(advisory.id)) {
      failures.push(`${advisory.severity} ${advisory.id} in ${advisory.packages.join(', ')}: ${advisory.title}`)
    }
  }
  for (const entry of allowlist) {
    if (!/^GHSA(-[0-9a-z]{4}){3}$/.test(entry.id) || !entry.reason || !/^\d{4}-\d{2}-\d{2}$/.test(entry.review_by)) {
      failures.push(`audit-allowlist.json: ${JSON.stringify(entry.id)} needs a GHSA ID, a reason and review_by (YYYY-MM-DD)`)
    } else if (entry.review_by < today) {
      failures.push(`audit-allowlist.json: ${entry.id} was to be reviewed by ${entry.review_by}: is a fix out yet?`)
    } else if (!found.some(advisory => advisory.id === entry.id)) {
      failures.push(`audit-allowlist.json: ${entry.id} is no longer reported: remove it`)
    }
  }
  return {failures, allowed: found.filter(advisory => listed.has(advisory.id))}
}

function main() {
  const run = spawnSync('npm', ['audit', '--json'], {encoding: 'utf8', maxBuffer: 64 * 1024 * 1024})
  let report
  try {
    report = JSON.parse(run.stdout)
  } catch {
    process.stderr.write(`npm audit gave no report (exit ${run.status}):\n${run.stderr}\n`)
    process.exit(1)
  }
  const allowlist = JSON.parse(readFileSync(new URL('../audit-allowlist.json', import.meta.url), 'utf8'))
  const {failures, allowed} = check(report, allowlist, new Date().toISOString().slice(0, 10))
  for (const advisory of allowed) {
    const entry = allowlist.find(e => e.id === advisory.id)
    process.stdout.write(`Allowed until ${entry.review_by}: ${advisory.id} in ${advisory.packages.join(', ')}\n`)
  }
  if (failures.length) {
    process.stderr.write(`${failures.join('\n')}\n`)
    process.exit(1)
  }
  process.stdout.write('npm audit: nothing but the allowed advisories.\n')
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()
