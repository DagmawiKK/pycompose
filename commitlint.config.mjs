// commitlint config — semantic (Conventional Commits) messages.
// Rules mirror AGENTS.md "Commit messages": no filler terms such as
// "phase", "wip", "update", "some" in the subject.
const FORBIDDEN = /\b(?:phase|wip|some|update|nit|stuff)\b/i;

export default {
  extends: ['@commitlint/config-conventional'],
  plugins: [
    {
      rules: {
        'pycompose/no-filler': ({ subject }) => [
          !FORBIDDEN.test(subject ?? ''),
          `subject must not contain filler terms (phase, wip, some, update, ...)`,
        ],
      },
    },
  ],
  rules: {
    'header-max-length': [2, 'always', 72],
    'subject-full-stop': [2, 'never', '.'],
    'pycompose/no-filler': [2, 'always'],
  },
};
