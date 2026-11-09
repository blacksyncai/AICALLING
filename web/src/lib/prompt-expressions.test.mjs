import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseExpressions, addExpression, editExpressionText, expressionRanges, removeExpression } from './prompt-expressions.ts';

test('selected speech gets a scoped emotion and visible text is unchanged', () => {
 const plain='Hey, this is James, right? Thanks for confirming.';
 const marked=addExpression(plain,0,25,'curious');
 assert.equal(marked,'<emotion value="curious"/>Hey, this is James, right?<emotion value="neutral"/> Thanks for confirming.');
 assert.equal(parseExpressions(marked).text,plain);
 assert.equal(expressionRanges(marked)[0].label,'Curious');
 assert.equal(expressionRanges(marked)[0].end,26);
});
test('existing annotations survive a reload and a later region does not inherit the selected emotion', () => {
 const raw='<emotion value="calm"/>Hello James. How are you?<emotion value="neutral"/> Thanks.';
 const next=addExpression(raw,13,25,'curious');
 assert.equal(parseExpressions(next).text,parseExpressions(raw).text);
 assert.ok(next.includes('<emotion value="calm"/>'));
 assert.ok(next.includes('<emotion value="curious"/>'));
 assert.ok(next.includes('<emotion value="neutral"/> Thanks.'));
});
test('lead variables stay whole when only part is highlighted', () => {
 const raw='Hey {{first_name}}, right?';
 const next=addExpression(raw,8,12,'curious');
 assert.ok(next.includes('<emotion value="curious"/>{{first_name}}<emotion value="neutral"/>'));
 assert.equal(parseExpressions(next).text,raw);
});
test('pauses are anchored after selection and can be removed without changing words', () => {
 const plain='Hello James. Thanks.';
 const marked=addExpression(plain,0,12,'pause:200');
 assert.equal(marked,'Hello James.<break time="200ms"/> Thanks.');
 const range=expressionRanges(marked)[0];
 assert.equal(range.label,'200 ms pause');
 assert.equal(removeExpression(marked,range.marker),plain);
 assert.equal(addExpression(plain,0,12,'pause:3000'),plain);
});
test('editing around and within a highlight preserves speech and adjusts ranges', () => {
 const raw=addExpression('Hello James. Thanks.',0,12,'curious');
 const changed=editExpressionText(raw,'Hello Jamie. Thanks.');
 assert.equal(parseExpressions(changed).text,'Hello Jamie. Thanks.');
 assert.equal(expressionRanges(changed)[0].end,12);
 const withVariable=editExpressionText(raw,'Hey! Hello James. Thanks.');
 assert.equal(parseExpressions(withVariable).text,'Hey! Hello James. Thanks.');
 assert.equal(expressionRanges(withVariable)[0].end,17);
});
test('deleting a highlighted span never leaks its emotion into following speech', () => {
 const raw=addExpression('Hello James. Thanks.',0,12,'curious');
 const changed=editExpressionText(raw,' Thanks.');
 assert.equal(parseExpressions(changed).text,' Thanks.');
 assert.equal(expressionRanges(changed).length,0);
 assert.equal(editExpressionText(raw,''),'');
});
test('removing emotion leaves words and pauses unchanged', () => {
 const raw='<emotion value="curious"/>Hey James?<break time="200ms"/><emotion value="neutral"/> Thanks.';
 const without=removeExpression(raw,0);
 assert.equal(parseExpressions(without).text,'Hey James? Thanks.');
 assert.deepEqual(expressionRanges(without).map(r=>r.label),['200 ms pause']);
});
test('unsupported or malformed controls remain editable text, invalid actions are rejected', () => {
 const raw='<emotion value="invented"/>Hello <break time="9999ms"/> James';
 assert.equal(parseExpressions(raw).text,raw);
 assert.equal(parseExpressions(raw).markers.length,0);
 assert.equal(addExpression('Hello',0,5,'invented'),'Hello');
 assert.equal(addExpression('Hello',0,99,'curious'),'Hello');
});
test('multiline scripts and emoji survive annotation and ordinary edits', () => {
 const plain='Hey James?\nWait for an answer.\nThanks 😊';
 const marked=addExpression(plain,0,10,'curious');
 assert.equal(parseExpressions(marked).text,plain);
 const changed=editExpressionText(marked,plain+'!');
 assert.equal(parseExpressions(changed).text,plain+'!');
});
