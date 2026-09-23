import { addressLooksValid, ddnsUrlProblem, personNameProblem, qrImageSource } from '@/features/access/shared'
import { describe, expect, test } from 'bun:test'

describe('access server of the panel', () => {
  test('a person is named the way core names them, and says why not', () => {
    expect(personNameProblem('anna')).toBeNull()
    expect(personNameProblem('dad-phone2')).toBeNull()
    expect(personNameProblem('')).toBe('empty')
    expect(personNameProblem('Anna')).toBe('format')
    expect(personNameProblem('-anna')).toBe('format')
    expect(personNameProblem('a'.repeat(33))).toBe('format')
    expect(personNameProblem('_health')).toBe('format') // the service user of the health check
  })

  test('an update URL is https only: its token must not travel in the clear', () => {
    expect(ddnsUrlProblem('https://www.duckdns.org/update?domains=home&token=t')).toBeNull()
    expect(ddnsUrlProblem('  ')).toBe('empty')
    expect(ddnsUrlProblem('http://www.duckdns.org/update?token=t')).toBe('https')
    expect(ddnsUrlProblem('https://a.example/one two')).toBe('https')
  })

  test('the address of the links is a host name or an address', () => {
    expect(addressLooksValid('myhome.duckdns.org')).toBe(true)
    expect(addressLooksValid('203.0.113.5')).toBe(true)
    expect(addressLooksValid('')).toBe(false)
    expect(addressLooksValid('my home')).toBe(false)
  })

  test('the QR code core rendered becomes an image source, never markup', () => {
    const source = qrImageSource('<svg><path d="M0 0"/></svg>')
    expect(source.startsWith('data:image/svg+xml;charset=utf-8,')).toBe(true)
    expect(source).not.toContain('<svg')
  })
})
