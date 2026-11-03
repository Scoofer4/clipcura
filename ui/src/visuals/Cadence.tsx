import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import type { Group } from "three";
import { Frame, FRAME_H, FRAME_W } from "./Frame";
import { useScene } from "./Scene";

/**
 * "What Clipcura does to this clip", as a working instrument rather than decoration:
 * frames arrive at the clip's real cadence (uneven for VFR), pass through the viewfinder gate and leave at the
 * chosen target rate. Frame density on each side is proportional to the actual frame rates, so picking 24, 30
 * or 60 visibly changes how many frames are dropped or repeated.
 *
 * Two clocks: free-running for previews, or driven by a job's processed-frame count, in which case the scene
 * is redrawn only when progress arrives and never competes with the transcode for the GPU.
 */

const TRACK = 4.6;
const SECONDS_SHOWN = 0.36;   // the track shows about a third of a second of footage
const STILL_TIME = 2.2;

function wrap(v: number, len: number) {
  return ((v % len) + len) % len;
}

function edgeScale(distanceToEdge: number) {
  return Math.min(1, Math.max(0, distanceToEdge / 0.6));
}

/** Deterministic uneven spacing: clumps and gaps like a phone or screen recorder writing frames on demand. */
function unevenOffsets(count: number, irregularity: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < count; i++) {
    const even = (i / count) * TRACK;
    const wobble = (Math.sin(i * 12.9898) * 43758.5453) % 1; // stable pseudo-random in -1..1
    out.push(wrap(even + wobble * irregularity * (TRACK / count) * 1.6, TRACK));
  }
  return out;
}

function Gate() {
  const { colors } = useScene();
  const w = FRAME_W + 0.38;
  const h = FRAME_H + 0.32;
  const arm = 0.42;
  const th = 0.045;
  const corners: [number, number, number, number][] = [];
  for (const sx of [-1, 1]) {
    for (const sy of [-1, 1]) {
      corners.push([sx * (w / 2 - arm / 2), sy * (h / 2), arm, th]);
      corners.push([sx * (w / 2), sy * (h / 2 - arm / 2), th, arm]);
    }
  }
  return (
    <group rotation={[0, -Math.PI / 2, 0]}>
      {corners.map(([x, y, cw, ch], i) => (
        <mesh key={i} position={[x, y, 0]}>
          <boxGeometry args={[cw, ch, th]} />
          <meshBasicMaterial color={colors.accent2} toneMapped={false} />
        </mesh>
      ))}
      <mesh>
        <planeGeometry args={[w, h]} />
        <meshBasicMaterial color={colors.accent2} transparent opacity={0.06} depthWrite={false} />
      </mesh>
    </group>
  );
}

export interface CadenceProps {
  /** Average input rate (avg_frame_rate). */
  inputFps: number;
  /** 0 = perfectly even input, 1 = heavy VFR (from the deep PTS check). */
  irregularity: number;
  targetFps: number;
  /** When set, the animation follows a running job instead of the clock. */
  processedFrames?: number;
}

export function Cadence({ inputFps, irregularity, targetFps, processedFrames }: CadenceProps) {
  const { live } = useScene();
  const invalidate = useThree((s) => s.invalidate);
  const driven = processedFrames !== undefined;
  const rawCount = Math.max(2, Math.round(inputFps * SECONDS_SHOWN));
  const evenCount = Math.max(2, Math.round(targetFps * SECONDS_SHOWN));
  const offsets = useMemo(() => unevenOffsets(rawCount, irregularity), [rawCount, irregularity]);
  const raw = useRef<(Group | null)[]>([]);
  const even = useRef<(Group | null)[]>([]);
  const speed = TRACK / SECONDS_SHOWN / 6; // slowed 6x so individual frames stay readable

  useEffect(() => invalidate(), [live, driven, processedFrames, targetFps, inputFps, irregularity, invalidate]);

  useFrame((state) => {
    // Driven mode: one processed frame advances the track by one output frame spacing.
    const t = driven
      ? ((processedFrames ?? 0) / targetFps) * (TRACK / SECONDS_SHOWN) / speed
      : live ? state.clock.elapsedTime : STILL_TIME;
    raw.current.forEach((f, i) => {
      if (!f) return;
      const d = wrap(t * speed + offsets[i], TRACK);
      f.position.set(-TRACK + d, 0, 0);
      f.rotation.set(0, -Math.PI / 2, (((i * 37) % 11) / 11 - 0.5) * 0.12 * irregularity);
      const s = edgeScale(Math.min(d, TRACK - d));
      f.scale.setScalar(s);
      f.visible = s > 0.03; // a frame shrunk to nothing would still draw its edges as a stray line
    });
    even.current.forEach((f, j) => {
      if (!f) return;
      const d = wrap(t * speed + (j / evenCount) * TRACK, TRACK);
      f.position.set(d, 0, 0);
      f.rotation.set(0, -Math.PI / 2, 0);
      const s = edgeScale(Math.min(d, TRACK - d));
      f.scale.setScalar(s);
      f.visible = s > 0.03;
    });
  });

  return (
    <group position={[0.2, -0.05, 0]}>
      <Gate />
      {offsets.map((_, i) => <Frame key={`r${rawCount}-${i}`} raw ref={(g) => { raw.current[i] = g; }} />)}
      {Array.from({ length: evenCount }, (_, j) => (
        <Frame key={`e${evenCount}-${j}`} ref={(g) => { even.current[j] = g; }} />
      ))}
    </group>
  );
}

/** Plain-language consequence of converting `inputFps` to `targetFps`, per second of footage. */
export function cadenceEffect(inputFps: number, targetFps: number): { kind: "drop" | "repeat" | "keep"; perSecond: number; uneven: boolean } {
  const diff = inputFps - targetFps;
  if (Math.abs(diff) < 0.05) return { kind: "keep", perSecond: 0, uneven: false };
  const ratio = inputFps / targetFps;
  const uneven = Math.abs(ratio - Math.round(ratio)) > 0.01 || Math.round(ratio) < 1;
  return { kind: diff > 0 ? "drop" : "repeat", perSecond: Math.round(Math.abs(diff)), uneven };
}
