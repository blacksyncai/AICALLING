import assert from 'node:assert/strict';
import { test } from 'node:test';
import { brandVariables, primaryText, DEFAULT_KIT } from './brand-theme.ts';

test('scheme derives all primary shades, safe fonts and button styles', () => {
  const vars = brandVariables({...DEFAULT_KIT, primary:'#2458a6', sidebar:'#10283e', font:'grotesk', button_shape:'pill'});
  for (const shade of [50,100,200,300,400,500,600,700,800]) assert.match(vars[`--color-brand-${shade}`], /^#[a-f0-9]{6}$/i);
  assert.equal(vars['--sidebar-surface'],'#10283e');
  assert.equal(vars['--brand-radius'],'999px');
  assert.ok(vars['--font-sans'].includes('Space Grotesk'));
});

test('primary button labels remain readable for bright and dark palettes', () => {
  assert.equal(primaryText('#ffffff'),'#000000');
  assert.equal(primaryText('#000000'),'#ffffff');
  assert.equal(brandVariables(DEFAULT_KIT)['--app-text'],DEFAULT_KIT.text);
});
