/**
 * Brick Lab builds (public/assets/brick-lab): ready-made furniture and props, modelled in the
 * brick kit's units (0.08 per stud) but at a bigger figure scale, so they're placed at
 * LAB_SCALE to sit right next to the agents. They keep their own colors.
 */

/** Their modelled size times this: close to the bricks' scale while leaving each zone room to walk. */
export const LAB_SCALE = 0.45

export type LabGroup = 'office' | 'tech' | 'design' | 'showroom' | 'plants' | 'decor'

/** Model bounds, read from each .glb: [group, width x, height, depth z, center x, center z]. */
export const LAB_MODELS = {
  'desk-lamp': ['decor', 0.192, 0.393, 0.346, 0, 0.056],
  'launch-rocket': ['decor', 0.479, 0.67, 0.479, 0, 0],
  'brand-hologram': ['design', 0.48, 0.752, 0.408, 0, 0],
  'camera-tripod': ['design', 0.444, 0.657, 0.389, 0, 0.06],
  'colour-fan': ['design', 0.472, 0.367, 0.16, 0, 0],
  'designer-desk': ['design', 0.96, 0.838, 0.518, 0, 0.019],
  'drafting-stool': ['design', 0.255, 0.416, 0.255, 0, 0],
  'easel': ['design', 0.4, 0.824, 0.456, 0, 0.006],
  'mood-board': ['design', 0.96, 0.96, 0.24, 0, 0],
  'printer-3d': ['design', 0.559, 0.851, 0.571, 0, 0.006],
  'softbox-light': ['design', 0.431, 1.195, 0.406, 0, 0.017],
  'swatch-wall': ['design', 0.879, 1.024, 0.2, 0, 0.076],
  'bookshelf': ['office', 0.64, 0.882, 0.24, 0, 0],
  'coffee-station': ['office', 0.495, 0.771, 0.338, 0, 0.001],
  'desk-setup': ['office', 0.96, 0.742, 0.479, 0, 0],
  'glass-door': ['office', 0.479, 1.17, 0.09, 0, 0.005],
  'glass-wall': ['office', 0.64, 1.17, 0.079, 0, 0],
  'kanban-board': ['office', 0.72, 1.12, 0.24, 0, 0],
  'meeting-table': ['office', 1.521, 0.504, 1.447, 0, -0.028],
  'office-chair': ['office', 0.375, 0.504, 0.419, 0, -0.014],
  'office-floor': ['office', 1.28, 0.05, 1.28, 0, 0],
  'printer': ['office', 0.4, 0.158, 0.419, 0, 0.05],
  'sofa': ['office', 0.799, 0.352, 0.319, 0, 0],
  'water-cooler': ['office', 0.24, 0.829, 0.288, 0, 0.024],
  'plant-desk': ['plants', 0.18, 0.256, 0.177, 0, -0.001],
  'plant-monstera': ['plants', 0.966, 0.48, 0.634, -0.014, -0.014],
  'plant-snake': ['plants', 0.333, 0.732, 0.32, -0.013, 0.02],
  'plant-tree': ['plants', 0.479, 0.85, 0.479, 0, 0],
  'accessory-wall': ['showroom', 1.039, 1.139, 0.175, 0, 0.064],
  'holo-product-table': ['showroom', 0.799, 0.836, 0.799, 0, 0],
  'phone-display': ['showroom', 0.192, 0.198, 0.192, 0, 0],
  'planter-bench': ['showroom', 0.752, 1.352, 0.752, 0, 0],
  'product-table': ['showroom', 1.52, 0.668, 0.559, 0, 0],
  'support-bar': ['showroom', 1.52, 0.732, 0.74, 0, 0.126],
  'video-wall': ['showroom', 1.599, 1.152, 0.639, 0, 0.04],
  'watch-case': ['showroom', 0.319, 0.608, 0.319, 0, 0],
  'dashboard-screen': ['tech', 0.879, 0.992, 0.24, 0, 0],
  'database': ['tech', 0.56, 0.618, 0.56, 0, 0],
  'holo-funnel': ['tech', 0.656, 0.878, 0.655, 0, 0],
  'laptop': ['tech', 0.319, 0.284, 0.308, 0, -0.034],
  'router': ['tech', 0.382, 0.315, 0.253, 0, -0.019],
  'server-rack': ['tech', 0.4, 0.978, 0.413, 0, 0.007],
} as const satisfies Record<string, readonly [LabGroup, number, number, number, number, number]>

export type LabModel = keyof typeof LAB_MODELS
export const LAB_GROUPS: { group: LabGroup; label: string }[] = [
  { group: 'office', label: 'Office' },
  { group: 'tech', label: 'Tech' },
  { group: 'design', label: 'Design studio' },
  { group: 'showroom', label: 'Showroom' },
  { group: 'plants', label: 'Plants' },
  { group: 'decor', label: 'Decor' },
]
