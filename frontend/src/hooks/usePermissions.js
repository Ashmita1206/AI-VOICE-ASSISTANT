import { useState, useCallback } from 'react';

export function usePermissions() {
  const [permissions, setPermissions] = useState({});
  const [isChecking, setIsChecking] = useState(false);

  const checkPermissions = useCallback(async (permList = ['microphone', 'accessibility', 'automation']) => {
    setIsChecking(true);
    try {
      const res = await fetch('/permissions/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ permissions: permList }),
      });
      const data = await res.json();
      if (data.granted) {
        setPermissions(data.granted);
      }
    } catch (err) {
      console.error('[PERMISSIONS] Check error:', err);
    } finally {
      setIsChecking(false);
    }
  }, []);

  const grantPermission = useCallback(async (permissionName) => {
    try {
      const res = await fetch('/permissions/grant', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ permission: permissionName }),
      });
      const data = await res.json();
      if (data.success) {
        setPermissions((prev) => ({ ...prev, [permissionName]: true }));
      }
      return data.success;
    } catch (err) {
      console.error('[PERMISSIONS] Grant error:', err);
      return false;
    }
  }, []);

  return {
    permissions,
    isChecking,
    checkPermissions,
    grantPermission,
  };
}
