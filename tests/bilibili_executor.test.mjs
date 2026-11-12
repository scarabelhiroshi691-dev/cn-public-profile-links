import assert from 'node:assert/strict';
import test from 'node:test';
import {accountStatements, parseCards} from '../scripts/bilibili_executor.mjs';
import {workLinks} from '../scripts/shared_browser.mjs';

test('UID deduplication preserves distinct same-name results and counts filtering separately', () => {
  const row = (uid, nickname) => ({url: 'https://space.bilibili.com/' + uid, nickname});
  const rows = [row('12345678901', '小林'), row('12345678901/', '小林'),
    row('9007199254740993', '小林'), row('3', 'test@example.org')];
  const result = parseCards(rows, 10);
  assert.deepEqual(result.cards.map(x => x.uid), ['12345678901', '9007199254740993']);
  assert.equal(result.visible, 4);
  assert.equal(result.unique, 2);
  assert.equal(result.skipped, 1);
  assert.equal(parseCards(rows, 1).cards.length, 1);
});

test('only explicit account statements lead outward and Chinese brackets end links', () => {
  const description = '我的 GitHub：〖https://github.com/author】\n' +
    '本集源码 https://github.com/author/project〗\n' +
    '推荐 https://github.com/other\n' +
    '我的 GitHub https://www.youtube.com/@wrong\n' +
    '我的 YouTube：https://www.youtube.com/@author」';
  assert.deepEqual(accountStatements(description), ['https://github.com/author', 'https://www.youtube.com/@author']);
  assert.deepEqual(workLinks(description), ['https://github.com/author', 'https://github.com/author/project', 'https://github.com/other']);
});

test('a Chinese parenthetical immediately after a URL stays out of both parsers', () => {
  const description = '我的 GitHub：https://github.com/ExampleCreator（欢迎关注）\n' +
    '项目源码 https://github.com/ExampleCreator/project（本期代码）';
  assert.deepEqual(accountStatements(description), ['https://github.com/examplecreator']);
  assert.deepEqual(workLinks(description), ['https://github.com/ExampleCreator', 'https://github.com/ExampleCreator/project']);
  const encoded = 'https://github.com/author/project?label=%EF%BC%88';
  assert.deepEqual(workLinks(encoded + '（说明）'), [encoded]);
});

