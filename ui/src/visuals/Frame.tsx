import { forwardRef, useMemo } from "react";
import { BoxGeometry, BufferAttribute, Color, EdgesGeometry, PlaneGeometry, type Group } from "three";
import { useScene } from "./Scene";

export const FRAME_W = 1.6;
export const FRAME_H = 0.9;

/** Picture plane with a horizontal colour ramp in vertex colours (no textures to load). */
function rampPlane(from: Color, to: Color): PlaneGeometry {
  const g = new PlaneGeometry(FRAME_W - 0.12, FRAME_H - 0.12, 8, 1);
  const pos = g.getAttribute("position");
  const colors = new Float32Array(pos.count * 3);
  const c = new Color();
  for (let i = 0; i < pos.count; i++) {
    const t = (pos.getX(i) + (FRAME_W - 0.12) / 2) / (FRAME_W - 0.12);
    c.copy(from).lerp(to, t);
    colors.set([c.r, c.g, c.b], i * 3);
  }
  g.setAttribute("color", new BufferAttribute(colors, 3));
  return g;
}

/**
 * One film frame: a thin slab with a picture. `raw` frames (not yet fixed) are desaturated; fixed frames
 * carry the accent. The same object is the motif of every 3D visual in the app.
 */
export const Frame = forwardRef<Group, { raw?: boolean; glow?: number; opacity?: number }>(function Frame(
  { raw = false, glow = 0, opacity = 1 },
  ref,
) {
  const { colors } = useScene();
  const body = useMemo(() => new BoxGeometry(FRAME_W, FRAME_H, 0.035), []);
  const edges = useMemo(() => new EdgesGeometry(body), [body]);
  const picture = useMemo(
    () => (raw
      // Unfixed footage: cool grey with a hint of the accent, alive but clearly "not yet".
      ? rampPlane(colors.muted.clone().lerp(colors.accent1, 0.12), colors.muted.clone().lerp(colors.accent3, 0.28))
      : rampPlane(colors.accent1, colors.accent3)),
    [raw, colors],
  );
  return (
    <group ref={ref}>
      <mesh geometry={body}>
        {/* Slightly metallic so the accent light glints along the edges as frames turn. */}
        <meshStandardMaterial color={colors.body} roughness={0.38} metalness={0.35} transparent opacity={opacity} />
      </mesh>
      <mesh geometry={picture} position={[0, 0, 0.019]}>
        <meshBasicMaterial vertexColors transparent opacity={opacity * (raw ? 0.75 : 0.85 + glow * 0.15)} toneMapped={false} />
      </mesh>
      <lineSegments geometry={edges}>
        <lineBasicMaterial color={colors.line} transparent opacity={opacity * (0.14 + glow * 0.4)} />
      </lineSegments>
    </group>
  );
});
