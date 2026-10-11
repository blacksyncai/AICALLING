"use client";

import * as React from "react";
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Slot } from "@radix-ui/react-slot";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  closestCenter,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragMoveEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import tunnel from "tunnel-rat";
import { cn } from "@/lib/utils";

/* ============================================================================
 * TYPES
 * ========================================================================== */

export interface TimelineSlotData {
  id: string;
  rowId: string;
  startTime: string; // "14:30"
  duration: number; // minutes
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}

export interface TimelineRowData {
  id: string;
  label: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}

export interface TimelineConfig {
  startHour: number;
  endHour: number;
  snapIntervalMinutes?: number;
  columnWidth?: number;
}

/** Props the Timeline injects into its children while dragging. */
interface InjectedProps {
  slots?: TimelineSlotData[];
  rows?: TimelineRowData[];
  activeSlotId?: string | null;
  overRowId?: string | null;
  draggedNewTime?: string | null;
  isValidDrop?: boolean;
  getSnappedDelta?: (deltaX: number) => number;
  _showDropRegion?: boolean;
  _dropRegionTime?: string | null;
}

/* ============================================================================
 * CONTEXT
 * ========================================================================== */

type TimelineContextValue = {
  config: TimelineConfig;
  pixelsPerMinute: number;
  timelineWidth: number;
  timelineRef: React.RefObject<HTMLDivElement | null>;
  columnRef: React.RefObject<HTMLDivElement | null>;
  dragPreviewTunnel: ReturnType<typeof tunnel>;
  onSlotPositionChange?: (slotId: string, newTime: string, newRowId: string) => Promise<boolean>;
  onValidateDrop?: (slotId: string, newTime: string, newRowId: string) => boolean;
  onSlotClick?: (slotId: string) => void;
};

const TimelineContext = createContext<TimelineContextValue | null>(null);

function useTimeline() {
  const context = useContext(TimelineContext);
  if (!context) throw new Error("Timeline components must be used within TimelineProvider");
  return context;
}

/* ============================================================================
 * UTILITIES
 * ========================================================================== */

export const timeToMinutes = (time: string): number => {
  const [hours, minutes] = time.split(":").map(Number);
  return hours * 60 + minutes;
};

export const minutesToTime = (minutes: number): string => {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return `${hours.toString().padStart(2, "0")}:${mins.toString().padStart(2, "0")}`;
};

/** "14:30" → "2:30 PM" */
export const formatClock = (time: string): string => {
  const m = timeToMinutes(time);
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return `${h % 12 || 12}${mm ? `:${String(mm).padStart(2, "0")}` : ""} ${h < 12 ? "AM" : "PM"}`;
};

/* ============================================================================
 * PROVIDER
 * ========================================================================== */

interface TimelineProviderProps {
  children: React.ReactNode;
  config: TimelineConfig;
  percentageInView?: number;
  onSlotPositionChange?: (slotId: string, newTime: string, newRowId: string) => Promise<boolean>;
  onValidateDrop?: (slotId: string, newTime: string, newRowId: string) => boolean;
  onSlotClick?: (slotId: string) => void;
  style?: React.CSSProperties;
  className?: string;
}

