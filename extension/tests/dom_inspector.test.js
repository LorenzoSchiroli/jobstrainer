import '../content/dom_inspector.js';
const { resolveLabel, buildSnapshot } = globalThis;

describe('resolveLabel', () => {
  test('returns aria-label when present', () => {
    document.body.innerHTML = '<input id="f1" aria-label="Full Name" />';
    expect(resolveLabel(document.getElementById('f1'))).toBe('Full Name');
  });

  test('returns label[for] text when present', () => {
    document.body.innerHTML = '<label for="f2">Email</label><input id="f2" />';
    expect(resolveLabel(document.getElementById('f2'))).toBe('Email');
  });

  test('returns placeholder when no label or aria-label', () => {
    document.body.innerHTML = '<input id="f3" placeholder="Enter phone" />';
    expect(resolveLabel(document.getElementById('f3'))).toBe('Enter phone');
  });

  test('returns empty string when nothing available', () => {
    document.body.innerHTML = '<input id="f4" />';
    expect(resolveLabel(document.getElementById('f4'))).toBe('');
  });
});

describe('buildSnapshot', () => {
  test('captures text input with label', () => {
    document.body.innerHTML = `
      <label for="name">Full Name</label>
      <input id="name" type="text" value="Alice" />
    `;
    const snap = buildSnapshot();
    expect(snap.fields).toHaveLength(1);
    expect(snap.fields[0]).toEqual({ id: 'name', label: 'Full Name', type: 'text', value: 'Alice' });
  });

  test('captures select with current value and options list', () => {
    document.body.innerHTML = `
      <label for="country">Country</label>
      <select id="country">
        <option value="US">United States</option>
        <option value="UK" selected>United Kingdom</option>
      </select>
    `;
    const snap = buildSnapshot();
    expect(snap.fields[0].type).toBe('select');
    expect(snap.fields[0].value).toBe('UK');
    expect(snap.fields[0].options).toEqual(['United States', 'United Kingdom']);
  });

  test('captures file input without value property', () => {
    document.body.innerHTML = `
      <label for="resume">Resume</label>
      <input id="resume" type="file" />
    `;
    const snap = buildSnapshot();
    expect(snap.fields[0]).toEqual({ id: 'resume', label: 'Resume', type: 'file' });
    expect(snap.fields[0]).not.toHaveProperty('value');
  });

  test('captures links with text, label, and href', () => {
    document.body.innerHTML = `<a href="/apply">Apply Now</a>`;
    const snap = buildSnapshot();
    expect(snap.links[0]).toEqual({ text: 'Apply Now', label: 'Apply Now', href: '/apply' });
  });

  test('assigns generated id to elements without an id', () => {
    document.body.innerHTML = `<input type="text" placeholder="Name" />`;
    const snap = buildSnapshot();
    expect(snap.fields[0].id).toMatch(/^field_/);
  });

  test('excludes hidden and submit inputs', () => {
    document.body.innerHTML = `
      <input type="hidden" value="secret" />
      <input type="submit" value="Submit" />
      <input id="visible" type="text" value="hello" />
    `;
    const snap = buildSnapshot();
    expect(snap.fields).toHaveLength(1);
    expect(snap.fields[0].id).toBe('visible');
  });

  test('captures textarea with type textarea', () => {
    document.body.innerHTML = `
      <label for="cover">Cover Letter</label>
      <textarea id="cover">Dear hiring manager</textarea>
    `;
    const snap = buildSnapshot();
    expect(snap.fields[0]).toEqual({
      id: 'cover',
      label: 'Cover Letter',
      type: 'textarea',
      value: 'Dear hiring manager',
    });
  });
});
