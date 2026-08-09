/* The reading guide, and the settings that control it.
 *
 * Written for someone who has never used a quantum computer. Anyone who
 * already knows this can dismiss it in one click and never see it again;
 * someone who does not has nowhere else to find it, and a viewer full of
 * unexplained colour is useless to them. So the guide is always one
 * click away from the top bar, never buried, and never permanently
 * dismissed: Settings can bring every notice back.
 */

import { h, panel, button, micro, clear } from './ui.js';

export const TOPICS = [
  {
    id: 'overview',
    title: 'What am I looking at?',
    blurb: 'Start here',
    body: [
      ['A program, frozen at every step',
        'A quantum program is a list of steps, called gates. Qlens ran your '
        + 'program and photographed it after every single gate, so what you '
        + 'are looking at is the whole run, not just the answer at the end.'],
      ['Why that is useful',
        'When a program gives the wrong answer, the answer alone does not '
        + 'tell you which step broke it. Having every step recorded lets you '
        + 'scrub back until the picture stops matching what you expected, '
        + 'and that is the step to look at.'],
      ['The four tabs',
        'Timeline is the whole run at once. State is a close-up of one '
        + 'moment. Diff compares two moments. Assertions lists the checks '
        + 'your test made and whether they held.'],
    ],
  },
  {
    id: 'waterfall',
    title: 'The waterfall',
    blurb: 'The big coloured panel',
    body: [
      ['Left to right is time',
        'Each vertical sliver is one gate. The leftmost is the first thing '
        + 'your program did, the rightmost is the last.'],
      ['Top to bottom is possible answers',
        'A quantum program does not hold one answer while it runs, it holds '
        + 'a weight on every possible answer at once. Each row is one of '
        + 'those possible answers, written in binary: for three qubits the '
        + 'rows run |000> at the top through |111> at the bottom.'],
      ['Brightness is how likely',
        'A bright row is an answer carrying a lot of weight at that moment. '
        + 'A black row is one carrying almost none. Watching brightness move '
        + 'left to right is watching the program make up its mind.'],
      ['Colour is phase',
        'Phase is the part of a quantum state you cannot see by measuring, '
        + 'but which decides how the possibilities add up or cancel out '
        + 'later. Two answers with opposing phases can wipe each other out. '
        + 'That cancellation is the whole trick of quantum computing, and '
        + 'the colour is there so you can see it coming.'],
      ['A column that goes dark',
        'When most of the picture darkens at one gate, possibilities just '
        + 'cancelled and the program concentrated onto a few answers. If '
        + 'that happens where you did not intend it, you have found your bug.'],
    ],
  },
  {
    id: 'positions',
    title: 'Positions and gates',
    blurb: 'What the numbers mean',
    body: [
      ['Position is a step number',
        'Position 0 is the state just after the first gate, position 1 after '
        + 'the second, and so on. The strip under the waterfall shows which '
        + 'qubits each gate touched, on the same left-to-right scale.'],
      ['Moving around',
        'Drag anywhere on the waterfall or the strip to move the cursor. '
        + 'Arrow keys step one gate at a time, space plays through, and '
        + 'shift with an arrow key jumps to the next check.'],
    ],
  },
  {
    id: 'checks',
    title: 'How checks are tested',
    blurb: 'Reading the Assertions tab',
    body: [
      ['What a check is',
        'A line in your test saying what you expected, for example that the '
        + 'answers should come out half |00> and half |11>. Qlens compares '
        + 'that against what the program produced.'],
      ['Why comparing is not obvious',
        'A quantum program is measured by running it many times and counting '
        + 'the answers, like polling. Even a perfectly correct program never '
        + 'gives a perfect 50/50 split, the same way 1000 coin flips rarely '
        + 'give exactly 500 heads. So a check has to decide how much wobble '
        + 'is acceptable, and there is more than one way to decide.'],
      ['chi_square',
        'The classic method. It answers "if the program were correct, how '
        + 'surprising would this result be?" and reports a p-value: small '
        + 'means surprising. It assumes every possible answer turns up a few '
        + 'times, which is often false for quantum programs.'],
      ['chi_square_exact',
        'The same question, answered by simulating thousands of correct runs '
        + 'and seeing where yours falls among them. Slower, and right no '
        + 'matter how rare some answers are.'],
      ['tvd',
        'A different question: "how far apart are these two sets of answers?" '
        + 'The result is a distance from 0 to 1, where 0.02 means they '
        + 'disagree about 2% of the time. Easier to picture than a p-value.'],
      ['If a check is flagged',
        'A yellow UNRELIABLE badge means the method you chose does not suit '
        + 'this data, so its verdict cannot be trusted in either direction. '
        + 'Qlens will not switch methods behind your back. Open the row to '
        + 'see why and to copy the line that fixes it.'],
    ],
  },
  {
    id: 'state',
    title: 'The State and Diff tabs',
    blurb: 'Close-ups and comparisons',
    body: [
      ['State',
        'The bars are how likely each answer is at the cursor. If your test '
        + 'said what it expected, that expectation is drawn as a grey ghost '
        + 'behind the bars, so a bar taller or shorter than its ghost is a '
        + 'disagreement you can see.'],
      ['Diff',
        'Pin two positions and compare them. Fidelity is the headline: 1.0 '
        + 'means the two moments are the same state, 0.0 means they have '
        + 'nothing in common. The bars below show which answers moved.'],
    ],
  },
];

