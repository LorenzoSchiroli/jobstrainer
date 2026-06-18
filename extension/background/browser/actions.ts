import Page from './page';
import { waitForNavCompleted, clickAndDetectNavigation } from './navigation';

export interface ActionResult {
  navigated: boolean;
}

type ActionFn = (
  page: Page,
  action: Record<string, unknown>,
  tabId: number,
) => Promise<ActionResult>;

const done = (fn: () => Promise<unknown>): Promise<ActionResult> =>
  fn().then(() => ({ navigated: false }));

const ACTIONS: Record<string, ActionFn> = {
  click_element: (page, a, tabId) =>
    clickAndDetectNavigation(tabId, () => page.clickElement(a.index as number))
      .then(navigated => ({ navigated })),

  input_text: (page, a) =>
    done(() => page.typeText(a.index as number, (a.text ?? '') as string)),

  select_option: (page, a) =>
    done(() => page.selectOption(a.index as number, ((a.text ?? a.value) ?? '') as string)),

  send_keys:        (page, a) => done(() => page.sendKeys((a.keys ?? '') as string)),
  wait:             (page, a) => done(() => page.wait((a.seconds ?? 2) as number)),

  go_back: async (page, _a, tabId) => {
    const navDone = waitForNavCompleted(tabId);
    await page.goBack();
    await navDone;
    return { navigated: true };
  },

  go_to_url: async (page, a, tabId) => {
    const navDone = waitForNavCompleted(tabId);
    await page.navigate(a.url as string);
    await navDone;
    return { navigated: true };
  },
};

export async function executeAction(
  page: Page,
  action: Record<string, unknown>,
  tabId: number,
): Promise<ActionResult> {
  const fn = ACTIONS[action.action as string];
  if (!fn) {
    console.warn('[actions] unknown action', action.action);
    return { navigated: false };
  }
  return fn(page, action, tabId);
}
