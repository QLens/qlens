/* The reading guide, the reliability notice, and the settings panel.
 *
 * Written for someone who has never used a quantum computer, with an
 * expert register available for anyone who has. Whoever already knows
 * this can dismiss it in one click and never see it again; whoever
 * doesn't has nowhere else to find it, and a viewer full of unexplained
 * colour is useless to them. So the guide is always one click away from
 * the top bar, never buried, and never permanently dismissed: Settings
 * can bring every notice back.
 *
 * The strings themselves live in copy.js, both registers side by side.
 */

import { h, button, micro, status } from './ui.js';
import { NOTICES, REMEDY_LABEL, SETTINGS_COPY, TOPICS, say } from './copy.js';

const TOPIC_BY_ID = new Map(TOPICS.map((topic) => [topic.id, topic]));

/** The guide overlay: topic list on the left, prose on the right. */
export function guideOverlay({ topicId, register, onTopic, onRegister, onClose }) {
  const topic = TOPIC_BY_ID.get(topicId) || TOPICS[0];
  return h('div', { class: 'guide-scrim', onClick: onClose },
    h('div', { class: 'guide', onClick: (event) => event.stopPropagation() },
      h('nav', { class: 'guide-rail' },
        micro('reading guide'),
        TOPICS.map((entry) => h('button', {
          class: 'guide-topic', type: 'button',
          'aria-current': String(entry.id === topic.id),
          onClick: () => onTopic(entry.id),
        },
          h('span', { class: 'guide-topic-title' }, say(entry.title, register)),
          h('span', { class: 'guide-topic-blurb' }, say(entry.blurb, register)),
        )),
      ),
      h('div', { class: 'guide-body' },
        h('div', { class: 'guide-content' },
          h('div', { class: 'guide-head' },
            h('h2', {}, say(topic.title, register)),
            registerToggle(register, onRegister),
          ),
          say(topic.body, register).map(([heading, text]) =>
            h('section', { class: 'guide-section' }, h('h3', {}, heading), h('p', {}, text))),
        ),
        h('div', { class: 'guide-foot' },
          button('Close', { variant: 'primary', onClick: onClose }),
          h('span', { class: 'readout lo' }, 'reopen any time from Guide in the top bar'),
        ),
      ),
    ),
  );
}

function registerToggle(register, onRegister) {
  return h('div', { class: 'register-toggle', role: 'group', 'aria-label': 'Explanation depth' },
    [['simple', 'Simple'], ['advanced', 'Advanced']].map(([value, label]) =>
      h('button', {
        class: 'register-option', type: 'button',
        'aria-pressed': String(value === register),
        onClick: () => onRegister(value),
      }, label)),
  );
}

/** Why a check's statistics can't support its own verdict, and the exact
 *  lines that would settle it. Shown in full on the open row rather than
 *  hidden behind a tooltip, because it's what the reader needs most. */
export function reliabilityNotice(assertion, register, { onLearnMore }) {
  const verdict = assertion.reliability;
  const notice = NOTICES[verdict.code];
  const body = notice
    ? say(notice, register)(verdict.detail || {})
    : verdict.summary;  // an unknown code still says something
  const heading = notice
    ? say(notice.heading, register)
    : 'Unreliable statistic';

  return h('div', { class: 'reliability' },
    h('div', { class: 'reliability-head' },
      status('warn', heading),
      h('span', { class: 'readout lo' }, `method: ${assertion.method || 'unknown'}`),
    ),
    h('p', { class: 'reliability-body' }, body),
    (verdict.remedies || []).length
      ? h('div', { class: 'remedies' },
        micro(say(REMEDY_LABEL, register)),
        verdict.remedies.map((remedy) => h('div', { class: 'remedy' },
          h('code', {}, remedy),
          copyButton('Copy', remedy),
        )),
      )
      : null,
    h('button', { class: 'btn btn-ghost', type: 'button', onClick: onLearnMore },
      register === 'simple' ? 'What does this mean?' : 'On test validity'),
  );
}

/** Viewer preferences, including bringing dismissed notices back. */
export function settingsOverlay({
  prefs, register, runSettings, onChange, onRegister, onResetNotices, onClose,
}) {
  const checkbox = (key, copy) => h('label', { class: 'settings-row' },
    h('input', {
      type: 'checkbox', checked: !!prefs[key],
      onChange: (event) => onChange(key, event.target.checked),
    }),
    h('span', {},
      h('span', { class: 'settings-label' }, copy.label),
      h('span', { class: 'settings-hint' }, say(copy.hint, register))),
  );

  return h('div', { class: 'guide-scrim', onClick: onClose },
    h('div', { class: 'settings', onClick: (event) => event.stopPropagation() },
      h('h2', {}, 'Settings'),
      h('div', { class: 'settings-group' },
        h('div', { class: 'settings-row' },
          registerToggle(register, onRegister),
          h('span', {},
            h('span', { class: 'settings-label' }, SETTINGS_COPY.register.label),
            h('span', { class: 'settings-hint' }, say(SETTINGS_COPY.register.hint, register))),
        ),
      ),
      h('div', { class: 'settings-group' },
        checkbox('showTour', SETTINGS_COPY.showTour),
        checkbox('overlayExpected', SETTINGS_COPY.overlayExpected),
      ),
      h('div', { class: 'settings-group' },
        h('div', { class: 'settings-row' },
          button(SETTINGS_COPY.reset.label, { variant: 'secondary', onClick: onResetNotices }),
          h('span', {},
            h('span', { class: 'settings-hint' }, say(SETTINGS_COPY.reset.hint, register))),
        ),
      ),
      h('div', { class: 'settings-group' },
        micro(SETTINGS_COPY.runSettings.label),
        Object.keys(runSettings || {}).length
          ? h('dl', { class: 'settings-facts' },
            Object.entries(runSettings).map(([key, value]) => [
              h('dt', {}, key.replace(/_/g, ' ')),
              h('dd', {}, String(value)),
            ]))
          : h('p', { class: 'settings-hint' }, say(SETTINGS_COPY.runSettingsMissing, register)),
        h('p', { class: 'settings-hint' }, say(SETTINGS_COPY.runSettings.hint, register)),
      ),
      h('div', { class: 'guide-foot' },
        button('Close', { variant: 'primary', onClick: onClose }),
      ),
    ),
  );
}

/** Copy text, reporting through the button itself rather than a toast. */
export function copyButton(label, text) {
  const element = button(label, {
    variant: 'secondary',
    onClick: async () => {
      try {
        await navigator.clipboard.writeText(text);
        element.textContent = 'Copied';
      } catch {
        // Clipboard access is refused on insecure origins in some
        // browsers; selecting the text is the fallback that always works.
        element.textContent = 'Press Ctrl/Cmd+C';
        select(element.closest('.remedy')?.querySelector('code'));
      }
      setTimeout(() => { element.textContent = label; }, 1600);
    },
  });
  return element;
}

function select(node) {
  if (!node) return;
  const range = document.createRange();
  range.selectNodeContents(node);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}
