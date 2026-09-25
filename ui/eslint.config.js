import { defineConfig } from 'eslint/config'
import nodePath from 'node:path'
import { fileURLToPath } from 'node:url'

import js from '@eslint/js'
import prettier from 'eslint-config-prettier'
import jsdoc from 'eslint-plugin-jsdoc'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import paths from 'eslint-plugin-paths'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import tailwindcss from 'eslint-plugin-tailwindcss'
import globals from 'globals'
import tseslint from 'typescript-eslint'

const __dirname = nodePath.dirname(fileURLToPath(import.meta.url))

// The props a person reads or hears: a string literal in them is interface text
const TEXT_ATTRIBUTES =
  '/^(aria-label|aria-description|aria-valuetext|title|placeholder|alt|label|hint|confirm|description|empty|tooltip)$/'
// A string with a letter in it: numbers and signs like "404" or "/" are the same in every language
const WORD = '/[A-Za-zА-Яа-яЁё]/'

export default defineConfig([
  {
    ignores: [
      '**/node_modules/**',
      '**/dist/**',
      '**/build/**',
      '**/.cache/**',
      '**/.git/**',
      '**/temp/**',
      '**/dist-test/**',
      '**/dist-npm/**',
      '**/packages-dist-npm/**',
      '**/artifacts/**',
      '**/generated/**',
    ],
  },

  {
    plugins: {
      '@typescript-eslint': tseslint.plugin,
      jsdoc,
      tailwindcss,
      paths,
    },
    settings: {
      tailwindcss: {
        cssConfigPath: __dirname + '/src/styles/index.css',
      },
    },
    languageOptions: {
      parserOptions: {
        tsconfigRootDir: __dirname,
        project: true,
      },
    },
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,
  tailwindcss.configs.recommended,

  {
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-namespace': 'off',
      '@typescript-eslint/no-require-imports': 'off',
      'no-irregular-whitespace': 'off',

      'object-shorthand': 'error',
      'no-shadow': ['error', { allow: ['className', 'props', 'error'], ignoreOnInitialization: true }],
      '@typescript-eslint/await-thenable': 'error',
      '@typescript-eslint/no-unnecessary-condition': 'error',
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/promise-function-async': 'error',
      '@typescript-eslint/return-await': ['error', 'always'],
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'separate-type-imports' },
      ],
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-console': 'error',
      // Env belongs to the shapes in `src/modules/env`, which type it, validate it lazily per variable, and decide what
      // reaches the browser. A raw read gets none of that and is invisible to all three.
      'no-restricted-properties': [
        'error',
        {
          object: 'process',
          property: 'env',
          message:
            'Read env through the typed handles — serverEnv / clientEnv / sharedEnv in @/modules/env. Missing a variable? Add it to the matching shape (server.ts for secrets, shared.ts for both sides / the browser).',
        },
      ],
      'jsdoc/check-line-alignment': 'error',
      'paths/alias': ['error', { configFilePath: './tsconfig.json' }],
      // `fix-font-accent` is a plain CSS class the email templates ship themselves
      'tailwindcss/no-custom-classname': ['error', { whitelist: ['fix-font-accent'] }],
      // Off until francoismassart/eslint-plugin-tailwindcss#469 is fixed: the autofix rewrites `leading-[1.65]` into
      // `leading-1.65`, which Tailwind 4 generates no CSS for, so `--fix` silently drops the line-height. The rule
      // takes no options, so it cannot be narrowed. Its real catches (`w-[100px]` → `w-25`) have to be done by hand.
      'tailwindcss/no-unnecessary-arbitrary-value': 'off',
    },
  },

  {
    files: ['**/ui/**/*.{jsx,tsx}'],
    rules: {
      'no-shadow': 'off',
    },
  },

  {
    // The only file-level exception to `no-restricted-properties`: this module IS the reader. `createEnv` parses
    // `process.env`, the shapes branch on it while they are being built, `client.ts` rewrites SERVER_URL before
    // anything reads it, and the test drives it by setting variables. Everywhere else uses a targeted inline disable.
    files: ['src/modules/env/**'],
    rules: {
      'no-restricted-properties': 'off',
    },
  },

  {
    files: ['**/*.{jsx,tsx}'],
    plugins: {
      react,
      'react-hooks': reactHooks,
      'jsx-a11y': jsxA11y,
    },
    languageOptions: {
      globals: {
        ...globals.browser,
      },
    },
    settings: {
      react: { version: 'detect' },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react/react-in-jsx-scope': 'off',
      'react-hooks/preserve-manual-memoization': 'off',
    },
  },

  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.es2021,
        ...globals.node,
        ...globals.browser,
      },
    },
  },

  {
    // The panel speaks through the catalog (src/modules/i18n): no bare text in any markup it can render
    // A primitive counts too: its words show up on every screen that uses it, so a list of screens is not enough
    files: ['src/**/*.tsx'],
    ignores: ['**/*.test.tsx'],
    plugins: { react },
    rules: {
      'react/jsx-no-literals': [
        'error',
        { noStrings: true, ignoreProps: true, allowedStrings: ['VibeDPN', '×', '·', '—', '/', ' '] },
      ],
      // jsx-no-literals skips props and the branches of an expression: the words that hide there
      'no-restricted-syntax': [
        'error',
        ...[
          `JSXAttribute[name.name=${TEXT_ATTRIBUTES}] > Literal[value=${WORD}]`,
          `JSXAttribute[name.name=${TEXT_ATTRIBUTES}] > JSXExpressionContainer > Literal[value=${WORD}]`,
          `:matches(JSXElement, JSXFragment) > JSXExpressionContainer > :matches(ConditionalExpression, LogicalExpression) > Literal[value=${WORD}]`,
        ].map((selector) => ({ selector, message: 'Text of the interface goes through the catalog: t(key)' })),
      ],
    },
  },

  prettier,

  {
    rules: {
      curly: ['error', 'all'],
    },
  },
])
