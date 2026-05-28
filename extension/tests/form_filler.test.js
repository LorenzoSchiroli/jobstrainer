import { fillField, clickElement, clickNextOrSubmit } from '../content/form_filler.js';

describe('fillField', () => {
  test('sets value on text input', () => {
    document.body.innerHTML = '<input id="name" type="text" />';
    fillField('name', 'Alice');
    expect(document.getElementById('name').value).toBe('Alice');
  });

  test('dispatches input and change events for React compatibility', () => {
    document.body.innerHTML = '<input id="email" type="email" />';
    const el = document.getElementById('email');
    const events = [];
    el.addEventListener('input', () => events.push('input'));
    el.addEventListener('change', () => events.push('change'));
    fillField('email', 'alice@example.com');
    expect(events).toEqual(['input', 'change']);
  });

  test('sets value on textarea', () => {
    document.body.innerHTML = '<textarea id="bio"></textarea>';
    fillField('bio', 'Hello world');
    expect(document.getElementById('bio').value).toBe('Hello world');
  });

  test('sets select by matching option text', () => {
    document.body.innerHTML = `
      <select id="country">
        <option value="US">United States</option>
        <option value="UK">United Kingdom</option>
      </select>
    `;
    fillField('country', 'United Kingdom');
    expect(document.getElementById('country').value).toBe('UK');
  });

  test('sets select by matching option value when text not found', () => {
    document.body.innerHTML = `
      <select id="emp">
        <option value="full_time">Full Time</option>
      </select>
    `;
    fillField('emp', 'full_time');
    expect(document.getElementById('emp').value).toBe('full_time');
  });

  test('does nothing silently when field not found', () => {
    expect(() => fillField('nonexistent', 'value')).not.toThrow();
  });
});

describe('clickElement', () => {
  test('clicks element by selector', () => {
    document.body.innerHTML = '<button id="next">Next</button>';
    let clicked = false;
    document.getElementById('next').addEventListener('click', () => { clicked = true; });
    clickElement('#next');
    expect(clicked).toBe(true);
  });

  test('does nothing silently when selector not found', () => {
    expect(() => clickElement('#missing')).not.toThrow();
  });
});

describe('clickNextOrSubmit', () => {
  test('returns submitted:true when clicking a submit button', () => {
    document.body.innerHTML = '<button id="sub">Submit Application</button>';
    const result = clickNextOrSubmit();
    expect(result.submitted).toBe(true);
  });

  test('returns submitted:false when clicking a next button', () => {
    document.body.innerHTML = '<button id="nxt">Next</button>';
    const result = clickNextOrSubmit();
    expect(result.submitted).toBe(false);
  });

  test('returns submitted:false when no button found', () => {
    document.body.innerHTML = '';
    const result = clickNextOrSubmit();
    expect(result.submitted).toBe(false);
  });
});
