import assert from 'node:assert/strict';
import { test } from 'node:test';
import { clerkDomainOptions } from './white-label-clerk.ts';

test('the primary app and unconfigured installs keep their existing Clerk setup', () => {
  delete process.env.WHITE_LABEL_PRIMARY_ORIGIN;
  assert.deepEqual(clerkDomainOptions('app.customer.example'), {});
  process.env.WHITE_LABEL_PRIMARY_ORIGIN = 'https://app.blacksync.example';
  assert.deepEqual(clerkDomainOptions('app.blacksync.example'), {});
});

test('customer hosts receive satellite domain settings and central auth URLs', () => {
  process.env.WHITE_LABEL_PRIMARY_ORIGIN = 'https://app.blacksync.example';
  assert.deepEqual(clerkDomainOptions('APP.CUSTOMER.EXAMPLE:443'), {
    isSatellite: true, domain: 'app.customer.example',
    signInUrl: 'https://app.blacksync.example/sign-in',
    signUpUrl: 'https://app.blacksync.example/sign-up',
  });
});

test('an invalid or insecure primary origin never produces an auth redirect', () => {
  for (const value of ['not a URL', 'http://app.example.com', 'https://user:password@app.example.com',
    'https://app.example.com/path', 'https://app.example.com?redirect=evil']) {
    process.env.WHITE_LABEL_PRIMARY_ORIGIN = value;
    assert.deepEqual(clerkDomainOptions('app.customer.example'), {});
  }
  delete process.env.WHITE_LABEL_PRIMARY_ORIGIN;
});
