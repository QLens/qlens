/* Every explanatory string in the viewer, in two registers.
 *
 * `simple` assumes no quantum background and spends words on what a
 * thing is before naming it. `advanced` assumes the reader knows the
 * field and wants the fact without the scaffolding. Settings switches
 * between them.
 *
 * Both registers live here rather than beside their components so a
 * change to one is a change made next to the other, and neither drifts
 * into being the only one anybody maintains.
 */

export const REGISTERS = ['simple', 'advanced'];

/** Pick a register's text, falling back rather than rendering nothing. */
export const say = (entry, register) =>
  (entry && (entry[register] ?? entry.simple ?? entry.advanced)) ?? '';

/* ---------- the guided tour over the timeline ---------- */

export const TOUR = {
  title: {
    simple: 'Reading the waterfall',
    advanced: 'Amplitude waterfall',
  },
  lede: {
    simple:
      "Every column is one gate. Every row is one possible answer. It's the "
      + "whole run at once, so you don't have to scrub around hunting for "
      + 'where things went wrong.',
    advanced:
      'Columns are gate positions, rows are computational basis states. '
      + 'The full amplitude history in one view.',
  },
  colour: {
    label: 'colour = phase',
    simple:
      "Hue is that amplitude's phase. Brightness is how much weight the "
      + "answer carries. You can't measure phase directly, but it's what "
      + 'decides whether possibilities reinforce or cancel later.',
    advanced:
      'Hue maps arg(amplitude) over −π to +π; lightness maps |amplitude|, '
      + 'normalized against a high percentile of the field.',
  },
  position: {
    label: 'x = position',
    simple: (count) =>
      `Left to right is time: ${count} columns, one for each gate applied.`,
    advanced: (count) => `${count} gate positions, in execution order.`,
  },
  cursor: {
    label: 'the cursor',
    simple:
      "Everything below the waterfall reads the state at this column. Drag "
      + 'anywhere on the field to move it.',
    advanced:
      'The cursor position every panel below reads from. Drag the field, '
      + 'the wire strip, or the scrubber.',
  },
  marks: {
    label: 'assertion rules',
    simple:
      "Green passed, red failed. shift+←→ jumps between them, and the panel "
      + "below shows whichever one you're nearest.",
    advanced:
      'Assertion markers at their recorded positions. shift+←→ steps '
      + 'between them.',
  },
  strip: {
    label: 'circuit shares this axis',
    simple:
      'The wire strip maps x the same way, so a break in the field lines up '
      + 'with the gate that caused it.',
    advanced: 'Per-qubit gate incidence on the same x scale as the field.',
  },
  foot: {
    simple: 'shown once · reopen from the ◎ in the panel header',
    advanced: 'shown once · reopen from the ◎ in the panel header',
  },
};

/* ---------- the reading guide ---------- */

