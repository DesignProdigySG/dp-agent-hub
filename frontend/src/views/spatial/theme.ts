import { useMemo } from 'react'

import { useHub } from '../../store/hub'
import type { Zone } from '../../types/contract'

/** Read Skinning Engine tokens so 3D materials follow the active theme. */
export function useSceneColors() {
  const theme = useHub((s) => s.theme)
  return useMemo(() => {
    const css = getComputedStyle(document.documentElement)
    const v = (name: string) => css.getPropertyValue(name).trim() || '#888888'
    const zone = (z: Zone) => v(`--zone-${z}`)
    return {
      theme,
      bg: v('--scene-bg'),
      floor: v('--scene-floor'),
      primary: v('--md-primary'),
      outline: v('--md-outline-variant'),
      error: v('--md-error'),
      onSurface: v('--md-on-surface'),
      zone,
    }
  }, [theme])
}
