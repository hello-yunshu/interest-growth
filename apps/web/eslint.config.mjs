import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';

export default defineConfig([
  ...nextVitals,
  {
    rules: {
      // These compact client pages intentionally load remote state from mount/
      // selection effects. React 19's compiler advisory is not a correctness
      // failure for this product architecture.
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/exhaustive-deps': 'off',
      '@next/next/no-img-element': 'off',
    },
  },
  globalIgnores(['out/**', '.next/**', 'node_modules/**']),
]);