export const TOPICS = [
  {
    id: 'overview',
    title: { simple: 'What am I looking at?', advanced: 'Overview' },
    blurb: { simple: 'Start here', advanced: 'Scope and layout' },
    body: {
      simple: [
        ['A program, frozen at every step',
          "A quantum program is a list of steps called gates. Qlens ran yours "
          + "and photographed it after every single gate, so what you're "
          + "looking at is the whole run, not just the answer at the end."],
        ['Why that helps',
          "When a program gives the wrong answer, the answer alone doesn't "
          + "tell you which step broke it. Having every step recorded lets "
          + "you scrub back until the picture stops matching what you "
          + "expected, and that's the step to look at."],
        ['The four tabs',
          "Timeline is the whole run at once. State is a close-up of one "
          + "moment. Diff compares two moments. Assertions lists the checks "
          + "your test made and whether they held."],
      ],
      advanced: [
        ['What is recorded',
          'One statevector per gate position, spooled to a compressed '
          + 'sidecar beside the trace. Nothing here re-executes the circuit.'],
        ['The four tabs',
          'Timeline: the amplitude history plus transport. State: '
          + 'probabilities at the cursor against any recorded expectation. '
          + 'Diff: fidelity and per-basis delta between two pinned '
          + 'positions. Assertions: recorded checks, their statistics, and '
          + 'their coverage over the run.'],
      ],
    },
  },
  {
    id: 'waterfall',
    title: { simple: 'The waterfall', advanced: 'Amplitude waterfall' },
    blurb: { simple: 'The big coloured panel', advanced: 'Encoding and reduction' },
    body: {
      simple: [
        ['Left to right is time',
          "Each vertical sliver is one gate. The leftmost is the first thing "
          + 'your program did, the rightmost is the last.'],
        ['Top to bottom is possible answers',
          "A quantum program doesn't hold one answer while it runs. It holds "
          + 'a weight on every possible answer at once, and each row is one '
          + 'of those answers written in binary: for three qubits the rows '
          + 'run |000⟩ at the top through |111⟩ at the bottom.'],
        ['Brightness is how likely',
          "A bright row is an answer carrying a lot of weight at that "
          + "moment. A black row is carrying almost none. Watching "
          + "brightness move left to right is watching the program make up "
          + 'its mind.'],
        ['Colour is phase',
          "Phase is the part of a quantum state you can't see by measuring, "
          + 'but it decides how the possibilities add up or cancel out '
          + "later. Two answers with opposing phases wipe each other out, "
          + "and that cancellation is the whole trick of quantum computing. "
          + "The colour's there so you can see it coming."],
        ['A column that goes dark',
          "When most of the picture darkens at one gate, possibilities just "
          + 'cancelled and the program concentrated onto a few answers. If '
          + "that happens where you didn't intend it, you've found your bug."],
      ],
      advanced: [
        ['Axes',
          'x is gate position, y is basis state index in canonical '
          + 'big-endian order (qubit 0 leftmost).'],
        ['Colour',
          'Hue is arg(amplitude) over −π to +π; lightness is |amplitude|. '
          + 'Both are quantized to 8 bits server-side and mapped through an '
          + 'OKLCH table, so the phase wheel is perceptually even.'],
        ['Normalization',
          'Magnitude normalizes against the 99.5th percentile of the field, '
          + 'not its maximum. Position 0 is a basis state at magnitude 1 and '
          + 'would otherwise set the scale for the whole run. Values above '
          + 'the percentile clip.'],
        ['Row reduction',
          'Above the display height, rows band together and each band shows '
          + "its largest-magnitude row, carrying that row's phase. The "
          + 'collapse control drops basis states whose magnitude never '
          + 'reaches a threshold anywhere in the run; a dashed rule marks '
          + 'where states were skipped.'],
      ],
    },
  },
  {
    id: 'positions',
    title: { simple: 'Positions and gates', advanced: 'Positions and transport' },
    blurb: { simple: 'What the numbers mean', advanced: 'Addressing the run' },
    body: {
      simple: [
        ['Position is a step number',
          'Position 0 is the state just after the first gate, position 1 '
          + 'after the second, and so on. The strip under the waterfall '
          + 'shows which qubits each gate touched, on the same left-to-right '
          + 'scale.'],
        ['Moving around',
          'Drag anywhere on the waterfall or the strip to move the cursor. '
          + 'Arrow keys step one gate at a time, space plays through, and '
          + 'shift with an arrow key jumps to the next check.'],
      ],
      advanced: [
        ['Positions',
          'Zero-based gate index in execution order. Layer-mode traces still '
          + 'spool every position, so the axis is per gate whichever capture '
          + 'mode recorded the run.'],
        ['Addressing from a test',
          'assert_distribution and assert_state take at=, which accepts '
          + 'negative indices and marks that position on this timeline.'],
        ['Transport',
          'space plays, ←→ steps, shift+←→ jumps between assertions, '
          + 'home/end go to the ends, 1–4 switch tabs.'],
      ],
    },
  },
  {
    id: 'checks',
    title: { simple: 'How checks are tested', advanced: 'Distribution tests' },
    blurb: { simple: 'Reading the Assertions tab', advanced: 'Methods and validity' },
    body: {
      simple: [
        ['What a check is',
          'A line in your test saying what you expected, for example that '
          + 'the answers should come out half |00⟩ and half |11⟩. Qlens '
          + 'compares that against what the program produced.'],
        ["Why comparing isn't obvious",
          "A quantum program is measured by running it many times and "
          + "counting the answers, a bit like polling. Even a perfectly "
          + "correct program never gives a perfect 50/50 split, the same way "
          + "1000 coin flips rarely give exactly 500 heads. So a check has "
          + 'to decide how much wobble is acceptable, and there’s more than '
          + 'one way to decide.'],
        ['chi_square',
          'The classic method. It answers "if the program were correct, how '
          + 'surprising would this result be?" and reports a p-value, where '
          + 'small means surprising. It assumes every possible answer turns '
          + "up a few times, which often isn't true for quantum programs."],
        ['chi_square_exact',
          'The same question, answered by simulating thousands of correct '
          + 'runs and seeing where yours falls among them. Slower, and right '
          + 'no matter how rare some answers are.'],
        ['tvd',
          'A different question: "how far apart are these two sets of '
          + 'answers?" The result is a distance from 0 to 1, where 0.02 '
          + "means they disagree about 2% of the time. That's easier to "
          + 'picture than a p-value.'],
        ['If a check is flagged',
          "A yellow UNRELIABLE badge means the method you chose doesn't suit "
          + "this data, so its verdict can't be trusted in either direction. "
          + "Qlens won't switch methods behind your back. Open the row to "
          + 'see why and to copy the line that fixes it.'],
      ],
      advanced: [
        ['chi_square',
          "Pearson's goodness-of-fit against the asymptotic χ² distribution. "
          + 'tolerance is the significance level; the assertion passes when '
          + 'p ≥ tolerance.'],
        ['chi_square_exact',
          'The same statistic with the p-value drawn from `resamples` '
          + 'multinomial draws under the null, so it makes no asymptotic '
          + 'assumption. The observed table counts as one of its own '
          + 'reference draws, which bounds the reported p-value below by '
          + '1/(resamples+1).'],
        ['tvd',
          'Total variation distance, ½Σ|p_obs − p_exp|, in [0, 1]. tolerance '
          + 'is that distance. Reported alongside the sampling noise floor: '
          + 'the 95th percentile of TVD under the null at the same shot '
          + 'count.'],
        ['ks',
          'Kolmogorov-Smirnov over continuous samples, one-sample against a '
          + 'named scipy distribution or two-sample against reference draws.'],
        ['Validity flags',
          "chi_square is flagged when any cell's expected count falls below "
          + 'min_expected_count (5 by default), where the asymptotic p-value '
          + 'stops holding and swings on the sampling seed. tvd is flagged '
          + 'when tolerance falls under the noise floor. Qlens reports and '
          + 'never substitutes; on_unreliable_statistics decides whether '
          + 'that warns, raises, or stays silent.'],
      ],
    },
  },
  {
    id: 'state',
    title: { simple: 'The State and Diff tabs', advanced: 'State and Diff' },
    blurb: { simple: 'Close-ups and comparisons', advanced: 'Per-position readouts' },
    body: {
      simple: [
        ['State',
          'The bars are how likely each answer is at the cursor. If your '
          + 'test said what it expected, that expectation is drawn as a grey '
          + 'ghost behind the bars, so a bar taller or shorter than its '
          + 'ghost is a disagreement you can see.'],
        ['Diff',
          'Pin two positions and compare them. Fidelity is the headline: 1.0 '
          + 'means the two moments are the same state, 0.0 means they have '
          + 'nothing in common. The bars below show which answers moved.'],
      ],
      advanced: [
        ['State',
          'Per-basis probabilities at the cursor, bar hue carrying phase. '
          + 'Any expectation recorded by a nearby assert_distribution is '
          + 'overlaid. Amplitudes come from the sidecar at full precision, '
          + 'not from the quantized waterfall planes.'],
        ['Diff',
          'Fidelity |⟨ψ_A|ψ_B⟩|², L2 distance between probability vectors, '
          + 'and the count of basis states whose probability moved by more '
          + 'than 0.004. Delta bars are signed, coloured by phase at B.'],
      ],
    },
  },
];