const TOPIC_BY_ID = new Map(TOPICS.map((topic) => [topic.id, topic]));

/** The guide overlay: topic list on the left, prose on the right. */
export function guideOverlay({ topicId, onTopic, onClose }) {
  const topic = TOPIC_BY_ID.get(topicId) || TOPICS[0];
  const content = h('div', { class: 'guide-content' },
    h('h2', {}, topic.title),
    topic.body.map(([heading, text]) => h('section', { class: 'guide-section' },
      h('h3', {}, heading),
      h('p', {}, text),
    )),
  );
  return h('div', { class: 'guide-scrim', onClick: onClose },
    h('div', { class: 'guide', onClick: (event) => event.stopPropagation() },
      h('nav', { class: 'guide-rail' },
        micro('reading guide'),
        TOPICS.map((entry) => h('button', {
          class: 'guide-topic', type: 'button',
          'aria-current': String(entry.id === topic.id),
          onClick: () => onTopic(entry.id),
        },
          h('span', { class: 'guide-topic-title' }, entry.title),
          h('span', { class: 'guide-topic-blurb' }, entry.blurb),
        )),
      ),
      h('div', { class: 'guide-body' },
        content,
        h('div', { class: 'guide-foot' },
          button('Close', { variant: 'primary', onClick: onClose }),
          h('span', { class: 'readout lo' }, 'reopen any time from Guide in the top bar'),
        ),
      ),
    ),
  );
}

/** Viewer preferences, including bringing dismissed notices back. */
export function settingsOverlay({ prefs, runSettings, onChange, onResetNotices, onClose }) {
  const rows = [
    ['Show the waterfall tour on a new run',
      'The annotated overlay pointing at the parts of the timeline.',
      'showTour'],
    ['Overlay the expected distribution',
      'Ghost what a test expected behind the observed bars, where a test said.',
      'overlayExpected'],
  ];
  return h('div', { class: 'guide-scrim', onClick: onClose },
    h('div', { class: 'settings', onClick: (event) => event.stopPropagation() },
      h('h2', {}, 'Settings'),
      h('div', { class: 'settings-group' },
        rows.map(([label, hint, key]) => h('label', { class: 'settings-row' },
          h('input', {
            type: 'checkbox', checked: !!prefs[key],
            onChange: (event) => onChange(key, event.target.checked),
          }),
          h('span', {},
            h('span', { class: 'settings-label' }, label),
            h('span', { class: 'settings-hint' }, hint)),
        )),
      ),
      h('div', { class: 'settings-group' },
        h('div', { class: 'settings-row' },
          button('Reset dismissed notices', { variant: 'secondary', onClick: onResetNotices }),
          h('span', {},
            h('span', { class: 'settings-hint' },
              'Brings back the tour and any guidance you have dismissed. '
              + 'Useful if you clicked one away before reading it.')),
        ),
      ),
      h('div', { class: 'settings-group' },
        micro('how this run was checked'),
        Object.keys(runSettings || {}).length
          ? h('dl', { class: 'settings-facts' },
            Object.entries(runSettings).map(([key, value]) => [
              h('dt', {}, key.replace(/_/g, ' ')),
              h('dd', {}, String(value)),
            ]))
          : h('p', { class: 'settings-hint' },
            'This run predates settings recording, so its test defaults are '
            + 'unknown. Runs recorded from now on carry them.'),
        h('p', { class: 'settings-hint' },
          'These were fixed when the test ran and cannot be changed here. '
          + 'Set them in your project’s pyproject.toml under [tool.qlens], '
          + 'or per call with test= on an assertion.'),
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

export { clear, panel };
