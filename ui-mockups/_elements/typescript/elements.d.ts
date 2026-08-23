// el-framework — TypeScript declarations
// ======================================
// Type definitions for every `el-*` class and `data-*` attribute in the
// framework. Import this file (or reference it via `"types"` in tsconfig)
// to get IntelliSense for the framework's primitives.
//
// Usage:
//   import "el-framework/typescript/elements.d.ts";
//
// All classes are typed as their underlying HTML element. For richer
// typing (e.g. `ElPill` as a custom React component) wrap this in your
// own component library.

declare namespace ElFramework {

  // ── Theme tokens (typed object you can read via getComputedStyle) ──

  interface ThemeTokens {
    // color · surface
    bg: string;
    panel: string;
    "panel-2": string;
    "panel-3": string;
    // color · line
    line: string;
    "line-2": string;
    "line-strong": string;
    // color · ink
    ink: string;
    "ink-soft": string;
    mute: string;
    "on-accent": string;
    // color · accent
    accent: string;
    "accent-hover": string;
    "accent-soft": string;
    // color · status
    ok: string;
    warn: string;
    fail: string;
    info: string;
    live: string;
    teal: string;
    // color · shadow + focus
    "shadow-1": string;
    "shadow-2": string;
    "shadow-3": string;
    overlay: string;
    "focus-ring": string;
    // typography
    "font-body": string;
    "font-display": string;
    "font-mono": string;
    "font-feat": string;
    // font sizes
    "fs-xs": string;
    "fs-sm": string;
    "fs-md": string;
    "fs-lg": string;
    "fs-xl": string;
    "fs-2xl": string;
    // space
    "space-1": string;
    "space-2": string;
    "space-3": string;
    "space-4": string;
    "space-5": string;
    "space-6": string;
    // radius
    "r-none": string;
    "r-sm": string;
    "r-md": string;
    "r-lg": string;
    "r-pill": string;
    // border
    bw: string;
    "bw-2": string;
    // motion
    "dur-fast": string;
    "dur-base": string;
    "dur-slow": string;
    ease: string;
    // size · affordance
    "size-xs": string;
    "size-sm": string;
    "size-md": string;
    "size-lg": string;
    "size-xl": string;
  }

  type ThemeSlug =
    | "neutral"
    | "polaroid"
    | "cockpit"
    | "cockpit-paper"
    | "console"
    | "compact"
    | "casebook"
    | "agent-paper"
    | "agent-pulse"
    | "agent-history"
    | "terminal"
    | "swiss";

  // ── Helper to read a token from the current theme ──

  function getToken(name: keyof ThemeTokens): string;
  function setTheme(slug: ThemeSlug): void;
  function getTheme(): ThemeSlug;

  // ── Display ──

  interface ElPill extends HTMLSpanElement {}
  interface ElDot extends HTMLSpanElement {}
  interface ElBigNum extends HTMLSpanElement {}
  interface ElGauge extends HTMLDivElement {}
  interface ElSparkline extends HTMLSpanElement {}
  interface ElBarograph extends HTMLSpanElement {}
  interface ElKbd extends HTMLKbdElement {}
  interface ElBadge extends HTMLSpanElement {}
  interface ElAvatar extends HTMLSpanElement {}
  interface ElProgress extends HTMLDivElement {}
  interface ElSkeleton extends HTMLDivElement {}
  interface ElSpinner extends HTMLSpanElement {}
  interface ElEmpty extends HTMLDivElement {}
  interface ElRating extends HTMLSpanElement {}
  interface ElColorSwatch extends HTMLSpanElement {}

  // ── Lists ──

  interface ElTimelineH extends HTMLDivElement {}
  interface ElTimelineV extends HTMLDivElement {}
  interface ElAccordion extends HTMLDivElement {}
  interface ElKanban extends HTMLDivElement {}
  interface ElTable extends HTMLTableElement {}
  interface ElCard extends HTMLDivElement {}
  interface ElHoverCard extends HTMLDivElement {}
  interface ElChip extends HTMLSpanElement {}
  interface ElTreeList extends HTMLUListElement {}
  interface ElBreadcrumb extends HTMLNavElement {}
  interface ElPagination extends HTMLDivElement {}
  interface ElDefList extends HTMLDListElement {}
  interface ElTaskList extends HTMLUListElement {}
  interface ElStepper extends HTMLOListElement {}

  // ── Controls ──

