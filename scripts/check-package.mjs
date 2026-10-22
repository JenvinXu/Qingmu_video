import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import * as asar from '@electron/asar';

const root = process.cwd();
const archive = path.join(root, 'release/win-unpacked/resources/app.asar');
const workbench = path.join('dist', 'workbench');
const html = asar.extractFile(archive, path.join(workbench, 'index.html'));
assert.ok(html.equals(fs.readFileSync(path.join(root, workbench, 'index.html'))));
const assetLinks = [...html.toString().matchAll(/(?:src|href)="([^"]+\/assets\/[^\"]+)"/g)];
assert.equal(assetLinks.length, 2, 'Expected current JavaScript and CSS links');
for (const match of assetLinks) {
  const relative = match[1].replace(/^\.\//, '');
  assert.ok(
    asar
      .extractFile(archive, path.join(workbench, relative))
      .equals(fs.readFileSync(path.join(root, workbench, relative))),
  );
}
const contents = fs.readFileSync(archive);
for (const prefix of ['cpk-', 'bce-v3/ALTAK-'])
  assert.ok(!contents.includes(Buffer.from(prefix)), 'Secret prefix in packaged application');
const hash = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const backend = hash(path.join(root, 'build-resources/backend/lime-backend.exe'));
assert.equal(backend, hash(path.join(root, 'release/win-unpacked/resources/backend/lime-backend.exe')));
const result = {
  status: 'passed',
  backend_sha256: backend,
  renderer_matches_current_build: true,
  secret_literals_present: false,
  checked_at: new Date().toISOString(),
};
fs.writeFileSync(path.join(root, 'data/reports/package-check.json'), JSON.stringify(result, null, 2));
console.log('PACKAGE_CHECK_PASSED');