export function TimelineProvider({
  children,
  config,
  percentageInView = 100,
  onSlotPositionChange,
  onValidateDrop,
  onSlotClick,
  style,
  className,
}: TimelineProviderProps) {
  const [viewportWidth, setViewportWidth] = useState(0);
  const timelineRef = useRef<HTMLDivElement>(null);
  const columnRef = useRef<HTMLDivElement>(null);
  const dragPreviewTunnel = useMemo(() => tunnel(), []);
  const columnWidth = config.columnWidth || 112;

  useEffect(() => {
    const measure = () => {
      if (timelineRef.current) setViewportWidth(timelineRef.current.clientWidth - columnWidth);
    };
    measure();
    window.addEventListener("resize", measure);
    const timeout = setTimeout(measure, 100);
    return () => {
      window.removeEventListener("resize", measure);
      clearTimeout(timeout);
    };
  }, [columnWidth]);

  const totalMinutes = (config.endHour - config.startHour) * 60;
  // Never squeeze an hour below ~72px (phones scroll sideways instead).
  const basePixelsPerMinute = viewportWidth > 0 ? Math.max(viewportWidth / totalMinutes, 1.2) : 10;
  const pixelsPerMinute = basePixelsPerMinute * (100 / percentageInView);
  const timelineWidth = totalMinutes * pixelsPerMinute;

  const value: TimelineContextValue = {
    config,
    pixelsPerMinute,
    timelineWidth,
    timelineRef,
    columnRef,
    dragPreviewTunnel,
    onSlotPositionChange,
    onValidateDrop,
    onSlotClick,
  };

  return (
    <TimelineContext.Provider value={value}>
      <div
        data-slot="timeline-wrapper"
        style={
          {
            "--timeline-column-width": `${columnWidth}px`,
            "--timeline-width": `${timelineWidth}px`,
            "--timeline-pixels-per-minute": pixelsPerMinute,
            ...style,
          } as React.CSSProperties
        }
        className={cn("relative w-full", className)}
      >
        {children}
      </div>
    </TimelineContext.Provider>
  );
}

/* ============================================================================
 * TIMELINE (container + drag & drop)
 * ========================================================================== */

interface TimelineProps {
  slots: TimelineSlotData[];
  rows: TimelineRowData[];
  children: React.ReactNode;
  className?: string;
}

export function Timeline({ slots, rows, children, className }: TimelineProps) {
  const { config, pixelsPerMinute, timelineRef, dragPreviewTunnel, onSlotPositionChange, onValidateDrop } = useTimeline();
  const [mousePosition, setMousePosition] = useState<{ x: number; y: number } | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  const snapInterval = config.snapIntervalMinutes || 15;
  const columnWidth = config.columnWidth || 112;

  const snapToInterval = (minutes: number) => Math.round(minutes / snapInterval) * snapInterval;
  const getSnappedDelta = (deltaX: number) => Math.round(deltaX / pixelsPerMinute / snapInterval) * snapInterval * pixelsPerMinute;
  const calculateNewTime = (originalTime: string, deltaX: number) => {
    const snapped = snapToInterval(timeToMinutes(originalTime) + Math.round(deltaX / pixelsPerMinute));
    return minutesToTime(Math.max(config.startHour * 60, Math.min((config.endHour - 1) * 60, snapped)));
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!timelineRef.current) return;
    const rect = timelineRef.current.getBoundingClientRect();
    setMousePosition({ x: e.clientX - rect.left + timelineRef.current.scrollLeft, y: e.clientY - rect.top });
  };

  const mouseMinutes = mousePosition ? Math.floor((mousePosition.x - columnWidth) / pixelsPerMinute) + config.startHour * 60 : null;
  const mouseTime =
    mouseMinutes != null && mousePosition && mousePosition.x > columnWidth && mouseMinutes < config.endHour * 60
      ? minutesToTime(Math.floor(mouseMinutes / 5) * 5)
      : null;

  const [activeSlot, setActiveSlot] = useState<string | null>(null);
  const [overRow, setOverRow] = useState<string | null>(null);
  const [draggedTime, setDraggedTime] = useState<string | null>(null);
  const [isValid, setIsValid] = useState(true);

  const reset = () => {
    setActiveSlot(null);
    setOverRow(null);
    setDraggedTime(null);
    setIsValid(true);
  };

  const handleDragStart = (event: DragStartEvent) => setActiveSlot(String(event.active.id));

  const handleDragOver = (event: DragOverEvent) => {
    if (event.over) setOverRow(String(event.over.id));
    else {
      setOverRow(null);
      setDraggedTime(null);
    }
  };

  const handleDragMove = (event: DragMoveEvent) => {
    const { over, active, delta } = event;
    if (!over) return;
    const slot = slots.find((s) => s.id === active.id);
    if (!slot) return;
    const newTime = calculateNewTime(slot.startTime, delta.x);
    setDraggedTime(newTime);
    setIsValid(onValidateDrop ? onValidateDrop(String(active.id), newTime, String(over.id)) : true);
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over, delta } = event;
    reset();
    if (!over) return;
    const slot = slots.find((s) => s.id === active.id);
    if (!slot) return;
    const newTime = calculateNewTime(slot.startTime, delta.x);
    const newRowId = String(over.id);
    if (onValidateDrop && !onValidateDrop(String(active.id), newTime, newRowId)) return;
    if (slot.rowId === newRowId && slot.startTime === newTime) return;
    await onSlotPositionChange?.(String(active.id), newTime, newRowId);
  };

  const dragged = activeSlot ? slots.find((s) => s.id === activeSlot) : null;

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragMove={handleDragMove}
      onDragEnd={handleDragEnd}
      onDragCancel={reset}
    >
      <div className="relative w-full">
        <div
          ref={timelineRef}
          data-slot="timeline-grid"
          className={cn("relative overflow-auto rounded-2xl bg-white ring-1 ring-zinc-900/[0.06]", className)}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setMousePosition(null)}
        >
          {mousePosition && mouseTime && !activeSlot && <TimelineMouseIndicator mouseX={mousePosition.x} time={mouseTime} />}
          {React.Children.map(children, (child) =>
            React.isValidElement(child)
              ? React.cloneElement(child as React.ReactElement<InjectedProps>, {
                  slots,
                  rows,
                  activeSlotId: activeSlot,
                  overRowId: overRow,
                  draggedNewTime: draggedTime,
                  isValidDrop: isValid,
                  getSnappedDelta,
                  _showDropRegion: !!(activeSlot && draggedTime),
                  _dropRegionTime: draggedTime,
                })
              : child,
          )}
        </div>

        <DragOverlay dropAnimation={null}>
          {dragged && (
            <div
              data-slot="timeline-drag-overlay"
              style={{ width: `${Math.max(dragged.duration * pixelsPerMinute, 112)}px`, height: "56px", position: "relative" }}
            >
              <dragPreviewTunnel.Out />
            </div>
          )}
        </DragOverlay>
      </div>
    </DndContext>
  );
}