  interface ElDropdown extends HTMLSelectElement {}
  interface ElCheck extends HTMLSpanElement {}
  interface ElToggle extends HTMLSpanElement {}
  interface ElSwitch extends HTMLSpanElement {}
  interface ElSlider extends HTMLInputElement {}
  interface ElRange extends HTMLDivElement {}
  interface ElSegmented extends HTMLDivElement {}
  interface ElSearch extends HTMLInputElement {}
  interface ElPalette extends HTMLDivElement {}
  interface ElCombobox extends HTMLDivElement {}
  interface ElMultiSelect extends HTMLDivElement {}
  interface ElDropdownMenu extends HTMLDivElement {}
  interface ElContextMenu extends HTMLDivElement {}
  interface ElRadio extends HTMLInputElement {}

  // ── Data viz ──

  interface ElMiniBar extends HTMLDivElement {}
  interface ElMiniLine extends HTMLDivElement {}
  interface ElEntityGraph extends HTMLDivElement {}
  interface ElTreemap extends HTMLDivElement {}
  interface ElHeatmap extends HTMLDivElement {}
  interface ElScatter extends HTMLDivElement {}
  interface ElSankey extends HTMLDivElement {}
  interface ElDiffView extends HTMLDivElement {}
  interface ElMarkdown extends HTMLDivElement {}

  // ── Containers ──

  interface ElPanel extends HTMLElement {}
  interface ElTabs extends HTMLDivElement {}
  interface ElModal extends HTMLDivElement {}
  interface ElDrawer extends HTMLAsideElement {}
  interface ElBento extends HTMLDivElement {}
  interface ElSplitPane extends HTMLDivElement {}
  interface ElStickyHeader extends HTMLElement {}
  interface ElStickyFooter extends HTMLElement {}
  interface ElStickySidebar extends HTMLElement {}
  interface ElMasonry extends HTMLDivElement {}
  interface ElScrollShadow extends HTMLDivElement {}
  interface ElToastRegion extends HTMLDivElement {}

  // ── Inputs ──

  interface ElInput extends HTMLInputElement {}
  interface ElTextarea extends HTMLTextAreaElement {}
  interface ElSearchBar extends HTMLDivElement {}
  interface ElPrompt extends HTMLTextAreaElement {}
  interface ElFileUpload extends HTMLDivElement {}
  interface ElColorSwatchInput extends HTMLInputElement {}
  interface ElSignaturePad extends HTMLCanvasElement {}
  interface ElAudioWaveform extends HTMLDivElement {}
  interface ElCodeBlock extends HTMLPreElement {}
  interface ElKbdInput extends HTMLInputElement {}

  // ── Interactions ──

  interface ElTooltip extends HTMLSpanElement {}
  interface ElPopover extends HTMLDivElement {}
  interface ElToast extends HTMLDivElement {}
  interface ElInfiniteScrollTrigger extends HTMLDivElement {}
  interface ElAnchorNav extends HTMLElement {}
}

// ── Global HTML element class augmentations ──
//
// These let `document.querySelector('.el-pill')` return an HTMLElement
// typed as `ElFramework.ElPill` rather than the bare Element type.