/* ---------- reliability notices ---------- */

/* Keyed by the verdict code recorded on the trace, so the viewer states
 * the case in the reader's register rather than replaying the one string
 * the Python warning used. An unknown code falls back to that string. */
export const NOTICES = {
  sparse_cells: {
    heading: { simple: 'This check can’t be trusted', advanced: 'Unreliable statistic' },
    simple: (d) =>
      `This method assumes every possible answer turns up about ${fmt(d.threshold)} `
      + `times or more. Here ${fmt(d.cells_below_threshold)} of `
      + `${fmt(d.cells_total)} answers were expected fewer than that `
      + `(the rarest, ${sig(d.smallest_expected_count)} times), and when that `
      + `happens the verdict can be wrong in either direction: it can fail a `
      + `correct program, and it can pass a broken one.`,
    advanced: (d) =>
      `${fmt(d.cells_below_threshold)} of ${fmt(d.cells_total)} cells have `
      + `expected counts below ${fmt(d.threshold)} (min `
      + `${sig(d.smallest_expected_count)}), so the asymptotic χ² `
      + `approximation doesn't hold and the p-value is uninformative in `
      + `both tails.`,
  },
  tolerance_below_noise: {
    heading: { simple: 'This check can’t be trusted', advanced: 'Tolerance under the noise floor' },
    simple: (d) =>
      `Measuring ${fmt(d.shots)} times lands about ${d.noise_floor.toFixed(4)} `
      + `away from the expected answers all by itself, just from sampling. `
      + `Asking for ${d.tolerance.toFixed(4)} is asking for closer agreement `
      + `than that, so correct programs will fail this check most of the time.`,
    advanced: (d) =>
      `The null TVD at ${fmt(d.shots)} shots has a 95th percentile of `
      + `${d.noise_floor.toFixed(4)}, above the tolerance of `
      + `${d.tolerance.toFixed(4)}. The check rejects at close to its full `
      + `rate regardless of the circuit.`,
  },
};

