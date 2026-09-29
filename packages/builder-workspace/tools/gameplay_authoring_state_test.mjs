import assert from 'node:assert/strict';
import { build } from 'esbuild';
const bundled = await build({ entryPoints: ['src/state/console_state_machine.ts'], bundle: true, write: false, format: 'esm', platform: 'node' });
const { ConsoleSM } = await import('data:text/javascript;base64,' + Buffer.from(bundled.outputFiles[0].text).toString('base64'));
const sm = new ConsoleSM();
const question = { kind: 'clarification', clarification_schema: 'xace.gameplay_authoring_selection.v1',
  clarification_session_id: 'catalog-one', questions: [{ question_id: 'strategy', question_type: 'CHOICE', prompt: 'Choose', options: ['Template'] }], reason: 'Requirements' };
sm.submitPrompt('Catalog request');
sm.receivePILResult(question);
assert.equal(sm.stateName, 'ClarificationFlow');
sm.receivePILResult({ ...question, clarification_session_id: 'catalog-two', questions: [{ ...question.questions[0], question_id: 'configuration' }] });
assert.equal(sm.state.currentQuestion.question_id, 'configuration');
sm.receivePILResult({ kind: 'mutation', transaction: { mutation_summary: 'Install package' } });
assert.equal(sm.stateName, 'PreviewPending');
sm.applyMutation();
assert.equal(sm.stateName, 'ApplyingMutation');
// Unsolicited continuation cannot replace an applying transaction.
sm.receivePILResult(question);
assert.equal(sm.stateName, 'ApplyingMutation');
console.log('XP-006 catalog clarification -> configuration -> preview -> explicit apply: passed');