declare global {
  interface HTMLElementTagNameMap {
    // Display
    "span.el-pill": ElFramework.ElPill;
    "span.el-dot": ElFramework.ElDot;
    "span.el-big-num": ElFramework.ElBigNum;
    "div.el-gauge": ElFramework.ElGauge;
    "span.el-sparkline": ElFramework.ElSparkline;
    "span.el-barograph": ElFramework.ElBarograph;
    "kbd.el-kbd": ElFramework.ElKbd;
    "span.el-badge": ElFramework.ElBadge;
    "span.el-avatar": ElFramework.ElAvatar;
    "div.el-progress": ElFramework.ElProgress;
    "div.el-skeleton": ElFramework.ElSkeleton;
    "span.el-spinner": ElFramework.ElSpinner;
    "div.el-empty": ElFramework.ElEmpty;
    "span.el-rating": ElFramework.ElRating;
    "span.el-swatch": ElFramework.ElColorSwatch;
    // Lists
    "div.el-timeline-h": ElFramework.ElTimelineH;
    "div.el-timeline-v": ElFramework.ElTimelineV;
    "div.el-accordion": ElFramework.ElAccordion;
    "div.el-kanban": ElFramework.ElKanban;
    "table.el-table": ElFramework.ElTable;
    "div.el-card": ElFramework.ElCard;
    "div.el-hover-card": ElFramework.ElHoverCard;
    "span.el-chip": ElFramework.ElChip;
    "ul.el-tree-list": ElFramework.ElTreeList;
    "nav.el-breadcrumb": ElFramework.ElBreadcrumb;
    "div.el-pagination": ElFramework.ElPagination;
    "dl.el-def-list": ElFramework.ElDefList;
    "ul.el-task-list": ElFramework.ElTaskList;
    "ol.el-stepper": ElFramework.ElStepper;
    // Controls
    "select.el-dropdown": ElFramework.ElDropdown;
    "span.el-check": ElFramework.ElCheck;
    "span.el-toggle": ElFramework.ElToggle;
    "span.el-switch": ElFramework.ElSwitch;
    "input.el-slider": ElFramework.ElSlider;
    "div.el-range": ElFramework.ElRange;
    "div.el-segmented": ElFramework.ElSegmented;
    "input.el-search": ElFramework.ElSearch;
    "div.el-palette": ElFramework.ElPalette;
    "div.el-combobox": ElFramework.ElCombobox;
    "div.el-multi-select": ElFramework.ElMultiSelect;
    "div.el-dropdown-menu": ElFramework.ElDropdownMenu;
    "div.el-context-menu": ElFramework.ElContextMenu;
    "input.el-radio": ElFramework.ElRadio;
    // Data viz
    "div.el-mini-bar": ElFramework.ElMiniBar;
    "div.el-mini-line": ElFramework.ElMiniLine;
    "div.el-entity-graph": ElFramework.ElEntityGraph;
    "div.el-treemap": ElFramework.ElTreemap;
    "div.el-heatmap": ElFramework.ElHeatmap;
    "div.el-scatter": ElFramework.ElScatter;
    "div.el-sankey": ElFramework.ElSankey;
    "div.el-diff-view": ElFramework.ElDiffView;
    "div.el-markdown": ElFramework.ElMarkdown;
    // Containers
    "div.el-panel": ElFramework.ElPanel;
    "div.el-tabs": ElFramework.ElTabs;
    "div.el-modal": ElFramework.ElModal;
    "aside.el-drawer": ElFramework.ElDrawer;
    "div.el-bento": ElFramework.ElBento;
    "div.el-split-pane": ElFramework.ElSplitPane;
    "div.el-sticky-header": ElFramework.ElStickyHeader;
    "div.el-sticky-footer": ElFramework.ElStickyFooter;
    "div.el-sticky-sidebar": ElFramework.ElStickySidebar;
    "div.el-masonry": ElFramework.ElMasonry;
    "div.el-scroll-shadow": ElFramework.ElScrollShadow;
    "div.el-toast-region": ElFramework.ElToastRegion;
    // Inputs
    "input.el-input": ElFramework.ElInput;
    "textarea.el-textarea": ElFramework.ElTextarea;
    "div.el-search-bar": ElFramework.ElSearchBar;
    "textarea.el-prompt": ElFramework.ElPrompt;
    "div.el-file-upload": ElFramework.ElFileUpload;
    "input.el-swatch-input": ElFramework.ElColorSwatchInput;
    "canvas.el-signature-pad": ElFramework.ElSignaturePad;
    "div.el-audio-waveform": ElFramework.ElAudioWaveform;
    "pre.el-code-block": ElFramework.ElCodeBlock;
    "input.el-kbd-input": ElFramework.ElKbdInput;
    // Interactions
    "span.el-tooltip": ElFramework.ElTooltip;
    "div.el-popover": ElFramework.ElPopover;
    "div.el-toast": ElFramework.ElToast;
    "div.el-infinite-scroll-trigger": ElFramework.ElInfiniteScrollTrigger;
    "nav.el-anchor-nav": ElFramework.ElAnchorNav;
  }
}

// ── Data-attribute hooks (for `elements.js` interactive elements) ──

interface HTMLOrSVGElement {
  dataset: DOMStringMap & {
    /** Marks the row as draggable; payload = `data-drag-label` or text content. */
    draggable?: "" | "true";
    dragLabel?: string;
    /** Marks a container as a drop zone; payload inserts into `data-target-list` UL. */
    targetList?: string;
    /** Click-to-toggle on `.el-chip`. */
    toggle?: "" | "true";
    /** Row select group; single-select among siblings. */
    group?: string;
    /** Target detail element id for row-select. */
    detail?: string;
    /** HTML payload injected into the detail element on select. */
    detailHtml?: string;
    /** Enables table sort on `th[data-sort-key]`. */
    sortable?: "" | "true";
    /** Column key for sort. */
    sortKey?: string;
    /** asc/desc. */
    sortDir?: "asc" | "desc";
    /** Accordion auto-closes siblings. */
    exclusive?: "" | "true";
    /** Hover-detail tooltip body. */
    hoverDetail?: "" | "true";
    /** Gauge value 0..1 for radial SVG stroke. */
    value?: string;
    /** Tabs body template id. */
    bodyId?: string;
    /** Palette on-select callback name (window[<name>]). */
    onSelect?: string;
    /** Tree-list node id. */
    treeId?: string;
    /** Theme slug override. */
    theme?: import("el-framework/typescript/elements").ThemeSlug;
  };
}

export {};