/* ============================================================================
 * HEADER
 * ========================================================================== */

export function TimelineHeader({ className, columnLabel = "Row" }: { className?: string; columnLabel?: React.ReactNode }) {
  const { config, pixelsPerMinute, columnRef } = useTimeline();
  const markers = [];
  for (let hour = config.startHour; hour < config.endHour; hour++) {
    markers.push({ hour, label: formatClock(minutesToTime(hour * 60)), position: (hour - config.startHour) * 60 * pixelsPerMinute });
  }
  return (
    <div data-slot="timeline-header" className={cn("sticky top-0 z-10 border-b border-zinc-100 bg-white/95 backdrop-blur", className)}>
      <div className="flex h-11">
        <div
          ref={columnRef}
          data-slot="timeline-header-column"
          className="sticky left-0 z-[1] flex w-[var(--timeline-column-width)] shrink-0 items-center border-r border-zinc-100 bg-white px-4 text-xs font-semibold uppercase tracking-wider text-zinc-500"
        >
          {columnLabel}
        </div>
        <div data-slot="timeline-header-markers" className="relative flex-1">
          {markers.map((m) => (
            <div
              key={m.hour}
              data-slot="timeline-hour-marker"
              className="absolute bottom-0 top-0 flex items-center whitespace-nowrap pl-2 text-[11px] font-medium text-zinc-400"
              style={{ left: `${m.position}px` }}
            >
              {m.label}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ============================================================================
 * ROW
 * ========================================================================== */

interface TimelineRowProps extends InjectedProps {
  row: TimelineRowData;
  slots: TimelineSlotData[];
  children: (slot: TimelineSlotData) => React.ReactNode;
  renderRowHeader?: (row: TimelineRowData) => React.ReactNode;
  /** Extra fixed content inside the row's grid (busy blocks, a "now" line…). */
  extra?: React.ReactNode;
  className?: string;
  asChild?: boolean;
}

export function TimelineRow({ row, slots, children, renderRowHeader, extra, className, asChild, ...props }: TimelineRowProps) {
  const { config, pixelsPerMinute, timelineWidth } = useTimeline();
  const Comp = asChild ? Slot : "div";
  const { setNodeRef, isOver } = useDroppable({ id: row.id });
  const rowSlots = slots.filter((s) => s.rowId === row.id);
  const isValidDrop = props.isValidDrop !== false;
  const isHovered = isOver || props.overRowId === row.id;

  const hourMarkers = [];
  for (let hour = config.startHour; hour <= config.endHour; hour++) {
    hourMarkers.push({ hour, position: (hour - config.startHour) * 60 * pixelsPerMinute });
  }
  const halfHourMarkers = [];
  for (let m = 30; m < (config.endHour - config.startHour) * 60; m += 60) halfHourMarkers.push(m * pixelsPerMinute);

  return (
    <Comp
      ref={setNodeRef}
      data-slot="timeline-row"
      data-state={isHovered ? (isValidDrop ? "hover-valid" : "hover-invalid") : "idle"}
      className={cn(
        "flex h-16 border-b border-zinc-100 bg-white last:border-b-0",
        isHovered && isValidDrop && "bg-brand-50/40 ring-2 ring-inset ring-brand-400",
        isHovered && !isValidDrop && "ring-2 ring-inset ring-red-400",
        className,
      )}
    >
      <div
        data-slot="timeline-row-label"
        className="sticky left-0 z-[9] flex w-[var(--timeline-column-width)] shrink-0 items-center border-r border-zinc-100 bg-white"
      >
        {renderRowHeader ? renderRowHeader(row) : <span className="px-4 text-sm font-medium">{row.label}</span>}
      </div>

      <div data-slot="timeline-row-grid" className="relative flex-1" style={{ width: `${timelineWidth}px` }}>
        {halfHourMarkers.map((left, i) => (
          <div key={`h-${i}`} className="absolute bottom-0 top-0 w-px border-l border-dashed border-zinc-100" style={{ left: `${left}px` }} />
        ))}
        {hourMarkers.map((m) => (
          <div key={m.hour} className="absolute bottom-0 top-0 w-px bg-zinc-100" style={{ left: `${m.position}px` }} />
        ))}
        {extra}

        {rowSlots.map((slot) => {
          const el = children(slot);
          return (
            <React.Fragment key={slot.id}>
              {React.isValidElement(el)
                ? React.cloneElement(el as React.ReactElement<InjectedProps>, {
                    activeSlotId: props.activeSlotId,
                    getSnappedDelta: props.getSnappedDelta,
                  })
                : el}
            </React.Fragment>
          );
        })}

        {isHovered && props.draggedNewTime && props.activeSlotId && (
          <TimelineDropGhost
            activeSlotId={props.activeSlotId}
            allSlots={slots}
            newTime={props.draggedNewTime}
            isValid={isValidDrop}
            pixelsPerMinute={pixelsPerMinute}
            config={config}
          />
        )}
      </div>
    </Comp>
  );
}

/* ============================================================================
 * SLOT (draggable)
 * ========================================================================== */

interface TimelineSlotProps extends InjectedProps {
  slot: TimelineSlotData;
  children: React.ReactNode;
  className?: string;
  asChild?: boolean;
  draggable?: boolean;
}

export function TimelineSlot({ slot, children, className, asChild, draggable = true, ...props }: TimelineSlotProps) {
  const { config, pixelsPerMinute, onSlotClick, dragPreviewTunnel } = useTimeline();
  const Comp = asChild ? Slot : "div";
  const { attributes, listeners, setNodeRef, isDragging, transform } = useDraggable({ id: slot.id, disabled: !draggable });

  const left = (timeToMinutes(slot.startTime) - config.startHour * 60) * pixelsPerMinute;
  const width = Math.max(slot.duration * pixelsPerMinute, 112);
  const isActive = props.activeSlotId === slot.id;

  const style: React.CSSProperties = {
    left: `${left}px`,
    width: `${width}px`,
    top: 0,
    bottom: 0,
    ...(transform && props.getSnappedDelta
      ? { transform: `translate3d(${props.getSnappedDelta(transform.x)}px, ${transform.y}px, 0)` }
      : {}),
  };

  const body = (
    <Comp
      data-slot="timeline-slot"
      data-state={isDragging ? "dragging" : "idle"}
      data-active={isActive}
      className={cn(
        "absolute inset-1 overflow-hidden rounded-lg transition-shadow",
        draggable && "cursor-grab active:cursor-grabbing",
        isDragging ? "opacity-40 ring-2 ring-zinc-900/30" : "shadow-sm",
        onSlotClick && "hover:ring-2 hover:ring-zinc-900/15",
        className,
      )}
      onClick={(e: React.MouseEvent) => {
        if (onSlotClick && !isDragging) {
          e.stopPropagation();
          onSlotClick(slot.id);
        }
      }}
    >
      {children}
    </Comp>
  );

  return (
    <div ref={setNodeRef} {...listeners} {...attributes} className="absolute z-[6]" style={style}>
      {body}
      {isActive && isDragging && (
        <dragPreviewTunnel.In>
          <Comp data-slot="timeline-slot-preview" className={cn("h-full w-full overflow-hidden rounded-lg shadow-lg", className)}>
            {children}
          </Comp>
        </dragPreviewTunnel.In>
      )}
    </div>
  );
}

/** Red "now" line inside one row (use as a row's `extra` when rows are days). */
export function TimelineNowLine() {
  const { config, pixelsPerMinute } = useTimeline();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const i = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(i);
  }, []);
  const minutes = now.getHours() * 60 + now.getMinutes();
  if (minutes < config.startHour * 60 || minutes > config.endHour * 60) return null;
  return (
    <div
      data-slot="timeline-now-line"
      className="pointer-events-none absolute bottom-0 top-0 z-[7] w-0.5 bg-red-500"
      style={{ left: `${(minutes - config.startHour * 60) * pixelsPerMinute}px` }}
    >
      <span className="absolute -left-1 top-0 h-2.5 w-2.5 rounded-full bg-red-500" />
    </div>
  );
}

/** A fixed block on the grid (e.g. a busy event from Google Calendar) — not draggable. */
export function TimelineBlock({
  startTime,
  duration,
  className,
  children,
  title,
}: {
  startTime: string;
  duration: number;
  className?: string;
  children?: React.ReactNode;
  title?: string;
}) {
  const { config, pixelsPerMinute } = useTimeline();
  const left = (timeToMinutes(startTime) - config.startHour * 60) * pixelsPerMinute;
  return (
    <div
      data-slot="timeline-block"
      title={title}
      className={cn("absolute bottom-1 top-1 z-[4] overflow-hidden rounded-lg", className)}
      style={{ left: `${left + 4}px`, width: `${Math.max(duration * pixelsPerMinute - 8, 24)}px` }}
    >
      {children}
    </div>
  );
}

/* ============================================================================
 * SLOT PRIMITIVES
 * ========================================================================== */

export function TimelineSlotLabel({ asChild, className, ...props }: React.ComponentProps<"div"> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "div";
  return <Comp data-slot="timeline-slot-label" className={cn("truncate text-xs font-medium", className)} {...props} />;
}

export function TimelineSlotContent({ asChild, className, ...props }: React.ComponentProps<"div"> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "div";
  return <Comp data-slot="timeline-slot-content" className={cn("text-xs", className)} {...props} />;
}

/* ============================================================================
 * INDICATORS
 * ========================================================================== */

function TimelineMouseIndicator({ mouseX, time }: { mouseX: number; time: string }) {
  return (
    <div data-slot="timeline-mouse-indicator" className="pointer-events-none absolute bottom-0 top-0 z-20" style={{ left: `${mouseX}px` }}>
      <div className="absolute bottom-0 left-0 top-0 w-px bg-brand-400/60" />
      <div className="absolute left-1/2 top-2.5 -translate-x-1/2 whitespace-nowrap rounded-md bg-zinc-900 px-1.5 py-0.5 text-[10px] font-semibold text-white shadow">
        {formatClock(time)}
      </div>
    </div>
  );
}

export function TimelineDropRegion({ startTime, duration }: { startTime: string; duration: number }) {
  const { config, pixelsPerMinute } = useTimeline();
  const columnWidth = config.columnWidth || 112;
  const start = timeToMinutes(startTime);
  const left = (start - config.startHour * 60) * pixelsPerMinute + columnWidth;
  const width = duration * pixelsPerMinute;
  return (
    <div data-slot="timeline-drop-region" className="pointer-events-none absolute bottom-0 top-0 z-[12]" style={{ left: `${left}px`, width: `${width}px` }}>
      <div className="absolute left-1/2 top-1.5 -translate-x-1/2 whitespace-nowrap rounded-md bg-brand-600 px-2 py-1 text-xs font-semibold text-white shadow-md">
        {formatClock(startTime)} – {formatClock(minutesToTime(start + duration))}
      </div>
      <div className="absolute bottom-0 left-0 top-0 w-0.5 bg-brand-500" />
      <div className="absolute bottom-0 right-0 top-0 w-0.5 bg-brand-500" />
      <div className="absolute inset-0 bg-brand-500/[0.06]" />
    </div>
  );
}

/** Red "now" line across every row (for single-day timelines). */
export function TimelineCurrentTime({ className, nowLabel = "Now" }: { className?: string; nowLabel?: string }) {
  const { config, pixelsPerMinute } = useTimeline();
  const columnWidth = config.columnWidth || 112;
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const i = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(i);
  }, []);
  const minutes = now.getHours() * 60 + now.getMinutes();
  if (minutes < config.startHour * 60 || minutes > config.endHour * 60) return null;
  const left = (minutes - config.startHour * 60) * pixelsPerMinute + columnWidth;
  return (
    <div data-slot="timeline-current-time" className={cn("pointer-events-none absolute bottom-0 top-0 z-[15] w-0.5 bg-red-500", className)} style={{ left: `${left}px` }}>
      <div className="absolute left-1/2 top-2.5 -translate-x-1/2 whitespace-nowrap rounded-md bg-red-500 px-1.5 py-0.5 text-[10px] font-semibold text-white shadow">
        {nowLabel} {formatClock(minutesToTime(minutes))}
      </div>
    </div>
  );
}

/* ============================================================================
 * GRID
 * ========================================================================== */

export function TimelineGrid({ children, className, ...props }: { children: React.ReactNode; className?: string } & InjectedProps) {
  const { timelineWidth, config } = useTimeline();
  const columnWidth = config.columnWidth || 112;
  const activeSlot = props._showDropRegion && props.slots ? props.slots.find((s) => s.id === props.activeSlotId) : null;
  return (
    <div data-slot="timeline-grid-container" className={cn("relative", className)} style={{ minWidth: `${timelineWidth + columnWidth}px` }}>
      {React.Children.map(children, (child) =>
        React.isValidElement(child) ? React.cloneElement(child as React.ReactElement<InjectedProps>, props) : child,
      )}
      {props._showDropRegion && props._dropRegionTime && activeSlot && (
        <TimelineDropRegion startTime={props._dropRegionTime} duration={activeSlot.duration} />
      )}
    </div>
  );
}

/* ============================================================================
 * DROP GHOST
 * ========================================================================== */

function TimelineDropGhost({
  activeSlotId,
  allSlots,
  newTime,
  isValid,
  config,
  pixelsPerMinute,
}: {
  activeSlotId: string;
  allSlots: TimelineSlotData[];
  newTime: string;
  isValid: boolean;
  config: TimelineConfig;
  pixelsPerMinute: number;
}) {
  const slot = allSlots.find((s) => s.id === activeSlotId);
  if (!slot || !isValid) return null;
  const left = (timeToMinutes(newTime) - config.startHour * 60) * pixelsPerMinute;
  return (
    <div
      data-slot="timeline-drop-ghost"
      className="pointer-events-none absolute z-[100] rounded-lg border-2 border-dashed border-brand-400 bg-brand-100/50"
      style={{ left: `${left}px`, width: `${Math.max(slot.duration * pixelsPerMinute, 112)}px`, top: "4px", bottom: "4px" }}
    />
  );
}

export { useTimeline, TimelineMouseIndicator };
export default Timeline;
