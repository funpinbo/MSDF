import dagre from '@dagrejs/dagre'

/**
 * dagre로 왼쪽→오른쪽 배치를 계산한다.
 * nodes: [{id, width, height, group?}], edges: [{source, target}]
 * group이 있으면 같은 그룹(서비스)을 한 상자로 묶는다.
 * 돌려주는 값: { positions: {id: {x, y}}, groups: {group: {x, y, width, height}} } (왼쪽 위 기준)
 */
export function layout(nodes, edges, { rankdir = 'LR', nodesep = 36, ranksep = 90, groupPad = 28 } = {}) {
  const g = new dagre.graphlib.Graph({ compound: true, multigraph: true })
  g.setGraph({ rankdir, nodesep, ranksep, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))
  const groups = new Set()
  for (const n of nodes) {
    g.setNode(n.id, { width: n.width, height: n.height })
    if (n.group) {
      if (!groups.has(n.group)) {
        g.setNode(`group:${n.group}`, { paddingTop: groupPad, paddingLeft: 16, paddingRight: 16, paddingBottom: 16 })
        groups.add(n.group)
      }
      g.setParent(n.id, `group:${n.group}`)
    }
  }
  edges.forEach((e, i) => {
    if (g.hasNode(e.source) && g.hasNode(e.target) && e.source !== e.target) g.setEdge(e.source, e.target, {}, `e${i}`)
  })
  dagre.layout(g)
  const positions = {}
  for (const n of nodes) {
    const p = g.node(n.id)
    positions[n.id] = { x: p.x - n.width / 2, y: p.y - n.height / 2 }
  }
  const boxes = {}
  for (const name of groups) {
    const p = g.node(`group:${name}`)
    boxes[name] = { x: p.x - p.width / 2, y: p.y - p.height / 2 - groupPad / 2, width: p.width, height: p.height + groupPad / 2 }
  }
  return { positions, groups: boxes }
}
