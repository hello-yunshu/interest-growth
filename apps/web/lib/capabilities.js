import { useEffect, useState } from 'react';
import { api } from './api';

export function useCapabilityAvailability() {
  const [state, setState] = useState(null);
  const [status, setStatus] = useState('loading');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setStatus('loading');
    api('/system/capability-state').then(value => {
      if (!active) return;
      setState(value);
      setStatus('available');
    }).catch(() => {
      if (!active) return;
      setState(null);
      setStatus('error');
    });
    return () => { active = false; };
  }, [revision]);
  function available(feature, plugin) {
    if (status !== 'available' || !state) return false;
    if (feature && state.features?.[feature] === false) return false;
    if (feature && !(feature in (state.features || {}))) return false;
    if (plugin) {
      const row = state.plugins?.[plugin];
      if (!row || !row.installed || !row.enabled || row.area_enabled === false) return false;
    }
    return true;
  }
  function availabilityStatus(feature, plugin) {
    if (status === 'loading' || status === 'error') return status;
    return available(feature, plugin) ? 'available' : 'unavailable';
  }
  return { state, status, available, availabilityStatus, refresh: () => setRevision(value => value + 1) };
}
