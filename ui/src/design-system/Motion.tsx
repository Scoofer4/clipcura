import { animate, motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "framer-motion";
import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";

/**
 * Card that tilts a few degrees toward the pointer, like a physical tile under a light.
 * Small angles and a damped spring keep it calm; reduced motion turns it off.
 */
export function Tilt({ children, max = 6, className = "" }: { children: ReactNode; max?: number; className?: string }) {
  const reduced = useReducedMotion();
  const px = useMotionValue(0.5);
  const py = useMotionValue(0.5);
  const spring = { stiffness: 260, damping: 26, mass: 0.6 };
  const rotateY = useSpring(useTransform(px, [0, 1], [-max, max]), spring);
  const rotateX = useSpring(useTransform(py, [0, 1], [max, -max]), spring);
  // A soft highlight follows the pointer across the surface.
  const sheenX = useTransform(px, (v) => `${v * 100}%`);
  const sheenY = useTransform(py, (v) => `${v * 100}%`);

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width);
    py.set((e.clientY - r.top) / r.height);
  };
  const reset = () => (px.set(0.5), py.set(0.5));

  if (reduced) return <div className={`h-full ${className}`}>{children}</div>;
  return (
    <div className={`h-full ${className}`} style={{ perspective: 900 }} onPointerMove={onMove} onPointerLeave={reset}>
      <motion.div style={{ rotateX, rotateY, transformStyle: "preserve-3d" }} className="relative h-full">
        {children}
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-[var(--radius-panel)]"
          style={{
            background: useTransform([sheenX, sheenY], ([x, y]) =>
              `radial-gradient(260px circle at ${x} ${y}, rgb(255 255 255 / 0.07), transparent 60%)`),
          }}
        />
      </motion.div>
    </div>
  );
}

/** Counts up to a new value so a changing total is noticed, without flashing. */
export function AnimatedNumber({ value, duration = 0.8 }: { value: number; duration?: number }) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(reduced ? value : 0);
  const from = useRef(reduced ? value : 0);
  useEffect(() => {
    if (reduced) {
      setShown(value);
      return;
    }
    const controls = animate(from.current, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setShown(Math.round(v)),
    });
    from.current = value;
    return () => controls.stop();
  }, [value, duration, reduced]);
  return <>{shown}</>;
}
