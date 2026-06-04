import { describe, it, expect } from 'vitest';
import { DOMElementNode, DOMTextNode } from '../views';

function makeElement(params: {
  tagName: string;
  highlightIndex?: number | null;
  attributes?: Record<string, string>;
  isVisible?: boolean;
  isTopElement?: boolean;
  isInViewport?: boolean;
}): DOMElementNode {
  return new DOMElementNode({
    tagName: params.tagName,
    xpath: `/${params.tagName}`,
    attributes: params.attributes ?? {},
    children: [],
    isVisible: params.isVisible ?? true,
    isInteractive: true,
    isTopElement: params.isTopElement ?? true,
    isInViewport: params.isInViewport ?? true,
    highlightIndex: params.highlightIndex ?? null,
    parent: null,
  });
}

describe('clickableElementsToString', () => {
  it('serialises a button with highlightIndex', () => {
    const root = makeElement({ tagName: 'div', highlightIndex: null });
    const btn = makeElement({ tagName: 'button', highlightIndex: 1, attributes: { type: 'submit' } });
    const txt = new DOMTextNode('Apply Now', true, btn);
    btn.children.push(txt);
    btn.parent = root;
    root.children.push(btn);

    const result = root.clickableElementsToString();
    expect(result).toContain('[1]');
    expect(result).toContain('button');
    expect(result).toContain('Apply Now');
  });

  it('serialises a file input', () => {
    const root = makeElement({ tagName: 'div', highlightIndex: null });
    const input = makeElement({ tagName: 'input', highlightIndex: 3, attributes: { type: 'file' } });
    input.parent = root;
    root.children.push(input);

    const result = root.clickableElementsToString();
    expect(result).toContain('[3]');
    expect(result).toContain('type=file');
  });

  it('omits elements with no highlightIndex', () => {
    const root = makeElement({ tagName: 'div', highlightIndex: null });
    const span = makeElement({ tagName: 'span', highlightIndex: null });
    root.children.push(span);

    const result = root.clickableElementsToString();
    expect(result).toBe('');
  });

  it('marks new elements with asterisk prefix', () => {
    const root = makeElement({ tagName: 'div', highlightIndex: null });
    const btn = makeElement({ tagName: 'button', highlightIndex: 0 });
    btn.isNew = true;
    btn.parent = root;
    root.children.push(btn);

    const result = root.clickableElementsToString();
    expect(result).toContain('*[0]');
  });
});
