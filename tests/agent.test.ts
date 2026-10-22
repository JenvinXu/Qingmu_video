import { test } from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs/promises';
import { AppServer } from '../packages/agent/rpc';
import { tools } from '../packages/agent/tools';
import { turnSkills } from '../packages/agent/skills';
import { dialogueCaptionAt, dialogueTiming } from '../apps/workbench/src/features/drama/dialogue';

test('drama turns load the two adapted creative skills only where they apply', () => {
  const idea = turnSkills('C:/studio-home', { kind: 'drama', action: 'idea' }).map((skill) => skill.name);
  const storyboard = turnSkills('C:/studio-home', { kind: 'drama', action: 'storyboard' }).map(
    (skill) => skill.name,
  );
  const automatic = turnSkills('C:/studio-home', { kind: 'drama', action: 'auto' }).map(
    (skill) => skill.name,
  );
  const narration = turnSkills('C:/studio-home', { kind: 'narration', action: 'auto' }).map(
    (skill) => skill.name,
  );
  assert.deepEqual(idea, ['video-director', 'screenwriting']);
  assert.deepEqual(storyboard, ['video-director', 'visual-video']);
  assert.deepEqual(automatic, ['video-director', 'screenwriting', 'visual-video']);
  assert.deepEqual(narration, ['video-director']);
});

test('agent scene tools expose the 1-30 second video range', () => {
  const storyboard = tools.find((tool) => tool.name === 'studio_save_storyboard')!;
  const schema = storyboard.inputSchema as any;
  const seconds = schema.properties.scenes.items.properties.video_seconds;
  assert.deepEqual(seconds, { type: 'integer', minimum: 1, maximum: 30 });
  assert.ok(schema.properties.scenes.items.required.includes('dialogue'));
  assert.equal(schema.properties.scenes.items.properties.speaker_id.type, 'string');
  assert.equal(schema.properties.scenes.items.properties.dialogue_start.type, 'number');
  assert.equal(schema.properties.scenes.items.properties.dialogue_end.type, 'number');
  assert.match(storyboard.description, /自然对白/);
  assert.match(storyboard.description, /实际开口/);
});

test('dialogue captions stay hidden before and after the speaking interval', () => {
  const scene = {
    dialogue: '先看着灯，再开口。',
    dialogue_start: 1.5,
    dialogue_end: 3.5,
    duration: 5,
  } as any;
  assert.deepEqual(dialogueTiming(scene), { start: 1.5, end: 3.5 });
  assert.equal(dialogueCaptionAt(scene, 1.49), '');
  assert.match(dialogueCaptionAt(scene, 1.5), /先看着灯/);
  assert.equal(dialogueCaptionAt(scene, 3.5), '');
});

test(
  'official latest app-server initializes and registers software operations',
  { timeout: 60000 },
  async () => {
    const home = await fs.mkdtemp(path.join(os.tmpdir(), 'lime-rpc-test-'));
    await fs.writeFile(
      path.join(home, 'config.toml'),
      'model = "agnes-2.5-flash"\nmodel_provider = "test"\n[model_providers.test]\nname = "test"\nbase_url = "http://127.0.0.1:9/v1"\nwire_api = "responses"\nenv_key = "TEST_AGENT_KEY"\nrequires_openai_auth = false\n',
    );
    const rpc = new AppServer(
      path.resolve('node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'),
      home,
      { TEST_AGENT_KEY: 'local-test-no-upstream' },
    );
    try {
      const initialized = await rpc.start();
      assert.ok(initialized.userAgent.includes('0.155.0-alpha.16'));
      const result = await rpc.request('thread/start', {
        modelProvider: 'test',
        cwd: home,
        ephemeral: true,
        dynamicTools: tools,
        sandbox: 'read-only',
        approvalPolicy: 'never',
      });
      assert.ok(result.thread.id);
      assert.equal(result.modelProvider, 'test');
    } finally {
      rpc.stop();
    }
  },
);