export const REMEDY_LABEL = {
  simple: 'try one of these instead',
  advanced: 'use instead',
};

/* ---------- settings ---------- */

export const SETTINGS_COPY = {
  register: {
    label: 'Explanations',
    hint: {
      simple:
        'Simple spells things out for anyone new to quantum computing. '
        + 'Advanced assumes you know the field and keeps it brief.',
      advanced:
        'Advanced assumes familiarity with the field. Simple explains from '
        + 'first principles.',
    },
  },
  showTour: {
    label: 'Show the waterfall tour on a new run',
    hint: {
      simple: 'The annotated overlay pointing at the parts of the timeline.',
      advanced: 'Anchored annotations over the timeline panels.',
    },
  },
  overlayExpected: {
    label: 'Overlay the expected distribution',
    hint: {
      simple:
        "Ghost what a test expected behind the observed bars, wherever a "
        + 'test said what it expected.',
      advanced: 'Overlay any recorded expectation behind the observed bars.',
    },
  },
  reset: {
    label: 'Reset dismissed notices',
    hint: {
      simple:
        "Brings back the tour and any guidance you've dismissed. Handy if "
        + 'you clicked one away before reading it.',
      advanced: 'Restores the tour and every dismissed notice.',
    },
  },
  runSettings: {
    label: 'how this run was checked',
    hint: {
      simple:
        'These were fixed when the test ran, so they can’t be changed here. '
        + 'Set them in your project’s pyproject.toml under [tool.qlens], or '
        + 'per call with test= on an assertion.',
      advanced:
        'Recorded at run time. Set in [tool.qlens], via qlens.configure(), '
        + 'or per call.',
    },
  },
  runSettingsMissing: {
    simple:
      'This run was recorded before Qlens stored its settings, so which '
      + 'methods it used isn’t known. Newer runs carry them.',
    advanced: 'Recorded before settings were stored on the trace.',
  },
};

const fmt = (value) =>
  Number.isFinite(value) ? String(Math.round(value)) : '—';

const sig = (value) => {
  if (!Number.isFinite(value)) return '—';
  if (value >= 0.01) return value.toFixed(2);
  return value.toExponential(1);
};
