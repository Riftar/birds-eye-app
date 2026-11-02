// Exercise the actual inline renderer with a small DOM and a pending run.
const assert = require('node:assert/strict');
class Node {
  constructor(tag = 'div', text = '') { this.tag = tag; this.text = text; this.children = []; this.dataset = {}; this.classList = {add() {}, remove() {}}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, handler) { this[name] = handler; }
  querySelectorAll() { return []; }
  get textContent() { return this.text + this.children.map(c => c.textContent).join(''); }
  set textContent(value) { this.text = value; }
}
const nodes = {};
global.document = {
  querySelector: s => nodes[s] ||= new Node(),
  querySelectorAll: () => [],
  createElement: tag => new Node(tag),
  createTextNode: text => new Node('#text', text),
};
let finish;
global.fetch = () => new Promise(resolve => { finish = resolve; });

// The Python test appends the page's script here, followed by these checks.
global.verifyDemo = async () => {
  const run = nodes['#form'].submit({preventDefault() {}});
  const cards = nodes['#result'].children;
  assert.match(cards[0].textContent, /PlannerRunning/);
  assert.equal(cards[0].children[1].className, 'skeleton');
  assert.match(cards[1].textContent, /WriterWaiting/);
  finish({ok: true, json: async () => ({stages: [
    {stage: 'Writer', structured: {format: 'carousel', beats: [
      {label: 'Cover', text: 'Hello'}, {label: 'Second', text: 'World'}
    ], caption: 'Caption'}, attempts: [{status: 'success', cost_usd: '0.00266225'}]},
    {stage: 'Reviewer', decision: 'approve', findings: [], output: 'unparseable'},
  ]})});
  await run;
  const [writer, reviewer] = nodes['#result'].children;
  const post = writer.children.find(c => c.tag === 'article');
  assert.equal(post.className, 'post well');
  assert.equal(post.children[1].children.length, 2);
  assert.match(post.textContent, /CoverHelloSecondWorldCaption/);
  assert.equal(post.children[0].children[1].className, 'small');
  assert.match(writer.textContent, /\$0\.0027/);
  assert.match(reviewer.textContent, /No findings/);
};
