import { useEffect, useState } from 'react';
import { api } from './api';

export function useCapabilityAvailability() {
  const [state, setState] = useState(null);
  useEffect(() => {
    let active = true;
    api('/system/capability-state').then(value => { if (active) setState(value); }).catch(() => {});
    return () => { active = false; };
  }, []);
  function available(feature, plugin) {
    if (!state) return true;
    if (feature && state.features?.[feature] === false) return false;
    if (plugin) {
      const row = state.plugins?.[plugin];
      if (!row || !row.installed || !row.enabled || row.area_enabled === false) return false;
    }
    return true;
  }
  return { state, available };
}
