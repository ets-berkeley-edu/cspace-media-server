import globals from 'globals'
import importPlugin from 'eslint-plugin-import'
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'
import vueParser from 'vue-eslint-parser'

// BOA's rules (github.com/ets-berkeley-edu/boac, eslint.config.js), so Serena's admin app reads like the team's other apps.
// Two differences, both on purpose:
//   - vue/no-v-html is an error here. The admin app shows text that comes from CollectionSpace and the ETL;
//     it is only ever rendered as text.
//   - BOA's scoped-CSS plugin and @vue/eslint-config-typescript are left out: each brings in packages that
//     `npm audit` reports, and the admin app keeps `npm audit` clean.
const vueLanguageOptions = {
  globals: {
    ...globals.node,
    ...globals.browser,
    // DOM types that TypeScript knows and ESLint's no-undef doesn't
    RequestInit: 'readonly',
    ScrollLogicalPosition: 'readonly'
  },
  parser: vueParser,
  parserOptions: {
    parser: tseslint.parser,
    extraFileExtensions: ['.vue']
  }
}

export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**']
  },
  {
    files: ['**/*.js', '**/*.ts', '**/*.vue'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      ...pluginVue.configs['flat/recommended'],
      importPlugin.flatConfigs.errors,
      importPlugin.flatConfigs.warnings,
      importPlugin.flatConfigs.typescript
    ],
    languageOptions: vueLanguageOptions,
    rules: {
      '@typescript-eslint/consistent-type-imports': 2,
      '@typescript-eslint/default-param-last': 2,
      '@typescript-eslint/no-explicit-any': 2,
      '@typescript-eslint/no-require-imports': 2,
      '@typescript-eslint/no-unsafe-function-type': 1,
      '@typescript-eslint/no-unused-vars': 2,
      'array-bracket-spacing': 2,
      eqeqeq: 2,
      'import/no-duplicates': 2,
      'import/no-unresolved': 0,
      'import/order': 2,
      'key-spacing': 2,
      'no-console': 2,
      'no-debugger': 2,
      'no-else-return': 2,
      'no-multi-spaces': 2,
      'no-trailing-spaces': 2,
      'no-undef': 2,
      'no-unexpected-multiline': 2,
      'object-curly-spacing': 2,
      quotes: [2, 'single'],
      semi: [2, 'never'],
      'sort-imports': [
        2,
        {
          ignoreCase: false,
          ignoreDeclarationSort: true,
          ignoreMemberSort: false,
          memberSyntaxSortOrder: ['none', 'all', 'multiple', 'single'],
          allowSeparatedGroups: true
        }
      ],
      'vue/arrow-spacing': 2,
      'vue/attributes-order': 2,
      'vue/block-order': 2,
      'vue/block-spacing': 2,
      'vue/brace-style': 2,
      'vue/camelcase': 2,
      'vue/comma-dangle': 2,
      'vue/component-name-in-template-casing': 2,
      'vue/no-deprecated-v-bind-sync': 2,
      'vue/eqeqeq': 2,
      'vue/html-closing-bracket-newline': 2,
      'vue/html-closing-bracket-spacing': 2,
      'vue/html-end-tags': 2,
      'vue/html-indent': 2,
      'vue/html-quotes': 2,
      'vue/html-self-closing': 2,
      'vue/attribute-hyphenation': 2,
      'vue/key-spacing': 2,
      'vue/match-component-file-name': 2,
      'vue/max-attributes-per-line': [2, {
        singleline: {
          max: 3
        },
        multiline: {
          max: 1
        }
      }],
      'vue/multi-word-component-names': 0,
      'vue/multiline-html-element-content-newline': 2,
      'vue/mustache-interpolation-spacing': 2,
      'vue/no-boolean-default': 2,
      'vue/no-deprecated-delete-set': 2,
      'vue/no-deprecated-destroyed-lifecycle': 2,
      'vue/no-deprecated-dollar-listeners-api': 2,
      'vue/no-deprecated-model-definition': 2,
      'vue/no-deprecated-props-default-this': 2,
      'vue/no-deprecated-slot-attribute': 2,
      'vue/no-deprecated-v-on-native-modifier': 2,
      'vue/no-multi-spaces': 2,
      'vue/no-multiple-template-root': 2,
      'vue/no-mutating-props': 2,
      'vue/no-required-prop-with-default': 2,
      'vue/no-restricted-props': 2,
      'vue/no-restricted-syntax': 2,
      'vue/no-undef-properties': 2,
      'vue/no-unused-refs': 2,
      'vue/no-use-v-if-with-v-for': 2,
      'vue/no-v-html': 2,
      'vue/no-v-for-template-key': 2,
      'vue/no-v-for-template-key-on-child': 2,
      'vue/no-v-model-argument': 2,
      'vue/no-v-text-v-html-on-component': 2,
      'vue/order-in-components': 2,
      'vue/require-default-prop': 2,
      'vue/require-direct-export': 2,
      'vue/require-prop-types': 2,
      'vue/script-indent': 2,
      'vue/singleline-html-element-content-newline': 0,
      'vue/space-infix-ops': 2,
      'vue/space-unary-ops': 2,
      'vue/this-in-template': 2,
      'vue/valid-define-options': 2,
      'vue/valid-v-else': 2,
      'vue/valid-next-tick': 2,
      'vue/valid-v-slot': [2, {allowModifiers: true}],
      'vue/v-bind-style': 2,
      'vue/v-on-event-hyphenation': 2,
      'vue/v-on-handler-style': 0,
      'vue/v-on-style': 2,
      'vue/v-slot-style': 2
    }
  },
  {
    // A test may define a small stand-in component or two beside the one it tests
    files: ['src/__tests__/**'],
    rules: {
      'vue/one-component-per-file': 0
    }
  }
)
