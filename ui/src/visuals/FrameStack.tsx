import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { CanvasTexture, MathUtils, type Group } from "three";
import { Frame } from "./Frame";
import { useScene } from "./Scene";

const COUNT = 7;
const STILL_TIME = 1.7; // pose used when motion is off: the fan at a calm, readable angle

interface Pose { x: number; y: number; z: number; rx: number; ry: number; rz: number }

/** Loose frames on an arc around the viewer: footage as it arrives, not yet in register. */
function fanPose(i: number, t: number): Pose {
  const k = i - (COUNT - 1) / 2;
  const a = k * 0.36;
  return {
    x: Math.sin(a) * 2.25,
    y: 0.09 * Math.sin(t * 0.8 + i * 0.9) + Math.abs(k) * 0.035,
    z: -(1 - Math.cos(a)) * 2.6,
    rx: 0.05 * Math.sin(t * 0.5 + i),
    ry: -a * 1.05,
    rz: k * 0.045 + 0.03 * Math.sin(t * 0.6 + i * 1.3),
  };
}

/** Frames in register: an evenly spaced deck seen at an angle. This is what "fixed" looks like. */
function alignedPose(i: number): Pose {
  return { x: i * 0.06, y: 0, z: -i * 0.34, rx: 0, ry: 0, rz: 0 };
}

/** Soft contact shadow so the frames sit in space instead of floating in a void. */
function useShadowTexture() {
  return useMemo(() => {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const g = c.getContext("2d")!;
    const r = g.createRadialGradient(64, 64, 4, 64, 64, 64);
    r.addColorStop(0, "rgba(0,0,0,0.55)");
    r.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = r;
    g.fillRect(0, 0, 128, 128);
    return new CanvasTexture(c);
  }, []);
}

export function FrameStack({ aligned }: { aligned: boolean }) {
  const { live, colors } = useScene();
  const invalidate = useThree((s) => s.invalidate);
  const group = useRef<Group>(null);
  const frames = useRef<(Group | null)[]>([]);
  const shadow = useShadowTexture();

  useEffect(() => invalidate(), [aligned, live, invalidate]);

  useFrame((state, delta) => {
    const t = live ? state.clock.elapsedTime : STILL_TIME;
    // Springy convergence while animating; jump straight to the pose when drawing a single still frame.
    const settle = (from: number, to: number) => (live ? MathUtils.damp(from, to, 5, delta) : to);
    frames.current.forEach((f, i) => {
      if (!f) return;
      const p = aligned ? alignedPose(i) : fanPose(i, t);
      f.position.set(settle(f.position.x, p.x), settle(f.position.y, p.y), settle(f.position.z, p.z));
      f.rotation.set(settle(f.rotation.x, p.rx), settle(f.rotation.y, p.ry), settle(f.rotation.z, p.rz));
    });
    if (group.current) {
      // The whole set turns gently toward the pointer: depth you can feel without a gimmick.
      const px = live ? state.pointer.x : 0;
      const py = live ? state.pointer.y : 0;
      group.current.rotation.y = settle(group.current.rotation.y, px * 0.3 + (aligned ? -0.62 : 0));
      group.current.rotation.x = settle(group.current.rotation.x, -py * 0.14 + (aligned ? 0.16 : 0.08));
    }
  });

  return (
    <group>
      <group ref={group} position={[0, 0.1, 0]}>
        {Array.from({ length: COUNT }, (_, i) => (
          <Frame key={i} ref={(g) => { frames.current[i] = g; }} raw={!aligned} glow={aligned && i === 0 ? 1 : 0} />
        ))}
      </group>
      <mesh position={[0, -0.72, -0.6]} rotation={[-Math.PI / 2, 0, 0]} scale={[5.6, 1.6, 1]}>
        <planeGeometry args={[1, 1]} />
        <meshBasicMaterial map={shadow} transparent opacity={colors.isDark ? 0.9 : 0.35} depthWrite={false} />
      </mesh>
    </group>
  );
}
